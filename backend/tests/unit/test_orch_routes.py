"""Wave 2 P1-4 — orch_routes 端点单测。

Plan Step 1:get_run 404 / plan 更新 409 锁定（dispatched_at 非 None）+
未派发 200 + 422 min_length 验证。
fixture 用 main 的 app（legacy_routes 无 app 变量）。

Wave 4 (2026-09-06): 历史编排记录功能移除 —— 删除 list_runs / resume_run 测试。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.data import database as db_mod
from backend.data.orch_run_repo import OrchRun, OrchRunRepository


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """tmp DB + SAGE_DB_PATH env + 重置全局 _db 单例,挂 legacy_router。"""
    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()
    # legacy_routes 无 app 变量 —— 用 main 的 app(挂载 legacy_router 含 orch 路由)。
    from backend.main import app

    return TestClient(app)


def test_get_run_returns_404(client):
    """不存在的 run → 404。"""
    r = client.get("/api/v1/orch/runs/orch-missing")
    assert r.status_code == 404


def test_update_plan_after_dispatch_returns_409(client):
    """已派发（dispatched_at 非 None）→ 409 锁定,即使 status 仍 running。"""
    repo = OrchRunRepository()
    repo.upsert(OrchRun(
        run_id="orch-dispatched", session_id="s-1", status="running",
        created_at=1000, plan_json='{"tasks":[]}',
        dispatched_at=1000,
    ))
    r = client.post(
        "/api/v1/orch/runs/orch-dispatched/plan",
        json={"plan": [{"task_id": "t1", "agent_id": "primary", "goal": "g"}]},
    )
    assert r.status_code == 409
    assert "locked" in r.json()["detail"].lower()


def test_update_plan_before_dispatch_succeeds(client):
    """未派发（dispatched_at 为 None）+ running → 200 更新成功。"""
    repo = OrchRunRepository()
    repo.upsert(OrchRun(
        run_id="orch-pending", session_id="s-1", status="running",
        created_at=1000, plan_json='{"tasks":[]}',
    ))
    r = client.post(
        "/api/v1/orch/runs/orch-pending/plan",
        json={"plan": [{"task_id": "t1", "agent_id": "primary", "goal": "g"}]},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    updated = repo.get("orch-pending")
    assert updated is not None
    assert updated.plan_json == json.dumps(
        {"tasks": [{"task_id": "t1", "agent_id": "primary", "goal": "g"}],
         "reasoning": ""},
        ensure_ascii=False,
    )


def test_update_plan_min_one_item_validation(client):
    """空 plan → 422 Pydantic 验证。"""
    repo = OrchRunRepository()
    repo.upsert(OrchRun(
        run_id="orch-running", session_id="s-1", status="running",
        created_at=1000, plan_json='{"tasks":[]}',
    ))
    r = client.post("/api/v1/orch/runs/orch-running/plan", json={"plan": []})
    assert r.status_code == 422


# Fix #3 (2026-09-06): 用户确认端点测试


def test_confirm_run_returns_404(client):
    """不存在的 run → 404。"""
    r = client.post("/api/v1/orch/runs/orch-missing/confirm")
    assert r.status_code == 404


def test_confirm_run_returns_409_when_cancelled(client):
    """已取消的 run → 409。"""
    repo = OrchRunRepository()
    repo.upsert(OrchRun(
        run_id="orch-cancelled", session_id="s-1", status="cancelled",
        created_at=1000, plan_json='{"tasks":[]}',
    ))
    r = client.post("/api/v1/orch/runs/orch-cancelled/confirm")
    assert r.status_code == 409


def test_confirm_run_running_succeeds(client):
    """running 状态的 run → 200 确认成功（即使无 pending confirm event 也返回 ok）。"""
    repo = OrchRunRepository()
    repo.upsert(OrchRun(
        run_id="orch-confirm-test", session_id="s-1", status="running",
        created_at=1000, plan_json='{"tasks":[]}',
    ))
    r = client.post("/api/v1/orch/runs/orch-confirm-test/confirm")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["run_id"] == "orch-confirm-test"
