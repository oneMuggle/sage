"""纯 Python 向量存储。

使用 JSON 文件存储嵌入向量，支持余弦相似度搜索。
存储路径: {project_root}/.llm-wiki/vectors.json
"""
from typing import Dict, List, Optional, Tuple

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ChunkRecord:
    """向量记录。"""

    id: str  # "{page_path}::{chunk_index}"
    page_path: str
    chunk_index: int
    content: str
    vector: List[float]


@dataclass
class SearchHit:
    """搜索结果。"""

    page_path: str
    chunk_index: int
    content: str
    score: float  # 余弦相似度


class VectorStore:
    """JSON 向量存储。"""

    def __init__(self, storage_path: Path, dim: int, records: Optional[List[ChunkRecord]] = None):
        self.storage_path = storage_path
        self.dim = dim
        self.records: List[ChunkRecord] = records or []
        self.by_page: Dict[str, List[int]] = {}  # page_path → record indices
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        """重建 page_path → indices 索引。"""
        self.by_page = {}
        for idx, rec in enumerate(self.records):
            if rec.page_path not in self.by_page:
                self.by_page[rec.page_path] = []
            self.by_page[rec.page_path].append(idx)

    @classmethod
    def open(cls, project_root: Path, dim: int) -> "VectorStore":
        """打开或创建向量存储。

        Args:
            project_root: 项目根目录
            dim: 向量维度

        Returns:
            VectorStore: 向量存储实例
        """
        storage_path = project_root / ".llm-wiki" / "vectors.json"

        if storage_path.exists():
            data = json.loads(storage_path.read_text(encoding="utf-8"))
            if data.get("dim") != dim:
                raise ValueError(f"向量维度不匹配: 文件={data.get('dim')}, 请求={dim}")

            records = [
                ChunkRecord(
                    id=r["id"],
                    page_path=r["page_path"],
                    chunk_index=r["chunk_index"],
                    content=r["content"],
                    vector=r["vector"],
                )
                for r in data.get("records", [])
            ]
            return cls(storage_path, dim, records)

        # 创建新存储
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        store = cls(storage_path, dim, [])
        store._flush()
        return store

    def upsert_chunks(self, page_path: str, chunks: List[Tuple[int, str, List[float]]]) -> None:
        """插入或更新页面的向量。

        Args:
            page_path: 页面路径
            chunks: 向量列表 [(chunk_index, content, vector), ...]
        """
        # 验证维度
        for _, _, vec in chunks:
            if len(vec) != self.dim:
                raise ValueError(f"向量维度不匹配: 期望 {self.dim}, 实际 {len(vec)}")

        # 删除旧记录
        self.delete_by_page(page_path)

        # 添加新记录
        for chunk_idx, content, vector in chunks:
            record = ChunkRecord(
                id=f"{page_path}::{chunk_idx}",
                page_path=page_path,
                chunk_index=chunk_idx,
                content=content,
                vector=vector,
            )
            self.records.append(record)

        self._rebuild_index()
        self._flush()

    def delete_by_page(self, page_path: str) -> int:
        """删除页面的所有向量。

        Args:
            page_path: 页面路径

        Returns:
            int: 删除的记录数
        """
        if page_path not in self.by_page:
            return 0

        indices_to_remove = set(self.by_page[page_path])
        self.records = [r for i, r in enumerate(self.records) if i not in indices_to_remove]
        self._rebuild_index()
        self._flush()
        return len(indices_to_remove)

    def search(self, query_vec: List[float], limit: int) -> List[SearchHit]:
        """搜索最相似的向量。

        Args:
            query_vec: 查询向量
            limit: 返回数量上限

        Returns:
            list[SearchHit]: 搜索结果（按相似度降序）
        """
        if len(query_vec) != self.dim:
            raise ValueError(f"向量维度不匹配: 期望 {self.dim}, 实际 {len(query_vec)}")

        hits = []
        for rec in self.records:
            score = _cosine_similarity(query_vec, rec.vector)
            hits.append(
                SearchHit(
                    page_path=rec.page_path,
                    chunk_index=rec.chunk_index,
                    content=rec.content,
                    score=score,
                )
            )

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def _flush(self) -> None:
        """原子写入磁盘。"""
        data = {
            "version": 1,
            "dim": self.dim,
            "records": [
                {
                    "id": r.id,
                    "page_path": r.page_path,
                    "chunk_index": r.chunk_index,
                    "content": r.content,
                    "vector": r.vector,
                }
                for r in self.records
            ],
        }

        tmp_path = self.storage_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.storage_path)


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)
