"""M2.5: 任务/run 级暂停控制器。

PauseState 是可复用的 asyncio 同步原语：运行中调用方 ``await wait_if_paused()``
阻塞于暂停状态；控制方调用同步的 ``request_pause()`` / ``request_resume()``
切换。内部使用 asyncio.Event；所有方法都应在事件循环线程内调用（与
``SageAgent.run_loop`` / dispatcher 调用方一致），无需额外加锁。
"""

from __future__ import annotations

import asyncio


class PauseState:
    """可恢复的暂停控制。

    初始为"未暂停"；``request_pause()`` 后所有 ``wait_if_paused`` 调用阻塞，
    直到 ``request_resume()`` 解除。两次相同方向请求返回 False（幂等）。
    """

    def __init__(self) -> None:
        # asyncio.Event: set = 可继续；clear = 已暂停
        self._gate = asyncio.Event()
        self._gate.set()
        self._paused = False

    @property
    def paused(self) -> bool:
        return self._paused

    async def wait_if_paused(self) -> None:
        """暂停时阻塞；未暂停立即返回。"""
        if self._paused:
            await self._gate.wait()

    def request_pause(self) -> bool:
        """请求暂停。已是暂停态返回 False；否则置位并返回 True。"""
        if self._paused:
            return False
        self._paused = True
        self._gate.clear()
        return True

    def request_resume(self) -> bool:
        """请求恢复。已是运行态返回 False；否则置位并返回 True。"""
        if not self._paused:
            return False
        self._paused = False
        self._gate.set()
        return True
