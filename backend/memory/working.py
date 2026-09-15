"""
Working Memory - 工作记忆模块
当前对话上下文，滑动窗口机制

支持 SQLite 持久化：进程内消息队列保持高性能，同时按会话快照到 SQLite，
确保重启后工作记忆不丢失。

Session 感知（WS-A）：
- 每条消息携带 session_id，容量约束（max_size / max_tokens）**按 session 各自计数淘汰**，
  多会话共享一个 WorkingMemory 实例时互不串味；
- API（add / get_context / get_recent / clear / total_tokens_for）均接受可选 session_id，
  session_id=None 归一为 "default" 会话（若构造时绑定了 session_id 则归于绑定会话），
  旧的无参/单 dict 调用方式保持兼容；
- 快照按 session_id 分行写入/恢复（写真实值，不再写 NULL）。
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_SESSION_ID = "default"


def normalize_session_id(session_id: Optional[str]) -> str:
    """归一化会话 ID：None / 空字符串 → "default"。"""
    if session_id is None or session_id == "":
        return DEFAULT_SESSION_ID
    return str(session_id)


def estimate_tokens(text: str) -> int:
    """
    估算文本的 Token 数量（中文约 1 字符 = 1 Token，英文约 4 字符 = 1 Token）

    模块级函数，供 WorkingMemory 与会话压缩 (backend/chat/compaction.py)
    共用同一套估算口径，避免多处实现漂移。

    Args:
        text: 输入文本

    Returns:
        估算的 Token 数量
    """
    # 简单估算：中文按字符计，英文按单词计
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other_chars = len(text) - chinese_chars
    return chinese_chars + other_chars // 4 + len(text) // 4


class WorkingMemory:
    """
    工作记忆 - 管理当前对话的上下文信息

    特性:
    - 基于 deque 实现滑动窗口（容量按 session 各自计数）
    - 支持最大消息数量限制（per-session）
    - 支持 Token 数量估算（per-session）
    - 自动淘汰旧消息（仅淘汰超限会话自身的旧消息）
    - 可选的 SQLite 持久化（传入 db 参数启用），快照按 session 分行
    - Session 感知：方法接受可选 session_id；构造时传入的 session_id
      作为实例默认会话（兼容旧的绑定式用法）
    """

    def __init__(
        self,
        max_size: int = 20,
        max_tokens: int = 4000,
        db: Optional[Any] = None,
        session_id: Optional[str] = None,
    ):
        """
        初始化工作记忆

        Args:
            max_size: 单个会话的最大消息数量
            max_tokens: 单个会话的最大 Token 数量（估算值）
            db: 可选的 Database 实例，传入后启用持久化
            session_id: 可选的绑定会话 ID。传入后，无参调用
                （add/get_context/clear 等）默认作用于该会话（兼容旧 API）；
                不传时为"未绑定"实例，无参调用作用于 "default" 会话，
                会话维度完全由方法参数表达（推荐用法，见 registry 单例）。
        """
        self.max_size = max_size
        self.max_tokens = max_tokens
        self._db = db
        # 构造时绑定的会话（None = 未绑定，无参调用落于 "default"）
        self._bound_sid: Optional[str] = (
            normalize_session_id(session_id) if session_id is not None else None
        )

        # 扁平消息队列：元素为携带 session_id 字段的消息 dict。
        # 不设 maxlen——容量约束由按 session 的手动淘汰控制。
        self._messages: deque = deque()
        # 全局 token 合计（向后兼容属性，可外部读写；按 session 统计见 total_tokens_for）
        self.total_tokens: int = 0
        # 按 session 的统计与辅助状态
        self._session_tokens: Dict[str, int] = {}
        self._session_seq: Dict[str, int] = {}
        self._summaries: Dict[str, str] = {}
        self._entities: Dict[str, List[str]] = {}
        self._variables: Dict[str, Dict[str, Any]] = {}

        # 如果提供了数据库，从快照恢复
        if self._db is not None:
            self._load_snapshot()

    # ==================== 内部工具 ====================

    def _resolve(self, session_id: Optional[str]) -> str:
        """解析生效会话：显式参数 > 构造绑定会话 > "default"。"""
        if session_id is not None and session_id != "":
            return str(session_id)
        return self._bound_sid or DEFAULT_SESSION_ID

    def resolve_session_id(self, session_id: Optional[str]) -> str:
        """解析生效会话 ID 的公开入口（供 MemoryManager 等上层合成 id 使用）。"""
        return self._resolve(session_id)

    def _session_messages(self, sid: str) -> List[Dict[str, Any]]:
        """取指定 session 的消息列表（保持插入序）。"""
        return [m for m in self._messages if m.get("session_id") == sid]

    # -------------------- 向后兼容属性视图 --------------------

    @property
    def messages(self):
        """消息队列视图。

        未绑定实例：返回完整扁平队列（deque，向后兼容）；
        绑定实例：仅返回绑定会话的消息列表。
        """
        if self._bound_sid is None:
            return self._messages
        return self._session_messages(self._bound_sid)

    @property
    def session_summary(self) -> str:
        return self._summaries.get(self._resolve(None), "")

    @session_summary.setter
    def session_summary(self, value: str) -> None:
        self._summaries[self._resolve(None)] = value

    @property
    def active_entities(self) -> List[str]:
        return self._entities.setdefault(self._resolve(None), [])

    @property
    def temp_variables(self) -> Dict[str, Any]:
        return self._variables.setdefault(self._resolve(None), {})

    # ==================== 核心 API ====================

    def add(self, session_id: Optional[Any] = None, message: Optional[Dict[str, Any]] = None) -> int:
        """
        添加消息到工作记忆

        支持两种调用形态：
        - 新形态：``add(session_id, message)``
        - 旧形态：``add(message)``（单个 dict 参数，落入默认/绑定会话）

        Args:
            session_id: 会话 ID（旧形态下该位置为消息 dict）
            message: 消息字典，包含 role, content 等字段

        Returns:
            该消息在所属会话内的自增序号（上层可据此合成 ``wm:<sid>:<seq>`` id）
        """
        # 兼容旧签名 add(message)：单个 dict 参数视为消息
        if message is None and isinstance(session_id, dict):
            session_id, message = None, session_id
        if message is None:
            message = {}

        sid = self._resolve(session_id)
        content = message.get("content", "")
        tokens = self._estimate_tokens(content)

        seq = self._session_seq.get(sid, 0) + 1
        self._session_seq[sid] = seq

        self._messages.append(
            {
                "session_id": sid,
                "role": message.get("role", "unknown"),
                "content": content,
                "tokens": tokens,
                "timestamp": time.time(),
                "seq": seq,
            }
        )

        self._session_tokens[sid] = self._session_tokens.get(sid, 0) + tokens
        self.total_tokens += tokens

        # 按 session 各自淘汰
        self._evict_session(sid)

        # 持久化到 SQLite
        self._save_snapshot(sid)

        logger.debug(
            f"工作记忆状态: session={sid}, "
            f"消息数={len(self._session_messages(sid))}, "
            f"Tokens={self._session_tokens.get(sid, 0)}/{self.max_tokens}"
        )
        return seq

    def _estimate_tokens(self, text: str) -> int:
        """
        估算文本的 Token 数量（委托给模块级 ``estimate_tokens``）

        Args:
            text: 输入文本

        Returns:
            估算的 Token 数量
        """
        return estimate_tokens(text)

    def _evict_session(self, sid: str) -> None:
        """按 session 淘汰：该会话自身超出 max_size / max_tokens 时移除其最旧消息。

        不影响其他会话的消息。
        """
        while True:
            session_msgs = self._session_messages(sid)
            if len(session_msgs) <= 1:
                break
            if (
                len(session_msgs) <= self.max_size
                and self._session_tokens.get(sid, 0) <= self.max_tokens
            ):
                break
            oldest = session_msgs[0]
            self._messages.remove(oldest)
            evicted_tokens = oldest.get("tokens", 0)
            self._session_tokens[sid] = self._session_tokens.get(sid, 0) - evicted_tokens
            self.total_tokens -= evicted_tokens

    def get_context(
        self, session_id: Optional[Any] = None, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        获取指定会话的当前上下文

        旧形态兼容：单个 int 参数视为 limit（即旧 ``get_context(limit)``）。

        Args:
            session_id: 会话 ID（None → 默认/绑定会话）
            limit: 可选，限制返回的消息数量

        Returns:
            消息列表
        """
        if isinstance(session_id, int):
            session_id, limit = None, session_id
        sid = self._resolve(session_id)
        msgs = self._session_messages(sid)
        if limit is None:
            return msgs
        return msgs[-limit:]

    def get_recent(self, session_id: Optional[Any] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """
        获取指定会话最近 N 条消息

        旧形态兼容：单个 int 参数视为 limit（即旧 ``get_recent(limit)``）。

        Args:
            session_id: 会话 ID（None → 默认/绑定会话）
            limit: 消息数量

        Returns:
            最近的消息列表
        """
        if isinstance(session_id, int):
            session_id, limit = None, session_id
        sid = self._resolve(session_id)
        return self._session_messages(sid)[-limit:]

    def clear(self, session_id: Optional[str] = None) -> None:
        """
        清空指定会话的工作记忆

        Args:
            session_id: 会话 ID（None → 默认/绑定会话）
        """
        sid = self._resolve(session_id)
        self._messages = deque(m for m in self._messages if m.get("session_id") != sid)
        self.total_tokens -= self._session_tokens.pop(sid, 0)
        self._summaries.pop(sid, None)
        self._entities.pop(sid, None)
        self._variables.pop(sid, None)
        # 持久化清空状态
        self._save_snapshot(sid)

    def total_tokens_for(self, session_id: Optional[str] = None) -> int:
        """
        获取指定会话的估算 Token 数量

        Args:
            session_id: 会话 ID（None → 默认/绑定会话）

        Returns:
            该会话的 Token 估算值
        """
        return self._session_tokens.get(self._resolve(session_id), 0)

    def session_ids(self) -> List[str]:
        """列出当前持有消息的全部 session ID（有序）。"""
        return sorted({m.get("session_id", DEFAULT_SESSION_ID) for m in self._messages})

    def set_summary(self, summary: str, session_id: Optional[str] = None) -> None:
        """
        设置会话摘要

        Args:
            summary: 摘要文本
            session_id: 会话 ID（None → 默认/绑定会话）
        """
        self._summaries[self._resolve(session_id)] = summary

    def get_summary(self, session_id: Optional[str] = None) -> str:
        """
        获取会话摘要

        Args:
            session_id: 会话 ID（None → 默认/绑定会话）

        Returns:
            摘要文本，如果未设置则返回默认描述
        """
        sid = self._resolve(session_id)
        summary = self._summaries.get(sid, "")
        if summary:
            return summary
        return f"[{len(self._session_messages(sid))} 条消息, ~{self._session_tokens.get(sid, 0)} tokens]"

    def add_entity(self, entity: str, session_id: Optional[str] = None) -> None:
        """
        添加活跃实体

        Args:
            entity: 实体名称
            session_id: 会话 ID（None → 默认/绑定会话）
        """
        entities = self._entities.setdefault(self._resolve(session_id), [])
        if entity not in entities:
            entities.append(entity)

    def set_variable(self, key: str, value: Any, session_id: Optional[str] = None) -> None:
        """
        设置临时变量

        Args:
            key: 变量名
            value: 变量值
            session_id: 会话 ID（None → 默认/绑定会话）
        """
        self._variables.setdefault(self._resolve(session_id), {})[key] = value

    def get_variable(self, key: str, default: Any = None, session_id: Optional[str] = None) -> Any:
        """
        获取临时变量

        Args:
            key: 变量名
            default: 默认值
            session_id: 会话 ID（None → 默认/绑定会话）

        Returns:
            变量值
        """
        return self._variables.get(self._resolve(session_id), {}).get(key, default)

    # ==================== 持久化方法 ====================

    def _save_snapshot(self, session_id: Optional[str] = None) -> None:
        """将指定会话的工作记忆快照保存到 SQLite

        按 session_id 分行写入真实会话值（不再写 NULL）。
        如果未配置数据库则静默跳过。写入失败只记录日志不抛异常。
        """
        if self._db is None:
            return

        sid = self._resolve(session_id)
        try:
            conn = self._db.get_connection()
            # 先清空该会话的旧快照
            conn.execute(
                "DELETE FROM working_memory_snapshot WHERE session_id = ?",
                (sid,),
            )
            # 插入该会话当前所有消息
            now_ms = int(time.time() * 1000)
            for msg in self._session_messages(sid):
                conn.execute(
                    """INSERT INTO working_memory_snapshot
                       (session_id, role, content, tokens, timestamp, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        sid,
                        msg.get("role", "unknown"),
                        msg.get("content", ""),
                        msg.get("tokens", 0),
                        msg.get("timestamp", 0.0),
                        now_ms,
                    ),
                )
            conn.commit()
            logger.debug(
                f"工作记忆快照已保存: session={sid}, 消息数={len(self._session_messages(sid))}"
            )
        except Exception as e:
            logger.warning(f"保存工作记忆快照失败: {e}")

    def _load_snapshot(self) -> None:
        """从 SQLite 恢复工作记忆快照

        - 绑定实例：只恢复绑定会话（WHERE session_id = 绑定值）；
        - 未绑定实例：恢复全部**具名**会话（session_id 非 NULL 且非 "default"）。
          默认会话不自动恢复，以保持 registry 单例"启动即空"的既有行为
          （旧实现因 ``session_id = NULL`` 比较恒假，事实上也从不恢复）。

        如果未配置数据库或表为空则静默跳过。加载失败只记录日志不抛异常。
        """
        if self._db is None:
            return

        try:
            conn = self._db.get_connection()
            if self._bound_sid is not None:
                cursor = conn.execute(
                    """SELECT session_id, role, content, tokens, timestamp
                       FROM working_memory_snapshot
                       WHERE session_id = ?
                       ORDER BY id ASC""",
                    (self._bound_sid,),
                )
            else:
                cursor = conn.execute(
                    """SELECT session_id, role, content, tokens, timestamp
                       FROM working_memory_snapshot
                       WHERE session_id IS NOT NULL AND session_id != ?
                       ORDER BY id ASC""",
                    (DEFAULT_SESSION_ID,),
                )
            rows = cursor.fetchall()
            for row in rows:
                sid = row["session_id"] or DEFAULT_SESSION_ID
                tokens = row["tokens"]
                seq = self._session_seq.get(sid, 0) + 1
                self._session_seq[sid] = seq
                self._messages.append(
                    {
                        "session_id": sid,
                        "role": row["role"],
                        "content": row["content"],
                        "tokens": tokens,
                        "timestamp": row["timestamp"],
                        "seq": seq,
                    }
                )
                self._session_tokens[sid] = self._session_tokens.get(sid, 0) + tokens
                self.total_tokens += tokens
            # 确保各会话不超过容量限制（以小阈值恢复时调整）
            for sid in list(self._session_tokens.keys()):
                self._evict_session(sid)
            if rows:
                logger.info(
                    f"工作记忆快照已恢复: sessions={self.session_ids()}, "
                    f"总消息数={len(self._messages)}, tokens={self.total_tokens}"
                )
        except Exception as e:
            logger.warning(f"加载工作记忆快照失败: {e}")
