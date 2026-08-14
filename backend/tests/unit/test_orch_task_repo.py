"""Wave 2 P1-4 — OrchTaskRepository 单测。

Plan Step 1:OrchTaskRepository CRUD roundtrip(失败 → 通过)。
"""
from __future__ import annotations

import pytest

from backend.data import database as db_mod
from backend.data.orch_task_repo import OrchTaskRepository


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """tmp DB + SAGE_DB_PATH env + 重置全局 _db 单例。"""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    return OrchTaskRepository()


def _upsert_run(run_id: str = "orch-1") -> None:
    """helper:写入一个 orch_run 外键供 task 引用。"""
    from backend.data.orch_run_repo import OrchRun, OrchRunRepository

    OrchRunRepository().upsert(OrchRun(
        run_id=run_id, session_id="s", status="running",
        created_at=1000, plan_json="{}",
    ))


def test_upsert_state_insert_and_get(repo):
    """upsert_state 插入新行 → get 拿到全部字段。"""
    _upsert_run()
    repo.upsert_state(
        task_id="t1",
        run_id="orch-1",
        agent_id="primary",
        goal="write tests",
        status="running",
        blocked_by=["t0"],
        scratch_dir="/tmp/x",
        started_at=100,
    )
    row = repo.get("t1")
    assert row is not None
    assert row.task_id == "t1"
    assert row.run_id == "orch-1"
    assert row.agent_id == "primary"
    assert row.goal == "write tests"
    assert row.status == "running"
    assert row.retry_count == 0
    assert row.blocked_by == ["t0"]
    assert row.scratch_dir == "/tmp/x"
    assert row.started_at == 100
    assert row.finished_at is None


def test_upsert_state_updates_on_conflict(repo):
    """同一 task_id 二次 upsert_state → status / retry_count / finished_at 更新。"""
    _upsert_run()
    repo.upsert_state(
        task_id="t1", run_id="orch-1", agent_id="primary",
        goal="g", status="running",
    )
    repo.upsert_state(
        task_id="t1", run_id="orch-1", agent_id="primary",
        goal="g", status="done", retry_count=2, finished_at=999,
    )
    row = repo.get("t1")
    assert row.status == "done"
    assert row.retry_count == 2
    assert row.finished_at == 999


def test_list_by_run_orders_by_task_id_asc(repo):
    """list_by_run 按 task_id ASC 返回所有该 run 的 task。"""
    _upsert_run()
    _upsert_run("orch-other")
    repo.upsert_state(task_id="t2", run_id="orch-1", agent_id="primary", goal="g2", status="queued")
    repo.upsert_state(task_id="t1", run_id="orch-1", agent_id="primary", goal="g1", status="queued")
    repo.upsert_state(task_id="t3", run_id="orch-other", agent_id="primary", goal="g3", status="queued")
    rows = repo.list_by_run("orch-1")
    assert [r.task_id for r in rows] == ["t1", "t2"]
    assert all(r.run_id == "orch-1" for r in rows)


def test_get_missing_returns_none(repo):
    """不存在的 task_id → None。"""
    assert repo.get("nope") is None


def test_blocked_by_roundtrip_json(repo):
    """blocked_by list → JSON 字符串存,读回时还原为 list。"""
    _upsert_run()
    repo.upsert_state(
        task_id="t1", run_id="orch-1", agent_id="primary",
        goal="g", status="queued", blocked_by=["a", "b", "c"],
    )
    row = repo.get("t1")
    assert row.blocked_by == ["a", "b", "c"]
