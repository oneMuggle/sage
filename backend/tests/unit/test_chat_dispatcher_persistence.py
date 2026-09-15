"""Wave 2 P1-4 — ChatDispatcher 状态迁移同步写库 + 写失败降级。

Plan Step 5:每次 _emit_task_status 末尾同步写库;写库抛异常 → logger.warning
降级,绝不阻塞聊天进度推送;init_orch_run 落库一行 orch_runs。
"""
from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import MagicMock

import pytest

from backend.data import database as db_mod


@pytest.mark.asyncio()
async def test_emit_task_status_persists_to_repo():
    """每次 _emit_task_status 末尾都调一次 _persist_task_state。"""
    from backend.orchestration.chat_dispatcher import ChatDispatcher, ChatTaskState

    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="orch-test",
    )
    mock_repo = MagicMock()
    dispatcher._orch_task_repo = mock_repo
    state = ChatTaskState(task_id="t1", agent_id="primary", goal="g", status="queued")
    dispatcher._emit_task_status(state)
    assert mock_repo.upsert_state.called
    assert mock_repo.upsert_state.call_args.kwargs["task_id"] == "t1"


@pytest.mark.asyncio()
async def test_persist_failure_does_not_block_emit():
    """写库抛异常 → logger.warning,不应 raise。"""
    from backend.orchestration.chat_dispatcher import ChatDispatcher, ChatTaskState

    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="orch-test",
    )
    mock_repo = MagicMock()
    mock_repo.upsert_state.side_effect = sqlite3.OperationalError("disk full")
    dispatcher._orch_task_repo = mock_repo
    state = ChatTaskState(task_id="t1", agent_id="primary", goal="g", status="queued")
    # 不应抛
    dispatcher._emit_task_status(state)


def test_init_orch_run_creates_db_row(tmp_path, monkeypatch):
    """init_orch_run 成功 → orch_runs 表有一行。"""
    from backend.orchestration.chat_dispatcher import ChatDispatcher

    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()

    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="orch-test",
    )
    dispatcher.init_orch_run(session_id="s-1", plan_json='{"tasks":[],"reasoning":""}')
    fetched = dispatcher._orch_run_repo.get("orch-test")
    assert fetched is not None
    assert fetched.session_id == "s-1"


def test_mark_run_dispatched_persists_dispatched_at(tmp_path, monkeypatch):
    """_mark_run_dispatched → orch_runs.dispatched_at 落库,二次调用不覆盖。"""
    from backend.orchestration.chat_dispatcher import ChatDispatcher

    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()

    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="orch-test",
    )
    dispatcher.init_orch_run(session_id="s-1", plan_json='{"tasks":[],"reasoning":""}')
    dispatcher._mark_run_dispatched(111)
    dispatcher._mark_run_dispatched(222)
    fetched = dispatcher._orch_run_repo.get("orch-test")
    assert fetched is not None
    assert fetched.dispatched_at == 111  # first-dispatch-wins


def test_mark_run_dispatched_failure_degrades():
    """落库抛异常 → 静默降级（不 raise）,保持降级铁律。"""
    from unittest.mock import MagicMock

    from backend.orchestration.chat_dispatcher import ChatDispatcher

    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="orch-test",
    )
    mock_repo = MagicMock()
    mock_repo.mark_dispatched.side_effect = sqlite3.OperationalError("disk full")
    dispatcher._orch_run_repo = mock_repo
    # 不应抛
    dispatcher._mark_run_dispatched(111)


@pytest.mark.asyncio()
async def test_dispatch_first_call_persists_dispatched_at(tmp_path, monkeypatch):
    """dispatch 首次调用 → _mark_run_dispatched 把 dispatched_at 落库。"""
    from backend.orchestration.chat_dispatcher import ChatDispatcher

    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()

    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="orch-test",
    )
    dispatcher.init_orch_run(session_id="s-1", plan_json='{"tasks":[],"reasoning":""}')

    async def fake_run_subagent(state):
        return "ok"

    dispatcher._run_subagent = fake_run_subagent
    # total_tasks=2 → 单次 dispatch 后 _next_task_index=1 < 2,跳过 review 分支
    dispatcher.total_tasks = 2
    await dispatcher.dispatch([{"agent_id": "primary", "goal": "g"}])
    fetched = dispatcher._orch_run_repo.get("orch-test")
    assert fetched is not None
    assert fetched.dispatched_at is not None


# Wave 3 A9 — original_request 列 + update_status（resume 恢复流原始请求）。
def test_init_orch_run_persists_original_request(tmp_path, monkeypatch):
    from backend.orchestration.chat_dispatcher import ChatDispatcher

    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()

    dispatcher = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-test")
    dispatcher.init_orch_run(
        session_id="s-1",
        plan_json='{"tasks":[],"reasoning":""}',
        original_request="帮我写一份报告",
    )
    fetched = dispatcher._orch_run_repo.get("orch-test")
    assert fetched is not None
    assert fetched.original_request == "帮我写一份报告"


def test_update_status_changes_status_only(tmp_path, monkeypatch):
    """update_status 改 status，不清 final_summary。"""
    from backend.data.orch_run_repo import OrchRun, OrchRunRepository

    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()

    repo = OrchRunRepository()
    repo.upsert(OrchRun(run_id="r1", session_id="s1", status="running", created_at=1, plan_json="{}"))
    repo.finalize("r1", "completed", "summary")
    repo.update_status("r1", "cancelled")
    fetched = repo.get("r1")
    assert fetched.status == "cancelled"
    assert fetched.final_summary == "summary"


def test_old_db_migrates_original_request_column(tmp_path, monkeypatch):
    """既有库缺列 → ALTER TABLE 幂等补列。"""
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE orch_runs (run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'running', created_at INTEGER NOT NULL, "
        "plan_json TEXT NOT NULL, final_summary TEXT, dispatched_at INTEGER)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()

    from backend.data.orch_run_repo import OrchRun, OrchRunRepository

    repo = OrchRunRepository()
    repo.upsert(OrchRun(run_id="r1", session_id="s1", status="running", created_at=1, plan_json="{}"))
    fetched = repo.get("r1")
    assert fetched is not None
