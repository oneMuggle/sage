"""Vector Store - 基于 sqlite-vec 的向量存储

为记忆系统提供语义向量检索能力。使用 sqlite-vec 扩展
实现向量相似度搜索（余弦距离），与现有 SQLite 数据库无缝融合。
"""

from __future__ import annotations

import logging
from typing import Any

import sqlite_vec

from backend.memory.embedder import Embedder

logger = logging.getLogger(__name__)


class VectorStore:
    """基于 sqlite-vec 的向量存储

    Attributes:
        dimensions: 向量维度（与 embedder 一致）

    Example:
        >>> from backend.memory.embedder import HashEmbedder
        >>> store = VectorStore(db, HashEmbedder(dimensions=256))
        >>> store.add("mem-1", "用户喜欢火锅", memory_type="episodic")
        >>> results = store.search("火锅", top_k=5)
    """

    def __init__(self, db: Any, embedder: Embedder) -> None:
        """初始化向量存储

        Args:
            db: Database 实例（共享 SQLite 连接）
            embedder: 文本向量化器
        """
        self._db = db
        self._embedder = embedder
        self.dimensions = embedder.dimensions
        self._init_table()

    def _init_table(self) -> None:
        """初始化 sqlite-vec 虚拟表

        加载 sqlite-vec 扩展并创建 memories_vec 虚拟表。
        表结构：embedding (float32 向量) + memory_id + memory_type。
        """
        conn = self._db.get_connection()

        # 加载 sqlite-vec 扩展
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
        except Exception as e:
            logger.warning(f"sqlite-vec 扩展加载失败（向量检索不可用）: {e}")
            return

        # 创建虚拟表
        try:
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec USING vec0(
                    embedding FLOAT[{self.dimensions}],
                    memory_id TEXT,
                    memory_type TEXT
                )
            """)
            conn.commit()
            logger.info(
                f"向量存储已初始化: dimensions={self.dimensions}, "
                f"sqlite-vec={sqlite_vec.__version__}"
            )
        except Exception as e:
            logger.warning(f"向量存储表创建失败: {e}")

    def add(self, memory_id: str, text: str, memory_type: str = "episodic") -> None:
        """添加记忆向量

        Args:
            memory_id: 记忆 ID
            text: 记忆文本（将被 embedder 编码为向量）
            memory_type: 记忆类型（episodic/semantic）
        """
        conn = self._db.get_connection()

        try:
            # 先删除已有的同 ID 条目（幂等）
            conn.execute(
                "DELETE FROM memories_vec WHERE memory_id = ?",
                (memory_id,),
            )

            # 编码文本为向量
            vec_bytes = self._embedder.encode_to_bytes(text)

            # 插入新条目（使用 memory_id 的哈希作为 rowid）
            rowid = abs(hash(memory_id)) % (2**31)
            conn.execute(
                """INSERT INTO memories_vec (rowid, embedding, memory_id, memory_type)
                   VALUES (?, ?, ?, ?)""",
                (rowid, vec_bytes, memory_id, memory_type),
            )
            conn.commit()
        except Exception as e:
            logger.warning(f"添加向量失败 (memory_id={memory_id}): {e}")

    def search(
        self,
        query: str,
        top_k: int = 10,
        memory_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """向量相似度搜索

        Args:
            query: 查询文本
            top_k: 返回结果数量
            memory_type: 可选，按记忆类型筛选

        Returns:
            搜索结果列表，每项包含 memory_id, distance
        """
        conn = self._db.get_connection()

        try:
            query_vec = self._embedder.encode_to_bytes(query)

            if memory_type:
                rows = conn.execute(
                    """SELECT memory_id, memory_type, distance
                       FROM memories_vec
                       WHERE embedding MATCH ?
                         AND memory_type = ?
                       ORDER BY distance
                       LIMIT ?""",
                    (query_vec, memory_type, top_k),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT memory_id, memory_type, distance
                       FROM memories_vec
                       WHERE embedding MATCH ?
                       ORDER BY distance
                       LIMIT ?""",
                    (query_vec, top_k),
                ).fetchall()

            return [
                {"memory_id": row[0], "memory_type": row[1], "distance": row[2]} for row in rows
            ]
        except Exception as e:
            logger.warning(f"向量搜索失败: {e}")
            return []

    def delete(self, memory_id: str) -> bool:
        """删除记忆向量

        Args:
            memory_id: 记忆 ID

        Returns:
            是否删除成功
        """
        conn = self._db.get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM memories_vec WHERE memory_id = ?",
                (memory_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.warning(f"删除向量失败 (memory_id={memory_id}): {e}")
            return False

    def count(self) -> int:
        """获取向量总数"""
        conn = self._db.get_connection()
        try:
            row = conn.execute("SELECT COUNT(*) FROM memories_vec").fetchone()
            return row[0] if row else 0
        except Exception:
            return 0
