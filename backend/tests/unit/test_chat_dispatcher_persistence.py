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
