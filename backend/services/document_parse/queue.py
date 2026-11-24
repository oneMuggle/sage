"""MinerU 后台队列：上传后异步补跑解析，前端按 task_key 轮询状态。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Dict, Optional

from backend.application.document_parse import DocumentParseService
from backend.domain.document_parse import ENGINE_MINERU, ParseRequest

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_UNKNOWN = "unknown"

_SENTINEL = None


@dataclass
class _Job:
    task_key: str
    content: bytes
    filename: str
    tier: Optional[str] = None
    page_range: Optional[str] = None
    status: str = STATUS_PENDING


class MineruBackgroundQueue:
    """单 worker 的进程内队列；同内容 + 同档位的任务去重。"""

    def __init__(self, service: DocumentParseService) -> None:
        self._service = service
        self._jobs: Dict[str, _Job] = {}
        self._queue: Optional[asyncio.Queue] = None
        self._worker: Optional[asyncio.Task] = None

    def submit(
        self,
        *,
        content: bytes,
        filename: str,
        tier: Optional[str] = None,
        page_range: Optional[str] = None,
    ) -> str:
        digest = hashlib.sha256(content).hexdigest()
        task_key = f"{digest}:{tier or 'auto'}"
        if task_key in self._jobs:
            return task_key
        job = _Job(
            task_key=task_key,
            content=content,
            filename=filename,
            tier=tier,
            page_range=page_range,
        )
        self._jobs[task_key] = job
        self._ensure_worker()
        self._ensure_queue().put_nowait(job)
        return task_key

    def get_status(self, task_key: str) -> str:
        job = self._jobs.get(task_key)
        if job is None:
            return STATUS_UNKNOWN
        return job.status

    # ── 内部 ────────────────────────────────────────────────────
    def _ensure_queue(self) -> asyncio.Queue:
        if self._queue is None:
            self._queue = asyncio.Queue()
        return self._queue

    def _ensure_worker(self) -> None:
        if self._worker is not None and not self._worker.done():
            return
        loop = asyncio.get_running_loop()
        self._worker = loop.create_task(self._run_worker())

    async def _run_worker(self) -> None:
        while True:
            job = await self._ensure_queue().get()
            if job is _SENTINEL:
                self._ensure_queue().task_done()
                break
            job.status = STATUS_RUNNING
            try:
                result = await self._service.parse(
                    ParseRequest(
                        filename=job.filename,
                        content_bytes=job.content,
                        engine_hint=ENGINE_MINERU,
                        tier=job.tier,
                        page_range=job.page_range,
                    )
                )
                job.status = (
                    STATUS_COMPLETED
                    if result.engine_used == ENGINE_MINERU
                    else STATUS_FAILED
                )
            except Exception:  # noqa: BLE001 — 单个任务失败不应终止 worker
                job.status = STATUS_FAILED
                logger.warning(
                    "MinerU 后台解析失败: %s", job.task_key, exc_info=True
                )
            finally:
                self._ensure_queue().task_done()
