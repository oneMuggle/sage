"""RAG 存储层 - SQLite + 全文搜索。

实现记忆的存储、检索和删除。
"""

import sqlite3
from typing import Any


class RAGStorage:
    """RAG 存储层。"""

    def __init__(self, db_path: str = "data/rag.db"):
        """初始化存储。

        Args:
            db_path: 数据库路径
        """
        self.db_path = db_path
        self.conn: sqlite3.Connection | None = None

    async def initialize(self) -> None:
        """初始化数据库。"""
        self.conn = sqlite3.connect(self.db_path)
        await self._create_tables()

    async def _create_tables(self) -> None:
        """创建数据表。"""
        assert self.conn is not None

        # 记忆表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 全文搜索虚拟表
        self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content,
                content='memories',
                content_rowid='rowid'
            )
        """)

        self.conn.commit()

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filters: dict | None = None,
    ) -> list[dict[str, Any]]:
        """检索记忆。

        Args:
            query: 查询文本
            top_k: 返回结果数量
            filters: 过滤条件

        Returns:
            检索结果列表
        """
        assert self.conn is not None

        # 使用 FTS5 全文搜索
        cursor = self.conn.execute("""
            SELECT id, content, metadata, rank
            FROM memories_fts
            WHERE memories_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, top_k))

        results = []
        for row in cursor.fetchall():
            results.append({
                "id": row[0],
                "content": row[1],
                "metadata": row[2] or "{}",
                "score": abs(row[3]),  # FTS5 rank 是负数，取绝对值
            })

        return results

    async def index(self, documents: list[dict]) -> int:
        """索引文档。

        Args:
            documents: 文档列表

        Returns:
            索引数量
        """
        assert self.conn is not None

        count = 0
        for doc in documents:
            # 插入记忆
            self.conn.execute("""
                INSERT OR REPLACE INTO memories (id, content, metadata)
                VALUES (?, ?, ?)
            """, (doc["id"], doc["content"], doc.get("metadata", "{}")))

            # 更新 FTS 索引
            self.conn.execute("""
                INSERT INTO memories_fts (rowid, content)
                SELECT rowid, content FROM memories WHERE id = ?
            """, (doc["id"],))

            count += 1

        self.conn.commit()
        return count

    async def delete(self, ids: list[str]) -> int:
        """删除文档。

        Args:
            ids: 文档 ID 列表

        Returns:
            删除数量
        """
        assert self.conn is not None

        count = 0
        for id in ids:
            # 删除 FTS 索引
            self.conn.execute("""
                DELETE FROM memories_fts WHERE rowid = (
                    SELECT rowid FROM memories WHERE id = ?
                )
            """, (id,))

            # 删除记忆
            cursor = self.conn.execute(
                "DELETE FROM memories WHERE id = ?", (id,)
            )
            count += cursor.rowcount

        self.conn.commit()
        return count

    async def shutdown(self) -> None:
        """关闭数据库。"""
        if self.conn:
            self.conn.close()
            self.conn = None
