"""
Convention Manager - 惯例管理
从交互模式中提取、评估和激活行为惯例
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.core.legacy.llm_client import LLMClient
from backend.data.database import get_database

logger = logging.getLogger(__name__)


@dataclass
class Convention:
    """惯例规则"""

    id: str
    name: str
    description: str
    category: str  # "coding", "communication", "memory", "tool_usage"
    confidence: float = 0.5
    usage_count: int = 0
    created_at: int = field(default_factory=lambda: int(time.time()))
    last_updated: int = field(default_factory=lambda: int(time.time()))
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "confidence": self.confidence,
            "usage_count": self.usage_count,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "is_active": self.is_active,
        }


class ConventionManager:
    """
    惯例管理器

    职责:
    - 从 LLM 分析中提取用户惯例
    - 管理惯例的生命周期 (创建、更新、衰减、停用)
    - 为 Agent 提供惯例上下文注入
    """

    CONFIDENCE_THRESHOLD = 0.7
    DECAY_FACTOR = 0.9
    MIN_CONFIDENCE = 0.1

    def __init__(self, llm_client: LLMClient | None = None):
        self.db = get_database()
        self.llm_client = llm_client
        self._ensure_table()

    def _ensure_table(self):
        """确保惯例表存在"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conventions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                usage_count INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL,
                last_updated INTEGER NOT NULL,
                is_active INTEGER DEFAULT 1
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_conventions_category ON conventions(category)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_conventions_confidence ON conventions(confidence)"
        )
        conn.commit()

    # ========== CRUD ==========

    def add(self, convention: Convention) -> str:
        """添加新惯例"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO conventions
            (id, name, description, category, confidence, usage_count, created_at, last_updated, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                convention.id,
                convention.name,
                convention.description,
                convention.category,
                convention.confidence,
                convention.usage_count,
                convention.created_at,
                convention.last_updated,
                int(convention.is_active),
            ),
        )
        conn.commit()
        logger.info(f"惯例添加: {convention.name} (confidence={convention.confidence})")
        return convention.id

    def update(self, convention_id: str, **kwargs) -> bool:
        """更新惯例"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        allowed = {"name", "description", "confidence", "usage_count", "is_active"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False

        updates["last_updated"] = int(time.time())
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [convention_id]

        cursor.execute(f"UPDATE conventions SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return cursor.rowcount > 0

    def get(self, convention_id: str) -> Convention | None:
        """获取单个惯例"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM conventions WHERE id = ?", (convention_id,))
        row = cursor.fetchone()
        if not row:
            return None
        row["is_active"] = bool(row["is_active"])
        return Convention(**dict(row))

    def get_active(self, category: str | None = None) -> list[Convention]:
        """获取活跃惯例"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        sql = "SELECT * FROM conventions WHERE is_active = 1"
        params = []
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY confidence DESC"

        cursor.execute(sql, params)
        results = []
        for row in cursor.fetchall():
            row["is_active"] = bool(row["is_active"])
            results.append(Convention(**dict(row)))
        return results

    def delete(self, convention_id: str) -> bool:
        """删除惯例"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM conventions WHERE id = ?", (convention_id,))
        conn.commit()
        return cursor.rowcount > 0

    # ========== 上下文注入 ==========

    def get_context_prompt(self) -> str:
        """获取注入到 Agent system prompt 的惯例文本"""
        conventions = self.get_active()
        if not conventions:
            return ""

        parts = []
        for c in conventions:
            parts.append(f"- [{c.category.upper()}] {c.name}: {c.description}")
        return "\n用户惯例:\n" + "\n".join(parts)

    # ========== LLM 驱动学习 ==========

    async def learn_from_conversation(self, messages: list[dict[str, Any]]) -> list[str]:
        """从对话中提取新惯例"""
        if not self.llm_client:
            return []

        try:
            user_msgs = [m for m in messages if m.get("role") == "user"][-5:]
            if not user_msgs:
                return []

            system_prompt = """你是一个惯例发现器。分析用户消息，发现用户的行为习惯或偏好。
类别: coding(编码习惯), communication(沟通习惯), memory(记忆管理), tool_usage(工具使用)。
回复 JSON 数组: [{"name": "名称", "description": "描述", "category": "类别"}]
只回复 JSON。"""

            text = "\n".join(f"- {m['content']}" for m in user_msgs)
            response = await self.llm_client.chat(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ]
            )

            items = json.loads(response.content)
            if not isinstance(items, list):
                return []

            new_ids = []
            for item in items:
                name = item.get("name", "")
                if not name:
                    continue
                existing = self._find_by_name(name)
                if existing:
                    self.update(existing.id, usage_count=existing.usage_count + 1)
                    continue

                c = Convention(
                    id=str(uuid.uuid4()),
                    name=name,
                    description=item.get("description", ""),
                    category=item.get("category", "communication"),
                    confidence=0.6,
                )
                new_ids.append(self.add(c))

            return new_ids
        except Exception as e:
            logger.warning(f"惯例学习失败: {e}")
            return []

    def _find_by_name(self, name: str) -> Convention | None:
        """按名称查找惯例"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM conventions WHERE name LIKE ?", (f"%{name}%",))
        row = cursor.fetchone()
        if not row:
            return None
        row["is_active"] = bool(row["is_active"])
        return Convention(**dict(row))

    # ========== 置信度管理 ==========

    def decay(self, days: int = 30) -> int:
        """衰减长时间未更新的惯例"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cutoff = int(time.time()) - (days * 86400)

        cursor.execute(
            """
            UPDATE conventions
            SET confidence = confidence * ?, last_updated = ?
            WHERE last_updated < ? AND is_active = 1 AND confidence > ?
        """,
            (self.DECAY_FACTOR, int(time.time()), cutoff, self.MIN_CONFIDENCE),
        )
        conn.commit()

        cursor.execute(
            "UPDATE conventions SET is_active = 0 WHERE confidence < ? AND is_active = 1",
            (self.MIN_CONFIDENCE,),
        )
        conn.commit()
        return cursor.rowcount

    def promote(self, convention_id: str) -> bool:
        """用户确认的惯例提升置信度"""
        c = self.get(convention_id)
        if not c:
            return False
        return self.update(convention_id, confidence=min(1.0, c.confidence + 0.15))

    def demote(self, convention_id: str) -> bool:
        """用户否定的惯例降低置信度"""
        c = self.get(convention_id)
        if not c:
            return False
        return self.update(convention_id, confidence=max(0.0, c.confidence - 0.2))

    # ========== 统计 ==========

    def get_stats(self) -> dict[str, Any]:
        """获取惯例统计"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) as total, COUNT(CASE WHEN is_active=1 THEN 1 END) as active FROM conventions"
        )
        row = cursor.fetchone()

        cursor.execute("SELECT category, COUNT(*) as count FROM conventions GROUP BY category")
        by_category = {r["category"]: r["count"] for r in cursor.fetchall()}

        return {
            "total": row["total"],
            "active": row["active"],
            "by_category": by_category,
        }
