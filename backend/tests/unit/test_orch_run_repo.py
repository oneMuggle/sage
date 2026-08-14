"""Wave 2 P1-4 — OrchRunRepository 单测。

Plan Step 1:OrchRunRepository CRUD roundtrip(失败 → 通过)。
"""
from __future__ import annotations

import pytest

from backend.data import database as db_mod
from backend.data.orch_run_repo import OrchRun, OrchRunRepository


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """tmp DB + SAGE_DB_PATH env + 重置全局 _db 单例。"""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    # 重置全局 _db 单例,让 get_database() 重新读 SAGE_DB_PATH
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    return OrchRunRepository()


def test_upsert_and_get_roundtrip(repo):
    """upsert 一行 → get 拿到完整字段。"""
    run = OrchRun(
        run_id="orch-abc",
        session_id="s-1",
        status="running",
        created_at=1700000000000,
        plan_json='{"tasks":[]}',
    )
    repo.upsert(run)
    fetched = repo.get("orch-abc")
    assert fetched is not None
    assert fetched.run_id == "orch-abc"
    assert fetched.session_id == "s-1"
    assert fetched.status == "running"
    assert fetched.created_at == 1700000000000
    assert fetched.plan_json == '{"tasks":[]}'
    assert fetched.final_summary is None
    assert fetched.dispatched_at is None


def test_upsert_roundtrips_dispatched_at(repo):
    """dispatched_at 非默认值也完整 roundtrip。"""
    repo.upsert(OrchRun(
        run_id="orch-disp", session_id="s", status="running",
        created_at=1000, plan_json="{}", dispatched_at=1234,
    ))
    fetched = repo.get("orch-disp")
    assert fetched.dispatched_at == 1234


def test_get_missing_returns_none(repo):
    """不存在的 run_id → None(非异常)。"""
    assert repo.get("nope") is None


def test_upsert_overwrites_on_conflict(repo):
    """同一 run_id 二次 upsert → 字段更新(ON CONFLICT DO UPDATE)。"""
    repo.upsert(OrchRun(
        run_id="orch-x", session_id="s-old", status="running",
        created_at=1000, plan_json="{}",
    ))
    repo.upsert(OrchRun(
        run_id="orch-x", session_id="s-new", status="completed",
        created_at=1000, plan_json='{"updated":true}',
    ))
    fetched = repo.get("orch-x")
    assert fetched.session_id == "s-new"
    assert fetched.status == "completed"
    assert fetched.plan_json == '{"updated":true}'


def test_list_orders_by_created_at_desc(repo):
    """list 按 created_at DESC 返回。"""
    repo.upsert(OrchRun(
        run_id="old", session_id="s", status="completed",
        created_at=1000, plan_json="{}",
    ))
    repo.upsert(OrchRun(
        run_id="new", session_id="s", status="completed",
        created_at=2000, plan_json="{}",
    ))
    rows = repo.list()
    assert [r.run_id for r in rows] == ["new", "old"]


def test_finalize_sets_status_and_summary(repo):
    """finalize 改 status + final_summary,不动其他字段。"""
    repo.upsert(OrchRun(
        run_id="orch-fin", session_id="s", status="running",
        created_at=1, plan_json="{}",
    ))
    repo.finalize("orch-fin", "completed", "all done")
    fetched = repo.get("orch-fin")
    assert fetched.status == "completed"
    assert fetched.final_summary == "all done"


def test_mark_dispatched_first_write_wins(repo):
    """mark_dispatched 幂等：首次写入生效,后续调用不覆盖（first-dispatch-wins）。"""
    repo.upsert(OrchRun(
        run_id="orch-md", session_id="s", status="running",
        created_at=1, plan_json="{}",
    ))
    repo.mark_dispatched("orch-md", 111)
    repo.mark_dispatched("orch-md", 222)
    fetched = repo.get("orch-md")
    assert fetched.dispatched_at == 111


def test_mark_dispatched_missing_run_is_noop(repo):
    """不存在的 run → mark_dispatched 静默跳过（不抛异常）。"""
    repo.mark_dispatched("orch-none", 111)  # 不应抛异常
    assert repo.get("orch-none") is None
