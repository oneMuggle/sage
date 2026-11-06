"""线程安全桥接：把 ``ChatService.run_turn_tracked`` 暴露给 APScheduler 后台线程。

该模块属于应用层，允许依赖 ``ChatService`` 与 ``sage_core``。
``backend.services.scheduler`` 不导入本模块，而是在 ``main.py`` 装配期通过
``SchedulerService.set_executor(make_threadsafe_runner(...))`` 注入，保持六边形边界。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from typing import TYPE_CHECKING

from sage_core import Message, Role

from backend.services.scheduler import RunOutcome, ScheduledTask

if TYPE_CHECKING:
    from backend.application.services.chat_service import ChatService
    from backend.services.scheduler import TaskRunner

logger = logging.getLogger(__name__)

# 脱敏固定文案（参见方案 §3.8）：不暴露原始异常类名/路径/凭据。
_TIMEOUT_ERROR = "Execution timed out"
_GENERIC_ERROR = "Execution failed; see backend logs for details"


def make_threadsafe_runner(
    chat_service: "ChatService",
    main_loop: asyncio.AbstractEventLoop,
    *,
    timeout: int = 300,
    max_iterations: int = 8,
) -> "TaskRunner":
    """返回同步 callable，APScheduler 后台线程直接调用。

    - 内部把 ``run_turn_tracked`` 调度到 ``main_loop``，并 ``.result(timeout)``
      等待完成，避免阻塞调度线程超过 ``timeout`` 秒。
    - 任何异常（包括 ``CancelledError``、loop 关闭）统一转换为
      ``RunOutcome(status='failed')``，``error`` 字段为脱敏固定文案。
    - ``timeout`` 触发时调用 ``future.cancel()`` 尝试中断尚未开始的协程。
    """

    def _runner(task: ScheduledTask) -> RunOutcome:
        start = time.monotonic()
        try:
            future = asyncio.run_coroutine_threadsafe(
                chat_service.run_turn_tracked(
                    task.session_id,
                    Message(role=Role.USER, content=task.content),
                    max_iterations=max_iterations,
                ),
                main_loop,
            )
        except Exception as exc:  # noqa: BLE001 — loop 关闭/签名错误等都不应抛回调度线程
            logger.warning(
                "task %s could not schedule coroutine: %s", task.id, exc,
            )
            return RunOutcome(
                status="failed",
                duration_ms=int((time.monotonic() - start) * 1000),
                error=_GENERIC_ERROR,
            )

        try:
            _messages, assistant_id = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            logger.warning("task %s timed out after %ds", task.id, timeout)
            return RunOutcome(
                status="failed",
                duration_ms=int((time.monotonic() - start) * 1000),
                error=_TIMEOUT_ERROR,
            )
        except concurrent.futures.CancelledError:
            logger.warning("task %s coroutine was cancelled", task.id)
            return RunOutcome(
                status="failed",
                duration_ms=int((time.monotonic() - start) * 1000),
                error=_GENERIC_ERROR,
            )
        except Exception:  # noqa: BLE001 — 任意异常脱敏
            logger.exception("task %s failed", task.id)
            return RunOutcome(
                status="failed",
                duration_ms=int((time.monotonic() - start) * 1000),
                error=_GENERIC_ERROR,
            )

        return RunOutcome(
            status="succeeded",
            message_id=assistant_id,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    return _runner
