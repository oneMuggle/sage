"""
Semantic Memory - 语义记忆模块
使用 SQLite FTS5 全文搜索存储知识和概念
注意：暂不使用 ChromaDB，保持简单
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any


class SemanticMemory:
    """
    语义记忆 - 管理知识和概念

    特性:
    - SQLite FTS5 全文搜索
    - 支持摘要生成
    - 持久化存储
    - 不引入 ChromaDB（保持简单）
    """

    def __init__(self, db):
        """
        初始化语义记忆

        Args:
            db: Database 实例
        """
        self.db = db
        self._init_fts()

    def _init_fts(self) -> None:
        """初始化 FTS5 全文搜索表"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 创建语义记忆主表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories_semantic (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                summary TEXT,
                tags TEXT DEFAULT '[]',
                created_at INTEGER NOT NULL
            )
        """)

        # 创建 FTS5 虚拟表（如果不存在）
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_semantic_fts USING fts5(
                content, summary, tags,
                content='memories_semantic',
                content_rowid='rowid'
            )
        """)

        conn.commit()

    def save(self, content: str, summary: str | None = None, tags: list[str] | None = None) -> str:
        """
        保存语义记忆

        Args:
            content: 记忆内容
            summary: 可选的摘要
            tags: 可选的标签列表

        Returns:
            生成的记忆 ID
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        memory_id = str(uuid.uuid4())
        now = int(time.time() * 1000)

        # 生成摘要
        if summary is None:
            summary = self._generate_summary(content)

        # 处理标签
        tags_json = json.dumps(tags or [], ensure_ascii=False)

        # 插入主表
        cursor.execute(
            """
            INSERT INTO memories_semantic (id, content, summary, tags, created_at)
            VALUES (?, ?, ?, ?, ?)
        """,
            (memory_id, content, summary, tags_json, now),
        )

        # 插入 FTS 表
        cursor.execute(
            """
            INSERT INTO memories_semantic_fts (rowid, content, summary, tags)
            VALUES (
                (SELECT rowid FROM memories_semantic WHERE id = ?),
                ?, ?, ?
            )
        """,
            (memory_id, content, summary, tags_json),
        )

        conn.commit()
        return memory_id

    def _generate_summary(self, content: str, max_length: int = 150) -> str:
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
        self, query: str, limit: int = 10, tags: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """
        搜索语义记忆

        Args:
            query: 搜索关键词
            limit: 返回数量限制
            tags: 可选，按标签筛选

        Returns:
            匹配的记忆列表
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        if not query or query.strip() == "":
            # 如果没有查询词，返回最近的记忆
            return self.get_recent(limit)

        # 使用 FTS5 搜索
        try:
            # FTS5 搜索 - 处理特殊字符
            fts_query = self._prepare_fts_query(query)

            cursor.execute(
                """
                SELECT m.* FROM memories_semantic m
                INNER JOIN memories_semantic_fts fts ON m.rowid = fts.rowid
                WHERE memories_semantic_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """,
                (fts_query, limit),
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
        except Exception:
            # FTS5 搜索失败时，回退到 LIKE 搜索
            return self._search_like(query, limit, tags)

    def _prepare_fts_query(self, query: str) -> str:
        """
        准备 FTS5 查询字符串

        Args:
            query: 原始查询

        Returns:
            处理后的 FTS5 查询
        """
        # 转义特殊字符，简单处理
        terms = query.strip().split()
        if not terms:
            return '""'
        # 使用 OR 连接多个词
        return " OR ".join(f'"{term}"' for term in terms if term)

    def _search_like(
        self, query: str, limit: int = 10, tags: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """
        使用 LIKE 进行回退搜索

        Args:
            query: 搜索关键词
            limit: 返回数量限制
            tags: 可选，按标签筛选

        Returns:
            匹配的记忆列表
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM memories_semantic
            WHERE content LIKE ? OR summary LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
        """,
            (f"%{query}%", f"%{query}%", limit),
        )

        results = []
        for row in cursor.fetchall():
            memory = dict(row)
            if memory.get("tags"):
                try:
                    memory["tags"] = json.loads(memory["tags"])
                except json.JSONDecodeError:
                    memory["tags"] = []

            # 标签过滤
            if tags:
                memory_tags = set(memory.get("tags", []))
                if not any(t in memory_tags for t in tags):
                    continue

            results.append(memory)

        return results

    def get_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """
        获取最近的语义记忆

        Args:
            limit: 返回数量限制

        Returns:
            记忆列表
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM memories_semantic
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

    def get_all(self) -> list[dict[str, Any]]:
        """
        获取所有语义记忆

        Returns:
            所有记忆列表
        """
        return self.get_recent(limit=10000)

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
            SELECT * FROM memories_semantic
            WHERE id = ?
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
            return memory
        return None

    def delete(self, memory_id: str) -> bool:
        """
        删除语义记忆

        Args:
            memory_id: 记忆 ID

        Returns:
            是否删除成功
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 获取 rowid 用于删除 FTS 条目
        cursor.execute("SELECT rowid FROM memories_semantic WHERE id = ?", (memory_id,))
        row = cursor.fetchone()
        if not row:
            return False

        rowid = row[0]

        # 删除 FTS 条目
        cursor.execute("DELETE FROM memories_semantic_fts WHERE rowid = ?", (rowid,))

        # 删除主表条目
        cursor.execute("DELETE FROM memories_semantic WHERE id = ?", (memory_id,))

        conn.commit()
        return cursor.rowcount > 0

    def count(self) -> int:
        """
        获取记忆总数

        Returns:
            记忆数量
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM memories_semantic")
        return cursor.fetchone()[0]

    def update_tags(self, memory_id: str, tags: list[str]) -> bool:
        """
        更新记忆标签

        Args:
            memory_id: 记忆 ID
            tags: 新的标签列表

        Returns:
            是否更新成功
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        tags_json = json.dumps(tags, ensure_ascii=False)

        cursor.execute(
            """
            UPDATE memories_semantic
            SET tags = ?
            WHERE id = ?
        """,
            (tags_json, memory_id),
        )

        # 同时更新 FTS 表
        cursor.execute(
            """
            UPDATE memories_semantic_fts
            SET tags = ?
            WHERE rowid = (SELECT rowid FROM memories_semantic WHERE id = ?)
        """,
            (tags_json, memory_id),
        )

        conn.commit()
        return cursor.rowcount > 0
