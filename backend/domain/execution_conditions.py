"""
闲时延迟执行系统 — 执行条件数据模型

定义触发条件和触发模式：
- ConditionType: 条件类型（空闲、资源、时间窗口等）
- TriggerMode: 触发模式（立即 vs 条件）
- ExecutionCondition: 单个执行条件
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class ConditionType(str, Enum):
    """执行条件类型"""

    TIME_WINDOW = "time_window"       # 在指定时间段内
    IDLE = "idle"                     # 用户空闲 N 分钟
    RESOURCE = "resource"             # 系统资源充足
    NO_ACTIVE_TASKS = "no_active"     # 无其他运行中 Agent 任务
    MANUAL = "manual"                 # 用户手动触发


class TriggerMode(str, Enum):
    """目标触发模式"""

    IMMEDIATE = "immediate"           # 立即执行（默认，与现有行为一致）
    CONDITIONAL = "conditional"       # 条件满足后执行


class IdleLevel(str, Enum):
    """空闲等级"""

    NONE = "none"                     # 用户活跃
    SHORT = "short"                   # 短暂空闲（5-30 分钟）
    DEEP = "deep"                     # 深度空闲（> 30 分钟）


@dataclass
class ExecutionCondition:
    """单个执行条件

    示例:
        ExecutionCondition(type=ConditionType.IDLE, params={"min_idle_minutes": 15})
        ExecutionCondition(type=ConditionType.TIME_WINDOW, params={"start": "02:00", "end": "06:00"})
        ExecutionCondition(type=ConditionType.RESOURCE, params={"max_cpu_pct": 30})
        ExecutionCondition(type=ConditionType.NO_ACTIVE_TASKS, params={})
    """

    type: ConditionType                           # 条件类型
    params: Dict[str, Any] = field(default_factory=dict)  # 条件参数

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 存储）"""
        return {
            "type": self.type.value,
            "params": self.params,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionCondition:
        """从字典创建"""
        return cls(
            type=ConditionType(data["type"]),
            params=data.get("params", {}),
        )


# ─── 默认条件快捷构造 ──────────────────────────────────────────────


def idle_condition(min_idle_minutes: int = 15) -> ExecutionCondition:
    """创建空闲条件"""
    return ExecutionCondition(
        type=ConditionType.IDLE,
        params={"min_idle_minutes": min_idle_minutes},
    )


def time_window_condition(start: str = "22:00", end: str = "06:00") -> ExecutionCondition:
    """创建时间窗口条件"""
    return ExecutionCondition(
        type=ConditionType.TIME_WINDOW,
        params={"start": start, "end": end},
    )


def resource_condition(max_cpu_pct: int = 30, max_memory_pct: int = 50) -> ExecutionCondition:
    """创建资源条件"""
    return ExecutionCondition(
        type=ConditionType.RESOURCE,
        params={"max_cpu_pct": max_cpu_pct, "max_memory_pct": max_memory_pct},
    )


def no_active_tasks_condition() -> ExecutionCondition:
    """创建无活动任务条件"""
    return ExecutionCondition(
        type=ConditionType.NO_ACTIVE_TASKS,
        params={},
    )


def manual_condition() -> ExecutionCondition:
    """创建手动触发条件（永不自动满足，需用户手动触发）"""
    return ExecutionCondition(
        type=ConditionType.MANUAL,
        params={},
    )
