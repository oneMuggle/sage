# ruff: noqa: UP006, UP007, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Async→sync bridge for design studio tools.

Why this module exists
----------------------

``BaseTool.execute`` is called **synchronously** by both dispatch paths
(``core/legacy/agent.py`` 的 ``tool.execute(**args)`` 与
``InprocToolAdapter.execute`` 的 ``to_thread(tool.execute, **args)``),
调用方随后直接读返回值的 ``.content`` / ``.output``。因此把 execute 写成
``async def`` 会返回协程对象而不是 ``ToolResult``，在分发点直接炸掉。

但 ``DesignStudio.generate`` / ``iterate`` 是协程（内部 ``await`` LLM 调用），
所以 execute 必须是同步外壳 + 把协程跑完。

为什么不照抄 image_gen/asr/tts 的 ``asyncio.run`` 写法
--------------------------------------------------------

那三个工具每次调用都新建 capability/client，跨调用不复用。而本模块服务的
``DesignGenerator`` 持有 **单个缓存的** ``httpx.AsyncClient``
(``LLMClient._client``)，它与首次创建它的事件循环绑定。``asyncio.run``
每次建新循环、用完即 ``close()``,于是：

- 第一次调用：建连接，正常返回；
- 第二次调用：keep-alive 连接池里躺着属于上一个（已关闭）循环的连接，
  httpx 复用时抛 ``RuntimeError: Event loop is closed``。

已实测复现（本地 HTTP keep-alive server + 复用同一 ``AsyncClient``）：
第 1 次 200，第 2 次 ``RuntimeError: Event loop is closed``。

对策：本模块为整个进程维持 **一个** 长生命周期事件循环（后台守护线程 +
``run_forever``），所有设计工具的协程都提交到它上面执行。事件循环只建一次，
``httpx.AsyncClient`` 的循环归属始终一致，跨调用安全。

``py38`` 兼容：用 ``run_coroutine_threadsafe`` + ``threading``，不依赖 3.9+
的 ``asyncio.to_thread``。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from typing import Awaitable, Optional, TypeVar

T = TypeVar("T")

#: Default timeout for LLM generation calls (seconds).
DEFAULT_TIMEOUT: float = 120.0

#: 进程级长生命周期事件循环（首次使用时惰性创建）。
_loop: Optional[asyncio.AbstractEventLoop] = None

#: 保护 ``_loop`` 的惰性初始化 —— 多个工具可能从不同线程首次并发调用。
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """Return the process-wide design loop, creating it on first use.

    The loop runs forever on a daemon thread, so httpx connection pools
    (and anything else loop-affine) stay valid across tool invocations.
    """
    global _loop
    if _loop is not None and not _loop.is_closed():
        return _loop

    with _loop_lock:
        if _loop is None or _loop.is_closed():
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=loop.run_forever,
                name="sage-design-loop",
                daemon=True,
            )
            thread.start()
            _loop = loop
    return _loop


async def _run_with_timeout(coro: Awaitable, timeout: Optional[float]) -> T:
    """Wrap *coro* with ``asyncio.wait_for`` when a timeout is given.

    ``asyncio.wait_for`` **cancels** the inner coroutine on timeout, which
    prevents ghost artifact writes after the caller has given up.  Python 3.8
    reports that timeout as ``asyncio.TimeoutError``, while ``run_sync``
    promises ``concurrent.futures.TimeoutError``; normalize the exception at
    this boundary so callers see one contract on every supported version.
    """
    if timeout is not None:
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError as exc:  # noqa: UP041 — py38 class differs
            raise concurrent.futures.TimeoutError(*exc.args) from exc
    return await coro


def run_sync(coro: Awaitable, timeout: Optional[float] = None):
    """Run a coroutine on the shared design loop and return its result.

    Safe to call from:
    - a worker thread with no running loop (``run_in_executor`` / ``to_thread``);
    - directly on the main thread with no running loop (tests);
    - **inside** a running loop -- ``run_coroutine_threadsafe`` targets the
      shared background loop, not the caller's, so this does not raise
      ``RuntimeError: the current event loop is already running``.

    Args:
        coro: The awaitable to execute. Must not be shared across calls.
        timeout: Optional seconds to wait before giving up.  When set,
            the coroutine is **cancelled** via ``asyncio.wait_for`` if the
            timeout elapses, preventing ghost writes.

    Returns:
        Whatever the coroutine returns.

    Raises:
        concurrent.futures.TimeoutError: If ``timeout`` elapses first.
        Exception: Whatever the coroutine raised.
    """
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(
        _run_with_timeout(coro, timeout), loop,
    )
    return future.result(timeout=timeout)


__all__ = ["run_sync", "DEFAULT_TIMEOUT"]
