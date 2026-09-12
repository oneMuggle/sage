"""工具执行内核共享件（hex-legacy 双栈收敛切片 A 起步）。

两栈（hex InprocToolAdapter 与 legacy run_loop 并行只读批次）共用的
超时语义与文案单源；后续统一执行内核在此扩展。
"""

from __future__ import annotations

import asyncio

# Python 3.10: asyncio.TimeoutError ≠ builtin TimeoutError；3.11+ 为同一类，
# 兼容两个名称（hex adapter 原内联写法收敛至此）。
TIMEOUT_EXCEPTIONS: tuple = (asyncio.TimeoutError, TimeoutError)  # noqa: UP041


def tool_timeout_message(timeout_seconds) -> str:
    """工具超时错误文案（两栈统一，供 LLM 观察结果解析）。"""
    return f"tool_timeout: exceeded {timeout_seconds}s"
