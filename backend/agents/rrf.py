"""M2-Task 3 — 多路 RRF（Reciprocal Rank Fusion）融合纯函数。

专家知识检索会把「每个绑定源的排序结果」当作一路，统一融合：::

    score(d) = Σ_i 1 / (k + rank_i(d))       # rank 从 0 起

与既有两个 RRF 实现的分工（避免误判为重复实现）：

- ``backend/wiki/rrf.py``：恰好两路（token + vector），返回 ``(id, score)``；
- ``backend/memory/fusion.py``：1-based 排名 + 归一化权重 + 向 dict
  注入 ``rrf_score``，服务于记忆召回；
- 本模块：N 路、0-based 排名（与 wiki 约定一致）、返回类型化的
  ``FusedRank``，并记录每条结果来自哪几路（``sources``），供检索层
  关联绑定元数据。

全部为纯函数，无 I/O；Python 3.8 兼容（``typing`` 泛型）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

#: RRF 常数；60 为 wiki/memory 两侧与业内默认值。
DEFAULT_RRF_K = 60.0


@dataclass(frozen=True)
class FusedRank:
    """融合后的单条排名。

    Attributes:
        item_id: 稳定文档标识（检索层约定 ``<page_path>::<chunk_index>``）。
        score: RRF 分数，越大越相关。
        sources: 贡献过该条目的路（ranking）下标元组，升序。
    """

    item_id: str
    score: float
    sources: Tuple[int, ...]


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    *,
    k: float = DEFAULT_RRF_K,
    top_k: Optional[int] = None,
) -> List[FusedRank]:
    """融合多路有序 id 列表，返回按 RRF 分数降序的结果。

    同一路排序内重复出现的 id 只计第一次排名（避免刷分）；跨路重复
    是 RRF 的正常语义，予以累加。

    Args:
        rankings: 每路的 id 序列，须已按相关性降序排列。
        k: RRF 常数，必须为正。
        top_k: 可选的截断长度（在排序之后应用）。

    Returns:
        List[FusedRank]: 分数降序；同分时按 ``item_id`` 字典序，保证
        确定性输出。

    Raises:
        ValueError: ``k <= 0``。
    """
    if k <= 0:
        raise ValueError(f"RRF 常数必须为正: {k!r}")

    scores: Dict[str, float] = {}
    sources: Dict[str, List[int]] = {}

    for ranking_index, ranking in enumerate(rankings):
        seen_in_ranking = set()
        for rank, item_id in enumerate(ranking):
            if item_id in seen_in_ranking:
                continue
            seen_in_ranking.add(item_id)
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
            sources.setdefault(item_id, []).append(ranking_index)

    fused = [
        FusedRank(item_id=item_id, score=score, sources=tuple(sources[item_id]))
        for item_id, score in scores.items()
    ]
    fused.sort(key=lambda item: (-item.score, item.item_id))

    if top_k is not None:
        fused = fused[: max(0, top_k)]
    return fused
