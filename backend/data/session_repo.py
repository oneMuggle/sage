"""
会话仓储层
负责会话的 CRUD 操作
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.data.database import get_database


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

    def get(self, session_id: str) -> Session | None:
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
            ORDER BY is_pinned DESC, updated_at DESC
            LIMIT ? OFFSET ?
        """,
            (limit, offset),
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

    @classmethod
    def from_row(cls, row) -> Message:
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
        }


class ForkSourceNotFoundError(LookupError):
    """分叉源不存在（会话或分叉点消息）。

    ``kind`` 取值 ``"session"`` / ``"message"``，路由层据此生成结构化 404。
    """

    def __init__(self, kind: str, ident: str):
        self.kind = kind
        self.ident = ident
        super().__init__(f"fork source {kind} not found: {ident}")


def _insert_forked_message_row(cursor: Any, session_id: str, src_msg: Message) -> None:
    """在给定 cursor 的当前事务中插入一条 fork 复制的消息行。

    独立成模块级函数是为了给测试留 seam：monkeypatch 本函数即可模拟
    "复制到一半失败"，验证 fork 事务的整体回滚（MEDIUM-2）。
    """
    cursor.execute(
        """
        INSERT INTO messages (id, session_id, role, content, model, provider, tool_calls, tool_call_id, reasoning_content, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            f"msg-{uuid.uuid4().hex[:12]}",  # 新 id，避免与源消息主键冲突
            session_id,
            src_msg.role,
            src_msg.content,
            src_msg.model,
            src_msg.provider,
            src_msg.tool_calls,
            src_msg.tool_call_id,
            src_msg.reasoning_content,
            src_msg.created_at,  # 保留原时间戳 → ORDER BY created_at ASC 保序
        ),
    )


def fork_session(
    session_repo: SessionRepository,
    message_repo: MessageRepository,
    source_id: str,
    at_message_id: Optional[str] = None,
    title: Optional[str] = None,
) -> Session:
    """从源会话分叉出一个新会话（M4，全量前缀复制，单事务原子落盘）。

    刻意偏离计划文档的 copy-on-write 设计：桌面级会话只有数百条消息，
    全量复制更简单、更安全（读写路径零特判）；CoW 推迟到真正出现
    存储压力时再做。

    语义:
        - 复制源会话中 ``at_message_id`` 及之前的全部消息；``at_message_id``
          省略时复制全部消息。
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
        prefix = all_messages[: cut_index + 1]  # 含分叉点本身
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
        for src_msg in prefix:
            _insert_forked_message_row(cursor, new_session_id, src_msg)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    forked = session_repo.get(new_session_id)
    if forked is None:  # pragma: no cover — 刚 commit 的会话必然可读
        raise RuntimeError(
            f"fork_session: new session {new_session_id} missing right after commit"
        )
    return forked


class MessageRepository:
    """消息仓储"""

    def __init__(self):
        self.db = get_database()

    def save(self, message: Message) -> Message:
        """保存消息"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO messages (id, session_id, role, content, model, provider, tool_calls, tool_call_id, reasoning_content, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                message.created_at,
            ),
        )

        conn.commit()
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
            # sqlite3 默认在首个 DML 处隐式 BEGIN，commit() 前所有语句
            # 同属一个事务；循环逐条 DELETE 避免 IN (?) 占位符数量上限。
            for message_id in delete_message_ids:
                cursor.execute("DELETE FROM messages WHERE id = ?", (message_id,))
            cursor.execute(
                """
                INSERT INTO messages (id, session_id, role, content, model, provider, tool_calls, tool_call_id, reasoning_content, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    continuation_message.created_at,
                ),
            )
            cursor.execute(
                "UPDATE sessions SET message_count = ?, updated_at = ? WHERE id = ?",
                (new_message_count, now, session_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

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

    def get(self, message_id: str) -> Message | None:
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

        cursor.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()

        return cursor.rowcount > 0

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
    ) -> Dict[str, Any]:
        """Insert a new message row and return the inserted record.

        The scheduler uses this to deliver one-shot/recurring task content
        into the target session. We deliberately bypass the LLM/agent path
        because scheduled messages are pre-formed (no streaming).
        """
        message_id = f"msg-{uuid.uuid4().hex[:12]}"
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO messages (id, session_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (message_id, session_id, role, content, created_at),
        )
        conn.commit()
        return {"id": message_id}
