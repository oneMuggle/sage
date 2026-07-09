"""HNSW 向量索引。

使用 hnswlib 实现高效的近似最近邻搜索，支持大规模向量检索（100k+ chunks）。
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import hnswlib
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ChunkRecord:
    """向量记录。"""

    id: str  # "{page_path}::{chunk_index}"
    page_path: str
    chunk_index: int
    content: str


@dataclass
class SearchHit:
    """搜索结果。"""

    page_path: str
    chunk_index: int
    content: str
    score: float  # 相似度分数


class HNSWVectorStore:
    """HNSW 向量存储。"""

    def __init__(
        self,
        storage_path: Path,
        dim: int,
        max_elements: int = 100000,
        ef_construction: int = 200,
        ef_search: int = 50,
        m_connections: int = 16,
    ):
        """初始化 HNSW 向量存储。

        Args:
            storage_path: 存储路径（.hnsw 索引文件 + .json 元数据文件）
            dim: 向量维度
            max_elements: 最大元素数量
            ef_construction: 构建时的搜索范围（越大越准确，但构建越慢）
            ef_search: 搜索时的范围（越大越准确，但搜索越慢）
            m_connections: 每个节点的连接数（越大越准确，但内存占用越大）
        """
        self.storage_path = storage_path
        self.index_path = storage_path.with_suffix(".hnsw")
        self.meta_path = storage_path.with_suffix(".json")
        self.dim = dim
        self.max_elements = max_elements
        self.ef_construction = ef_construction
        self.ef_search = ef_search
        self.M = m_connections

        # 元数据：id -> ChunkRecord
        self.records: Dict[str, ChunkRecord] = {}
        self.label_to_id: Dict[int, str] = {}  # HNSW label -> record id
        self.next_label = 0

        # 初始化或加载索引
        self.index = self._load_or_create_index()

    def _load_or_create_index(self) -> hnswlib.Index:
        """加载或创建 HNSW 索引。"""
        # 创建新索引
        index = hnswlib.Index(space="cosine", dim=self.dim)

        if self.index_path.exists() and self.meta_path.exists():
            # 加载现有索引
            try:
                index.load_index(str(self.index_path))
                index.set_ef(self.ef_search)

                # 加载元数据
                meta_data = json.loads(self.meta_path.read_text(encoding="utf-8"))
                self.records = {k: ChunkRecord(**v) for k, v in meta_data["records"].items()}
                self.label_to_id = {int(k): v for k, v in meta_data["label_to_id"].items()}
                self.next_label = meta_data.get("next_label", len(self.records))

                logger.info(f"加载 HNSW 索引: {len(self.records)} 个记录, " f"维度 {self.dim}")
                return index

            except Exception as e:
                logger.warning(f"加载 HNSW 索引失败，重新创建: {e}")

        # 创建新索引
        index.init_index(
            max_elements=self.max_elements,
            ef_construction=self.ef_construction,
            M=self.M,
        )
        index.set_ef(self.ef_search)

        logger.info(f"创建新 HNSW 索引: 维度 {self.dim}, " f"最大元素 {self.max_elements}")
        return index

    def upsert_chunks(self, page_path: str, chunks: List[Tuple[int, str, List[float]]]) -> None:
        """插入或更新页面的向量。

        Args:
            page_path: 页面路径
            chunks: 向量列表 [(chunk_index, content, vector), ...]
        """
        # 删除旧记录
        self.delete_by_page(page_path)

        # 添加新记录
        vectors = []
        labels = []

        for chunk_idx, content, vector in chunks:
            if len(vector) != self.dim:
                raise ValueError(f"向量维度不匹配: 期望 {self.dim}, 实际 {len(vector)}")

            record_id = f"{page_path}::{chunk_idx}"
            label = self.next_label
            self.next_label += 1

            record = ChunkRecord(
                id=record_id,
                page_path=page_path,
                chunk_index=chunk_idx,
                content=content,
            )

            self.records[record_id] = record
            self.label_to_id[label] = record_id

            vectors.append(vector)
            labels.append(label)

        # 批量添加向量
        if vectors:
            vectors_array = np.array(vectors, dtype=np.float32)
            labels_array = np.array(labels, dtype=np.int64)
            self.index.add_items(vectors_array, labels_array)

        # 保存索引和元数据
        self._save()

    def delete_by_page(self, page_path: str) -> int:
        """删除页面的所有向量。

        Args:
            page_path: 页面路径

        Returns:
            int: 删除的记录数
        """
        # 找到该页面的所有记录
        records_to_delete = [
            (record_id, record)
            for record_id, record in self.records.items()
            if record.page_path == page_path
        ]

        if not records_to_delete:
            return 0

        # 找到对应的 labels
        labels_to_delete = []
        for label, record_id in self.label_to_id.items():
            if record_id.startswith(f"{page_path}::"):
                labels_to_delete.append(label)

        # 删除记录
        for record_id, _ in records_to_delete:
            del self.records[record_id]

        for label in labels_to_delete:
            if label in self.label_to_id:
                del self.label_to_id[label]

        # HNSW 不支持直接删除，需要重建索引
        # 这里我们标记为删除，在搜索时过滤
        # TODO: 实现定期重建索引以清理已删除的记录

        # 保存元数据
        self._save()

        return len(records_to_delete)

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

        if len(self.records) == 0:
            return []

        # 执行搜索
        query_array = np.array([query_vec], dtype=np.float32)
        labels, distances = self.index.knn_query(query_array, k=min(limit, len(self.records)))

        # 转换结果
        hits = []
        for label, distance in zip(labels[0], distances[0], strict=False):
            if label not in self.label_to_id:
                continue

            record_id = self.label_to_id[label]
            record = self.records.get(record_id)
            if not record:
                continue

            # HNSW 返回的是距离，转换为相似度（1 - distance）
            similarity = 1.0 - distance

            hits.append(
                SearchHit(
                    page_path=record.page_path,
                    chunk_index=record.chunk_index,
                    content=record.content,
                    score=similarity,
                )
            )

        # 按相似度排序
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def _save(self) -> None:
        """保存索引和元数据。"""
        # 保存 HNSW 索引
        self.index.save_index(str(self.index_path))

        # 保存元数据
        meta_data = {
            "records": {
                k: {
                    "id": v.id,
                    "page_path": v.page_path,
                    "chunk_index": v.chunk_index,
                    "content": v.content,
                }
                for k, v in self.records.items()
            },
            "label_to_id": {str(k): v for k, v in self.label_to_id.items()},
            "next_label": self.next_label,
        }

        self.meta_path.write_text(
            json.dumps(meta_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def open(
        cls,
        project_root: Path,
        dim: int,
        max_elements: int = 100000,
    ) -> "HNSWVectorStore":
        """打开或创建 HNSW 向量存储。

        Args:
            project_root: 项目根目录
            dim: 向量维度
            max_elements: 最大元素数量

        Returns:
            HNSWVectorStore: 向量存储实例
        """
        storage_path = project_root / ".llm-wiki" / "vectors.hnsw"
        storage_path.parent.mkdir(parents=True, exist_ok=True)

        return cls(
            storage_path=storage_path,
            dim=dim,
            max_elements=max_elements,
        )
