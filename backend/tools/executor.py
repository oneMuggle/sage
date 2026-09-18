"""工具执行内核共享件（hex-legacy 双栈收敛切片 A 起步）。

两栈（hex InprocToolAdapter 与 legacy run_loop 并行只读批次）共用的
超时语义与文案单源；后续统一执行内核在此扩展。
"""

from __future__ import annotations

import asyncio
from typing import Tuple

# Python 3.10: asyncio.TimeoutError ≠ builtin TimeoutError；3.11+ 为同一类，
# 兼容两个名称（hex adapter 原内联写法收敛至此）。
TIMEOUT_EXCEPTIONS: tuple = (asyncio.TimeoutError, TimeoutError)  # noqa: UP041


def tool_timeout_message(timeout_seconds) -> str:
    """工具超时错误文案（两栈统一，供 LLM 观察结果解析）。"""
    return f"tool_timeout: exceeded {timeout_seconds}s"


def truncate_output(output: str, max_output_bytes: int) -> Tuple[str, dict]:
    """按 utf-8 字节截断工具输出（两栈统一，切片 A 收口）。

    Returns:
        (截断后字符串, metadata dict)。未截断时 metadata 为空 dict，
        截断时为 {"truncated": True, "original_bytes": N, "max_output_bytes": M}。
    """
    raw_bytes = output.encode("utf-8")
    if len(raw_bytes) <= max_output_bytes:
        return output, {}
    truncated = raw_bytes[:max_output_bytes].decode("utf-8", errors="replace")
    return truncated, {
        "truncated": True,
        "original_bytes": len(raw_bytes),
        "max_output_bytes": max_output_bytes,
    }
