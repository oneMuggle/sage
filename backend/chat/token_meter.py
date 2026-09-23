# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""上下文压力计量（DSH 对标 R4，TM1）。

对标 deepseek-harness 的 token-meter：对**已装配**的请求消息做确定性
估算，输出 total / by_role / budget / pressure——回答"当前请求用了多少
上下文、各部分占多少、离窗口上限还有多远"。

口径纪律：估算复用 ``compaction.estimate_messages_tokens``（与
WorkingMemory / 压缩阈值同源），本轮**不引入新估算口径、不改任何预算
阈值行为**——纯计量，无副作用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.chat.compaction import estimate_messages_tokens
from backend.chat.history_context import history_token_budget


@dataclass
class ContextPressure:
    """一次请求的上下文水位快照。"""

    total_tokens: int
    budget_tokens: int
    pressure: float
    by_role: Dict[str, int] = field(default_factory=dict)
    #: 与 budget 同源的口径说明（防两条预算线漂移时误读）
    estimator: str = "estimate_messages_tokens"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "budget_tokens": self.budget_tokens,
            "pressure": round(self.pressure, 4),
            "by_role": dict(self.by_role),
            "estimator": self.estimator,
        }


def measure_request_messages(
    messages: List[Dict[str, Any]],
    effective_window: Optional[int] = None,
) -> ContextPressure:
    """计量已装配请求消息的上下文水位（纯函数）。

    Args:
        messages: ``build_request_messages[_from_events]`` 的产出
            （``[system, attachments?, *history, trailing_system?, user]``）。
        effective_window: catalog 解析的模型窗口；None 时 budget 走
            ``history_token_budget`` 的 env/settings 回退链（与截断同源）。

    Returns:
        :class:`ContextPressure`。``pressure = total / budget`` 封顶 1.0；
        budget ≤ 0（极端小窗口/配置错误）时恒 1.0，让上层"接近满"的
        语义 fail-safe。
    """
    total = 0
    by_role: Dict[str, int] = {}
    for msg in messages:
        cost = estimate_messages_tokens([msg])
        total += cost
        role = str(msg.get("role") or "unknown")
        by_role[role] = by_role.get(role, 0) + cost

    budget = history_token_budget(effective_window)
    pressure = 1.0 if budget <= 0 else min(1.0, total / budget)
    return ContextPressure(
        total_tokens=total,
        budget_tokens=budget,
        pressure=pressure,
        by_role=by_role,
    )


__all__ = ["ContextPressure", "measure_request_messages"]
