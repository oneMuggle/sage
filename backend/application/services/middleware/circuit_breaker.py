"""
重复调用熔断 (A13 CircuitBreaker, from LLM_Simple)

当模型以完全相同的参数反复调用同一工具（失败后无脑重试）达到
max_repeats 次以上时，熔断该 (tool, args) 组合，强制模型换一种
思路而不是无限循环。

问题：
- 工具调用失败后，模型用相同参数反复重试 → 死循环烧 token
- 相同失败重复 N 次结果不会改变，必须换参数或换工具

解决方案：
- 以 (tool_name, 规范化参数) 为键计数
- 计数超过 max_repeats 时返回阻断消息（作为工具结果注入）
- 调用成功时 mark_success 清零该键计数

使用示例：
    breaker = CircuitBreaker(max_repeats=3)

    block = breaker.check("terminal", {"command": "pytest"})
    if block:
        # 将 block 作为工具结果返回给模型，不真正执行
        tool_result = block
    else:
        result = execute_tool(...)
        if result.success:
            breaker.mark_success("terminal", {"command": "pytest"})

Ported from LLM_Simple's api/middleware/circuit.py, with deterministic
JSON canonicalization of arguments (handles nested dicts regardless of
key insertion order).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


class CircuitBreaker:
    """
    检测并阻断工具调用的无限重试循环。

    以 ``(tool_name, 规范化 arguments)`` 为键累计调用次数：
    - 前 max_repeats 次放行（返回 None）
    - 第 max_repeats+1 次起返回阻断消息
    - mark_success 清零对应键（循环被打破后恢复）

    Attributes:
        max_repeats: 允许的最大相同调用次数（默认 3）
    """

    def __init__(self, max_repeats: int = 3) -> None:
        if max_repeats < 1:
            raise ValueError(f"max_repeats must be >= 1, got {max_repeats}")

        self.max_repeats: int = max_repeats
        self._call_counts: Dict[str, int] = {}

    def check(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
        """
        记录一次调用并检查是否应熔断。

        Args:
            tool_name: 工具名
            arguments: 工具参数（dict，允许嵌套）

        Returns:
            应阻断时返回注入给模型的阻断消息；放行时返回 None。
        """
        key = _canonical_key(tool_name, arguments)
        count = self._call_counts.get(key, 0) + 1
        self._call_counts[key] = count

        if count > self.max_repeats:
            return (
                f"CIRCUIT BREAKER: '{tool_name}' called {count} times "
                f"with identical arguments. This tool call is BLOCKED. "
                f"Try a DIFFERENT approach — different arguments or "
                f"a different tool. Diagnose the root cause before retrying."
            )

        return None

    def mark_success(self, tool_name: str, arguments: Dict[str, Any]) -> None:
        """调用成功后清零该 (tool, args) 的计数"""
        key = _canonical_key(tool_name, arguments)
        self._call_counts[key] = 0

    def call_count(self, tool_name: str, arguments: Dict[str, Any]) -> int:
        """查询某 (tool, args) 的当前累计调用次数"""
        return self._call_counts.get(_canonical_key(tool_name, arguments), 0)

    def reset(self) -> None:
        """清零所有计数（新会话时调用）"""
        self._call_counts.clear()


def _canonical_key(tool_name: str, arguments: Dict[str, Any]) -> str:
    """
    生成 (tool, args) 的规范化键。

    使用 json.dumps(sort_keys=True) 递归规范化，参数键的插入顺序
    不影响结果；default=str 兜底不可序列化对象。
    """
    try:
        encoded = json.dumps(
            arguments,
            sort_keys=True,
            default=str,
            ensure_ascii=False,
        )
    except (TypeError, ValueError):
        encoded = repr(arguments)
    return f"{tool_name}::{encoded}"
