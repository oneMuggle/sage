"""Task 9 — 任务层级化端到端：计划 → 派发 → 持久化 → 历史回放。"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.api.orch_routes import _run_detail
from backend.data import database as db_mod
from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.orchestration.plan_hierarchy import normalize_task_hierarchy


def _dispatcher(tmp_path, monkeypatch, plan_tasks):
    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()
    dispatcher = ChatDispatcher(
        stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-e2e"
    )
    dispatcher.init_orch_run(
        session_id="s1",
        plan_json=json.dumps({"tasks": plan_tasks}, ensure_ascii=False),
    )
    return dispatcher


def test_normalize_three_levels():
    normalized = normalize_task_hierarchy(
        [
            {"task_id": "t1", "agent_id": "a", "goal": "root"},
            {
                "task_id": "t2",
                "agent_id": "b",
                "goal": "child",
                "parent_task_id": "t1",
            },
            {
                "task_id": "t3",
                "agent_id": "c",
                "goal": "grand",
                "parent_task_id": "t2",
            },
        ]
    )
    assert [item["depth"] for item in normalized] == [0, 1, 2]


@pytest.mark.asyncio()
async def test_hierarchy_flows_to_dispatch_and_persistence(tmp_path, monkeypatch):
    plan_tasks = [
        {"task_id": "t1", "agent_id": "a", "goal": "root"},
        {
            "task_id": "t2",
            "agent_id": "b",
            "goal": "child",
            "parent_task_id": "t1",
            "depth": 1,
        },
    ]
    dispatcher = _dispatcher(tmp_path, monkeypatch, plan_tasks)

    async def fake_run(state):
        state.status = "done"
        state.output = "ok"
        return "ok"

    dispatcher._run_subagent = fake_run
    await dispatcher.dispatch(
        [{"task_id": "t2", "agent_id": "b", "goal": "child"}]
    )

    # 状态层带层级
    assert dispatcher._states["t2"].parent_task_id == "t1"
    assert dispatcher._states["t2"].depth == 1

    # 持久化层带层级
    stored = dispatcher._orch_task_repo.get("t2")
    assert stored is not None
    assert stored.parent_task_id == "t1"
    assert stored.depth == 1

    # 历史回放带层级
    run = dispatcher._orch_run_repo.get("orch-e2e")
    detail = _run_detail(run)
    t2 = next(t for t in detail.tasks if t["task_id"] == "t2")
    assert t2["parent_task_id"] == "t1"
    assert t2["depth"] == 1


@pytest.mark.asyncio()
async def test_dynamic_task_inherits_hierarchy_and_persists(tmp_path, monkeypatch):
    dispatcher = _dispatcher(
        tmp_path,
        monkeypatch,
        [{"task_id": "t1", "agent_id": "a", "goal": "root"}],
    )

    result = dispatcher.add_task_to_plan(
        task_id="t9",
        goal="child",
        agent_id="b",
        depends_on=[],
        parent_task_id="t1",
    )
    assert result["success"] is True
    assert result["depth"] == 1

    reloaded = json.loads(dispatcher._orch_run_repo.get("orch-e2e").plan_json)
    t9 = next(t for t in reloaded["tasks"] if t["task_id"] == "t9")
    assert t9["parent_task_id"] == "t1"
    assert t9["depth"] == 1

    # 新增任务不能污染执行依赖：计划父级不写 depends_on。
    assert t9["depends_on"] == []
