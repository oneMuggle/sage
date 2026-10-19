"""标签共现图谱 - 轻量级知识图谱

基于记忆标签的共现关系构建简单图谱，用于增强检索。

核心思想：
- 标签经常一起出现的记忆之间存在关联
- 查询命中某标签时，关联标签的记忆也应被召回
- 用共现频率作为关联强度权重

数据结构：
- tag_cooccurrence: Dict[tag_a, Dict[tag_b, count]]
  记录标签对 (a, b) 共同出现的次数
- tag_memory_index: Dict[tag, Set[memory_id]]
  记录每个标签关联的记忆 ID 集合

使用方式：
    graph = TagCooccurrenceGraph()

    # 构建图谱（从现有记忆）
    graph.build_from_memories(episodic_memory, semantic_memory)

    # 查询关联记忆
    related_ids = graph.query(["python", "fastapi"], top_k=10)
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)


class TagCooccurrenceGraph:
    """标签共现图谱

    Attributes:
        tag_cooccurrence: 标签共现矩阵
        tag_memory_index: 标签到记忆的索引
        total_memories: 构建图谱时使用的记忆总数
    """

    def __init__(self) -> None:
        """初始化图谱"""
        self.tag_cooccurrence: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.tag_memory_index: Dict[str, Set[str]] = defaultdict(set)
        self.total_memories = 0

    def build_from_memories(
        self,
        episodic_memory: Any,
        semantic_memory: Any,
        limit: int = 1000,
    ) -> None:
        """从现有记忆构建共现图谱

        Args:
            episodic_memory: EpisodicMemory 实例
            semantic_memory: SemanticMemory 实例
            limit: 每张表最多处理的记忆数量
        """
        logger.info("[tag_graph] 开始构建标签共现图谱...")

        # 收集所有记忆的标签
        all_tags: List[List[str]] = []
        memory_ids: List[str] = []

        # 从 episodic 记忆抽取
        episodic_recent = episodic_memory.get_recent(limit=limit)
        for mem in episodic_recent:
            tags = mem.get("tags") or []
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except json.JSONDecodeError:
                    tags = []
            if tags:
                all_tags.append(tags)
                memory_ids.append(mem["id"])

        # 从 semantic 记忆抽取
        semantic_recent = semantic_memory.get_recent(limit=limit)
        for mem in semantic_recent:
            tags = mem.get("tags") or []
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except json.JSONDecodeError:
                    tags = []
            if tags:
                all_tags.append(tags)
                memory_ids.append(mem["id"])

        # 构建共现矩阵
        for tags in all_tags:
            # 去重
            unique_tags = list(set(tags))
            # 两两共现
            for i, tag_a in enumerate(unique_tags):
                for tag_b in unique_tags[i + 1 :]:
                    # 对称更新
                    self.tag_cooccurrence[tag_a][tag_b] += 1
                    self.tag_cooccurrence[tag_b][tag_a] += 1

        # 构建标签到记忆的索引
        for mem_id, tags in zip(memory_ids, all_tags):  # noqa: B905
            for tag in tags:
                self.tag_memory_index[tag].add(mem_id)

        self.total_memories = len(memory_ids)
        logger.info(
            f"[tag_graph] 图谱构建完成: {self.total_memories} 条记忆, "
            f"{len(self.tag_cooccurrence)} 个标签, "
            f"{sum(len(v) for v in self.tag_cooccurrence.values()) // 2} 条边"
        )

    def query(
        self,
        query_tags: List[str],
        top_k: int = 10,
        min_cooccurrence: int = 2,
    ) -> List[Dict[str, Any]]:
        """查询关联记忆

        Args:
            query_tags: 查询标签列表
            top_k: 返回的最大记忆数
            min_cooccurrence: 最小共现次数阈值（过滤噪声）

        Returns:
            关联记忆列表，每项包含：
                - memory_id: 记忆 ID
                - score: 关联强度分数
                - matched_tags: 匹配的标签列表
        """
        if not query_tags:
            return []

        # 收集所有关联标签及其强度
        related_tag_scores: Dict[str, float] = defaultdict(float)

        for query_tag in query_tags:
            # 直接匹配
            related_tag_scores[query_tag] += 1.0

            # 共现标签
            cooccurrence = self.tag_cooccurrence.get(query_tag, {})
            for related_tag, count in cooccurrence.items():
                if count >= min_cooccurrence:
                    # 共现强度 = 共现次数 / 查询标签的总边数（归一化）
                    total_edges = sum(cooccurrence.values())
                    strength = count / total_edges if total_edges > 0 else 0
                    related_tag_scores[related_tag] += strength

        # 按关联强度排序标签
        sorted_tags = sorted(related_tag_scores.items(), key=lambda x: x[1], reverse=True)

        # 收集关联记忆
        memory_scores: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"score": 0.0, "matched_tags": []}
        )

        for tag, tag_score in sorted_tags[:20]:  # 只取 top 20 标签
            for mem_id in self.tag_memory_index.get(tag, set()):
                memory_scores[mem_id]["score"] += tag_score
                memory_scores[mem_id]["matched_tags"].append(tag)

        # 按分数排序，返回 top_k
        sorted_memories = sorted(
            memory_scores.items(),
            key=lambda x: x[1]["score"],
            reverse=True,
        )[:top_k]

        results = [
            {
                "memory_id": mem_id,
                "score": data["score"],
                "matched_tags": list(set(data["matched_tags"])),  # 去重
            }
            for mem_id, data in sorted_memories
        ]

        logger.debug(
            f"[tag_graph] 查询 {query_tags} → {len(results)} 条关联记忆"
        )
        return results

    def get_related_tags(
        self,
        tag: str,
        top_k: int = 10,
        min_cooccurrence: int = 2,
    ) -> List[Dict[str, Any]]:
        """获取与指定标签最相关的标签

        Args:
            tag: 查询标签
            top_k: 返回的最大标签数
            min_cooccurrence: 最小共现次数阈值

        Returns:
            相关标签列表，每项包含：
                - tag: 标签名
                - cooccurrence: 共现次数
                - strength: 关联强度
        """
        cooccurrence = self.tag_cooccurrence.get(tag, {})
        if not cooccurrence:
            return []

        # 过滤低共现
        filtered = {
            related_tag: count
            for related_tag, count in cooccurrence.items()
            if count >= min_cooccurrence
        }

        # 计算总边数（用于归一化）
        total_edges = sum(cooccurrence.values())

        # 排序
        sorted_tags = sorted(filtered.items(), key=lambda x: x[1], reverse=True)[:top_k]

        return [
            {
                "tag": related_tag,
                "cooccurrence": count,
                "strength": count / total_edges if total_edges > 0 else 0,
            }
            for related_tag, count in sorted_tags
        ]

    def export_stats(self) -> Dict[str, Any]:
        """导出图谱统计信息

        Returns:
            统计信息字典
        """
        total_edges = sum(len(v) for v in self.tag_cooccurrence.values()) // 2
        avg_edges_per_tag = (
            total_edges / len(self.tag_cooccurrence) if self.tag_cooccurrence else 0
        )

        return {
            "total_memories": self.total_memories,
            "total_tags": len(self.tag_cooccurrence),
            "total_edges": total_edges,
            "avg_edges_per_tag": avg_edges_per_tag,
            "top_tags": sorted(
                self.tag_cooccurrence.keys(),
                key=lambda t: len(self.tag_memory_index.get(t, set())),
                reverse=True,
            )[:20],
        }
