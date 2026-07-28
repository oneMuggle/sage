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


def fork_session(
    session_repo: SessionRepository,
    message_repo: MessageRepository,
    source_id: str,
    at_message_id: Optional[str] = None,
    title: Optional[str] = None,
) -> Session:
    """从源会话分叉出一个新会话（M4，全量前缀复制）。

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

    new_session = session_repo.create(title=title or f"Fork: {source.title}")

    # 逐条复制：新 id + 原 created_at。插入顺序 = 源顺序，
    # messages 表 ORDER BY created_at ASC（同值按 rowid）保持序。
    for src_msg in prefix:
        message_repo.save(
            Message(
                id=f"msg-{uuid.uuid4().hex[:12]}",
                session_id=new_session.id,
                role=src_msg.role,
                content=src_msg.content,
                created_at=src_msg.created_at,
                model=src_msg.model,
                provider=src_msg.provider,
                tool_calls=src_msg.tool_calls,
                tool_call_id=src_msg.tool_call_id,
                reasoning_content=src_msg.reasoning_content,
            )
        )

    update_fields: Dict[str, Any] = {"fork_root": source.id, "message_count": len(prefix)}
    if at_message_id is not None:
        update_fields["forked_at_message_id"] = at_message_id
    if prefix:
        update_fields["last_message_at"] = prefix[-1].created_at
    session_repo.update(new_session.id, **update_fields)

    forked = session_repo.get(new_session.id)
    assert forked is not None  # 刚 create 的会话必然存在
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
