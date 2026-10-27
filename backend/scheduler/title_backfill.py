"""启动后回补历史未命名会话的标题。

旧版标题生成只在首两轮对话触发，失败后永不重试，导致大量历史会话长期
停留在占位标题「新对话」。本模块在应用启动若干秒后，对**已有真实消息**
的未命名会话批量补生成标题（LLM 优先，失败走启发式），保证最终一致性。

约束（见 ``docs/plans/2026-10-27_session-title-optimization.md`` §3.2.6）：

- 启动后 ``STARTUP_DELAY_S`` 秒触发，避免与启动期初始化争用；
- 单次最多 ``MAX_BATCH`` 个会话；
- 并发 ≤ ``CONCURRENCY``；
- 调用速率 ≤ ``RATE_PER_MINUTE``；
- 无论成功与否都递增 ``title_attempts``，避免每次启动反复重试。

本模块只负责调度与生成；落库经 ``SessionRepository.update``。
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.chat.title_generator import (
    DEFAULT_TITLE,
    MAX_TITLE_ATTEMPTS,
    TitleGenerator,
)

logger = logging.getLogger(__name__)

#: 启动后延迟多久开始回补（秒）。
STARTUP_DELAY_S = 30.0

#: 单次回补最多处理的会话数。
MAX_BATCH = 100

#: 并发生成标题的上限。
CONCURRENCY = 3

#: 每分钟最多发起的标题生成数（LLM 调用）。
RATE_PER_MINUTE = 10

#: 两次发起之间的最小间隔（秒）。
MIN_INTERVAL_S = 60.0 / RATE_PER_MINUTE

#: 单个会话标题生成的超时（秒）——防止坏端点拖住整轮回补。
PER_SESSION_TIMEOUT_S = 15.0

#: 读取每个会话消息时的上限；标题只需首轮内容。
MESSAGES_PER_SESSION = 10


def _build_default_generator() -> Optional[Any]:
    """构建默认 LLM 客户端（专用标题模型优先，回退聊天模型）。"""
    from backend.chat.title_generator import TitleModelFactory

    return TitleModelFactory.build()


class TitleBackfill:
    """历史未命名会话的标题回补器（每个进程一次）。"""

    def __init__(
        self,
        session_repo: Any,
        message_repo: Any,
        generator_factory: Optional[Callable[[], Optional[Any]]] = None,
        *,
        startup_delay_s: float = STARTUP_DELAY_S,
        max_batch: int = MAX_BATCH,
        concurrency: int = CONCURRENCY,
        min_interval_s: float = MIN_INTERVAL_S,
        per_session_timeout_s: float = PER_SESSION_TIMEOUT_S,
    ) -> None:
        self._session_repo = session_repo
        self._message_repo = message_repo
        self._generator_factory = generator_factory or _build_default_generator
        self._startup_delay_s = startup_delay_s
        self._max_batch = max_batch
        self._concurrency = max(1, concurrency)
        self._min_interval_s = max(0.0, min_interval_s)
        self._per_session_timeout_s = per_session_timeout_s
        self._task: Optional[asyncio.Task] = None
        self._next_slot = 0.0
        self._rate_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # 调度
    # ------------------------------------------------------------------ #

    def schedule(self) -> None:
        """在启动延迟后调度一次回补；重复调用无副作用。"""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._delayed_run(), name="title-backfill"
        )

    async def _delayed_run(self) -> None:
        try:
            await asyncio.sleep(self._startup_delay_s)
        except asyncio.CancelledError:
            raise
        await self.run()

    async def stop(self) -> None:
        """取消尚未跑完的回补任务（应用关停时调用）。"""
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):  # noqa: BLE001
                await task

    # ------------------------------------------------------------------ #
    # 回补主流程
    # ------------------------------------------------------------------ #

    async def run(self) -> Dict[str, int]:
        """执行一次回补，返回统计 ``{scanned, titled, failed}``。"""
        stats = {"scanned": 0, "titled": 0, "failed": 0}
        try:
            sessions = await self._in_thread(
                self._session_repo.list_untitled,
                DEFAULT_TITLE,
                MAX_TITLE_ATTEMPTS,
                self._max_batch,
            )
        except Exception as exc:  # noqa: BLE001 — 查询失败静默降级
            logger.warning("标题回补：查询未命名会话失败: %s", exc)
            return stats

        if not sessions:
            return stats

        stats["scanned"] = len(sessions)
        llm = await self._build_llm_once()
        semaphore = asyncio.Semaphore(self._concurrency)

        async def process(session: Any) -> bool:
            async with semaphore:
                await self._acquire_slot()
                return await self._process_session(session, llm)

        results = await asyncio.gather(*(process(s) for s in sessions))
        stats["titled"] = sum(1 for ok in results if ok)
        stats["failed"] = len(results) - stats["titled"]
        logger.info(
            "标题回补完成：扫描 %d，成功 %d，失败 %d",
            stats["scanned"],
            stats["titled"],
            stats["failed"],
        )
        return stats

    async def _build_llm_once(self) -> Optional[Any]:
        try:
            return await self._in_thread(self._generator_factory)
        except Exception as exc:  # noqa: BLE001 — 构建失败走启发式
            logger.warning("标题回补：构建 LLM 客户端失败: %s", exc)
            return None

    async def _process_session(self, session: Any, llm: Optional[Any]) -> bool:
        """为单个会话生成并落库标题；返回是否得到真实标题。"""
        user_text, assistant_text = await self._first_turn_texts(session.id)
        if not user_text and not assistant_text:
            # 有消息计数但读不到内容（异常数据）：记一次尝试，避免反复扫描
            await self._record_attempt(session, DEFAULT_TITLE)
            return False

        try:
            title = await asyncio.wait_for(
                TitleGenerator(llm).generate(user_text, assistant_text),
                timeout=self._per_session_timeout_s,
            )
        except asyncio.TimeoutError:  # noqa: UP041 — py3.8 下与内置 TimeoutError 非同对象
            logger.warning("标题回补：会话 %s 生成超时", session.id)
            title = DEFAULT_TITLE
        except Exception as exc:  # noqa: BLE001 — 任何故障都记尝试次数
            logger.warning("标题回补：会话 %s 生成失败: %s", session.id, exc)
            title = DEFAULT_TITLE

        await self._record_attempt(session, title)
        return title != DEFAULT_TITLE

    async def _first_turn_texts(self, session_id: str) -> Tuple[str, str]:
        try:
            messages: List[Any] = await self._in_thread(
                self._message_repo.get_by_session, session_id, MESSAGES_PER_SESSION
            )
        except Exception as exc:  # noqa: BLE001 — 读消息失败按无内容处理
            logger.warning("标题回补：读取会话 %s 消息失败: %s", session_id, exc)
            return "", ""

        user_text = ""
        assistant_text = ""
        for msg in messages:
            role = getattr(msg, "role", "")
            role_value = getattr(role, "value", role)
            content = (getattr(msg, "content", "") or "").strip()
            if not content:
                continue
            if not user_text and role_value == "user":
                user_text = content
            elif not assistant_text and role_value == "assistant":
                assistant_text = content
            if user_text and assistant_text:
                break
        return user_text, assistant_text

    async def _record_attempt(self, session: Any, title: str) -> None:
        attempts = int(getattr(session, "title_attempts", 0) or 0) + 1
        try:
            await self._in_thread(
                self._session_repo.update,
                session.id,
                title=title,
                title_attempts=attempts,
            )
        except Exception as exc:  # noqa: BLE001 — 落库失败仅告警
            logger.warning("标题回补：会话 %s 落库失败: %s", session.id, exc)

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #

    async def _acquire_slot(self) -> None:
        """速率闸门：按 ``min_interval_s`` 均匀放行。"""
        async with self._rate_lock:
            now = time.monotonic()
            wait_for = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self._min_interval_s
        if wait_for > 0:
            await asyncio.sleep(wait_for)

    @staticmethod
    async def _in_thread(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """在默认线程池执行同步函数（py3.8 无 ``asyncio.to_thread``）。"""
        loop = asyncio.get_running_loop()
        if kwargs:
            from functools import partial

            return await loop.run_in_executor(None, partial(func, *args, **kwargs))
        return await loop.run_in_executor(None, func, *args)
