# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""站点登录后台任务管理器（进程内）。

前端点击「登录网站」后，REST 只负责启动任务并立即返回 job_id；真正的
``browser_login`` 在后台线程里等待用户完成浏览器登录（最长 5 分钟），
前端轮询 job 状态。与 ``download_jobs`` 同口径：进程内存态、重启清零，
任务表有界（终态任务保留上限 + TTL）。

同一时间只跑一个登录任务：``browser_login`` 复用同一个持久 profile /
可见窗口，并发只会互相抢标签页。重复 start 返回正在运行的任务 id。
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

#: 单个登录任务等待用户操作的超时（秒）
LOGIN_TIMEOUT_SECONDS = 300

#: 终态任务保留时长（秒）与数量上限
JOB_TTL_SECONDS = 600
MAX_FINISHED_JOBS = 20

PENDING = "pending"
RUNNING = "running"
SUCCESS = "success"
FAILED = "failed"

_TERMINAL = (SUCCESS, FAILED)


def _now() -> float:
    return time.time()


def _run_browser_login(url: str) -> Dict[str, Any]:
    """默认 runner：调用现有 browser_login 工具（阻塞直到用户完成登录）。"""
    from backend.tools.browser_tool import BrowserLoginTool

    result = BrowserLoginTool().execute(url=url, timeout_seconds=LOGIN_TIMEOUT_SECONDS)
    if not getattr(result, "success", False):
        return {"ok": False, "error": str(getattr(result, "error", "") or "login_failed")[:500]}
    content = getattr(result, "content", None) or {}
    return {
        "ok": True,
        "saved_domains": [str(d) for d in (content.get("saved_domains") or [])],
    }


class SiteLoginJobs:
    """线程安全的登录任务表；runner 可注入（测试不启动浏览器）。"""

    def __init__(
        self,
        runner: Optional[Callable[[str], Dict[str, Any]]] = None,
        max_workers: int = 1,
    ) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._runner = runner or _run_browser_login
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def start(self, url: str) -> str:
        """启动登录任务。

        同一 URL 已在进行中 → 复用其 job_id；不同 URL 已有任务在等待 →
        抛 ``ValueError("login_in_progress")``（登录窗口只有一个，避免
        用户以为在登录 B 实际在等 A）。
        """
        url = (url or "").strip()
        if not url:
            raise ValueError("url 不能为空")
        with self._lock:
            active = self._active_job_locked()
            if active is not None:
                if active["url"] == url:
                    return str(active["job_id"])
                raise ValueError("login_in_progress")
            job_id = uuid.uuid4().hex[:12]
            self._jobs[job_id] = {
                "job_id": job_id,
                "url": url,
                "status": PENDING,
                "result": None,
                "error": None,
                "created_at": _now(),
                "updated_at": _now(),
            }
            self._evict_locked()
        self._executor.submit(self._run, job_id, url)
        return job_id

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._evict_locked()
            job = self._jobs.get((job_id or "").strip())
            return dict(job) if job else None

    # ----------------------------------------------------------------- internal

    def _active_job_locked(self) -> Optional[Dict[str, Any]]:
        for job in self._jobs.values():
            if job["status"] in (PENDING, RUNNING):
                return job
        return None

    def _evict_locked(self) -> None:
        now = _now()
        stale = [
            job
            for job in self._jobs.values()
            if job["status"] in _TERMINAL
            and now - float(job.get("updated_at") or job.get("created_at") or 0) > JOB_TTL_SECONDS
        ]
        for job in stale:
            self._jobs.pop(job["job_id"], None)
        finished = sorted(
            (
                job
                for job in self._jobs.values()
                if job["status"] in _TERMINAL
            ),
            key=lambda job: float(job.get("updated_at") or 0),
        )
        overflow = len(finished) - MAX_FINISHED_JOBS
        for job in finished[: max(0, overflow)]:
            self._jobs.pop(job["job_id"], None)

    def _run(self, job_id: str, url: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["status"] = RUNNING
            job["updated_at"] = _now()
        try:
            outcome = self._runner(url)
        except Exception as exc:  # noqa: BLE001 — 登录失败如实回传，不吞掉任务
            outcome = {"ok": False, "error": str(exc)[:500]}
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["status"] = SUCCESS if outcome.get("ok") else FAILED
            job["result"] = outcome if outcome.get("ok") else None
            job["error"] = None if outcome.get("ok") else str(outcome.get("error") or "")
            job["updated_at"] = _now()


    def reset(self) -> None:
        """清空任务表（测试隔离用；不替换 executor）。"""
        with self._lock:
            self._jobs.clear()


#: 进程级单例（与 download_jobs 同口径）
site_login_jobs = SiteLoginJobs()


__all__ = [
    "FAILED",
    "PENDING",
    "RUNNING",
    "SUCCESS",
    "SiteLoginJobs",
    "site_login_jobs",
]
