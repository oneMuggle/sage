"""Vector Store - 基于 sqlite-vec 的向量存储

为记忆系统提供语义向量检索能力。使用 sqlite-vec 扩展
实现向量相似度搜索（余弦距离），与现有 SQLite 数据库无缝融合。
"""

from __future__ import annotations

import logging
import re
import struct
from typing import Any, Dict, List, Optional

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

    def __init__(self, db: Any, embedder: Embedder, table_name: str = "memories_vec") -> None:
        """初始化向量存储

        Args:
            db: Database 实例（共享 SQLite 连接）
            embedder: 文本向量化器
            table_name: 虚拟表名。不同嵌入器维度不兼容, 各用独立表
                (Hash=256 → memories_vec; Onnx=512 → memories_vec_512)。
        """
        self._db = db
        self._embedder = embedder
        self.dimensions = embedder.dimensions
        self.table_name = table_name
        # sqlite-vec 扩展加载/建表失败时置 False —— add/search/backfill no-op
        # (Round 1: 向量路缺席时关键词路独立可用, 不拖垮记忆系统)
        self._available = False
        self._init_table()

    def _init_table(self) -> None:
        """初始化 sqlite-vec 虚拟表

        加载 sqlite-vec 扩展并创建虚拟表 (表名见 self.table_name)。
        表结构：embedding (float32 向量) + memory_id + memory_type。

        同表维度防护 (Round 1): 表名相同但存量维度与当前 embedder 不同时
        （如 ModelEmbedder 改了 SAGE_EMBED_DIM 复用同名表），DROP + 重建
        —— 向量是可再生的派生索引, 由 backfill_from_tables() 重嵌。
        """
        conn = self._db.get_connection()

        # 加载 sqlite-vec 扩展
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
        except Exception as e:
            logger.warning(f"sqlite-vec 扩展加载失败（向量检索不可用）: {e}")
            return

        # 同表维度防护：存量表维度 != 当前 embedder 维度 → 重建
        existing_dim = self._existing_table_dimension(conn)
        if existing_dim is not None and existing_dim != self.dimensions:
            logger.warning(
                "向量维度变更: %s 存量 %d 维 → embedder %d 维，重建向量表"
                "（backfill 将重嵌存量记忆）",
                self.table_name,
                existing_dim,
                self.dimensions,
            )
            try:
                conn.execute(f"DROP TABLE IF EXISTS {self.table_name}")
                conn.commit()
            except Exception as e:
                logger.warning(f"向量表维度迁移失败（向量检索不可用）: {e}")
                return

        # 创建虚拟表
        try:
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {self.table_name} USING vec0(
                    embedding FLOAT[{self.dimensions}],
                    memory_id TEXT,
                    memory_type TEXT,
                    session_id TEXT
                )
            """)
            conn.commit()
            self._available = True
            logger.info(
                f"向量存储已初始化: table={self.table_name}, "
                f"dimensions={self.dimensions}, sqlite-vec={sqlite_vec.__version__}"
            )
        except Exception as e:
            logger.warning(f"向量存储表创建失败: {e}")

    def _existing_table_dimension(self, conn: Any) -> Optional[int]:
        """从 sqlite_master 读存量虚拟表的建表维度；表不存在返回 None"""
        try:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (self.table_name,),
            ).fetchone()
            if not row or not row[0]:
                return None
            m = re.search(r"FLOAT\[(\d+)\]", str(row[0]))
            return int(m.group(1)) if m else None
        except Exception:
            return None

    def add(
        self,
        memory_id: str,
        text: str,
        memory_type: str = "episodic",
        session_id: Optional[str] = None,
    ) -> None:
        """添加记忆向量

        Args:
            memory_id: 记忆 ID
            text: 记忆文本（将被 embedder 编码为向量）
            memory_type: 记忆类型（episodic/semantic）
        """
        if not self._available:
            return
        conn = self._db.get_connection()

        try:
            # 先删除已有的同 ID 条目（幂等）
            conn.execute(
                f"DELETE FROM {self.table_name} WHERE memory_id = ?",
                (memory_id,),
            )

            # 编码文本为向量
            vec_bytes = self._embedder.encode_to_bytes(text)

            # 插入新条目（使用 memory_id 的哈希作为 rowid）
            rowid = abs(hash(memory_id)) % (2**31)
            conn.execute(
                f"""INSERT INTO {self.table_name} (rowid, embedding, memory_id, memory_type, session_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (rowid, vec_bytes, memory_id, memory_type, session_id),
            )
            conn.commit()
        except Exception as e:
            logger.warning(f"添加向量失败 (memory_id={memory_id}): {e}")

    def search(
        self,
        query: str,
        top_k: int = 10,
        memory_type: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """向量相似度搜索

        Args:
            query: 查询文本
            top_k: 返回结果数量
            memory_type: 可选，按记忆类型筛选
            session_id: 可选,按会话 ID 严格过滤（spec §4.3 step 5 严禁跨 session 串味）

        Returns:
            搜索结果列表，每项包含 memory_id, memory_type, session_id, distance
        """
        if not self._available:
            return []
        conn = self._db.get_connection()

        try:
            query_vec = self._embedder.encode_to_bytes(query)

            # spec §4.3 step 5:session_id 过滤可能让 KNN 候选被裁掉,
            # 这里过取 4x 以确保最终返回至少 top_k 个 (允许 0/不足时退化)。
            fetch_k = top_k * 4 if session_id is not None else top_k

            sql_parts = [
                "SELECT memory_id, memory_type, session_id, distance",
                f"FROM {self.table_name}",
                "WHERE embedding MATCH ?",
            ]
            params: List[Any] = [query_vec]

            if memory_type:
                sql_parts.append("AND memory_type = ?")
                params.append(memory_type)

            if session_id is not None:
                sql_parts.append("AND session_id = ?")
                params.append(session_id)

            sql_parts.append("ORDER BY distance LIMIT ?")
            params.append(fetch_k)

            rows = conn.execute(" ".join(sql_parts), params).fetchall()
            results: List[Dict[str, Any]] = [
                {
                    "memory_id": row[0],
                    "memory_type": row[1],
                    "session_id": row[2],
                    "distance": row[3],
                }
                for row in rows[:top_k]
            ]
            return results
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
                f"DELETE FROM {self.table_name} WHERE memory_id = ?",
                (memory_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.warning(f"删除向量失败 (memory_id={memory_id}): {e}")
            return False

    def count(self) -> int:
        """获取向量总数"""
        if not self._available:
            return 0
        conn = self._db.get_connection()
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {self.table_name}").fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def pending_backfill_count(self) -> int:
        """主表中尚无向量条目的持久记忆数量（>0 表示需要回填）

        对比向量表已索引的 memory_id 集合与两张主表的 id 并集。
        向量表不可用时返回 0（此时向量路整体缺席，回填无意义）。
        """
        if not self._available:
            return 0
        conn = self._db.get_connection()
        try:
            row = conn.execute(
                f"""
                SELECT COUNT(*) FROM (
                    SELECT id FROM memories_episodic
                    UNION
                    SELECT id FROM memories_semantic
                ) WHERE id NOT IN (SELECT memory_id FROM {self.table_name})
                """
            ).fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.debug(f"统计待回填数量失败: {e}")
            return 0

    def backfill_from_tables(self, limit: int = 500, batch_size: int = 64) -> int:
        """回填存量记忆的向量（维度迁移后 / 语义 Embedder 首次启用后）

        从两张主表按 created_at 降序取尚未建向量的记忆，批量编码后写入。
        best-effort：单条/单批失败跳过（下一轮 backfill 可续），整体异常
        返回已回填数。

        Args:
            limit: 本次回填的最大条数（SAGE_VEC_BACKFILL_MAX 可设）
            batch_size: 每批编码条数

        Returns:
            实际回填的条数
        """
        if not self._available:
            return 0
        conn = self._db.get_connection()
        try:
            rows = conn.execute(
                f"""
                SELECT id, content, memory_type, session_id FROM (
                    SELECT id, content, 'episodic' AS memory_type,
                           session_id, created_at FROM memories_episodic
                    UNION ALL
                    SELECT id, content, 'semantic' AS memory_type,
                           NULL AS session_id, created_at FROM memories_semantic
                ) WHERE id NOT IN (SELECT memory_id FROM {self.table_name})
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        except Exception as e:
            logger.warning(f"回填查询失败: {e}")
            return 0

        if not rows:
            return 0

        done = 0
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            try:
                vectors = self._embedder.encode_batch([r[1] or "" for r in batch])
            except Exception as e:
                # 熔断打开 / 端点故障：终止本轮，剩余留给下次
                logger.warning(f"回填编码失败（终止本轮，已回填 {done} 条）: {e}")
                break
            # py3.8 兼容: zip 不用 strict=(两侧等长)
            for ((mem_id, _content, mem_type, session_id), vec) in zip(batch, vectors):  # noqa: B905
                try:
                    rowid = abs(hash(mem_id)) % (2**31)
                    conn.execute(
                        f"""INSERT INTO {self.table_name} (rowid, embedding, memory_id, memory_type, session_id)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            rowid,
                            struct.pack(f"<{len(vec)}f", *vec),
                            mem_id,
                            mem_type,
                            # vec0 TEXT 元数据列不接受 NULL —— 无会话用空串
                            # （session_id 过滤检索自然不命中, 与缺席等价）
                            session_id or "",
                        ),
                    )
                    done += 1
                except Exception as e:
                    logger.warning(f"回填写向量失败 (memory_id={mem_id}): {e}")
            try:
                conn.commit()
            except Exception as e:
                logger.warning(f"回填提交失败: {e}")
        if done:
            logger.info(f"向量回填完成: 本次 {done} 条")
        return done


def prune_orphan_vectors(db: Any) -> int:
    """补偿式对账: 删除 memories_vec 中不再对应任何主表记录的孤儿向量。

    与 backfill_semantic_fts 同属补偿模式 —— evolution 的修剪/过期/超限
    删除只写主表, 向量条目会残留成为孤儿; 本函数按主表存活 id 集合做
    一次性清扫。best-effort: memories_vec 尚未初始化 (hex 路径从未运行)
    或查询失败时仅告警并返回 0, 不影响调用方事务。

    Returns:
        清理的孤儿向量条数
    """
    try:
        conn = db.get_connection()
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name LIKE 'memories_vec%'"
            ).fetchall()
        ]
        total = 0
        for table in tables:
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE memory_id NOT IN ("
                "SELECT id FROM memories_episodic "
                "UNION SELECT id FROM memories_semantic)"
            )
            total += cursor.rowcount
        conn.commit()
        if total:
            logger.info(f"清理孤儿向量: {total} 条")
        return total
    except Exception as e:  # noqa: BLE001 — 对账失败不拖垮调用方
        logger.warning(f"孤儿向量清理失败 (补偿式, 可下次重试): {e}")
        return 0
