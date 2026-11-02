"""OCR 批处理任务（多图/PDF 页的队列与进度）。

设计取舍：
- 进程内单 worker（CPU 推理不宜高并发），任务状态 + 结果在内存；
- 每项结果独立失败，不影响后续项；
- 任务保留最近 N 条，避免无限增长；
- 仅供本地 REST/前端使用，不持久化到磁盘（重启丢失，可重试）。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional

from .service import OcrService, get_ocr_service

logger = logging.getLogger(__name__)

MAX_BATCH_ITEMS = 20
MAX_PDF_PAGES = 50
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_RETAINED_JOBS = 50
#: 已完成任务的默认保留期（7 天）；运行中任务不会被 TTL 清理。
MAX_JOB_AGE_SECONDS = 7 * 24 * 3600


@dataclass
class OcrBatchJob:
    job_id: str
    total: int
    lang: str
    max_side: Optional[int]
    status: str = "pending"           # pending/running/completed/cancelled/failed
    source: str = "images"            # images/pdf
    completed: int = 0
    failed: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: Optional[str] = None
    results: List[Optional[Dict[str, Any]]] = field(default_factory=list)
    cancelled: bool = False
    deleted: bool = False


def _default_store_dir() -> Path:
    """任务持久化目录；未注入用户数据目录时退回系统临时目录。"""
    base = os.environ.get("SAGE_OCR_JOB_DIR") or os.environ.get("SAGE_USER_DATA_DIR")
    if base:
        return Path(base) / "cache" / "ocr_batch"
    return Path(tempfile.gettempdir()) / "sage-ocr-batch"


class OcrBatchService:
    """单 worker 批处理队列；任务表持久化到用户数据目录。"""

    def __init__(
        self,
        service_provider=get_ocr_service,
        store_dir: Optional[Path] = None,
    ) -> None:
        self._service_provider = service_provider
        self._store_dir = Path(store_dir) if store_dir is not None else _default_store_dir()
        self._jobs: Dict[str, OcrBatchJob] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ocr-batch"
        )
        self._load_persisted()

    def submit(
        self,
        images: List[bytes],
        *,
        lang: str = "auto",
        max_side: Optional[int] = None,
        max_items: int = MAX_BATCH_ITEMS,
        source: str = "images",
    ) -> OcrBatchJob:
        if not images:
            raise ValueError("batch requires at least one image")
        if len(images) > max_items:
            raise ValueError("batch supports at most %d images" % max_items)
        job = OcrBatchJob(
            job_id=uuid.uuid4().hex[:12],
            total=len(images),
            lang=lang,
            max_side=max_side,
            source=source,
            results=[None] * len(images),
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._cleanup_expired_locked(time.time())
            self._prune_locked()
            self._persist_locked(job)
        self._executor.submit(self._run, job, list(images))
        return job

    def submit_pdf(
        self,
        pdf_bytes: bytes,
        *,
        lang: str = "auto",
        max_side: Optional[int] = None,
        max_pages: int = MAX_PDF_PAGES,
    ) -> OcrBatchJob:
        """光栅化 PDF 页并提交批处理；解析失败抛 ValueError。"""
        images = rasterize_pdf_pages(pdf_bytes, max_pages=max_pages)
        return self.submit(
            images,
            lang=lang,
            max_side=max_side,
            max_items=MAX_PDF_PAGES,
            source="pdf",
        )

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
            self._persist_locked(job)
            return True

    def delete(self, job_id: str) -> bool:
        """删除任务及其快照；运行中任务会被标记取消并阻止回写。"""
        with self._lock:
            job = self._jobs.pop(job_id, None)
            if job is None:
                return False
            job.deleted = True
            job.cancelled = True
            job.updated_at = time.time()
            self._unlink_job(job_id)
            return True

    def cleanup(self, older_than_s: Optional[float] = None) -> int:
        """清理已结束且超过保留期的任务；返回删除数量。"""
        with self._lock:
            return self._cleanup_expired_locked(time.time(), older_than_s)

    def _unlink_job(self, job_id: str) -> None:
        try:
            self._job_path(job_id).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("remove OCR batch job file failed", exc_info=True)

    def _cleanup_expired_locked(
        self,
        now: float,
        older_than_s: Optional[float] = None,
    ) -> int:
        ttl = MAX_JOB_AGE_SECONDS if older_than_s is None else max(0.0, older_than_s)
        cutoff = now - ttl
        removed = 0
        for job in list(self._jobs.values()):
            if job.status in ("pending", "running"):
                continue
            if job.updated_at >= cutoff:
                continue
            self._jobs.pop(job.job_id, None)
            self._unlink_job(job.job_id)
            removed += 1
        return removed

    def _run(self, job: OcrBatchJob, images: List[bytes]) -> None:
        try:
            service: OcrService = self._service_provider()
            with self._lock:
                job.status = "running"
                job.updated_at = time.time()
                self._persist_locked(job)
            for index, image in enumerate(images):
                with self._lock:
                    if job.cancelled:
                        job.status = "cancelled"
                        job.updated_at = time.time()
                        self._persist_locked(job)
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
                    self._persist_locked(job)
            with self._lock:
                job.status = "completed"
                job.updated_at = time.time()
                self._persist_locked(job)
        except Exception as exc:  # noqa: BLE001 — 任务级失败可读返回
            logger.warning("OCR batch failed", exc_info=True)
            with self._lock:
                job.status = "failed"
                job.error = str(exc)
                job.updated_at = time.time()
                self._persist_locked(job)

    def _job_path(self, job_id: str) -> Path:
        return self._store_dir / f"{job_id}.json"

    def _persist_locked(self, job: OcrBatchJob) -> None:
        """原子写入任务快照；持久化失败不阻断 OCR 本身。"""
        if job.deleted:
            return
        try:
            self._store_dir.mkdir(parents=True, exist_ok=True)
            path = self._job_path(job.job_id)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(
                json.dumps(asdict(job), ensure_ascii=False), encoding="utf-8"
            )
            tmp.replace(path)
        except OSError:
            logger.warning("persist OCR batch job failed", exc_info=True)

    def _load_persisted(self) -> None:
        """加载历史任务；重启时仍在运行的任务标记为 interrupted。"""
        try:
            self._store_dir.mkdir(parents=True, exist_ok=True)
            paths = sorted(
                self._store_dir.glob("*.json"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )[:MAX_RETAINED_JOBS]
        except OSError:
            logger.warning("load OCR batch jobs failed", exc_info=True)
            return

        valid_fields = {item.name for item in fields(OcrBatchJob)}
        for path in reversed(paths):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("job file is not an object")
                data = {key: value for key, value in raw.items() if key in valid_fields}
                job = OcrBatchJob(**data)
            except (OSError, ValueError, TypeError):
                logger.warning("skip invalid OCR batch job file: %s", path)
                continue
            if job.status in ("pending", "running"):
                job.status = "failed"
                job.error = "interrupted: backend restarted"
                job.updated_at = time.time()
                self._persist_locked(job)
            self._jobs[job.job_id] = job
        self._cleanup_expired_locked(time.time())

    def _prune_locked(self) -> None:
        if len(self._jobs) <= MAX_RETAINED_JOBS:
            return
        ordered = sorted(self._jobs.values(), key=lambda item: item.created_at)
        for job in ordered[: len(self._jobs) - MAX_RETAINED_JOBS]:
            self._jobs.pop(job.job_id, None)
            self._unlink_job(job.job_id)

    @staticmethod
    def _serialize(job: OcrBatchJob) -> Dict[str, Any]:
        return {
            "job_id": job.job_id,
            "status": job.status,
            "source": job.source,
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


def decode_pdf_data_url(data_url: str) -> bytes:
    """解码 ``data:application/pdf;base64,``；非法输入抛 ValueError。"""
    prefix = "data:application/pdf;base64,"
    if not isinstance(data_url, str) or not data_url.startswith(prefix):
        raise ValueError("not a valid PDF data URL")
    payload = data_url[len(prefix):]
    if not payload:
        raise ValueError("missing PDF base64 payload")
    try:
        pdf_bytes = base64.b64decode(payload, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("PDF base64 decode failed") from exc
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise ValueError(f"PDF exceeds {MAX_PDF_BYTES} bytes")
    return pdf_bytes


def rasterize_pdf_pages(
    pdf_bytes: bytes,
    *,
    max_pages: int = MAX_PDF_PAGES,
    dpi: int = 200,
) -> List[bytes]:
    """把 PDF 每页渲染为 PNG 字节；依赖 PyMuPDF（懒加载）。"""
    if not pdf_bytes:
        raise ValueError("empty PDF")
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")
    try:
        import fitz  # noqa: PLC0415 — 可选/重量级依赖，调用时加载
    except ImportError as exc:
        raise ValueError("PyMuPDF (fitz) is required for PDF OCR") from exc

    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            page_count = document.page_count
            if page_count < 1:
                raise ValueError("PDF has no pages")
            if page_count > max_pages:
                raise ValueError(
                    "PDF has %d pages, max %d" % (page_count, max_pages)
                )
            pages: List[bytes] = []
            for page in document:
                pixmap = page.get_pixmap(dpi=dpi, alpha=False)
                pages.append(pixmap.tobytes("png"))
            return pages
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 — 第三方解析错误统一折叠
        raise ValueError(f"invalid PDF: {exc}") from exc


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
