from __future__ import annotations

import asyncio
import json

import pytest

from backend.data import database as db_mod
from backend.orchestration.chat_dispatcher import ChatDispatcher, ChatTaskState


def make_dispatcher(tmp_path, monkeypatch, plan_json: str) -> ChatDispatcher:
    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()
    dispatcher = ChatDispatcher(
        stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-test"
    )
    dispatcher.init_orch_run(session_id="s1", plan_json=plan_json)
    return dispatcher


@pytest.mark.asyncio
async def test_dispatch_creates_plan_parent_state(tmp_path, monkeypatch):
    plan = json.dumps(
        {
            "tasks": [
                {"task_id": "t1", "agent_id": "a", "goal": "root"},
                {
                    "task_id": "t2",
                    "agent_id": "b",
                    "goal": "child",
                    "parent_task_id": "t1",
                    "depth": 1,
                },
            ]
        }
    )
    dispatcher = make_dispatcher(tmp_path, monkeypatch, plan)

    async def fake_run(state):
        state.status = "done"
        state.output = "ok"
        return "ok"

    dispatcher._run_subagent = fake_run
    await dispatcher.dispatch([{"task_id": "t2", "agent_id": "x", "goal": "ignored"}])

    state = dispatcher._states["t2"]
    assert state.parent_task_id == "t1"
    assert state.depth == 1


def test_task_status_emits_hierarchy_fields(tmp_path, monkeypatch):
    dispatcher = make_dispatcher(tmp_path, monkeypatch, '{"tasks":[]}')
    events = []
    dispatcher.entry_queue.put_nowait = events.append
    state = ChatTaskState(
        task_id="t2",
        agent_id="b",
        goal="child",
        parent_task_id="t1",
        depth=1,
    )

    dispatcher._emit_task_status(state)

    assert events[0]["parent_task_id"] == "t1"
    assert events[0]["depth"] == 1
