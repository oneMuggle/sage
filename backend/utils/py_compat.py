# ruff: noqa: UP006, UP007, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Python 3.8 兼容垫片（win7 LTS 支持用）。

- ``to_thread``：asyncio.to_thread 是 3.9+ 才有的标准库 API；
  3.8 退化为 ``loop.run_in_executor``（默认线程池，语义等价——都不能取消已入池任务）。
"""
from __future__ import annotations

import asyncio
import functools
import sys
from typing import Any, Callable

_has_native_to_thread = sys.version_info >= (3, 9)


async def to_thread(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """``asyncio.to_thread`` 的 py38 等价实现。"""
    if _has_native_to_thread:
        return await asyncio.to_thread(func, *args, **kwargs)
    call = functools.partial(func, **kwargs)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, call, *args)


# wait_for / wait 超时异常族：py38 中 asyncio.TimeoutError 与 builtin
# TimeoutError 是两个类（3.11 起合流），except 必须同时覆盖。
# 以常量形式提供，避免各 except 行被 UP041 autofix 改回单型。
TIMEOUT_ERRORS = (TimeoutError, getattr(asyncio, "TimeoutError", TimeoutError))
