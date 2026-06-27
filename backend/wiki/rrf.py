"""Reciprocal Rank Fusion (RRF)。

实现 RRF 算法，融合 token 搜索和向量搜索的结果。
"""

# 默认 RRF 常数
DEFAULT_RRF_K = 60.0


def rrf_fuse(
    token_items: list[str],
    vector_items: list[str],
    k: float = DEFAULT_RRF_K,
) -> list[tuple[str, float]]:
    """融合两个排序列表。

    RRF 公式: score(item) = Σ 1 / (k + rank_i)

    Args:
        token_items: token 搜索结果（按相关性排序的 item 列表）
        vector_items: 向量搜索结果（按相似度排序的 item 列表）
        k: RRF 常数（默认 60.0）

    Returns:
        list[tuple[str, float]]: 融合后的 (item, score) 列表，按 score 降序
    """
    scores: dict[str, float] = {}

    # Token 搜索贡献
    for rank, item in enumerate(token_items):
        scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)

    # 向量搜索贡献
    for rank, item in enumerate(vector_items):
        scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)

    # 按分数排序
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
