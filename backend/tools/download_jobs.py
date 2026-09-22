# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""DL2 后台下载任务管理器（Round 21）：ThreadPoolExecutor + 线程安全任务表。

- 任务表进程内存态（重启清零，与 web_metrics 同口径）；完成后结果保留供
  ``download_status`` 查询（含最终 path/bytes/sha256）；
- cancel 语义（诚实口径）：仅 **pending**（排队未启动）可取消；running 的下载
  不可中断（现有 execute 无 chunk 级取消钩子），如实返回不可取消；
- 全局单例经 ``get_download_job_manager()`` 访问；``reset_download_job_manager()``
  供测试清零。
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import (
    Future,  # noqa: F401 — re-export 语义清晰
    ThreadPoolExecutor,
)
from typing import Any, Dict, Optional

#: 后台下载 worker 线程数
MAX_WORKERS = 2

#: 终态任务的保留上限（超出淘汰最旧的终态任务，防止任务表无限增长）
MAX_FINISHED_JOBS = 200

PENDING = "pending"
RUNNING = "running"
SUCCESS = "success"
FAILED = "failed"
CANCELLED = "cancelled"


class DownloadJobManager:
    """后台下载任务管理器：executor 队列 + 线程安全任务表。"""

    def __init__(self, max_workers: int = MAX_WORKERS) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._run_kwargs: Dict[str, Dict[str, Any]] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    # ------------------------------------------------------------------ API

    def submit(self, tool: Any, **kwargs: Any) -> str:
        """提交后台下载任务，返回 job_id。kwargs 透传 HttpDownloadTool.execute。"""
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "url": str(kwargs.get("url", "")),
                "status": PENDING,
                "result": None,
                "error": None,
                "cancel_requested": False,
                "created_at": _now(),
            }
            self._run_kwargs[job_id] = {"tool": tool, "kwargs": dict(kwargs)}
            self._evict_finished_locked()
        self._executor.submit(self._run, job_id)
        return job_id

    def cancel(self, job_id: str) -> Dict[str, Any]:
        """取消任务。仅 pending 可取消；running 的下载不可中断（诚实返回）。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {"ok": False, "error": "job_not_found: 任务不存在或已被清理"}
            if job["status"] == PENDING:
                job["status"] = CANCELLED
                job["error"] = "cancelled by user"
                self._run_kwargs.pop(job_id, None)
                return {"ok": True, "status": CANCELLED}
            return {
                "ok": False,
                "error": f"cannot_cancel: 任务已 {job['status']}，不可取消",
            }

    def status(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def all_jobs(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {jid: dict(job) for jid, job in self._jobs.items()}

    def reset(self) -> None:
        with self._lock:
            self._jobs.clear()
            self._run_kwargs.clear()

    # ------------------------------------------------------------- internals

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["status"] != PENDING:
                return  # cancelled while queued
            entry = self._run_kwargs.pop(job_id, None)
            if entry is None:
                job["status"] = FAILED
                job["error"] = "run kwargs missing"
                return
            job["status"] = RUNNING
        tool = entry["tool"]
        kwargs = entry["kwargs"]
        try:
            result = tool.execute(**kwargs)
        except Exception as exc:  # noqa: BLE001 — 后台任务兜底
            self._finish(job_id, FAILED, error=str(exc))
            return
        if result.success:
            self._finish(job_id, SUCCESS, result=result.content)
        else:
            self._finish(job_id, FAILED, error=result.error)

    def _finish(self, job_id: str, status: str, result: Any = None, error: Any = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["status"] = status
            job["result"] = result
            job["error"] = error
            self._evict_finished_locked()

    def _evict_finished_locked(self) -> None:
        finished = sorted(
            (
                jid
                for jid, job in self._jobs.items()
                if job["status"] in (SUCCESS, FAILED, CANCELLED)
            ),
            key=lambda jid: self._jobs[jid].get("created_at") or 0.0,
        )
        overflow = len(finished) - MAX_FINISHED_JOBS
        for jid in finished[: max(0, overflow)]:
            self._jobs.pop(jid, None)
            self._run_kwargs.pop(jid, None)


def _now() -> float:
    import time

    return time.time()


_manager: Optional[DownloadJobManager] = None
_manager_lock = threading.Lock()


def get_download_job_manager() -> DownloadJobManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = DownloadJobManager(max_workers=MAX_WORKERS)
        return _manager


def reset_download_job_manager() -> None:
    global _manager
    with _manager_lock:
        _manager = None
