"""
会话仓储层
负责会话的 CRUD 操作
"""
import json
import time
import uuid
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

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
    
    @classmethod
    def from_row(cls, row) -> "Session":
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
        
        cursor.execute("""
            INSERT INTO sessions (id, title, created_at, updated_at, parent_id)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, title, now, now, parent_id))
        
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
        
        cursor.execute("""
            SELECT * FROM sessions
            WHERE is_archived = 0
            ORDER BY is_pinned DESC, updated_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        
        return [Session.from_row(row) for row in cursor.fetchall()]
    
    def update(self, session_id: str, **kwargs) -> bool:
        """更新会话"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        if not kwargs:
            return False
        
        now = int(time.time() * 1000)
        kwargs["updated_at"] = now
        
        set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [session_id]
        
        cursor.execute(f"""
            UPDATE sessions SET {set_clause} WHERE id = ?
        """, values)
        
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

    @classmethod
    def from_row(cls, row) -> "Message":
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
        }


class MessageRepository:
    """消息仓储"""

    def __init__(self):
        self.db = get_database()

    def save(self, message: Message) -> Message:
        """保存消息"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO messages (id, session_id, role, content, model, provider, tool_calls, tool_call_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            message.id,
            message.session_id,
            message.role,
            message.content,
            message.model,
            message.provider,
            message.tool_calls,
            message.tool_call_id,
            message.created_at,
        ))

        conn.commit()
        return message

    def get_by_session(self, session_id: str, limit: int = 100, offset: int = 0) -> List[Message]:
        """获取会话消息列表"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM messages
            WHERE session_id = ?
            ORDER BY created_at ASC
            LIMIT ? OFFSET ?
        """, (session_id, limit, offset))

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
