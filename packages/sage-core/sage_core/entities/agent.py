"""Agent 领域模型（纯，零外部依赖）。

包含 ReAct 状态机所需的状态枚举与决策值对象。
不允许引入 fastapi / pydantic / httpx 或任何项目内部模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class AgentState(str, Enum):
    """ReAct 状态机枚举。"""

    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    DONE = "done"
    FAILED = "failed"

    @classmethod
    def initial(cls) -> "AgentState":
        """返回初始状态。"""
        return cls.IDLE

    def can_transition_to(self, other: "AgentState") -> bool:
        """检查从当前状态到 ``other`` 的迁移是否合法。

        合法迁移：
        - IDLE      → THINKING
        - THINKING  → ACTING / DONE / FAILED
        - ACTING    → OBSERVING / FAILED
        - OBSERVING → THINKING / DONE / FAILED
        - DONE      → ∅（终态）
        - FAILED    → ∅（终态）
        """
        legal: dict[AgentState, set[AgentState]] = {
            AgentState.IDLE: {AgentState.THINKING},
            AgentState.THINKING: {
                AgentState.ACTING,
                AgentState.DONE,
                AgentState.FAILED,
            },
            AgentState.ACTING: {AgentState.OBSERVING, AgentState.FAILED},
            AgentState.OBSERVING: {
                AgentState.THINKING,
                AgentState.DONE,
                AgentState.FAILED,
            },
            AgentState.DONE: set(),
            AgentState.FAILED: set(),
        }
        return other in legal.get(self, set())


@dataclass(frozen=True)
class AgentDecision:
    """Agent 在某一步的决策输出（不可变值对象）。

    Attributes:
        state:          决策对应的状态
        final_message:  当 state == DONE 时的最终回复文本
        action_name:    当 state == ACTING 时的工具/动作名
        action_args:    当 state == ACTING 时的参数字典
    """

    state: AgentState
    final_message: str | None = None
    action_name: str | None = None
    action_args: dict[str, Any] | None = None
