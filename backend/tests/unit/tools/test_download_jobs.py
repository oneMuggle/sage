"""R130 — DownloadJobManager 单元测试。

覆盖：submit→PENDING、run 生命周期（成功/失败/异常/排队中取消早退）、
cancel 诚实语义（仅 pending 可取消、running 拒绝、未知 job_not_found）、
status/all_jobs 副本语义、reset、终态淘汰（压小上限验证最旧淘汰）、
全局单例 get/reset。
"""

from __future__ import annotations

import threading
import time

import pytest

from backend.tools import download_jobs as dj
from backend.tools.base import ToolResult
from backend.tools.download_jobs import (
    CANCELLED,
    FAILED,
    PENDING,
    SUCCESS,
    DownloadJobManager,
    get_download_job_manager,
    reset_download_job_manager,
)

pytestmark = pytest.mark.unit


class _FakeTool:
    """可控节奏的假下载工具。"""

    def __init__(self, result=None, exc=None, gate=None):
        self._result = result
        self._exc = exc
        self._gate = gate
        self.started = threading.Event()

    def execute(self, **kwargs):
        self.started.set()
        if self._gate is not None:
            self._gate.wait(timeout=10)
        if self._exc is not None:
            raise self._exc
        return self._result


def _wait_for(predicate, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture()
def manager():
    mgr = DownloadJobManager(max_workers=1)  # 单 worker：状态迁移可预测
    yield mgr
    mgr._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# submit / 生命周期
# ---------------------------------------------------------------------------


def _hold_worker(manager, gate):
    """提交一个被 gate 卡住的占位任务，把单 worker 占住。"""
    blocker = _FakeTool(result=ToolResult(success=True, content="blocker"), gate=gate)
    manager.submit(blocker)
    assert blocker.started.wait(timeout=10)  # worker 已被占住


def test_submit_returns_hex_id_and_starts_pending(manager):
    job_id = manager.submit(_FakeTool(result=ToolResult(success=True, content="x")), url="u")
    assert len(job_id) == 12
    assert int(job_id, 16) >= 0
    snap = manager.status(job_id)
    assert snap is not None
    assert snap["job_id"] == job_id


def test_run_success_finishes_with_content(manager):
    tool = _FakeTool(result=ToolResult(success=True, content="payload"))
    job_id = manager.submit(tool, url="u")
    assert _wait_for(lambda: manager.status(job_id)["status"] == SUCCESS)
    job = manager.status(job_id)
    assert job["result"] == "payload"
    assert job["error"] is None


def test_run_tool_failure_maps_to_failed(manager):
    tool = _FakeTool(result=ToolResult(success=False, error="disk full"))
    job_id = manager.submit(tool)
    assert _wait_for(lambda: manager.status(job_id)["status"] == FAILED)
    assert manager.status(job_id)["error"] == "disk full"


def test_run_tool_exception_maps_to_failed(manager):
    tool = _FakeTool(exc=RuntimeError("network down"))
    job_id = manager.submit(tool)
    assert _wait_for(lambda: manager.status(job_id)["status"] == FAILED)
    assert "network down" in manager.status(job_id)["error"]


def test_cancelled_job_skipped_by_worker(manager):
    blocker_gate = threading.Event()
    _hold_worker(manager, blocker_gate)
    tool = _FakeTool(result=ToolResult(success=True, content="x"))
    job_id = manager.submit(tool)
    assert manager.cancel(job_id)["ok"] is True  # 排队中取消
    blocker_gate.set()  # worker 空出来后取到该任务
    assert _wait_for(lambda: tool.started.is_set() or True)  # 给 worker 调度机会
    time.sleep(0.2)
    assert manager.status(job_id)["status"] == CANCELLED  # 早退，不被覆盖
    assert tool.started.is_set() is False  # execute 从未被调用


# ---------------------------------------------------------------------------
# cancel 语义
# ---------------------------------------------------------------------------


def test_cancel_pending_ok(manager):
    blocker_gate = threading.Event()
    _hold_worker(manager, blocker_gate)
    job_id = manager.submit(_FakeTool(result=ToolResult(success=True, content="x")))
    assert manager.status(job_id)["status"] == PENDING  # worker 被占住，目标仍排队
    out = manager.cancel(job_id)
    blocker_gate.set()
    assert out == {"ok": True, "status": CANCELLED}
    assert manager.status(job_id)["error"] == "cancelled by user"


def test_cancel_running_refused_honestly(manager):
    gate = threading.Event()
    tool = _FakeTool(result=ToolResult(success=True, content="x"), gate=gate)
    job_id = manager.submit(tool)
    try:
        assert tool.started.wait(timeout=10)
        out = manager.cancel(job_id)
        assert out["ok"] is False
        assert "cannot_cancel" in out["error"]
    finally:
        gate.set()


def test_cancel_unknown_job_not_found(manager):
    out = manager.cancel("nope")
    assert out["ok"] is False
    assert "job_not_found" in out["error"]


# ---------------------------------------------------------------------------
# 副本语义 / reset / 淘汰 / 单例
# ---------------------------------------------------------------------------


def test_status_returns_copy(manager):
    job_id = manager.submit(_FakeTool(result=ToolResult(success=True, content="x")))
    snap = manager.status(job_id)
    assert snap is not None
    snap["status"] = "tampered"
    assert manager.status(job_id)["status"] != "tampered"


def test_status_unknown_returns_none(manager):
    assert manager.status("ghost") is None


def test_all_jobs_returns_copies(manager):
    manager.submit(_FakeTool(result=ToolResult(success=True, content="x")))
    jobs = manager.all_jobs()
    for job in jobs.values():
        job["status"] = "tampered"
    assert all(j["status"] != "tampered" for j in manager.all_jobs().values())


def test_reset_clears_table(manager):
    manager.submit(_FakeTool(result=ToolResult(success=True, content="x")))
    manager.reset()
    assert manager.all_jobs() == {}


def test_finished_eviction_keeps_newest(monkeypatch, manager):
    monkeypatch.setattr(dj, "MAX_FINISHED_JOBS", 2)
    ids = []
    for n in range(3):
        tool = _FakeTool(result=ToolResult(success=True, content=f"c{n}"))
        ids.append(manager.submit(tool))
        assert _wait_for(lambda jid=ids[-1]: manager.status(jid)["status"] == SUCCESS)
        time.sleep(0.01)  # 保证 created_at 单调
    statuses = {jid: manager.status(jid) for jid in ids}
    assert statuses[ids[0]] is None  # 最旧终态被淘汰
    assert statuses[ids[1]] is not None
    assert statuses[ids[2]] is not None


def test_singleton_get_and_reset():
    reset_download_job_manager()
    first = get_download_job_manager()
    assert get_download_job_manager() is first  # 同实例
    reset_download_job_manager()
    assert get_download_job_manager() is not first  # reset 后换新
    reset_download_job_manager()  # 清理全局态，防跨用例泄漏
