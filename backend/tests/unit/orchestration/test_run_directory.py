"""M4.2 (2026-11-23) — 统一运行视图：canonical run 目录端点单测。

- repo ``list_by_statuses`` / ``list_active``：跨会话状态过滤 + 新→旧排序 + limit
- repo ``list_by_runs``：批量取子任务
- ``GET /orch/runs/directory``：200 目录（run + plan + tasks）/ scope 过滤 / limit 校验
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.data import database as db_mod
from backend.data.orch_run_repo import OrchRun, OrchRunRepository
from backend.data.orch_task_repo import OrchTaskRepository

_DEFAULT_PLAN = '{"tasks": [{"task_id": "t1", "agent_id": "researcher", "goal": "g"}]}'


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    # 全量套件下 backend.main 可能已被早前用例装配过模块级 _task_repo
    # （绑定旧的 Database 句柄）→ 目录端点的 tasks 查询会落到旧库。
    # 重置后端点按本用例的 tmp 库现建仓库。
    from backend.api import orch_run_control

    monkeypatch.setattr(orch_run_control, "_task_repo", None)
    db_mod.get_database().init_db()
    from backend.main import app

    return TestClient(app)


def _fresh_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


def _seed_run(run_id, session_id, created_at, status="running", plan_json=None):
    OrchRunRepository().upsert(OrchRun(
        run_id=run_id,
        session_id=session_id,
        status=status,
        created_at=created_at,
        plan_json=_DEFAULT_PLAN if plan_json is None else plan_json,
    ))


# --------------------------------------------------------------- repo: runs


def test_repo_list_by_statuses_filters_cross_session(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    _seed_run("orch-run-a", "s-1", 1000, status="running")
    _seed_run("orch-run-b", "s-2", 2000, status="running")
    _seed_run("orch-done", "s-1", 3000, status="completed")
    _seed_run("orch-fail", "s-2", 4000, status="failed")
    _seed_run("orch-cancel", "s-1", 5000, status="cancelled")

    runs = OrchRunRepository().list_by_statuses(("running",))
    assert [r.run_id for r in runs] == ["orch-run-b", "orch-run-a"]

    mixed = OrchRunRepository().list_by_statuses(("running", "completed"))
    assert [r.run_id for r in mixed] == ["orch-done", "orch-run-b", "orch-run-a"]


def test_repo_list_active_excludes_terminal(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    _seed_run("orch-run-a", "s-1", 1000, status="running")
    _seed_run("orch-done", "s-1", 2000, status="completed")
    _seed_run("orch-fail", "s-2", 3000, status="failed")
    _seed_run("orch-cancel", "s-2", 4000, status="cancelled")

    runs = OrchRunRepository().list_active()
    assert [r.run_id for r in runs] == ["orch-run-a"]


def test_repo_list_by_statuses_respects_limit(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    for i in range(5):
        _seed_run(f"orch-{i}", "s-1", 1000 + i)

    runs = OrchRunRepository().list_active(limit=2)
    assert [r.run_id for r in runs] == ["orch-4", "orch-3"]


def test_repo_list_by_statuses_empty_input_returns_empty(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    _seed_run("orch-run-a", "s-1", 1000, status="running")

    assert OrchRunRepository().list_by_statuses(()) == []


# -------------------------------------------------------------- repo: tasks


def test_repo_list_by_runs_batches_across_runs(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    _seed_run("orch-a", "s-1", 1000, status="running")
    _seed_run("orch-b", "s-1", 2000, status="running")
    _seed_run("orch-c", "s-1", 3000, status="running")
    repo = OrchTaskRepository()
    repo.upsert_state(
        task_id="a1", run_id="orch-a", agent_id="researcher", goal="g1", status="done",
    )
    repo.upsert_state(
        task_id="b1", run_id="orch-b", agent_id="writer", goal="g2", status="running",
    )
    repo.upsert_state(
        task_id="c1", run_id="orch-c", agent_id="other", goal="g3", status="queued",
    )

    tasks = repo.list_by_runs(["orch-a", "orch-b"])
    assert {t.task_id for t in tasks} == {"a1", "b1"}


def test_repo_list_by_runs_empty_input_returns_empty(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    _seed_run("orch-a", "s-1", 1000, status="running")
    repo = OrchTaskRepository()
    repo.upsert_state(
        task_id="a1", run_id="orch-a", agent_id="researcher", goal="g1", status="done",
    )

    assert repo.list_by_runs([]) == []


# ----------------------------------------------------------------- endpoint


def test_endpoint_lists_active_runs_with_plan_and_tasks(client):
    _seed_run("orch-a", "s-1", 1000, status="running")
    _seed_run("orch-done", "s-1", 2000, status="completed")
    OrchTaskRepository().upsert_state(
        task_id="t1",
        run_id="orch-a",
        agent_id="researcher",
        goal="调研",
        status="running",
    )

    r = client.get("/api/v1/orch/runs/directory", params={"scope": "active"})
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "active"
    assert len(body["runs"]) == 1
    run = body["runs"][0]
    assert run["run_id"] == "orch-a"
    assert run["session_id"] == "s-1"
    assert run["status"] == "running"
    assert run["plan"][0]["task_id"] == "t1"
    assert len(run["tasks"]) == 1
    assert run["tasks"][0]["task_id"] == "t1"
    assert run["tasks"][0]["agent_id"] == "researcher"
    assert run["tasks"][0]["status"] == "running"


def test_endpoint_defaults_to_active_scope(client):
    _seed_run("orch-a", "s-1", 1000, status="running")
    _seed_run("orch-done", "s-1", 2000, status="completed")

    r = client.get("/api/v1/orch/runs/directory")
    assert r.status_code == 200
    assert [x["run_id"] for x in r.json()["runs"]] == ["orch-a"]


def test_endpoint_scope_failed_and_finished(client):
    _seed_run("orch-a", "s-1", 1000, status="running")
    _seed_run("orch-f", "s-1", 2000, status="failed")
    _seed_run("orch-c", "s-1", 3000, status="completed")
    _seed_run("orch-x", "s-1", 4000, status="cancelled")

    r = client.get("/api/v1/orch/runs/directory", params={"scope": "failed"})
    assert [x["run_id"] for x in r.json()["runs"]] == ["orch-f"]

    r = client.get("/api/v1/orch/runs/directory", params={"scope": "finished"})
    assert [x["run_id"] for x in r.json()["runs"]] == ["orch-x", "orch-c"]

    r = client.get("/api/v1/orch/runs/directory", params={"scope": "all"})
    assert len(r.json()["runs"]) == 4


def test_endpoint_lists_runs_across_sessions(client):
    _seed_run("orch-a", "s-1", 1000, status="running")
    _seed_run("orch-b", "s-2", 2000, status="running")

    r = client.get("/api/v1/orch/runs/directory", params={"scope": "active"})
    sessions = sorted(x["session_id"] for x in r.json()["runs"])
    assert sessions == ["s-1", "s-2"]


def test_endpoint_rejects_invalid_scope(client):
    r = client.get("/api/v1/orch/runs/directory", params={"scope": "bogus"})
    assert r.status_code == 422


def test_endpoint_rejects_out_of_range_limit(client):
    assert client.get("/api/v1/orch/runs/directory", params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/orch/runs/directory", params={"limit": 999}).status_code == 422


def test_endpoint_empty_directory_returns_empty_list(client):
    r = client.get("/api/v1/orch/runs/directory")
    assert r.status_code == 200
    body = r.json()
    assert body["runs"] == []
    assert body["generated_at"] > 0


def test_endpoint_tolerates_malformed_plan_json(client):
    _seed_run("orch-bad", "s-1", 1000, status="running", plan_json="not-json")

    r = client.get("/api/v1/orch/runs/directory")
    assert r.status_code == 200
    run = r.json()["runs"][0]
    assert run["plan"] == []
    assert run["tasks"] == []
