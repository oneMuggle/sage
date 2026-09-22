"""R21 DL2 后台下载任务管理器单元测试（DownloadJobManager 生命周期）。"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest

from backend.tools import download_jobs as dj
from backend.tools.download_jobs import DownloadJobManager

pytestmark = pytest.mark.unit


class _FakeTool:
    """可控的假下载工具：execute 等待 release 事件后返回/抛错。"""

    def __init__(self, gate: threading.Event, fail: bool = False) -> None:
        self._gate = gate
        self._fail = fail
        self.calls: list[dict[str, Any]] = []

    def execute(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(dict(kwargs))
        self._gate.wait(timeout=5)
        if self._fail:
            raise RuntimeError("download boom")
        return SimpleNamespace(
            success=True,
            content={"path": "out.pdf", "bytes_written": 10, "sha256": "ab" * 32},
            error=None,
        )


@pytest.fixture(autouse=True)
def _reset_manager():
    dj.reset_download_job_manager()
    yield
    dj.reset_download_job_manager()


class TestLifecycle:
    def test_submit_pending_then_success(self):
        gate = threading.Event()
        gate.set()
        mgr = DownloadJobManager(max_workers=1)
        jid = mgr.submit(_FakeTool(gate), url="https://example.com/f.pdf")
        for _ in range(100):
            if mgr.status(jid)["status"] == dj.SUCCESS:
                break
            threading.Event().wait(0.05)
        job = mgr.status(jid)
        assert job["status"] == dj.SUCCESS
        assert job["result"]["path"] == "out.pdf"
        assert job["error"] is None

    def test_cancel_pending_job(self):
        gate = threading.Event()
        gate.clear()
        mgr = DownloadJobManager(max_workers=1)
        blocker = _FakeTool(gate)
        first = mgr.submit(blocker, url="https://example.com/a.pdf")
        # 等 worker 取走 first（running）后提交第二个（pending）
        for _ in range(100):
            if mgr.status(first)["status"] == dj.RUNNING:
                break
            threading.Event().wait(0.05)
        second = mgr.submit(_FakeTool(gate), url="https://example.com/b.pdf")
        out = mgr.cancel(second)
        assert out["ok"] is True
        assert mgr.status(second)["status"] == dj.CANCELLED

    def test_cancel_running_not_allowed(self):
        gate = threading.Event()
        mgr = DownloadJobManager(max_workers=1)
        blocker = _FakeTool(gate)
        first = mgr.submit(blocker, url="https://example.com/a.pdf")
        for _ in range(100):
            if mgr.status(first)["status"] == dj.RUNNING:
                break
            threading.Event().wait(0.05)
        out = mgr.cancel(first)
        assert out["ok"] is False
        assert "cannot_cancel" in out["error"]
        gate.set()

    def test_cancel_missing_job(self):
        mgr = DownloadJobManager()
        out = mgr.cancel("nonexistent")
        assert out["ok"] is False
        assert out["error"] == "job_not_found: 任务不存在或已被清理"

    def test_failure_records_error(self):
        gate = threading.Event()
        gate.set()
        mgr = DownloadJobManager(max_workers=1)

        class _Boom:
            def execute(self, **kwargs):
                raise RuntimeError("disk full")

        jid = mgr.submit(_Boom(), url="https://example.com/f.pdf")
        for _ in range(100):
            if mgr.status(jid)["status"] in (dj.SUCCESS, dj.FAILED):
                break
            threading.Event().wait(0.05)
        job = mgr.status(jid)
        assert job["status"] == dj.FAILED
        assert "disk full" in job["error"]


class TestEviction:
    def test_finished_jobs_evicted_beyond_cap(self):
        gate = threading.Event()
        gate.set()
        mgr = DownloadJobManager(max_workers=4)

        class _Fast:
            def execute(self, **kwargs):
                return SimpleNamespace(success=True, content={"p": "x"}, error=None)

        for i in range(dj.MAX_FINISHED_JOBS + 10):
            mgr._jobs[f"j{i}"] = {
                "job_id": f"j{i}",
                "url": "u",
                "status": dj.SUCCESS,
                "result": None,
                "error": None,
                "cancel_requested": False,
                "created_at": float(i),
            }
        # 触发一次 submit 的淘汰逻辑（直接调内部方法验证）
        mgr._evict_finished_locked()
        assert len(mgr._jobs) <= dj.MAX_FINISHED_JOBS
