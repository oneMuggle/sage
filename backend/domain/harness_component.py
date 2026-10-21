"""Harness 组件领域模型（纯，零外部依赖）。

Harness 是围绕 LLM 模型的运行时脚手架，使模型能够作为自主 agent 行动。
Sage 的 harness 由 8 个可替换组件组成，每个组件都有独立的 effectiveness 指标。

对标参考：
- Google Harness 2: 8 个可编辑组件 (system_prompt/guardrails/memory/tool_guidance/
  subagents/skills/scripts/plugins)
- DeepSeek Harness: everything-is-a-plugin + Capability seams
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

# Harness 组件类型（8 个，对齐 Harness 2）
HarnessComponentType = Literal[
    "system_prompt",      # 系统提示词组装
    "guardrails",         # 安全守卫规则
    "memory",             # 记忆系统
    "tool_guidance",      # 工具描述与使用指导
    "subagents",          # 子代理编排策略
    "skills",             # 技能系统
    "scripts",            # 脚本工具（白名单）
    "plugins",            # 扩展插件（新增机制）
]


@dataclass(frozen=True)
class EffectivenessMetrics:
    """Harness 组件的 effectiveness 指标。

    用于衡量组件的使用情况和质量，为自动优化提供数据基础。

    Attributes:
        usage_count:          调用次数
        success_rate:         成功率 [0, 1]
        avg_latency_ms:       平均延迟（毫秒）
        user_satisfaction:    用户满意度 [0, 1]，可选（未来扩展）
        last_used_at:         最后使用时间（ISO-8601）
    """

    usage_count: int = 0
    success_rate: float = 1.0
    avg_latency_ms: float = 0.0
    user_satisfaction: Optional[float] = None
    last_used_at: Optional[str] = None

    @classmethod
    def from_usage_data(
        cls,
        usage_count: int,
        success_count: int,
        total_latency_ms: float,
        user_satisfaction_sum: float = 0.0,
        user_satisfaction_count: int = 0,
        last_used_at: Optional[str] = None,
    ) -> EffectivenessMetrics:
        """从原始使用数据计算 effectiveness 指标。

        Args:
            usage_count: 总调用次数
            success_count: 成功次数
            total_latency_ms: 总延迟（毫秒）
            user_satisfaction_sum: 用户满意度总和
            user_satisfaction_count: 用户满意度评分次数
            last_used_at: 最后使用时间

        Returns:
            EffectivenessMetrics 实例
        """
        success_rate = success_count / usage_count if usage_count > 0 else 1.0
        avg_latency_ms = total_latency_ms / usage_count if usage_count > 0 else 0.0
        user_satisfaction = (
            user_satisfaction_sum / user_satisfaction_count
            if user_satisfaction_count > 0
            else None
        )

        return cls(
            usage_count=usage_count,
            success_rate=success_rate,
            avg_latency_ms=avg_latency_ms,
            user_satisfaction=user_satisfaction,
            last_used_at=last_used_at,
        )


@dataclass(frozen=True)
class HarnessComponent:
    """Harness 组件。

    每个组件都有唯一的 ID、类型、名称、版本和配置，以及 effectiveness 指标。

    Attributes:
        id:            组件唯一标识（如 "skill:academic-search", "tool:bash"）
        type:          组件类型（8 种之一）
        name:          组件显示名称
        version:       组件版本（语义化版本）
        config:        组件配置（JSON 对象）
        effectiveness: effectiveness 指标
        created_at:    创建时间（ISO-8601）
        updated_at:    更新时间（ISO-8601）
    """

    id: str
    type: HarnessComponentType
    name: str
    version: str = "1.0.0"
    config: Dict[str, Any] = field(default_factory=dict)
    effectiveness: EffectivenessMetrics = field(default_factory=EffectivenessMetrics)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def is_plugin(self) -> bool:
        """判断是否为插件类型组件。"""
        return self.type == "plugins"

    def is_skill(self) -> bool:
        """判断是否为技能类型组件。"""
        return self.type == "skills"

    def needs_improvement(self) -> bool:
        """判断组件是否需要改进。

        基于 effectiveness 指标判断：
        - 成功率 < 0.8
        - 平均延迟 > 1000ms
        - 用户满意度 < 0.5（如果有评分）

        Returns:
            True 表示需要改进
        """
        if self.effectiveness.success_rate < 0.8:
            return True
        if self.effectiveness.avg_latency_ms > 1000:
            return True
        if (
            self.effectiveness.user_satisfaction is not None
            and self.effectiveness.user_satisfaction < 0.5
        ):
            return True
        return False
