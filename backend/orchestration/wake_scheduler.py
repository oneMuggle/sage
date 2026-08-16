"""WakeScheduler —— A4 Suspend-Resume 的唤醒消费循环。

在 FastAPI lifespan 中以后台 asyncio task 运行，每 ``tick_seconds`` 扫描
一次 ``WakeStore.get_due_wakes()``，把到期的 wake 逐条交给注入的
``resumer`` 恢复对应会话（fire-once：先标记 FIRED 再恢复，保证每条 wake
至多消费一次，resumer 失败只记日志不重试）。

策略对齐 OpenWorker ``automation/scheduler.py``：

- **run-once-catch-up** —— 启动后立即跑首轮 tick，进程停机期间到期的
  wake 在启动时补放一次；
- **顺序消费** —— resumer 契约是"快速返回"（内部自行 spawn 长任务），
  因此单循环顺序 await 即可，既避免重复消费也不需要 overlap guard。

与 ``backend.services.scheduler.SchedulerService``（APScheduler，跑用户
配置的 cron / 定时任务）职责分离：本调度器只服务 agent 自注册的唤醒。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Callable, Optional

from backend.application.services.wake_store import WakeStore

logger = logging.getLogger(__name__)

# Python 3.8 不支持 typing.Awaitable[] subscript（与 chat_stream_registry
# 同款约束）—— resumer 签名: async (Wake) -> None
ResumerFn = Callable[..., Any]


class WakeScheduler:
    """周期性消费到期 wake 并恢复挂起会话的后台调度器。"""

    def __init__(
        self,
        store: WakeStore,
        resumer: ResumerFn,
        *,
        tick_seconds: float = 15.0,
    ) -> None:
        """
        Args:
            store:        wake 记录仓储。
            resumer:      ``async (wake: Wake) -> None`` 回调；负责在
                          ``wake.session_id`` 会话中注入唤醒轮次。契约：
                          快速返回，耗时工作自行 spawn task，否则会阻塞
                          后续 wake 的消费。
            tick_seconds: 扫描间隔（秒）。
        """
        self.store = store
        self.resumer = resumer
        self.tick_seconds = tick_seconds
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """启动后台循环（幂等：已启动则 no-op）。"""
        if self._task is None:
            self._task = asyncio.create_task(
                self._loop(), name="wake-scheduler"
            )
            logger.info(
                "WakeScheduler 已启动（tick=%.1fs，catch-up 首轮立即执行）",
                self.tick_seconds,
            )

    async def stop(self) -> None:
        """取消后台循环并等待退出（幂等）。"""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("WakeScheduler 已停止")

    # ------------------------------------------------------------------ #
    # 核心
    # ------------------------------------------------------------------ #

    async def tick(self) -> int:
        """单轮扫描：消费所有到期 wake。返回成功恢复的数量。

        fire-once 语义：``mark_fired`` 在 ``resumer`` 之前调用 —— wake 被
        消费即进终态，resumer 抛错只记日志（不重试、不饿死后续 wake）。
        单轮 tick 内的异常被本方法吞掉并记录，绝不外抛到循环。
        """
        resumed = 0
        try:
            due = self.store.get_due_wakes()
        except Exception:  # noqa: BLE001 — DB 瞬时故障不得杀死调度循环
            logger.exception("wake 到期扫描失败")
            return 0
        for wake in due:
            self.store.mark_fired(wake.id)
            try:
                await self.resumer(wake)
                resumed += 1
                logger.info(
                    "wake %s 已消费：session=%s kind=%s",
                    wake.id,
                    wake.session_id,
                    wake.kind.value,
                )
            except Exception:  # noqa: BLE001 — resumer 是不可信业务回调
                logger.exception(
                    "wake %s 恢复会话失败（session=%s）",
                    wake.id,
                    wake.session_id,
                )
        return resumed

    async def _loop(self) -> None:
        # 首轮 = catch-up：补放停机期间到期的 wake
        await self.tick()
        try:
            while True:
                await asyncio.sleep(self.tick_seconds)
                await self.tick()
        except asyncio.CancelledError:
            return
