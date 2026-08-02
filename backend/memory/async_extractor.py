"""异步记忆提取队列 — 让聊天响应关键路径不再等待 LLM 事实提取。

把 ``extract_and_store_memory``（含一次 LLM 调用）从 hex ``run_turn``
第 7 步与 legacy ``_extract_legacy_chat_memory`` 的 inline await 中
剥离出来，投递到本队列由**单 worker** 串行消费：

- 顺序保证 + 天然背压：单 worker 串行，LLM 提取本就慢，并发只会叠加负载
- best-effort：任何失败只 warning，绝不外抛、不影响聊天
- 可测试：``drain()`` 等待队列清空 + worker 空闲，测试可确定性断言
- 六边形纯净：不依赖 FastAPI（``BackgroundTasks`` 方案已评估否决）

与 ``file_mutation_queue.py``（A26）同构，但 ``submit`` 是**非阻塞**
（只入队即返回，不等结果）—— 记忆提取不需要调用方等待结果。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractionRequest:
    """一次记忆提取请求（与 ``extract_and_store_memory`` 参数同构）。"""

    memory_port: Any
    extractor: Any
    user_text: str
    assistant_text: str
    session_id: Optional[str]
    enabled: bool


class MemoryExtractionQueue:
    """异步记忆提取队列（单 worker 串行消费）。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[ExtractionRequest] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._completed = 0
        self._failed = 0
        self._skipped = 0

    # ---- 公共 API ------------------------------------------------------- #

    def submit(self, request: ExtractionRequest) -> None:
        """非阻塞投递提取请求；无效请求（None port / disabled）直接跳过。"""
        if request.memory_port is None or not request.enabled:
            self._skipped += 1
            return
        self._queue.put_nowait(request)
        self._ensure_worker()

    def start(self) -> None:
        """确保 worker 已启动（幂等；main.py lifespan 调用）。"""
        self._ensure_worker()

    def stop(self) -> None:
        """取消 worker 任务（生产 shutdown 用）。"""
        if self._worker_task is not None and not self._worker_task.done():
            with contextlib.suppress(Exception):
                self._worker_task.cancel()
        self._worker_task = None

    async def drain(self, timeout: float = 5.0) -> None:
        """等待队列清空 + 所有项处理完成；超时返回（best-effort，不抛）。"""
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except Exception:  # noqa: BLE001 - best-effort，超时/异常都不外抛
            logger.debug("memory extraction drain timed out after %.1fs", timeout)

    def pending(self) -> int:
        """当前排队未处理的请求数。"""
        return self._queue.qsize()

    @property
    def completed(self) -> int:
        return self._completed

    @property
    def failed(self) -> int:
        return self._failed

    @property
    def skipped(self) -> int:
        return self._skipped

    # ---- 内部实现 ------------------------------------------------------- #

    def _ensure_worker(self) -> None:
        """懒启动 worker（幂等）；submit 与 start 共用。"""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(
                self._worker(), name="memory-extraction-worker"
            )

    async def _worker(self) -> None:
        """单 worker 循环：消费队列 → 提取 → 失败隔离。"""
        while True:
            try:
                request = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:  # noqa: UP041 — py3.10/3.8 中 asyncio.TimeoutError ≠ builtin TimeoutError
                continue
            except asyncio.CancelledError:
                break
            try:
                await self._process(request)
                self._completed += 1
            except Exception as exc:  # noqa: BLE001 - 单条失败不杀 worker
                self._failed += 1
                logger.warning(
                    "memory extraction failed (session=%s): %s",
                    request.session_id,
                    exc,
                )
            finally:
                self._queue.task_done()

    async def _process(self, request: ExtractionRequest) -> None:
        """复用 hex/legacy 共用的统一写入路径（worker 内惰性导入防循环）。"""
        from backend.application.services.chat_service import extract_and_store_memory

        await extract_and_store_memory(
            memory_port=request.memory_port,
            extractor=request.extractor,
            user_text=request.user_text,
            assistant_text=request.assistant_text,
            session_id=request.session_id,
            enabled=request.enabled,
        )


# 全局单例（与 get_usage_store 同模式）
_extraction_queue: Optional[MemoryExtractionQueue] = None


def get_memory_extraction_queue() -> MemoryExtractionQueue:
    """获取全局 MemoryExtractionQueue 单例。"""
    global _extraction_queue
    if _extraction_queue is None:
        _extraction_queue = MemoryExtractionQueue()
    return _extraction_queue


def reset_memory_extraction_queue() -> None:
    """重置单例并取消残留 worker（仅测试用）。"""
    global _extraction_queue
    if _extraction_queue is not None:
        _extraction_queue.stop()
        _extraction_queue = None
