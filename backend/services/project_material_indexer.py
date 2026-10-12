"""项目资料语义索引服务 (M4, 2026-10-12)。

将 project_materials 表中的资料异步索引到 sqlite-vec 向量表，
提供语义检索能力，替代 L4 材料层的全量文本注入。

架构:
  add(material) → status=pending_index
       │
       ▼
  BackgroundIndexer (asyncio.Task)
  - 定期扫描 pending_index 资料
  - 分块 (chunk_markdown)
  - 向量化 (Embedder.encode_to_bytes)
  - 写入 project_materials_vec (sqlite-vec)
  - mark_ready()
       │
       ▼
  semantic_search(project_id, query, top_k)
  - 查询向量化
  - sqlite-vec 余弦距离
  - 返回匹配 chunks

复用现有设施:
  - Embedder Protocol + create_embedder() 工厂
  - sqlite-vec 扩展 (已在 requirements.txt)
  - wiki.embeddings.chunk_markdown() 分块器
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# sqlite-vec 扩展 + 向量表相关
try:
    import sqlite_vec
    _SQLITE_VEC_AVAILABLE = True
except ImportError:
    _SQLITE_VEC_AVAILABLE = False
    logger.debug("sqlite-vec not available, semantic indexing disabled")

# 向量表名 (按 embedder 维度区分)
_VEC_TABLE_PREFIX = "project_materials_vec"


@dataclass
class SemanticSearchResult:
    """语义检索结果。"""

    material_id: str
    chunk_index: int
    content: str
    score: float  # 0-1, 越高越相关
    project_id: str


@dataclass
class IndexingStats:
    """索引统计。"""

    total_materials: int = 0
    indexed_materials: int = 0
    pending_materials: int = 0
    failed_materials: int = 0
    total_chunks: int = 0
    embedder_type: str = "hash"
    embedder_dims: int = 256


class ProjectMaterialIndexer:
    """项目资料语义索引器。

    使用方式::

        indexer = ProjectMaterialIndexer()
        # 索引单个资料
        await indexer.index_material(material_id)
        # 语义检索
        results = indexer.search(project_id, "查询内容", top_k=5)
        # 后台批量索引
        await indexer.backfill_pending()
    """

    def __init__(self, embedder: Any = None) -> None:
        """初始化索引器。

        Args:
            embedder: Embedder 实例。为 None 时从工厂创建。
        """
        if embedder is not None:
            self._embedder = embedder
        else:
            from backend.memory.embedder_factory import create_embedder
            self._embedder = create_embedder()

        self._vec_table = f"{_VEC_TABLE_PREFIX}_{self._embedder.dimensions}"
        self._available = _SQLITE_VEC_AVAILABLE
        if not self._available:
            logger.warning(
                "sqlite-vec 不可用，语义索引功能禁用"
            )

    @property
    def available(self) -> bool:
        """索引器是否可用（sqlite-vec + embedder 就绪）。"""
        return self._available and self._embedder is not None

    @property
    def dimensions(self) -> int:
        """当前 embedder 向量维度。"""
        return self._embedder.dimensions

    @property
    def vec_table(self) -> str:
        """向量表名。"""
        return self._vec_table

    def _get_vec_table_name(self) -> str:
        """获取向量表名（按维度区分）。"""
        return self._vec_table

    def _ensure_vec_table(self) -> None:
        """确保向量表存在（幂等）。"""
        if not self._available:
            return

        from backend.data.database import get_database
        db = get_database()
        conn = db.get_connection()

        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
        except Exception as e:
            logger.warning("sqlite-vec 扩展加载失败: %s", e)
            self._available = False
            return

        dims = self._embedder.dimensions
        table = self._vec_table

        # 检查表是否已存在
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()

        if existing is None:
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {table}
                USING vec0(
                    material_id TEXT PRIMARY KEY,
                    chunk_index INTEGER,
                    project_id TEXT,
                    embedding FLOAT[{dims}]
                )
            """)
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_project "
                f"ON {table}(project_id)"
            )
            conn.commit()
            logger.info("创建向量表 %s (dims=%d)", table, dims)

    def index_material(self, material_id: str) -> bool:
        """索引单个资料（同步方法，可在 executor 中调用）。

        流程:
        1. 从 repo 读取资料内容
        2. 分块 (按段落/标题)
        3. 向量化每个 chunk
        4. 写入向量表
        5. 更新资料状态为 ready

        Args:
            material_id: 资料 ID

        Returns:
            True 成功, False 失败
        """
        if not self._available:
            return False

        from backend.data.project_material_repo import ProjectMaterialRepository
        repo = ProjectMaterialRepository()
        material = repo.get(material_id)

        if material is None:
            logger.warning("资料不存在: %s", material_id)
            return False

        if material.status == "ready":
            # 已经索引过，跳过（幂等）
            return True

        try:
            self._ensure_vec_table()
            chunks = self._chunk_content(material.content)

            if not chunks:
                repo.mark_ready(material_id)
                return True

            from backend.data.database import get_database
            db = get_database()
            conn = db.get_connection()

            # 删除旧的向量（重新索引）
            table = self._vec_table
            conn.execute(
                f"DELETE FROM {table} WHERE material_id = ?",
                (material_id,),
            )

            # 写入新的向量
            for chunk_idx, chunk_text in enumerate(chunks):
                embedding_bytes = self._embedder.encode_to_bytes(chunk_text)
                # vec0 使用 rowid 方式插入
                conn.execute(
                    f"INSERT INTO {table}(rowid, material_id, chunk_index, project_id, embedding) "
                    f"VALUES (?, ?, ?, ?, ?)",
                    (
                        _make_rowid(material_id, chunk_idx),
                        material_id,
                        chunk_idx,
                        material.project_id,
                        embedding_bytes,
                    ),
                )

            conn.commit()
            repo.mark_ready(material_id)
            logger.info(
                "资料 %s 索引完成: %d chunks, dims=%d",
                material_id, len(chunks), self._embedder.dimensions,
            )
            return True

        except Exception as exc:
            logger.error("资料 %s 索引失败: %s", material_id, exc)
            repo.mark_failed(material_id, str(exc))
            return False

    async def backfill_pending(self, batch_size: int = 50) -> int:
        """批量索引 pending_index 状态的资料。

        Args:
            batch_size: 每批处理数量

        Returns:
            成功索引的资料数量
        """
        if not self._available:
            return 0

        from backend.data.database import get_database
        from backend.data.project_material_repo import (
            MATERIAL_STATUS_PENDING,
        )

        db = get_database()
        conn = db.get_connection()

        # 查找 pending_index 资料
        rows = conn.execute(
            """
            SELECT id FROM project_materials
            WHERE status = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (MATERIAL_STATUS_PENDING, batch_size),
        ).fetchall()

        if not rows:
            return 0

        material_ids = [row[0] if isinstance(row, tuple) else row["id"] for row in rows]
        indexed = 0

        for mid in material_ids:
            # 在线程池中执行同步索引，避免阻塞事件循环
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, self.index_material, mid)
            if success:
                indexed += 1

        logger.info("批量索引完成: %d/%d", indexed, len(material_ids))
        return indexed

    def search(
        self,
        project_id: str,
        query: str,
        top_k: int = 5,
    ) -> List[SemanticSearchResult]:
        """语义检索项目资料。

        Args:
            project_id: 项目 ID
            query: 查询文本
            top_k: 返回前 K 个结果

        Returns:
            SemanticSearchResult 列表，按相关性降序
        """
        if not self._available:
            return []

        try:
            self._ensure_vec_table()
        except Exception:
            return []

        from backend.data.database import get_database
        db = get_database()
        conn = db.get_connection()

        table = self._vec_table
        query_bytes = self._embedder.encode_to_bytes(query)

        try:
            # sqlite-vec KNN 查询
            rows = conn.execute(
                f"""
                SELECT
                    m.id AS material_id,
                    v.chunk_index,
                    m.content,
                    v.distance
                FROM {table} v
                JOIN project_materials m ON m.id = v.material_id
                WHERE v.project_id = ?
                  AND m.status = 'ready'
                  AND COALESCE(m.enabled, 1) = 1
                ORDER BY v.embedding MATCH ?
                LIMIT ?
                """,
                (project_id, query_bytes, top_k),
            ).fetchall()
        except Exception as exc:
            logger.warning("语义检索失败 (project=%s): %s", project_id, exc)
            return []

        results = []
        for row in rows:
            if isinstance(row, tuple):
                mid, chunk_idx, content, distance = row
            else:
                mid = row["material_id"]
                chunk_idx = row["chunk_index"]
                content = row["content"]
                distance = row["distance"]

            # sqlite-vec 返回 L2 距离，转换为相似度分数 (0-1)
            score = max(0.0, 1.0 - distance)

            results.append(SemanticSearchResult(
                material_id=mid,
                chunk_index=chunk_idx,
                content=content,
                score=score,
                project_id=project_id,
            ))

        return results

    def get_stats(self, project_id: Optional[str] = None) -> IndexingStats:
        """获取索引统计信息。"""
        from backend.data.database import get_database
        db = get_database()
        conn = db.get_connection()

        where_clause = ""
        params: Tuple = ()
        if project_id:
            where_clause = "WHERE project_id = ?"
            params = (project_id,)

        total = conn.execute(
            f"SELECT COUNT(*) FROM project_materials {where_clause}", params
        ).fetchone()[0]

        pending = conn.execute(
            f"SELECT COUNT(*) FROM project_materials "
            f"{'WHERE' if not where_clause else where_clause + ' AND'} "
            f"status = 'pending_index'"
            + (" AND project_id = ?" if project_id else ""),
            params + ("pending_index",) if project_id else ("pending_index",),
        ).fetchone()[0]

        failed = conn.execute(
            f"SELECT COUNT(*) FROM project_materials "
            f"{'WHERE' if not where_clause else where_clause + ' AND'} "
            f"status = 'failed'"
            + (" AND project_id = ?" if project_id else ""),
            params + ("failed",) if project_id else ("failed",),
        ).fetchone()[0]

        indexed = total - pending - failed

        # 向量表中的 chunk 总数
        chunk_count = 0
        if self._available:
            try:
                table = self._vec_table
                if project_id:
                    chunk_count = conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE project_id = ?",
                        (project_id,),
                    ).fetchone()[0]
                else:
                    chunk_count = conn.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
            except Exception:
                pass

        return IndexingStats(
            total_materials=total,
            indexed_materials=indexed,
            pending_materials=pending,
            failed_materials=failed,
            total_chunks=chunk_count,
            embedder_type=type(self._embedder).__name__.lower().replace("embedder", ""),
            embedder_dims=self._embedder.dimensions,
        )

    def delete_vectors(self, material_id: str) -> None:
        """删除资料的向量（资料被删除时调用）。"""
        if not self._available:
            return

        from backend.data.database import get_database
        db = get_database()
        conn = db.get_connection()

        try:
            table = self._vec_table
            conn.execute(
                f"DELETE FROM {table} WHERE material_id = ?",
                (material_id,),
            )
            conn.commit()
        except Exception as exc:
            logger.debug("删除向量失败 (%s): %s", material_id, exc)

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    def _chunk_content(self, content: str) -> List[str]:
        """将资料内容分块。

        优先使用 wiki 的 chunk_markdown()，失败时回退到简单段落分割。
        """
        # 尝试使用 wiki 分块器
        try:
            from backend.wiki.embeddings import chunk_markdown
            chunks = chunk_markdown(content, target_chunk_size=500)
            if chunks:
                return chunks
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("wiki chunk_markdown 失败: %s, 回退段落分割", exc)

        # 回退 — 按双换行分割段落
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

        # 合并短段落，分割超长段落
        chunks: List[str] = []
        current = ""
        max_chars = 1000

        for para in paragraphs:
            if len(current) + len(para) + 1 <= max_chars:
                current = f"{current}\n\n{para}".strip() if current else para
            else:
                if current:
                    chunks.append(current)
                if len(para) > max_chars:
                    # 超长段落按句子分割
                    sentences = _split_sentences(para)
                    current = ""
                    for sent in sentences:
                        if len(current) + len(sent) + 1 <= max_chars:
                            current = f"{current} {sent}".strip() if current else sent
                        else:
                            if current:
                                chunks.append(current)
                            current = sent
                else:
                    current = para

        if current:
            chunks.append(current)

        return chunks if chunks else [content[:max_chars]] if content else []


def _make_rowid(material_id: str, chunk_index: int) -> int:
    """将 (material_id, chunk_index) 转为唯一整数 rowid。

    使用 material_id 的 hash + chunk_index 组合。
    """
    import hashlib
    h = hashlib.md5(f"{material_id}:{chunk_index}".encode()).hexdigest()
    return int(h[:8], 16)


def _split_sentences(text: str) -> List[str]:
    """按句子分割文本（支持中英文标点）。"""
    import re
    # 中英文句子结束标点
    pattern = r"(?<=[.。!！?？\n])\s*"
    parts = re.split(pattern, text)
    return [p.strip() for p in parts if p.strip()]


__all__ = [
    "IndexingStats",
    "ProjectMaterialIndexer",
    "SemanticSearchResult",
]
