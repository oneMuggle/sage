"""B3 (2026-09-09): 单任务跳过端点 POST /orch/runs/{run_id}/tasks/{task_id}/cancel。

- 活动 run + 可跳过任务 → 200 且 skip 事件置位
- run 不活动 → 404；任务未知/已终态 → 409
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.data import database as db_mod


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()
    from backend.main import app

    return TestClient(app)


@pytest.fixture()
def active_dispatcher():
    """往进程内注册表塞一个活动 dispatcher（含一个可跳过的 queued 任务）。"""
    from backend.orchestration.chat_dispatcher import (
        _ACTIVE_DISPATCHERS,
        ChatDispatcher,
    )

    d = ChatDispatcher(
        stream_id="s-ep", entry_queue=asyncio.Queue(), run_id="orch-ep-skip"
    )
    from backend.orchestration.chat_dispatcher import ChatTaskState

    d._states["t1"] = ChatTaskState(
        task_id="t1", agent_id="r", goal="g", status="queued"
    )
    d._task_skip_events["t1"] = asyncio.Event()
    _ACTIVE_DISPATCHERS["orch-ep-skip"] = d
    yield d
    _ACTIVE_DISPATCHERS.pop("orch-ep-skip", None)


def test_cancel_task_ok(client, active_dispatcher):
    r = client.post("/api/v1/orch/runs/orch-ep-skip/tasks/t1/cancel")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["task_id"] == "t1"
    assert active_dispatcher._task_skip_events["t1"].is_set()


def test_cancel_task_unknown_returns_409(client, active_dispatcher):
    r = client.post("/api/v1/orch/runs/orch-ep-skip/tasks/t-ghost/cancel")
    assert r.status_code == 409


def test_cancel_task_inactive_run_returns_404(client):
    r = client.post("/api/v1/orch/runs/orch-never-registered/tasks/t1/cancel")
    assert r.status_code == 404


def test_cancel_task_twice_returns_409(client, active_dispatcher):
    client.post("/api/v1/orch/runs/orch-ep-skip/tasks/t1/cancel")
    r = client.post("/api/v1/orch/runs/orch-ep-skip/tasks/t1/cancel")
    assert r.status_code == 409
