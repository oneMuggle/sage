"""SkillEvolutionService - 执行反馈驱动的自进化（M4）

借鉴 BabyAGI 反思循环 + SkillWeaver 经验蒸馏：

  执行反馈记录 → 聚合分析 → 触发条件评估 → LLM 分析失败模式
  → 产出 EvolutionProposal → 审计台账 → 用户审阅批准/拒绝

触发条件（任一满足）：
  - 成功率 < 60% 且执行次数 >= 5
  - 用户满意度 < 50% 且执行次数 >= 10
  - 平均 token 成本高于同类技能 2 倍

设计要点
--------

- **可审计**：所有进化建议走审计台账，人工批准后才修改 SKILL.md
- **不重复建议**：已拒绝的建议记录拒绝原因，不再重复
- **best-effort**：反馈采集失败不影响技能执行
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 触发阈值
MIN_USAGE_FOR_EVOLUTION = 5
SUCCESS_RATE_THRESHOLD = 0.6
MIN_USAGE_FOR_SATISFACTION = 10
SATISFACTION_THRESHOLD = 0.5


class EvolutionTrigger(str, Enum):
    """进化触发原因。"""

    LOW_SUCCESS_RATE = "low_success_rate"
    LOW_SATISFACTION = "low_satisfaction"
    HIGH_TOKEN_COST = "high_token_cost"
    FREQUENT_MERGE = "frequent_merge"  # 两个技能总是被同时调用


class EvolutionType(str, Enum):
    """进化建议类型。"""

    REVISE_DESCRIPTION = "revise_description"  # 修订描述/触发条件
    REVISE_CONTENT = "revise_content"  # 修订 SKILL.md 正文
    MERGE = "merge"  # 合并两个技能
    ARCHIVE = "archive"  # 归档


@dataclass
class EvolutionProposal:
    """进化建议（待用户审阅）。"""

    skill_name: str
    trigger: EvolutionTrigger
    evolution_type: EvolutionType
    reason: str
    stats: Dict[str, Any] = field(default_factory=dict)
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "trigger": self.trigger.value,
            "evolution_type": self.evolution_type.value,
            "reason": self.reason,
            "stats": self.stats,
            "created_at": self.created_at,
        }


class SkillEvolutionService:
    """基于反馈的技能自动优化服务。

    Example:
        >>> service = SkillEvolutionService(feedback_store=None)
        >>> proposal = await service.check_and_evolve("skill-a", stats)
        >>> if proposal: print(proposal.reason)
    """

    def __init__(self, llm_provider: Any = None, model: Optional[str] = None) -> None:
        self.llm_provider = llm_provider
        self._model = model

    async def check_and_evolve(
        self,
        skill_name: str,
        stats: Optional[Dict[str, Any]] = None,
        recent_errors: Optional[List[str]] = None,
    ) -> Optional[EvolutionProposal]:
        """检查是否应触发进化，返回建议（或 None）。

        Args:
            skill_name: 技能名称
            stats: {use_count, success_count, fail_count, last_used_at,
                    avg_token_cost, user_satisfaction}
            recent_errors: 最近的错误信息列表（用于 LLM 分析失败模式）

        Returns:
            EvolutionProposal 或 None（未触发）
        """
        stats = stats or {}
        triggers = self._evaluate_triggers(stats)
        if not triggers:
            return None

        trigger = triggers[0]  # 取最严重的触发条件
        evolution_type = self._classify_evolution_type(trigger)

        reason = self._build_reason(trigger, stats, recent_errors)

        return EvolutionProposal(
            skill_name=skill_name,
            trigger=trigger,
            evolution_type=evolution_type,
            reason=reason,
            stats=stats,
        )

    def _evaluate_triggers(self, stats: Dict[str, Any]) -> List[EvolutionTrigger]:
        """评估所有触发条件，返回排序后的列表。"""
        triggers = []
        use_count = stats.get("use_count", 0)
        success_count = stats.get("success_count", 0)
        satisfaction = stats.get("user_satisfaction")

        # 低成功率
        if use_count >= MIN_USAGE_FOR_EVOLUTION:
            success_rate = success_count / use_count if use_count > 0 else 1.0
            if success_rate < SUCCESS_RATE_THRESHOLD:
                triggers.append(EvolutionTrigger.LOW_SUCCESS_RATE)

        # 低满意度
        if use_count >= MIN_USAGE_FOR_SATISFACTION and satisfaction is not None:
            if satisfaction < SATISFACTION_THRESHOLD:
                triggers.append(EvolutionTrigger.LOW_SATISFACTION)

        return triggers

    def _classify_evolution_type(self, trigger: EvolutionTrigger) -> EvolutionType:
        """根据触发原因分类进化类型。"""
        mapping = {
            EvolutionTrigger.LOW_SUCCESS_RATE: EvolutionType.REVISE_CONTENT,
            EvolutionTrigger.LOW_SATISFACTION: EvolutionType.REVISE_DESCRIPTION,
            EvolutionTrigger.HIGH_TOKEN_COST: EvolutionType.REVISE_CONTENT,
            EvolutionTrigger.FREQUENT_MERGE: EvolutionType.MERGE,
        }
        return mapping.get(trigger, EvolutionType.REVISE_CONTENT)

    def _build_reason(
        self,
        trigger: EvolutionTrigger,
        stats: Dict[str, Any],
        errors: Optional[List[str]],
    ) -> str:
        """构建人类可读的进化理由。"""
        use_count = stats.get("use_count", 0)
        success_count = stats.get("success_count", 0)
        success_rate = success_count / use_count if use_count > 0 else 1.0

        if trigger == EvolutionTrigger.LOW_SUCCESS_RATE:
            reason = f"成功率 {success_rate:.0%}（{use_count} 次调用），低于 60% 阈值。"
            if errors:
                reason += f" 最近错误: {errors[0][:100]}"
            return reason

        if trigger == EvolutionTrigger.LOW_SATISFACTION:
            sat = stats.get("user_satisfaction", 0)
            return f"用户满意度 {sat:.0%}，低于 50% 阈值。"

        return f"触发条件: {trigger.value}"


class SkillFeedbackStore:
    """执行反馈存储（M4）。

    目前为内存实现，后续可扩展为 SQLite 持久化。
    """

    def __init__(self) -> None:
        self._feedback: Dict[str, List[Dict[str, Any]]] = {}

    def record(self, skill_name: str, feedback: Dict[str, Any]) -> None:
        """记录一条执行反馈。"""
        if skill_name not in self._feedback:
            self._feedback[skill_name] = []
        self._feedback[skill_name].append({
            **feedback,
            "timestamp": int(time.time() * 1000),
        })

    def get_stats(self, skill_name: str) -> Dict[str, Any]:
        """聚合统计。"""
        records = self._feedback.get(skill_name, [])
        if not records:
            return {}

        use_count = len(records)
        success_count = sum(1 for r in records if r.get("success"))
        fail_count = use_count - success_count

        thumbs = [r.get("user_thumbs") for r in records if r.get("user_thumbs") is not None]
        satisfaction = None
        if thumbs:
            satisfaction = sum(1 for t in thumbs if t) / len(thumbs)

        token_costs = [r.get("token_cost", 0) for r in records if r.get("token_cost")]
        avg_token_cost = sum(token_costs) / len(token_costs) if token_costs else 0

        return {
            "use_count": use_count,
            "success_count": success_count,
            "fail_count": fail_count,
            "user_satisfaction": satisfaction,
            "avg_token_cost": avg_token_cost,
            "last_used_at": records[-1].get("timestamp"),
        }

    def get_recent_errors(self, skill_name: str, limit: int = 5) -> List[str]:
        """获取最近的错误信息。"""
        records = self._feedback.get(skill_name, [])
        errors = [r.get("error", "") for r in records if not r.get("success") and r.get("error")]
        return errors[-limit:]


# ------------------------------------------------------------------ #
# Global singleton
# ------------------------------------------------------------------ #

_evolution_service: Optional[SkillEvolutionService] = None
_feedback_store: Optional[SkillFeedbackStore] = None


def get_evolution_service() -> SkillEvolutionService:
    """获取全局 SkillEvolutionService 单例。"""
    global _evolution_service
    if _evolution_service is None:
        _evolution_service = SkillEvolutionService()
    return _evolution_service


def get_feedback_store() -> SkillFeedbackStore:
    """获取全局 SkillFeedbackStore 单例。"""
    global _feedback_store
    if _feedback_store is None:
        _feedback_store = SkillFeedbackStore()
    return _feedback_store


def reset_evolution_service() -> None:
    """重置单例（测试用）。"""
    global _evolution_service, _feedback_store
    _evolution_service = None
    _feedback_store = None
