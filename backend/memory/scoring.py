"""P4 四因子检索评分 — recency × importance × confidence × relevance。

对标 Generative Agents (Park et al.) 的 retrieval scoring 与 Zep 的时间
有效性排序：RRF 融合只回答"像不像"（relevance），四因子把"新不新 /
重要不重要 / 可不可信"一并计入，综合分 ``composite_score`` ∈ [0, 1]。

各因子（均归一化到 [0,1]）:

- **relevance**  : RRF 融合分（k=60, 权重≤1 → 理论上限 1/61·2, 线性映射）。
  无 rrf_score 的行（非混合检索路径）按 0.5 中性处理。
- **recency**    : ``max(created_at, accessed_at)`` 的指数衰减
  （半衰期 30 天）。时间戳单位在存储层是毫秒，此处对秒级历史脏数据
  做防御性归一。
- **importance** : 存储层 1-10 评分 / 10；semantic 行无该列 → 0.5 中性。
- **confidence** : "被验证过"的启发式组合——经进化/固化晋升的行、
  冲突消解链上的最新事实（携带 supersedes_id）、被反复召回
  （access_count 加成）。基线 0.5, 上限 1.0。

注意：confidence 含 access_count, 而 ``episodic.get_by_id`` 会在检索时
自增计数——这是有意的"常用即可信"信号, 与 Generative Agents 的
reflection 加权同理。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 因子权重（和为 1.0）。relevance 占大头但不独占——避免纯字面命中
#: 的陈旧低可信记忆压过语义次优但更新更可信的事实。
WEIGHTS: Dict[str, float] = {
    "relevance": 0.40,
    "recency": 0.15,
    "importance": 0.25,
    "confidence": 0.20,
}

#: recency 半衰期（天）：30 天未更新的记忆 recency 因子减半
RECENCY_HALF_LIFE_DAYS = 30.0

#: RRF 分数的线性归一上限（k=60 双路满权重时约 2/61 ≈ 0.0328）
RRF_NORM_MAX = 2.0 / 61.0

#: 视为"被系统验证/晋升过"的 source 值（confidence 加成）
PROMOTED_SOURCES = frozenset(
    {"evolution", "consolidation_pipeline", "consolidation_cron", "reflection"}
)

#: 毫秒/秒归一的阈值（epoch 秒 ≈ 1.7e9, epoch 毫秒 ≈ 1.7e12）
_TS_SECOND_LIKE_LIMIT = 1e11


def _as_millis(ts: Any) -> Optional[float]:
    try:
        v = float(ts)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return v * 1000.0 if v < _TS_SECOND_LIKE_LIMIT else v


def _max_ts(row: Dict[str, Any]) -> Optional[float]:
    stamps = [
        t
        for t in (_as_millis(row.get("created_at")), _as_millis(row.get("accessed_at")))
        if t is not None
    ]
    return max(stamps) if stamps else None


# ---- 各因子 ----------------------------------------------------------------


def relevance_factor(row: Dict[str, Any]) -> float:
    try:
        rrf = float(row.get("rrf_score", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.5
    if rrf <= 0:
        return 0.5  # 非混合检索路径的行: 中性, 让其余因子说话
    return min(1.0, rrf / RRF_NORM_MAX)


def recency_factor(row: Dict[str, Any], now_ms: Optional[float] = None) -> float:
    ts = _max_ts(row)
    if ts is None:
        return 0.5
    now = now_ms if now_ms is not None else time.time() * 1000
    days = max(0.0, (now - ts) / 86_400_000)
    return 0.5 ** (days / RECENCY_HALF_LIFE_DAYS)


def importance_factor(row: Dict[str, Any]) -> float:
    try:
        imp = float(row.get("importance", 5) or 5)
    except (TypeError, ValueError):
        return 0.5
    return max(0.1, min(10.0, imp)) / 10.0


def confidence_factor(row: Dict[str, Any]) -> float:
    c = 0.5
    if str(row.get("source") or "") in PROMOTED_SOURCES:
        c += 0.2
    if row.get("supersedes_id"):
        # 冲突消解链上的最新事实：刚被"新信息"确认过一次
        c += 0.1
    try:
        accesses = int(row.get("access_count") or 0)
    except (TypeError, ValueError):
        accesses = 0
    c += 0.02 * min(max(accesses, 0), 10)
    return min(1.0, c)


def composite_score(row: Dict[str, Any], now_ms: Optional[float] = None) -> float:
    """四因子加权和 ∈ [0, 1]。"""
    return (
        WEIGHTS["relevance"] * relevance_factor(row)
        + WEIGHTS["recency"] * recency_factor(row, now_ms=now_ms)
        + WEIGHTS["importance"] * importance_factor(row)
        + WEIGHTS["confidence"] * confidence_factor(row)
    )


def rank_by_composite(
    rows: List[Dict[str, Any]], now_ms: Optional[float] = None
) -> List[Dict[str, Any]]:
    """给每行浅拷贝打上 ``composite_score`` 并按降序重排。

    不修改入参行（存储层返回的 dict 可能被调用方共享）。
    """
    now = now_ms if now_ms is not None else time.time() * 1000
    scored = []
    for row in rows:
        item = dict(row)
        item["composite_score"] = composite_score(item, now_ms=now)
        scored.append(item)
    scored.sort(key=lambda r: r["composite_score"], reverse=True)
    return scored


__all__ = [
    "PROMOTED_SOURCES",
    "RECENCY_HALF_LIFE_DAYS",
    "WEIGHTS",
    "composite_score",
    "confidence_factor",
    "importance_factor",
    "rank_by_composite",
    "recency_factor",
    "relevance_factor",
]
