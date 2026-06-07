"""
Episodic Memory - 情景记忆模块
基于 SQLite 存储对话历史和事件序列
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any


class EpisodicMemory:
    """
    情景记忆 - 管理事件序列和经历

    特性:
    - SQLite 持久化存储
    - 支持重要性评分 (1-10)
    - 支持标签系统
    - 访问计数和 TTL 支持
    """

    def __init__(self, db):
        """
        初始化情景记忆

        Args:
            db: Database 实例
        """
        self.db = db

    def save(
        self,
        content: str,
        importance: int = 5,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
        memory_type: str = "conversation",
    ) -> str:
        """
        保存情景记忆

        Args:
            content: 记忆内容
            importance: 重要性评分 (1-10)
            metadata: 额外元数据
            session_id: 关联的会话 ID
            memory_type: 记忆类型

        Returns:
            生成的记忆 ID
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        memory_id = str(uuid.uuid4())
        now = int(time.time() * 1000)

        # 处理标签
        tags = "[]"
        if metadata and "tags" in metadata:
            tags = json.dumps(metadata["tags"], ensure_ascii=False)
        elif metadata and "tags" in metadata:
            tags = json.dumps(metadata.get("tags", []), ensure_ascii=False)

        # 生成摘要
        summary = self._generate_summary(content)

        cursor.execute(
            """
            INSERT INTO memories_episodic
            (id, content, summary, session_id, memory_type, importance, tags, created_at, is_valid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
            (memory_id, content, summary, session_id, memory_type, importance, tags, now),
        )

        conn.commit()
        return memory_id

    def _generate_summary(self, content: str, max_length: int = 100) -> str:
        """
        生成记忆摘要

        Args:
            content: 原始内容
            max_length: 最大长度

        Returns:
            摘要文本
        """
        if len(content) <= max_length:
            return content
        return content[:max_length] + "..."

    def search(
        self, query: str, limit: int = 10, min_importance: int = 1, memory_type: str | None = None
    ) -> list[dict[str, Any]]:
        """
        搜索情景记忆

        Args:
            query: 搜索关键词
            limit: 返回数量限制
            min_importance: 最小重要性
            memory_type: 可选，按记忆类型筛选

        Returns:
            匹配的记忆列表
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        sql = """
            SELECT * FROM memories_episodic
            WHERE is_valid = 1
            AND (content LIKE ? OR summary LIKE ?)
            AND importance >= ?
        """
        params = [f"%{query}%", f"%{query}%", min_importance]

        if memory_type:
            sql += " AND memory_type = ?"
            params.append(memory_type)

        sql += " ORDER BY importance DESC, access_count DESC, created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(sql, params)
        results = []

        for row in cursor.fetchall():
            memory = dict(row)
            # 解析标签 JSON
            if memory.get("tags"):
                try:
                    memory["tags"] = json.loads(memory["tags"])
                except json.JSONDecodeError:
                    memory["tags"] = []
            results.append(memory)
            # 更新访问统计
            self._update_access(memory["id"])

        return results

    def get_recent(self, limit: int = 10, session_id: str | None = None) -> list[dict[str, Any]]:
        """
        获取最近的记忆

        Args:
            limit: 返回数量限制
            session_id: 可选，按会话 ID 筛选

        Returns:
            记忆列表
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        if session_id:
            cursor.execute(
                """
                SELECT * FROM memories_episodic
                WHERE session_id = ? AND is_valid = 1
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (session_id, limit),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM memories_episodic
                WHERE is_valid = 1
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (limit,),
            )

        results = []
        for row in cursor.fetchall():
            memory = dict(row)
            if memory.get("tags"):
                try:
                    memory["tags"] = json.loads(memory["tags"])
                except json.JSONDecodeError:
                    memory["tags"] = []
            results.append(memory)

        return results

    def get_by_session(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """
        获取指定会话的记忆

        Args:
            session_id: 会话 ID
            limit: 返回数量限制

        Returns:
            记忆列表
        """
        return self.get_recent(limit=limit, session_id=session_id)

    def delete(self, memory_id: str) -> bool:
        """
        删除记忆（软删除）

        Args:
            memory_id: 记忆 ID

        Returns:
            是否删除成功
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE memories_episodic
            SET is_valid = 0
            WHERE id = ?
        """,
            (memory_id,),
        )

        conn.commit()
        return cursor.rowcount > 0

    def _update_access(self, memory_id: str) -> None:
        """
        更新记忆访问统计

        Args:
            memory_id: 记忆 ID
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        now = int(time.time() * 1000)
        cursor.execute(
            """
            UPDATE memories_episodic
            SET access_count = access_count + 1, accessed_at = ?
            WHERE id = ?
        """,
            (now, memory_id),
        )

        conn.commit()

    def get_by_id(self, memory_id: str) -> dict[str, Any] | None:
        """
        根据 ID 获取记忆

        Args:
            memory_id: 记忆 ID

        Returns:
            记忆字典，不存在则返回 None
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM memories_episodic
            WHERE id = ? AND is_valid = 1
        """,
            (memory_id,),
        )

        row = cursor.fetchone()
        if row:
            memory = dict(row)
            if memory.get("tags"):
                try:
                    memory["tags"] = json.loads(memory["tags"])
                except json.JSONDecodeError:
                    memory["tags"] = []
            self._update_access(memory_id)
            return memory
        return None

    def count(self) -> int:
        """
        获取记忆总数

        Returns:
            有效记忆数量
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM memories_episodic
            WHERE is_valid = 1
        """)

        return cursor.fetchone()[0]
