"""Reciprocal Rank Fusion - 混合检索融合

借鉴 Cherry Studio 的 RRF 实现，将多路检索结果（向量、关键词、图等）
融合为统一的排名列表。RRF 的优势是不需要归一化不同检索器的分数尺度。

公式: score = sum(α_i / (k + rank_i))
- k: 常数，通常取 60（Cherry Studio 默认）
- α_i: 第 i 路检索器的权重
- rank_i: 结果在第 i 路检索中的排名（1-based）
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(
    result_lists: list[list[dict[str, Any]]],
    weights: list[float] | None = None,
    k: int = 60,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion 融合多路检索结果

    Args:
        result_lists: 多路检索结果列表。每路是一个 dict 列表，
                      每个 dict 至少包含 "id" 字段用于去重。
        weights: 每路检索的权重（默认等权）。长度需与 result_lists 一致。
        k: RRF 常数，默认 60（Cherry Studio 使用值）。

    Returns:
        融合后的结果列表，按 RRF 分数降序排列。
        每个结果 dict 新增 "rrf_score" 字段。

    Example:
        >>> vector_results = [{"id": "a", "content": "..."}, {"id": "b"}]
        >>> keyword_results = [{"id": "b", "content": "..."}, {"id": "c"}]
        >>> fused = reciprocal_rank_fusion(
        ...     [vector_results, keyword_results],
        ...     weights=[0.6, 0.4]
        ... )
        >>> # "b" 在两路都出现，RRF 分数最高
    """
    if not result_lists:
        return []

    n_lists = len(result_lists)
    if weights is None:
        weights = [1.0 / n_lists] * n_lists
    elif len(weights) != n_lists:
        logger.warning(
            f"weights 长度 ({len(weights)}) 与 result_lists 长度 ({n_lists}) 不一致，使用等权"
        )
        weights = [1.0 / n_lists] * n_lists

    # 按 id 聚合分数
    scores: dict[str, float] = {}
    items: dict[str, dict[str, Any]] = {}

    for results, weight in zip(result_lists, weights, strict=False):
        for rank, item in enumerate(results, start=1):
            item_id = str(item.get("id", item.get("memory_id", id(item))))
            if item_id not in scores:
                scores[item_id] = 0.0
                items[item_id] = item
            scores[item_id] += weight / (k + rank)

    # 按 RRF 分数排序
    sorted_ids = sorted(scores, key=scores.get, reverse=True)

    result = []
    for item_id in sorted_ids:
        item = dict(items[item_id])  # 浅拷贝避免修改原始数据
        item["rrf_score"] = scores[item_id]
        result.append(item)

    return result
