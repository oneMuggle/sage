"""队列后台守护进程测试。"""

from __future__ import annotations

import pytest

from backend.wiki import queue_daemon as qd, queue_worker as qw

pytestmark = pytest.mark.unit


@pytest.mark.asyncio()
async def test_daemon_processes_pending_project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    calls = []

    async def fake_process(project_root, limit=1):
        calls.append((project_root, limit))
        return {"processed": [{"task_id": "t1", "status": "completed"}]}

    monkeypatch.setattr(qw, "process_pending", fake_process)
    monkeypatch.setattr(qd, "_pending_projects", lambda: [root])

    await qd.run_queue_daemon(poll_seconds=0, max_cycles=1)

    assert calls == [(root, qd.BATCH_LIMIT)]


@pytest.mark.asyncio()
async def test_daemon_skips_when_no_pending(monkeypatch):
    calls = []

    async def fake_process(project_root, limit=1):  # pragma: no cover
        calls.append(project_root)

    monkeypatch.setattr(qw, "process_pending", fake_process)
    monkeypatch.setattr(qd, "_pending_projects", lambda: [])

    await qd.run_queue_daemon(poll_seconds=0, max_cycles=1)

    assert calls == []


@pytest.mark.asyncio()
async def test_daemon_skips_when_manual_processing_holds_lock(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    calls = []

    class _HeldLock:
        def locked(self) -> bool:
            return True

    async def fake_process(project_root, limit=1):  # pragma: no cover
        calls.append(project_root)

    monkeypatch.setattr(qw, "process_pending", fake_process)
    monkeypatch.setattr(qw, "queue_process_lock", _HeldLock())
    monkeypatch.setattr(qd, "_pending_projects", lambda: [root])

    await qd.run_queue_daemon(poll_seconds=0, max_cycles=1)

    assert calls == []
