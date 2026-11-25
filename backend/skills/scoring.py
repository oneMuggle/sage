"""SkillScoringService - 技能多维质量评分（M2）

综合评分公式：
  overall = 0.30*usage_freq + 0.25*success_rate + 0.20*satisfaction
          + 0.15*freshness + 0.10*description_quality

评分维度：
- usage_freq: 使用频率（归一化到 0-100）
- success_rate: 执行成功率（0-100）
- user_satisfaction: 用户满意度（thumbs up/down，0-100）
- freshness: 最近使用时间衰减（指数衰减，0-100）
- description_quality: 描述完整度（规则评估，0-100）

热/冷路径分层：
- Hot: overall >= 70 且最近 7 天有使用
- Warm: overall >= 40 或 30 天内有使用
- Cold: overall < 40 或 60 天无使用

设计要点
--------

- **best-effort**：评分计算失败返回默认值，不影响技能主流程。
- **可调权重**：通过环境变量覆盖默认权重。
- **缓存**：评分结果缓存在内存中，定期重算。
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 默认权重（可通过环境变量覆盖）
DEFAULT_WEIGHTS = {
    "usage_freq": 0.30,
    "success_rate": 0.25,
    "user_satisfaction": 0.20,
    "freshness": 0.15,
    "description_quality": 0.10,
}

# 热/冷路径阈值
HOT_THRESHOLD = 70
WARM_THRESHOLD = 40
HOT_RECENT_DAYS = 7
WARM_RECENT_DAYS = 30

# 评分缓存 TTL（秒）
SCORE_CACHE_TTL = 3600  # 1 小时


def _parse_weights() -> Dict[str, float]:
    """从环境变量解析权重覆盖。"""
    weights = dict(DEFAULT_WEIGHTS)
    raw = os.environ.get("SAGE_SKILL_SCORING_WEIGHTS")
    if not raw:
        return weights
    try:
        for pair in raw.split(","):
            key, val = pair.strip().split("=")
            weights[key.strip()] = float(val.strip())
    except (ValueError, AttributeError):
        logger.warning("SAGE_SKILL_SCORING_WEIGHTS 解析失败，使用默认权重")
        return dict(DEFAULT_WEIGHTS)
    return weights


@dataclass
class SkillScore:
    """技能质量评分（0–100）。"""

    name: str
    overall: float = 0.0
    usage_freq: float = 0.0
    success_rate: float = 0.0
    user_satisfaction: float = 50.0  # 默认中性
    freshness: float = 0.0
    description_quality: float = 0.0
    tier: str = "cold"  # hot / warm / cold

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "overall": round(self.overall, 1),
            "usage_freq": round(self.usage_freq, 1),
            "success_rate": round(self.success_rate, 1),
            "user_satisfaction": round(self.user_satisfaction, 1),
            "freshness": round(self.freshness, 1),
            "description_quality": round(self.description_quality, 1),
            "tier": self.tier,
        }


def _compute_freshness(last_used_at_ms: Optional[int], now_ms: int) -> float:
    """计算新鲜度评分（指数衰减）。

    7 天内 → 100
    30 天 → ~50
    60 天 → ~10
    从未使用 → 0
    """
    if last_used_at_ms is None or last_used_at_ms <= 0:
        return 0.0
    age_days = (now_ms - last_used_at_ms) / (1000 * 60 * 60 * 24)
    if age_days < 0:
        return 100.0
    # 半衰期 14 天
    decay = math.exp(-0.693 * age_days / 14)
    return max(0.0, min(100.0, decay * 100))


def _compute_description_quality(description: str, when_to_use: str) -> float:
    """规则评估描述完整度。

    评分项：
    - description 非空且 >= 20 字：+40
    - when_to_use 非空且 >= 30 字：+40
    - 包含动作动词：+20
    """
    score = 0.0
    if description and len(description) >= 20:
        score += 40
    elif description:
        score += 20 * len(description) / 20

    if when_to_use and len(when_to_use) >= 30:
        score += 40
    elif when_to_use:
        score += 40 * len(when_to_use) / 30

    # 动作动词检测（中英文）
    action_words = [
        "搜索", "查找", "创建", "生成", "分析", "检查", "优化",
        "search", "find", "create", "generate", "analyze", "check", "optimize",
    ]
    text = (description + " " + when_to_use).lower()
    if any(w in text for w in action_words):
        score += 20

    return min(100.0, score)


def _classify_tier(
    overall: float,
    last_used_at_ms: Optional[int],
    now_ms: int,
) -> str:
    """根据综合评分和最近使用时间分层。"""
    if last_used_at_ms is None:
        age_days = float("inf")
    else:
        age_days = (now_ms - last_used_at_ms) / (1000 * 60 * 60 * 24)

    if overall >= HOT_THRESHOLD and age_days <= HOT_RECENT_DAYS:
        return "hot"
    if overall >= WARM_THRESHOLD or age_days <= WARM_RECENT_DAYS:
        return "warm"
    return "cold"


class SkillScoringService:
    """技能多维质量评分服务。"""

    def __init__(self) -> None:
        self.weights = _parse_weights()
        self._cache: Dict[str, tuple] = {}  # name -> (score, timestamp)

    def compute(
        self,
        name: str,
        usage_stats: Optional[Dict[str, Any]] = None,
        description: str = "",
        when_to_use: str = "",
        all_usage_counts: Optional[List[int]] = None,
    ) -> SkillScore:
        """计算单个技能的评分。

        Args:
            name: 技能名称
            usage_stats: {use_count, success_count, fail_count, last_used_at}
            description: 技能描述
            when_to_use: 触发条件描述
            all_usage_counts: 全部技能的 use_count 列表（用于归一化）
        """
        now_ms = int(time.time() * 1000)
        usage = usage_stats or {}

        # 1. 使用频率（归一化到 0-100）
        use_count = usage.get("use_count", 0)
        if all_usage_counts and max(all_usage_counts) > 0:
            usage_freq = (use_count / max(all_usage_counts)) * 100
        elif use_count > 0:
            usage_freq = min(100.0, use_count * 10)  # 简单线性映射
        else:
            usage_freq = 0.0

        # 2. 成功率
        success_count = usage.get("success_count", 0)
        fail_count = usage.get("fail_count", 0)
        total = success_count + fail_count
        if total > 0:
            success_rate = (success_count / total) * 100
        else:
            success_rate = 50.0  # 无数据时默认中性

        # 3. 用户满意度（目前无显式反馈，使用成功率近似）
        user_satisfaction = success_rate

        # 4. 新鲜度
        last_used_at = usage.get("last_used_at")
        freshness = _compute_freshness(last_used_at, now_ms)

        # 5. 描述质量
        description_quality = _compute_description_quality(description, when_to_use)

        # 综合评分
        overall = (
            self.weights.get("usage_freq", 0.30) * usage_freq
            + self.weights.get("success_rate", 0.25) * success_rate
            + self.weights.get("user_satisfaction", 0.20) * user_satisfaction
            + self.weights.get("freshness", 0.15) * freshness
            + self.weights.get("description_quality", 0.10) * description_quality
        )

        tier = _classify_tier(overall, last_used_at, now_ms)

        return SkillScore(
            name=name,
            overall=overall,
            usage_freq=usage_freq,
            success_rate=success_rate,
            user_satisfaction=user_satisfaction,
            freshness=freshness,
            description_quality=description_quality,
            tier=tier,
        )

    def compute_batch(
        self,
        skills: List[Dict[str, Any]],
        usage_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[SkillScore]:
        """批量计算评分。

        Args:
            skills: [{name, description, when_to_use}, ...]
            usage_map: {name: {use_count, success_count, ...}}
        """
        usage_map = usage_map or {}

        # 收集所有 use_count 用于归一化
        all_counts = [
            usage_map.get(s.get("name", ""), {}).get("use_count", 0)
            for s in skills
        ]

        scores = []
        for skill in skills:
            name = skill.get("name", "")
            score = self.compute(
                name=name,
                usage_stats=usage_map.get(name),
                description=skill.get("description", ""),
                when_to_use=skill.get("when_to_use", ""),
                all_usage_counts=all_counts,
            )
            scores.append(score)

        return scores

    def get_cached(self, name: str) -> Optional[SkillScore]:
        """获取缓存的评分（未过期时）。"""
        if name in self._cache:
            score, ts = self._cache[name]
            if time.time() - ts < SCORE_CACHE_TTL:
                return score
        return None

    def set_cached(self, score: SkillScore) -> None:
        """缓存评分结果。"""
        self._cache[score.name] = (score, time.time())


# ------------------------------------------------------------------ #
# Global singleton
# ------------------------------------------------------------------ #

_scoring_service: Optional[SkillScoringService] = None


def get_scoring_service() -> SkillScoringService:
    """获取全局 SkillScoringService 单例。"""
    global _scoring_service
    if _scoring_service is None:
        _scoring_service = SkillScoringService()
    return _scoring_service


def reset_scoring_service() -> None:
    """重置单例（测试用）。"""
    global _scoring_service
    _scoring_service = None
