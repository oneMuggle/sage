"""
会话仓储层
负责会话的 CRUD 操作
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.data.database import get_database

logger = logging.getLogger(__name__)


def _append_session_event(
    cursor: Any,
    session_id: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    surface_op: Optional[Dict[str, Any]] = None,
) -> None:
    """DSH 对标 R1 (SE1)：在**当前未提交事务**里追加会话事件（best-effort）。

    事件日志（session_events）是 append-only 事实源，与 messages 写入
    同事务落盘（先于 commit），保证"凡进模型请求的内容能从日志重建"。
    事件写入失败只告警不阻断业务写 —— 与 FTS 索引挂钩同一降级口径；
    严格化（fail-closed）留待 SE2 评估。
    """
    try:
        from backend.data.session_event_repo import SessionEventRepository

        SessionEventRepository.append_with_cursor(
            cursor, session_id, event_type, payload=payload, surface_op=surface_op
        )
    except Exception as exc:  # noqa: BLE001 — 事件日志故障不影响消息写入
        logger.warning("会话事件双写失败 (%s): %s", event_type, exc)


@dataclass
class Session:
    """会话数据模型"""

    id: str
    title: str
    created_at: int
    updated_at: int
    last_message_at: Optional[int] = None
    message_count: int = 0
    metadata: Optional[str] = None
    total_tokens: int = 0
    total_cost: float = 0.0
    is_pinned: bool = False
    is_archived: bool = False
    parent_id: Optional[str] = None
    # M4 会话分叉：fork_root 记录分叉源会话 id；forked_at_message_id 记录
    # 分叉点（源会话中被复制的最后一条消息的 *源* id，None 表示复制到末尾）。
    fork_root: Optional[str] = None
    forked_at_message_id: Optional[str] = None
    # S1 (2026-09-06): 会话级运行态 —— 侧边栏状态徽章数据源。
    # idle=无运行; running/suspended=活跃流; completed/failed=上一轮流终态。
    run_status: str = "idle"
    last_error: Optional[str] = None
    last_run_at: Optional[int] = None

    @classmethod
    def from_row(cls, row) -> Session:
        return cls(
            id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_message_at=row["last_message_at"],
            message_count=row["message_count"],
            metadata=row["metadata"],
            total_tokens=row["total_tokens"] or 0,
            total_cost=row["total_cost"] or 0.0,
            is_pinned=bool(row["is_pinned"] or 0),
            is_archived=bool(row["is_archived"] or 0),
            parent_id=row["parent_id"],
            fork_root=row["fork_root"],
            forked_at_message_id=row["forked_at_message_id"],
            # S1: 迁移前的存量行三列为 NULL/缺失 → 兜底 idle
            run_status=row["run_status"] or "idle",
            last_error=row["last_error"],
            last_run_at=row["last_run_at"],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_message_at": self.last_message_at,
            "message_count": self.message_count,
            "is_pinned": self.is_pinned,
            "metadata": json.loads(self.metadata) if self.metadata else None,
            # M4: 侧栏 fork 徽标依赖这两个字段（list_sessions 序列化必须带上）
            "fork_root": self.fork_root,
            "forked_at_message_id": self.forked_at_message_id,
            # S1: 侧栏状态徽章 / 错误 tooltip 依赖
            "run_status": self.run_status,
            "last_error": self.last_error,
            "last_run_at": self.last_run_at,
        }


class SessionRepository:
    """会话仓储"""

    def __init__(self):
        self.db = get_database()

    def create(self, title: str = "新对话", parent_id: Optional[str] = None) -> Session:
        """创建新会话"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        now = int(time.time() * 1000)
        session_id = str(uuid.uuid4())

        cursor.execute(
            """
            INSERT INTO sessions (id, title, created_at, updated_at, parent_id)
            VALUES (?, ?, ?, ?, ?)
        """,
            (session_id, title, now, now, parent_id),
        )

        conn.commit()

        return Session(
            id=session_id,
            title=title,
            created_at=now,
            updated_at=now,
            parent_id=parent_id,
        )

    def get(self, session_id: str) -> Optional[Session]:
        """获取会话"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()

        if row:
            return Session.from_row(row)
        return None

    def list(self, limit: int = 100, offset: int = 0) -> List[Session]:
        """获取会话列表"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM sessions
            WHERE is_archived = 0
            ORDER BY is_pinned DESC,
                     CASE WHEN run_status IN ('running', 'suspended') THEN 1 ELSE 0 END DESC,
                     updated_at DESC
            LIMIT ? OFFSET ?
        """,
            (limit, offset),
        )

        return [Session.from_row(row) for row in cursor.fetchall()]

    def search(self, query: str, limit: int = 10) -> List[Session]:
        """按标题模糊搜索会话（P1-3.7 全局搜索）。

        使用 LIKE 匹配，不区分大小写。仅搜索未归档会话。
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        pattern = f"%{query}%"
        cursor.execute(
            """
            SELECT * FROM sessions
            WHERE is_archived = 0 AND title LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (pattern, limit),
        )
        return [Session.from_row(row) for row in cursor.fetchall()]

    def update(self, session_id: str, **kwargs) -> bool:
        """更新会话"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        if not kwargs:
            return False

        now = int(time.time() * 1000)
        kwargs["updated_at"] = now

        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [session_id]

        cursor.execute(
            f"""
            UPDATE sessions SET {set_clause} WHERE id = ?
        """,
            values,
        )

        conn.commit()
        return cursor.rowcount > 0

    def delete(self, session_id: str) -> bool:
        """删除会话"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()

        return cursor.rowcount > 0

    def archive(self, session_id: str) -> bool:
        """归档会话"""
        return self.update(session_id, is_archived=1)

    def pin(self, session_id: str, pinned: bool = True) -> bool:
        """置顶/取消置顶会话"""
        return self.update(session_id, is_pinned=1 if pinned else 0)

    def update_run_status(
        self, session_id: str, status: str, error: Optional[str] = None
    ) -> bool:
        """更新会话运行态（S1，2026-09-06）。

        与通用 ``update`` 的区别：**不动 updated_at** —— 运行态变化不应
        重排侧栏（list 按 updated_at DESC 排序）。``last_run_at`` 记录本次
        状态迁移时间（epoch ms）；``error`` 仅在终态为 failed 时传入（其余
        状态传 None 清空旧错误），截断到 500 字符防长堆刷库。

        会话不存在（如 /btw 伪会话 ``__btw__``）时静默返回 False。
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        now = int(time.time() * 1000)
        cursor.execute(
            "UPDATE sessions SET run_status = ?, last_run_at = ?, last_error = ? WHERE id = ?",
            (status, now, error[:500] if error else None, session_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def recover_stale_run_states(self) -> int:
        """启动恢复（S1）：遗留 ``running`` 会话统一标记为 failed。

        后端随应用退出被杀时，producer 的 finally 写库点没有机会执行，
        sessions.run_status 会滞留 running。与编排 finalize 的 default-failed
        语义一致（legacy_routes._finalize_orch_run），重启后统一按"运行中断"
        收口；suspended 不动 —— A4 wake 记录仍在，语义上仍是"等待唤醒"。

        Returns:
            被改写的会话数（用于启动日志）。
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        now = int(time.time() * 1000)
        cursor.execute(
            "UPDATE sessions SET run_status = 'failed', last_error = ?, last_run_at = ? "
            "WHERE run_status = 'running'",
            ("应用重启，运行中断", now),
        )
        conn.commit()
        return cursor.rowcount


# ==================== 消息仓储 ====================


@dataclass
class Message:
    """消息数据模型"""

    id: str
    session_id: str
    role: str
    content: str
    created_at: int
    model: Optional[str] = None
    provider: Optional[str] = None
    tool_calls: Optional[str] = None
    tool_call_id: Optional[str] = None
    reasoning_content: Optional[str] = None  # LLM 思考/推理过程
    # 2026-09 step-by-step: 同一 session 内 assistant 行的步序号（从 0 开始）。
    # user/tool/system 行 → None。多步 run 时每个 ReAct 迭代产生一行 step_index=N。
    step_index: Optional[int] = None
    # 2026-09 context-isolation: 主题段隔离。segment_id 从 0 开始,每次"切话题"
    # 增加。subtype='topic_separator' 标记这是一条段切换 marker(由 user 主动
    # 调用 /topic-new 或类似动作产生),正常消息 subtype=None。
    segment_id: int = 0
    subtype: Optional[str] = None
    # R38 透明度增强 (2026-09-18): 三条通知信息的 JSON-in-TEXT 载荷（原样字符串）。
    # 写入端 json.dumps(..., ensure_ascii=False)；to_dict 解析成结构化值。
    activated_skills: Optional[str] = None
    compact_info: Optional[str] = None
    memory_refs: Optional[str] = None
    # R81 统一参考来源 (2026-09-19): 引用溯源 JSON-in-TEXT 载荷，同上序列化约定。
    # rag_citations: r71 附件检索溯源 [{media_id, filename, mode, chunks}]；
    # sources:       工具命中 [{kind: web|wiki|tool, ...}]（sources_extractor 提取）。
    rag_citations: Optional[str] = None
    sources: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> Message:
        row_keys = set(row.keys())  # set() 避免 sqlite3.Row.keys() 触发 SIM118
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
            model=row["model"],
            provider=row["provider"],
            tool_calls=row["tool_calls"],
            tool_call_id=row["tool_call_id"],
            reasoning_content=row["reasoning_content"],
            step_index=row["step_index"] if "step_index" in row_keys else None,
            segment_id=row["segment_id"] if "segment_id" in row_keys else 0,
            subtype=row["subtype"] if "subtype" in row_keys else None,
            activated_skills=(
                row["activated_skills"] if "activated_skills" in row_keys else None
            ),
            compact_info=row["compact_info"] if "compact_info" in row_keys else None,
            memory_refs=row["memory_refs"] if "memory_refs" in row_keys else None,
            rag_citations=(
                row["rag_citations"] if "rag_citations" in row_keys else None
            ),
            sources=row["sources"] if "sources" in row_keys else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
            "model": self.model,
            "provider": self.provider,
            "tool_calls": self.tool_calls,
            "tool_call_id": self.tool_call_id,
            "reasoning_content": self.reasoning_content,
            "step_index": self.step_index,
            "segment_id": self.segment_id,
            "subtype": self.subtype,
            # R38: 解析成结构化值供前端直接消费；形状不符 → None（降级不报错）。
            "activated_skills": _parse_json_column(self.activated_skills, list),
            "compact_info": _parse_json_column(self.compact_info, dict),
            "memory_refs": _parse_json_column(self.memory_refs, list),
            # R81: 引用溯源同款解析口径（list / 畸形降级 None）。
            "rag_citations": _parse_json_column(self.rag_citations, list),
            "sources": _parse_json_column(self.sources, list),
        }


def _parse_json_column(raw: Optional[str], expected: type):
    """把 JSON-in-TEXT 列解析成结构化值；类型不符或解析失败一律降级为 None。

    降级而非抛错：历史行可能由更早版本写入、或手工改库留下畸形值，
    读路径不应因此整批失败（前端视 None 为"无信息"）。
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, expected) else None


class ForkSourceNotFoundError(LookupError):
    """分叉源不存在（会话或分叉点消息）。

    ``kind`` 取值 ``"session"`` / ``"message"``，路由层据此生成结构化 404。
    """

    def __init__(self, kind: str, ident: str):
        self.kind = kind
        self.ident = ident
        super().__init__(f"fork source {kind} not found: {ident}")


def _insert_forked_message_row(cursor: Any, session_id: str, src_msg: Message) -> str:
    """在给定 cursor 的当前事务中插入一条 fork 复制的消息行，返回新消息 id。

    独立成模块级函数是为了给测试留 seam：monkeypatch 本函数即可模拟
    "复制到一半失败"，验证 fork 事务的整体回滚（MEDIUM-2）。
    """
    new_message_id = f"msg-{uuid.uuid4().hex[:12]}"  # 新 id，避免与源消息主键冲突
    cursor.execute(
        """
        INSERT INTO messages (id, session_id, role, content, model, provider, tool_calls, tool_call_id, reasoning_content, step_index, activated_skills, compact_info, memory_refs, rag_citations, sources, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            new_message_id,
            session_id,
            src_msg.role,
            src_msg.content,
            src_msg.model,
            src_msg.provider,
            src_msg.tool_calls,
            src_msg.tool_call_id,
            src_msg.reasoning_content,
            src_msg.step_index,
            src_msg.activated_skills,  # R38: fork 同步复制通知列，避免子会话丢通知
            src_msg.compact_info,
            src_msg.memory_refs,
            # R81: 引用溯源列随 fork 复制，子会话保留完整引用区块
            src_msg.rag_citations,
            src_msg.sources,
            src_msg.created_at,  # 保留原时间戳 → ORDER BY created_at ASC 保序
        ),
    )
    return new_message_id


def fork_session(
    session_repo: SessionRepository,
    message_repo: MessageRepository,
    source_id: str,
    at_message_id: Optional[str] = None,
    title: Optional[str] = None,
    before_message: bool = False,
) -> Session:
    """从源会话分叉出一个新会话（M4，全量前缀复制，单事务原子落盘）。

    刻意偏离计划文档的 copy-on-write 设计：桌面级会话只有数百条消息，
    全量复制更简单、更安全（读写路径零特判）；CoW 推迟到真正出现
    存储压力时再做。

    语义:
        - 复制源会话中 ``at_message_id`` 及之前的全部消息；``at_message_id``
          省略时复制全部消息。
        - ``before_message=True`` 时改为**开区间**：复制 ``at_message_id``
          **之前**的消息（不含本身）；目标是首条消息时得到空前缀会话。
          U5' 编辑重发依赖此语义——编辑某条 user 消息 = 分叉其前缀。
        - 复制的消息获得**新 id**，但保留原顺序 / role / content / 时间戳 /
          model / provider / tool 字段。
        - 新会话写入 ``fork_root=<源 id>``；``forked_at_message_id`` 取显式
          传入的分叉点（源消息 id），省略分叉点时为 ``None``（表示"复制到
          末尾"）。
        - **原子性**（MEDIUM-2）：新会话行 + 全部复制消息行在**同一事务**
          落盘，任何一步失败整体回滚（连会话行一起），不留半成品孤儿会话。

    Args:
        session_repo: 会话仓储
        message_repo: 消息仓储
        source_id: 源会话 id
        at_message_id: 可选分叉点消息 id（必须属于源会话）
        title: 可选新标题；缺省为 ``"Fork: <源标题>"``
        before_message: 开区间截断开关（见语义段）

    Returns:
        新创建的 Session（含 fork_root / forked_at_message_id）

    Raises:
        ForkSourceNotFoundError: 源会话不存在，或分叉点消息不存在 / 不属于源会话
    """
    source = session_repo.get(source_id)
    if source is None:
        raise ForkSourceNotFoundError("session", source_id)

    all_messages = message_repo.get_by_session(source_id, limit=100000)

    if at_message_id is not None:
        cut_index = next(
            (i for i, m in enumerate(all_messages) if m.id == at_message_id), None
        )
        if cut_index is None:
            raise ForkSourceNotFoundError("message", at_message_id)
        prefix = (
            all_messages[:cut_index] if before_message else all_messages[: cut_index + 1]
        )
    else:
        prefix = all_messages

    new_session_id = str(uuid.uuid4())
    now = int(time.time() * 1000)

    # 单事务：会话行 + 所有消息行同生共死。sqlite3 默认在首个 DML 处隐式
    # BEGIN，commit() 前的一切语句属于同一事务；异常时 rollback() 把会话
    # 行也一并抹掉，无需手工清理孤儿。
    conn = session_repo.db.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO sessions (id, title, created_at, updated_at, last_message_at, message_count, fork_root, forked_at_message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                new_session_id,
                title or f"Fork: {source.title}",
                now,
                now,
                prefix[-1].created_at if prefix else None,
                len(prefix),
                source.id,
                at_message_id,
            ),
        )
        # 逐条复制：插入顺序 = 源顺序，messages 表
        # ORDER BY created_at ASC（同值按 rowid）保持序。
        # SE2: 每条复制行同事务补 message.appended 事件（fork 是最后一个
        # 不落事件的原始 SQL 写入路径；复制行无 subtype/segment，如实记录
        # 表默认值 0/NULL）。事件 payload 携带新 id —— 投影 parity 要求
        # 事件 id 与 messages 行 id 一致。
        from backend.data.session_event_repo import EVENT_MESSAGE_APPENDED

        for src_msg in prefix:
            forked_message_id = _insert_forked_message_row(
                cursor, new_session_id, src_msg
            )
            _append_session_event(
                cursor,
                new_session_id,
                EVENT_MESSAGE_APPENDED,
                payload={
                    "id": forked_message_id,
                    "role": src_msg.role,
                    "content": src_msg.content,
                    "subtype": None,
                    "segment_id": 0,
                    "tool_calls": src_msg.tool_calls,
                    "created_at": src_msg.created_at,
                },
            )
        # B1 (对标增强第五轮批次 A): fork 继承源会话的活跃工作区绑定——
        # 分叉的是"同一段工作在另一条分支上的延续"，丢了绑定 agent 就没有
        # 工作区。workspace_path 原样带走；generation 是 per-session 的
        # 陈旧缓存检测序号，新会话无旧缓存，从 1 重新起算；activated_at
        # 取 fork 时刻（对新会话而言是一次全新激活）。
        cursor.execute(
            """
            INSERT INTO session_workspace_bindings (
                session_id, workspace_path, generation, activated_at, revoked_at
            )
            SELECT ?, workspace_path, 1, ?, NULL
            FROM session_workspace_bindings
            WHERE session_id = ? AND revoked_at IS NULL
            """,
            (new_session_id, now, source.id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    forked = session_repo.get(new_session_id)
    if forked is None:  # pragma: no cover — 刚 commit 的会话必然可读
        raise RuntimeError(
            f"fork_session: new session {new_session_id} missing right after commit"
        )

    # Round 2: fork 复制的消息同步进全文索引（事务外 best-effort，
    # 索引故障不影响 fork 结果）。
    try:
        from backend.data.message_search import get_message_search_index

        index = get_message_search_index()
        # win7 分支同款修复 (回流): 必须用 message_repo.get_by_session —
        # SessionRepository 没有该方法, AttributeError 会被下面的 except
        # 吞成一条 warning, fork 会话从此永远搜不到。
        for m in message_repo.get_by_session(new_session_id, limit=100000):
            index.index_message(
                m.id, m.session_id, m.role, m.content, m.created_at
            )
    except Exception as exc:  # noqa: BLE001 — 索引故障不影响 fork
        logger.warning("fork 消息索引挂钩失败: %s", exc)

    return forked


class MessageRepository:
    """消息仓储"""

    def __init__(self):
        self.db = get_database()

    def save(self, message: Message) -> Message:
        """保存消息"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Task 1 (2026-09-17): 写入时绑定当前活跃 segment_id,
        # 保证 advance_segment() 后的消息落在新段上
        active_segment_id = self.get_active_segment_id(message.session_id)

        cursor.execute(
            """
            INSERT INTO messages (id, session_id, role, content, model, provider, tool_calls, tool_call_id, reasoning_content, step_index, activated_skills, compact_info, memory_refs, rag_citations, sources, created_at, segment_id, subtype)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                message.id,
                message.session_id,
                message.role,
                message.content,
                message.model,
                message.provider,
                message.tool_calls,
                message.tool_call_id,
                message.reasoning_content,
                message.step_index,
                message.activated_skills,
                message.compact_info,
                message.memory_refs,
                message.rag_citations,
                message.sources,
                message.created_at,
                active_segment_id,
                message.subtype,
            ),
        )

        # SE1 同事务事件双写（best-effort，失败仅告警）。
        # win7 分支注：变量是 active_segment_id（win7 的 save() 为无条件
        # 解析变体，与 main 的 seg 条件解析不同 —— R23 教训实例）。
        from backend.data.session_event_repo import EVENT_MESSAGE_APPENDED

        _append_session_event(
            cursor,
            message.session_id,
            EVENT_MESSAGE_APPENDED,
            payload={
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "subtype": message.subtype,
                "segment_id": active_segment_id,
                "tool_calls": message.tool_calls,
                "created_at": message.created_at,
            },
        )

        conn.commit()
        # Round 2: 同步消息全文索引（session_search 工具）。best-effort，
        # 索引故障不影响消息写入。
        try:
            from backend.data.message_search import get_message_search_index

            get_message_search_index().index_message(
                message.id,
                message.session_id,
                message.role,
                message.content,
                message.created_at,
            )
        except Exception as exc:  # noqa: BLE001 — 索引故障不影响写入
            logger.warning("save 消息索引挂钩失败: %s", exc)
        return message

    def replace_prefix_with_continuation(
        self,
        session_id: str,
        delete_message_ids: List[str],
        continuation_message: Message,
        new_message_count: int,
    ) -> None:
        """原子地用续接消息替换被压缩的消息前缀（M4，CRITICAL-1）。

        三个动作——删除被替代的消息行、插入续接摘要行、更新会话
        ``message_count``——在**同一事务**中落盘。任何一步失败整体
        回滚，杜绝旧逐条提交流程中"历史已删、摘要未写入"的崩溃窗口
        （那会永久丢失历史且没有摘要兜底）。

        Args:
            session_id: 目标会话 id
            delete_message_ids: 要被摘要替代的消息 id 列表（压缩前缀）
            continuation_message: 续接摘要消息（id 由调用方生成）
            new_message_count: 压缩后的消息总数（写入 sessions.message_count）

        Raises:
            Exception: 任一 SQL 失败时抛出；事务已回滚，DB 保持调用前状态。
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        now = int(time.time() * 1000)
        try:
            # Round 4 (压缩谱系): 删除前把前缀消息归档进派生会话 ——
            # 同 cursor 同事务，与压缩同生共死；「历史已删、归档未写」
            # 与「历史已删、摘要未写」同为不可接受的永久丢失窗口。
            try:
                from backend.data.session_lineage import archive_prefix_in_transaction

                archive_prefix_in_transaction(
                    cursor,
                    session_id,
                    delete_message_ids,
                    reason="compaction",
                    now_ms=now,
                )
            except Exception:
                raise  # 归档失败 → 整体回滚（与压缩强一致）
            # sqlite3 默认在首个 DML 处隐式 BEGIN，commit() 前所有语句
            # 同属一个事务；循环逐条 DELETE 避免 IN (?) 占位符数量上限。
            for message_id in delete_message_ids:
                cursor.execute("DELETE FROM messages WHERE id = ?", (message_id,))
            cursor.execute(
                """
                INSERT INTO messages (id, session_id, role, content, model, provider, tool_calls, tool_call_id, reasoning_content, step_index, activated_skills, compact_info, memory_refs, rag_citations, sources, created_at, segment_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    continuation_message.id,
                    continuation_message.session_id,
                    continuation_message.role,
                    continuation_message.content,
                    continuation_message.model,
                    continuation_message.provider,
                    continuation_message.tool_calls,
                    continuation_message.tool_call_id,
                    continuation_message.reasoning_content,
                    continuation_message.step_index,
                    continuation_message.activated_skills,
                    continuation_message.compact_info,
                    continuation_message.memory_refs,
                    continuation_message.rag_citations,
                    continuation_message.sources,
                    continuation_message.created_at,
                    getattr(continuation_message, "segment_id", 0) or 0,
                ),
            )
            cursor.execute(
                "UPDATE sessions SET message_count = ?, updated_at = ? WHERE id = ?",
                (new_message_count, now, session_id),
            )
            # SE1 压缩事件：前缀删除以一等事件落日志（而非旁路消失），
            # 与删除/续接插入同事务，杜绝"历史已删、事件未记"窗口。
            # 续接消息本身也是模型可见行，同样落 message.appended 事件
            # （它不走 save()，必须在此显式补事件）。
            from backend.data.session_event_repo import (
                EVENT_COMPACTION_PERFORMED,
                EVENT_MESSAGE_APPENDED,
            )

            _append_session_event(
                cursor,
                session_id,
                EVENT_COMPACTION_PERFORMED,
                payload={
                    "deleted_ids": list(delete_message_ids),
                    "continuation_id": continuation_message.id,
                    "removed_count": len(delete_message_ids),
                    "reason": "compaction",
                    "created_at": now,
                },
            )
            _append_session_event(
                cursor,
                session_id,
                EVENT_MESSAGE_APPENDED,
                payload={
                    "id": continuation_message.id,
                    "role": continuation_message.role,
                    "content": continuation_message.content,
                    "subtype": getattr(continuation_message, "subtype", None),
                    "segment_id": getattr(continuation_message, "segment_id", 0) or 0,
                    "tool_calls": continuation_message.tool_calls,
                    "created_at": continuation_message.created_at,
                },
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        # Round 2: 压缩续接消息同步全文索引（事务外 best-effort）
        try:
            from backend.data.message_search import get_message_search_index

            get_message_search_index().index_message(
                continuation_message.id,
                continuation_message.session_id,
                continuation_message.role,
                continuation_message.content,
                continuation_message.created_at,
            )
        except Exception as exc:  # noqa: BLE001 — 索引故障不影响压缩
            logger.warning("压缩续接消息索引挂钩失败: %s", exc)

    def get_by_session(self, session_id: str, limit: int = 100, offset: int = 0) -> List[Message]:
        """获取会话消息列表"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM messages
            WHERE session_id = ?
            ORDER BY created_at ASC
            LIMIT ? OFFSET ?
        """,
            (session_id, limit, offset),
        )

        return [Message.from_row(row) for row in cursor.fetchall()]

    def get(self, message_id: str) -> Optional[Message]:
        """获取单条消息"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
        row = cursor.fetchone()

        if row:
            return Message.from_row(row)
        return None

    def delete(self, message_id: str) -> bool:
        """删除消息"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 先取 session_id（删后就查不到了），再删行
        session_id = self._session_id_of(message_id, cursor)
        cursor.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        # SE1 同事务事件双写（best-effort，失败仅告警）
        from backend.data.session_event_repo import EVENT_MESSAGE_DELETED

        _append_session_event(
            cursor,
            session_id,
            EVENT_MESSAGE_DELETED,
            payload={"id": message_id, "reason": "message_delete"},
        )
        conn.commit()

        return cursor.rowcount > 0

    @staticmethod
    def _session_id_of(message_id: str, cursor: Any) -> str:
        """查消息所属会话（删除事件需要 session_id 定位日志）。"""
        cursor.execute("SELECT session_id FROM messages WHERE id = ?", (message_id,))
        row = cursor.fetchone()
        return str(row[0]) if row and row[0] is not None else ""

    def delete_by_session(self, session_id: str) -> int:
        """删除会话的所有消息"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.commit()

        return cursor.rowcount

    def insert(
        self,
        session_id: str,
        role: str,
        content: str,
        created_at: int,
        segment_id: Optional[int] = None,
        subtype: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert a new message row and return the inserted record.

        The scheduler uses this to deliver one-shot/recurring task content
        into the target session. We deliberately bypass the LLM/agent path
        because scheduled messages are pre-formed (no streaming).

        SE1 (win7 对齐 main 语义): ``segment_id`` / ``subtype`` 可选 ——
        不传则绑定当前活跃段（旧行为不变）；advance_segment 传显式值以
        单事务落标记，消除 INSERT→UPDATE 两步之间的崩溃窗口。
        """
        message_id = f"msg-{uuid.uuid4().hex[:12]}"
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Task 1 (2026-09-17): 写入时绑定当前活跃 segment_id
        active_segment_id = self.get_active_segment_id(session_id)
        seg = active_segment_id if segment_id is None else segment_id

        cursor.execute(
            "INSERT INTO messages (id, session_id, role, content, created_at, segment_id, subtype) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (message_id, session_id, role, content, created_at, seg, subtype),
        )

        # SE1 同事务事件双写（best-effort，失败仅告警）
        from backend.data.session_event_repo import EVENT_MESSAGE_APPENDED

        _append_session_event(
            cursor,
            session_id,
            EVENT_MESSAGE_APPENDED,
            payload={
                "id": message_id,
                "role": role,
                "content": content,
                "subtype": subtype,
                "segment_id": seg,
                "tool_calls": None,
                "created_at": created_at,
            },
        )

        conn.commit()
        # Round 2: 定时消息同步全文索引（best-effort）
        try:
            from backend.data.message_search import get_message_search_index

            get_message_search_index().index_message(
                message_id, session_id, role, content, created_at
            )
        except Exception as exc:  # noqa: BLE001 — 索引故障不影响写入
            logger.warning("定时消息索引挂钩失败: %s", exc)
        return {"id": message_id}

    def get_active_segment(self, session_id: str) -> List[Message]:
        """Return messages after the last topic_separator (context-isolation)."""
        all_msgs = self.get_by_session(session_id, limit=100000)
        last_sep_idx = -1
        for i in range(len(all_msgs) - 1, -1, -1):
            if all_msgs[i].subtype == "topic_separator":
                last_sep_idx = i
                break
        return all_msgs[last_sep_idx + 1:]

    def get_active_segment_id(self, session_id: str) -> int:
        """获取当前会话最新的 segment_id（如果不存在消息则返回 0）。

        用于 L13 记忆上下文注入等场景，避免依赖 ``history_rows[-1].segment_id``
        的脆弱推导（需要确保 history_rows 非空且最后一条携带正确 segment_id）。
        直接查询 MAX(segment_id) 更健壮、语义更明确。

        Args:
            session_id: 会话 ID

        Returns:
            当前活跃段 id（0 表示初始段或无消息）
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(MAX(segment_id), 0) FROM messages WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def advance_segment(self, session_id: str) -> int:
        """Insert a topic_separator message and return the new segment_id.

        SE1 (win7 对齐 main 单事务语义): 直接 INSERT 一条带
        ``segment_id=new_seg, subtype='topic_separator'`` 的 system 消息。
        旧实现分 INSERT → UPDATE 两步,中间进程崩溃会留下没标记的 system
        消息,下一次 ``get_active_segment()`` 无法识别本次上下文重置。

        Flow: query current max segment_id → INSERT fully-marked separator
        in one atomic write. Returns the new segment_id (0-based, incremented).
        """
        all_msgs = self.get_by_session(session_id, limit=100000)
        max_seg = max((m.segment_id for m in all_msgs), default=-1)
        new_seg = max_seg + 1
        self.insert(
            session_id=session_id,
            role="system",
            content="[上下文已在此处重置]",
            created_at=int(time.time() * 1000),
            segment_id=new_seg,
            subtype="topic_separator",
        )
        return new_seg
        return new_seg

    def retreat_segment(self, session_id: str) -> bool:
        """Remove the last topic_separator (if any) and merge segments.

        Returns True if a separator was deleted, False if none existed.
        Used for 'undo' on false-positive auto-detection of topic shifts.
        """
        all_msgs = self.get_by_session(session_id, limit=100000)
        for i in range(len(all_msgs) - 1, -1, -1):
            if all_msgs[i].subtype == "topic_separator":
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM messages WHERE id = ?", (all_msgs[i].id,))
                # SE1 同事务事件双写：separator 删除也要落事件，否则事件
                # 投影仍会在已删除的 separator 处切片（与 messages 分叉）。
                from backend.data.session_event_repo import EVENT_MESSAGE_DELETED

                _append_session_event(
                    cursor,
                    session_id,
                    EVENT_MESSAGE_DELETED,
                    payload={"id": all_msgs[i].id, "reason": "segment_retreat"},
                )
                conn.commit()
                return True
        return False
