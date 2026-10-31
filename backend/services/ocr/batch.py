"""OCR 批处理任务（多图/PDF 页的队列与进度）。

设计取舍：
- 进程内单 worker（CPU 推理不宜高并发），任务状态 + 结果在内存；
- 每项结果独立失败，不影响后续项；
- 任务保留最近 N 条，避免无限增长；
- 仅供本地 REST/前端使用，不持久化到磁盘（重启丢失，可重试）。
"""

from __future__ import annotations

import base64
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .service import OcrService, get_ocr_service

logger = logging.getLogger(__name__)

MAX_BATCH_ITEMS = 20
MAX_RETAINED_JOBS = 50


@dataclass
class OcrBatchJob:
    job_id: str
    total: int
    lang: str
    max_side: Optional[int]
    status: str = "pending"           # pending/running/completed/cancelled/failed
    completed: int = 0
    failed: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: Optional[str] = None
    results: List[Optional[Dict[str, Any]]] = field(default_factory=list)
    cancelled: bool = False


class OcrBatchService:
    """单 worker 批处理队列；线程安全的任务表。"""

    def __init__(self, service_provider=get_ocr_service) -> None:
        self._service_provider = service_provider
        self._jobs: Dict[str, OcrBatchJob] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ocr-batch"
        )

    def submit(
        self,
        images: List[bytes],
        *,
        lang: str = "auto",
        max_side: Optional[int] = None,
    ) -> OcrBatchJob:
        if not images:
            raise ValueError("batch requires at least one image")
        if len(images) > MAX_BATCH_ITEMS:
            raise ValueError("batch supports at most %d images" % MAX_BATCH_ITEMS)
        job = OcrBatchJob(
            job_id=uuid.uuid4().hex[:12],
            total=len(images),
            lang=lang,
            max_side=max_side,
            results=[None] * len(images),
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._prune_locked()
        self._executor.submit(self._run, job, list(images))
        return job

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return self._serialize(job) if job is not None else None

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            job.cancelled = True
            job.updated_at = time.time()
            return True

    def _run(self, job: OcrBatchJob, images: List[bytes]) -> None:
        try:
            service: OcrService = self._service_provider()
            with self._lock:
                job.status = "running"
                job.updated_at = time.time()
            for index, image in enumerate(images):
                with self._lock:
                    if job.cancelled:
                        job.status = "cancelled"
                        job.updated_at = time.time()
                        return
                result = service.recognize_bytes(
                    image, lang=job.lang, max_side=job.max_side
                )
                entry = result.to_dict()
                entry["index"] = index
                with self._lock:
                    job.results[index] = entry
                    job.completed += 1
                    if not result.ok:
                        job.failed += 1
                    job.updated_at = time.time()
            with self._lock:
                job.status = "completed"
                job.updated_at = time.time()
        except Exception as exc:  # noqa: BLE001 — 任务级失败可读返回
            logger.warning("OCR batch failed", exc_info=True)
            with self._lock:
                job.status = "failed"
                job.error = str(exc)
                job.updated_at = time.time()

    def _prune_locked(self) -> None:
        if len(self._jobs) <= MAX_RETAINED_JOBS:
            return
        ordered = sorted(self._jobs.values(), key=lambda item: item.created_at)
        for job in ordered[: len(self._jobs) - MAX_RETAINED_JOBS]:
            self._jobs.pop(job.job_id, None)

    @staticmethod
    def _serialize(job: OcrBatchJob) -> Dict[str, Any]:
        return {
            "job_id": job.job_id,
            "status": job.status,
            "total": job.total,
            "completed": job.completed,
            "failed": job.failed,
            "lang": job.lang,
            "max_side": job.max_side,
            "error": job.error,
            "results": job.results,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }


def decode_batch_images(data_urls: List[str]) -> List[bytes]:
    """把 data URL 列表解码为字节；非法项抛 ValueError。"""
    images: List[bytes] = []
    for index, data_url in enumerate(data_urls):
        if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
            raise ValueError("images[%d] is not a valid image data URL" % index)
        try:
            _header, _sep, payload = data_url.partition(",")
            if not payload:
                raise ValueError("missing base64 payload")
            images.append(base64.b64decode(payload, validate=True))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("images[%d] base64 decode failed" % index) from exc
    return images


_global_service: Optional[OcrBatchService] = None
_global_lock = threading.Lock()


def get_ocr_batch_service() -> OcrBatchService:
    global _global_service
    if _global_service is None:
        with _global_lock:
            if _global_service is None:
                _global_service = OcrBatchService()
    return _global_service


def reset_ocr_batch_service() -> None:
    """测试用：清空任务表（不关闭线程池，避免后续 submit 失败）。"""
    global _global_service
    with _global_lock:
        _global_service = None
