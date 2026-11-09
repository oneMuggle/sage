"""记忆质量评分器（Task 3.3）。

反思任务负责"合并/失效"，但一条记忆是否值得留在库里，取决于另一组
信号：写得清不清楚、重不重要、多久没用过、是不是跟别的记忆重复。
本模块给每条记忆算一个 0-1 的质量分，并给出"是否该清理"的判定。

维度与权重（总和 1.0）：

===========  ======  ==========================================
维度          权重    依据
===========  ======  ==========================================
清晰度        0.25   长度适中、无截断痕迹
重要性        0.25   ``importance`` 字段（0-10）
新鲜度        0.20   创建时间距今，半衰期 60 天
使用频率      0.15   ``access_count``
独特性        0.15   与库中其他记忆的最大相似度（越不相似越高）
===========  ======  ==========================================

**时间戳一律毫秒**。``memories_episodic.created_at`` / ``accessed_at``
写的是 ``int(time.time() * 1000)``；遗留行可能是秒级，统一经
``scoring._as_millis`` 归一（< 1e11 视为秒）。

独特性需要"其他记忆"作参照，故评分器接受一个语料（corpus）。
没有语料时独特性按 1.0 计 —— 无法判断时不该惩罚，更不该因此删记忆。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from backend.memory.scoring import _as_millis

logger = logging.getLogger(__name__)

#: 各维度权重（总和 = 1.0）
WEIGHTS: Dict[str, float] = {
    "clarity": 0.25,
    "importance": 0.25,
    "recency": 0.20,
    "usage": 0.15,
    "uniqueness": 0.15,
}

#: 新鲜度半衰期（天）—— 比检索排序的 30 天宽松：这里的"新鲜"只作
#: 轻微衰减，不该让一条老但重要的记忆被判死刑。
RECENCY_HALF_LIFE_DAYS = 60.0

#: 质量分低于此值才具备被清理的资格（还要再满足"长期未访问"）
LOW_QUALITY_THRESHOLD = 0.3

#: 距上次访问超过此天数才允许清理 —— 新建但还没被检索到的记忆
#: 天然 access_count=0，只靠质量分会误伤。
STALE_DAYS = 90.0

#: 访问多少次算"用得很勤"（封顶 1.0）
USAGE_SATURATION = 10

#: 内容长度：低于此值视为残缺；此值以内视为"长度适中"
MIN_CONTENT_LENGTH = 4
IDEAL_CONTENT_LENGTH = 30
#: 超过此值开始扣分
MAX_CONTENT_LENGTH = 500

#: 语料上限 —— 独特性是 O(N*M) 比较，语料太大时按最近 N 条取样。
MAX_CORPUS = 200

#: importance 字段的取值上限
MAX_IMPORTANCE = 10.0

#: 截断痕迹 —— 命中则清晰度减半
_TRUNCATION_MARKERS = ("...", "…")


def _bigrams(text: str) -> Set[str]:
    """字符二元组集合（中文上比单字更能区分文本）。"""
    compact = "".join((text or "").split())
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / float(len(a | b))


class MemoryQualityScorer:
    """记忆质量评分器。

    Args:
        corpus: 用于计算独特性的参照语料（记忆 dict 列表，含
            ``id`` / ``content``）。可为空 —— 此时独特性恒为 1.0。
        now_ms: 当前时间（毫秒）。测试可注入固定值。
    """

    def __init__(
        self,
        corpus: Optional[Iterable[Dict[str, Any]]] = None,
        now_ms: Optional[float] = None,
    ) -> None:
        self.now_ms = float(now_ms) if now_ms is not None else time.time() * 1000.0
        self._corpus: List[Dict[str, Any]] = []
        self._corpus_bigrams: List[Set[str]] = []
        self.set_corpus(corpus or [])

    # ---- 语料 ---------------------------------------------------------------

    def set_corpus(self, corpus: Iterable[Dict[str, Any]]) -> None:
        """设置参照语料（截断到 ``MAX_CORPUS`` 条）。"""
        rows = list(corpus or [])[:MAX_CORPUS]
        self._corpus = rows
        self._corpus_bigrams = [_bigrams(r.get("content") or "") for r in rows]

    # ---- 单维度因子 ---------------------------------------------------------

    @staticmethod
    def _score_clarity(content: str) -> float:
        """清晰度：长度适中且无截断痕迹 → 1.0。

        长度只数有效字符（字母/数字/汉字）—— 标点与空白不算。"嗯..."
        这类只剩语气词和省略号的内容不该因为凑够 4 个字符就算"适中"。
        """
        text = (content or "").strip()
        if not text:
            return 0.0
        length = sum(1 for ch in text if ch.isalnum())
        if length < MIN_CONTENT_LENGTH:
            score = 0.2
        elif length <= IDEAL_CONTENT_LENGTH:
            score = 1.0
        elif length <= MAX_CONTENT_LENGTH:
            score = 1.0 - 0.5 * (length - IDEAL_CONTENT_LENGTH) / (
                MAX_CONTENT_LENGTH - IDEAL_CONTENT_LENGTH
            )
        else:
            # 超长继续衰减，但留一个 0.5 的底 —— 长记忆往往信息量大，
            # 不该因为长就判死刑。
            score = 0.5 * max(
                0.0,
                1.0 - (length - MAX_CONTENT_LENGTH) / MAX_CONTENT_LENGTH,
            )
        if text.endswith(_TRUNCATION_MARKERS):
            score *= 0.5
        return max(0.0, min(1.0, score))

    @staticmethod
    def _score_importance(memory: Dict[str, Any]) -> float:
        """重要性：``importance`` 字段（0-10）归一到 0-1。"""
        try:
            value = float(memory.get("importance") or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value < 0:
            value = 0.0
        return min(1.0, value / MAX_IMPORTANCE)

    def _score_recency(self, memory: Dict[str, Any]) -> float:
        """新鲜度：距今天数按半衰期衰减。"""
        created = _as_millis(memory.get("created_at"))
        if not created:
            return 0.0
        days_old = max(0.0, (self.now_ms - created) / 86_400_000.0)
        return 0.5 ** (days_old / RECENCY_HALF_LIFE_DAYS)

    @staticmethod
    def _score_usage(memory: Dict[str, Any]) -> float:
        """使用频率：``access_count`` 饱和到 1.0。"""
        try:
            count = float(memory.get("access_count") or 0)
        except (TypeError, ValueError):
            count = 0.0
        if count < 0:
            count = 0.0
        return min(1.0, count / USAGE_SATURATION)

    def _score_uniqueness(self, memory: Dict[str, Any]) -> float:
        """独特性：1 - 与语料中其他记忆的最大相似度。

        没有语料时返回 1.0 —— 无法判断时不该惩罚。
        """
        if not self._corpus:
            return 1.0
        own = _bigrams(memory.get("content") or "")
        if not own:
            return 0.0
        own_id = memory.get("id")
        best = 0.0
<<<<<<< HEAD
        for row, bigrams in zip(self._corpus, self._corpus_bigrams):
=======
        for row, bigrams in zip(self._corpus, self._corpus_bigrams):  # noqa: B905 -- py3.8 兼容
>>>>>>> origin/main
            if own_id is not None and row.get("id") == own_id:
                continue
            best = max(best, _jaccard(own, bigrams))
            if best >= 1.0:
                break
        return max(0.0, 1.0 - best)

    # ---- 汇总 ---------------------------------------------------------------

    def score_breakdown(self, memory: Dict[str, Any]) -> Dict[str, float]:
        """各维度得分（诊断用：低分时能看出是哪一项拖后腿）。"""
        return {
            "clarity": self._score_clarity(memory.get("content") or ""),
            "importance": self._score_importance(memory),
            "recency": self._score_recency(memory),
            "usage": self._score_usage(memory),
            "uniqueness": self._score_uniqueness(memory),
        }

    def calculate_quality_score(self, memory: Dict[str, Any]) -> float:
        """计算记忆质量分（0-1）。"""
        parts = self.score_breakdown(memory)
        score = sum(WEIGHTS[key] * value for key, value in parts.items())
        return max(0.0, min(1.0, score))

    def days_since_access(self, memory: Dict[str, Any]) -> float:
        """距上次访问（无访问记录则用创建时间）的天数。"""
        stamp = _as_millis(memory.get("accessed_at")) or _as_millis(
            memory.get("created_at")
        )
        if not stamp:
            return float("inf")
        return max(0.0, (self.now_ms - stamp) / 86_400_000.0)

    def should_delete(self, memory: Dict[str, Any]) -> bool:
        """质量分低于阈值 **且** 长期未被访问 → 该清理。

        两个条件缺一不可：只看质量分会误伤"刚建好还没被用到"的记忆。
        """
        if self.calculate_quality_score(memory) >= LOW_QUALITY_THRESHOLD:
            return False
        return self.days_since_access(memory) > STALE_DAYS

    def rank_lowest(
        self, memories: Sequence[Dict[str, Any]], limit: int = 10
    ) -> List[Tuple[str, float]]:
        """挑出质量分最低的若干条（诊断/候选清单用）。"""
        scored = [
            (m.get("id", ""), self.calculate_quality_score(m)) for m in memories
        ]
        scored.sort(key=lambda pair: pair[1])
        return scored[:limit]


__all__ = [
    "LOW_QUALITY_THRESHOLD",
    "MAX_CORPUS",
    "MemoryQualityScorer",
    "RECENCY_HALF_LIFE_DAYS",
    "STALE_DAYS",
    "WEIGHTS",
]
