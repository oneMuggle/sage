"""质量中间件 (A13, from LLM_Simple)。

在 Agent 工具调用循环中拦截 LLM 的常见失败模式：

- :class:`NudgeGuard` — 检测被动读取循环（只读不动手），注入推动消息
- :class:`CircuitBreaker` — 熔断相同参数的重复工具调用，强制换思路
"""

from backend.application.services.middleware.circuit_breaker import CircuitBreaker
from backend.application.services.middleware.nudge_guard import (
    DEFAULT_ACTION_KEYWORDS,
    DEFAULT_NUDGE_MESSAGE,
    DEFAULT_PASSIVE_READ_TOOLS,
    NudgeGuard,
)

__all__ = [
    "CircuitBreaker",
    "NudgeGuard",
    "DEFAULT_ACTION_KEYWORDS",
    "DEFAULT_NUDGE_MESSAGE",
    "DEFAULT_PASSIVE_READ_TOOLS",
]
