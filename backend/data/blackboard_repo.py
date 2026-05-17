"""
Blackboard Repository - Agent 间通信共享黑板
基于 SQLite 的发布/订阅模式
"""
import json
import time
import uuid
import logging
from typing import List, Dict, Any, Optional

from backend.data.database import get_database

logger = logging.getLogger(__name__)


class BlackboardRepo:
    """
    黑板数据仓库 - Agent 间通信
    """

    def __init__(self, db=None):
        self.db = db or get_database()
        self.ensure_table()

    def ensure_table(self):
        """确保黑板表存在"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_blackboard (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                message_type TEXT NOT NULL,
                content TEXT NOT NULL,
                target_agent TEXT,
                created_at INTEGER NOT NULL,
                read_by TEXT DEFAULT '[]',
                expires_at INTEGER
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_blackboard_session ON agent_blackboard(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_blackboard_target ON agent_blackboard(target_agent, session_id)")

        conn.commit()

    def publish(
        self,
        session_id: str,
        agent_name: str,
        message_type: str,
        content: Dict[str, Any],
        target_agent: Optional[str] = None,
        ttl_seconds: Optional[int] = None
    ) -> str:
        """发布消息到黑板"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        message_id = str(uuid.uuid4())
        now = int(time.time())
        expires_at = (now + ttl_seconds) if ttl_seconds else None

        cursor.execute("""
            INSERT INTO agent_blackboard
            (id, session_id, agent_name, message_type, content, target_agent, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            message_id, session_id, agent_name, message_type,
            json.dumps(content, ensure_ascii=False), target_agent, now, expires_at
        ))

        conn.commit()
        logger.debug(f"黑板发布: {agent_name} -> {message_type}")
        return message_id

    def subscribe(
        self,
        agent_name: str,
        session_id: str,
        message_type: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """订阅黑板消息"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        now = int(time.time())
        sql = """
            SELECT * FROM agent_blackboard
            WHERE session_id = ?
            AND (target_agent IS NULL OR target_agent = ?)
            AND (expires_at IS NULL OR expires_at > ?)
        """
        params = [session_id, agent_name, now]

        if message_type:
            sql += " AND message_type = ?"
            params.append(message_type)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(sql, params)

        results = []
        for row in cursor.fetchall():
            msg = dict(row)
            try:
                msg["content"] = json.loads(msg["content"])
            except (json.JSONDecodeError, TypeError):
                pass
            try:
                msg["read_by"] = json.loads(msg.get("read_by", "[]"))
            except (json.JSONDecodeError, TypeError):
                msg["read_by"] = []
            results.append(msg)

        return results

    def mark_read(self, message_id: str, agent_name: str) -> bool:
        """标记消息已读"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT read_by FROM agent_blackboard WHERE id = ?", (message_id,))
        row = cursor.fetchone()
        if not row:
            return False

        read_by = json.loads(row["read_by"]) if row["read_by"] else []
        if agent_name not in read_by:
            read_by.append(agent_name)

        cursor.execute(
            "UPDATE agent_blackboard SET read_by = ? WHERE id = ?",
            (json.dumps(read_by), message_id)
        )
        conn.commit()
        return True

    def clean_expired(self) -> int:
        """清理过期消息"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        now = int(time.time())
        cursor.execute(
            "DELETE FROM agent_blackboard WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,)
        )
        conn.commit()
        return cursor.rowcount

    def get_session_messages(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """获取会话的所有黑板消息"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM agent_blackboard
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (session_id, limit))

        results = []
        for row in cursor.fetchall():
            msg = dict(row)
            try:
                msg["content"] = json.loads(msg["content"])
            except (json.JSONDecodeError, TypeError):
                pass
            results.append(msg)

        return results
