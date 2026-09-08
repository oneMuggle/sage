"""O5 (2026-09-08): 子代理嵌套深度防护。

``ContextVar`` 记录当前协程所处的子代理嵌套深度：conductor（主 agent）
为 0，编排子代理执行期间置 1（``ChatDispatcher._run_subagent_impl``）。
``AgentTool.execute_async`` 在深度达到上限时拒绝派生孙代理 —— 此前
嵌套只靠 profile 工具白名单结构性拦截（种子角色均不含 ``agent``），
自定义 profile 把 ``agent`` 加入白名单即可穿透且无任何深度限制。

已知限制：``loop.run_in_executor`` 同步遗弃线程通路不复制 contextvars，
线程内深度恒为 0，不设防。生产 run_loop 对 ``agent`` 工具优先走
``execute_async``（agent.py 特判），同步通路仅测试桩/旧调用方回落。

上限默认 1（子代理不允许再派生），env ``SAGE_MAX_SUBAGENT_DEPTH``
可调（≥1），非法值静默回退默认。
"""

from __future__ import annotations

import os
from contextvars import ContextVar, Token

#: 当前协程的子代理嵌套深度。conductor = 0。
_subagent_depth: ContextVar[int] = ContextVar("sage_subagent_depth", default=0)

#: 默认嵌套上限：子代理之内不再允许派生。
DEFAULT_MAX_SUBAGENT_DEPTH = 1


def current_subagent_depth() -> int:
    """返回当前协程的子代理嵌套深度（conductor 为 0）。"""
    return _subagent_depth.get()


def max_nested_subagent_depth() -> int:
    """允许的最大嵌套深度（含）。env 非法/小于 1 时回退默认 1。"""
    raw = os.environ.get("SAGE_MAX_SUBAGENT_DEPTH", "").strip()
    if raw:
        try:
            value = int(raw)
            if value >= 1:
                return value
        except ValueError:
            pass
    return DEFAULT_MAX_SUBAGENT_DEPTH


class _SubagentDepthToken:
    """set/restore 配对令牌（封装 ContextVar.Token，调用方无需 import）。"""

    def __init__(self, token: Token) -> None:
        self._token = token


def enter_subagent_depth(depth: int) -> _SubagentDepthToken:
    """置位当前协程深度，返回配对令牌（``exit_subagent_depth`` 恢复）。"""
    return _SubagentDepthToken(_subagent_depth.set(depth))


def exit_subagent_depth(token: _SubagentDepthToken) -> None:
    """恢复 ``enter_subagent_depth`` 之前的深度（finally 配对调用）。"""
    _subagent_depth.reset(token._token)


def is_nesting_allowed() -> bool:
    """当前深度下是否还允许再派生子代理。"""
    return current_subagent_depth() < max_nested_subagent_depth()


__all__ = [
    "DEFAULT_MAX_SUBAGENT_DEPTH",
    "current_subagent_depth",
    "enter_subagent_depth",
    "exit_subagent_depth",
    "is_nesting_allowed",
    "max_nested_subagent_depth",
]
