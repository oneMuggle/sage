"""C1 (2026-09-09) — 会话编排 run 列表（历史任务板恢复）单测。

- repo ``list_by_session``：会话过滤 + 新→旧排序 + limit
- ``GET /orch/runs?session_id=``：200 列表（含 tasks）/ 缺参 422 / 未知会话空列表
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.data import database as db_mod
from backend.data.orch_run_repo import OrchRun, OrchRunRepository
from backend.data.orch_task_repo import OrchTaskRepository


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()
    from backend.main import app

    return TestClient(app)


def _seed_run(run_id: str, session_id: str, created_at: int, status: str = "completed"):
    OrchRunRepository().upsert(OrchRun(
        run_id=run_id,
        session_id=session_id,
        status=status,
        created_at=created_at,
        plan_json='{"tasks": [{"task_id": "t1", "agent_id": "researcher", "goal": "g"}]}',
    ))


def test_repo_list_by_session_orders_and_filters(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()
    _seed_run("orch-old", "s-1", 1000)
    _seed_run("orch-new", "s-1", 2000)
    _seed_run("orch-other", "s-2", 3000)

    runs = OrchRunRepository().list_by_session("s-1")
    assert [r.run_id for r in runs] == ["orch-new", "orch-old"]


def test_repo_list_by_session_limit(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()
    for i in range(5):
        _seed_run(f"orch-{i}", "s-1", 1000 + i)
    runs = OrchRunRepository().list_by_session("s-1", limit=2)
    assert [r.run_id for r in runs] == ["orch-4", "orch-3"]


def test_endpoint_lists_runs_with_tasks(client):
    _seed_run("orch-a", "s-1", 1000)
    OrchTaskRepository().upsert_state(
        task_id="t1",
        run_id="orch-a",
        agent_id="researcher",
        goal="调研",
        status="done",
        output_preview="结果",
    )
    r = client.get("/api/v1/orch/runs", params={"session_id": "s-1"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["runs"]) == 1
    run = body["runs"][0]
    assert run["run_id"] == "orch-a"
    assert run["status"] == "completed"
    assert len(run["tasks"]) == 1
    assert run["tasks"][0]["output_preview"] == "结果"
    assert run["plan"][0]["task_id"] == "t1"


def test_endpoint_requires_session_id(client):
    r = client.get("/api/v1/orch/runs")
    assert r.status_code == 422


def test_endpoint_unknown_session_returns_empty(client):
    r = client.get("/api/v1/orch/runs", params={"session_id": "s-none"})
    assert r.status_code == 200
    assert r.json()["runs"] == []
