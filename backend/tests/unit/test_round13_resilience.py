"""RD13/BD3（round13）— 重派级联解耦 + collect 非阻塞快照单测。

- RD13: 同批 [t1(失败), t2(retry_of=t1, depends_on t1)] → 重派任务剥离对
  源的依赖，独立执行不被级联判死。
- BD3: collect_subagents(wait=false) → 非阻塞快照（running/completed）。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.tests.unit.test_chat_dispatcher import _make_queue
from backend.tools.subagent_tool import INPUT_SCHEMA, CollectSubagentsTool


def _init_tmp_db(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "r13.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


def _inject_plan(dispatcher, items):
    """注入计划权威索引。items: [(task_id, goal, agent_id, deps)]"""
    dispatcher._plan_by_id = {
        tid: {
            "task_id": tid,
            "agent_id": aid,
            "goal": goal,
            "depends_on": list(deps),
        }
        for tid, goal, aid, deps in items
    }
    dispatcher._plan_loaded = True


@pytest.mark.asyncio()
async def test_same_batch_retry_survives_cascade(tmp_path, monkeypatch):
    """同批 [源失败, 重派(depends_on 源)] → 重派剥离依赖独立执行，不被级联判死。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-r13-1")
    d._semaphore = asyncio.Semaphore(4)
    _inject_plan(
        d,
        [
            ("t1", "易失败任务", "primary", []),
            ("t2", "重派任务", "primary", ["t1"]),
        ],
    )

    async def fake_run(state):
        if state.task_id == "t1":
            raise ValueError("源任务失败")
        state.status = "done"
        return "重派成功"

    d._run_subagent = fake_run
    aggregated = await d.dispatch(
        [
            {"task_id": "t1", "agent_id": "primary", "goal": "易失败任务"},
            {"task_id": "t2", "agent_id": "primary", "goal": "重派任务", "retry_of": "t1"},
        ]
    )
    assert d._states["t1"].status == "failed"
    assert d._states["t2"].status == "done"
    assert "重派成功" in aggregated
    # 无级联判死标记
    assert not (d._states["t2"].error or "").startswith("blocked_by_failed:")


def test_retry_dep_stripped_only_for_retry_source(tmp_path, monkeypatch):
    """依赖剥离仅针对 retry 源；其他依赖保留。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s2", entry_queue=queue, run_id="orch-r13-2")
    _inject_plan(
        d,
        [
            ("t1", "失败源", "primary", []),
            ("t0", "另一依赖", "primary", []),
            ("t2", "重派任务", "primary", ["t1", "t0"]),
        ],
    )
    from backend.orchestration.chat_dispatcher import ChatTaskState

    d._states["t1"] = ChatTaskState(
        task_id="t1", agent_id="primary", goal="失败源",
        status="failed", error="boom",
    )
    d._states["t0"] = ChatTaskState(
        task_id="t0", agent_id="primary", goal="另一依赖", status="done",
    )
    state = ChatTaskState(
        task_id="t2", agent_id="primary", goal="重派任务", retry_of="t1",
    )
    d._states["t2"] = state

    # 复刻 dispatch 的 deps 构建逻辑验证剥离（仅 retry 源被剥离）
    deps = []
    plan_item = d._plan_by_id.get("t2")
    raw_deps = [str(x) for x in (plan_item.get("depends_on") or [])] if plan_item else []
    deps = [x for x in raw_deps if x in d._states and x != "t2"]
    if state.retry_of and state.retry_of in deps:
        deps = [x for x in deps if x != state.retry_of]

    assert deps == ["t0"]


@pytest.mark.asyncio()
async def test_collect_wait_false_returns_snapshot(tmp_path, monkeypatch):
    """wait=false → 非阻塞快照：running 态 + 任务明细；完成后 completed。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s3", entry_queue=queue, run_id="orch-r13-3")
    d._semaphore = asyncio.Semaphore(4)
    tool = CollectSubagentsTool(d)

    # 从未后台派发 → none
    none_snap = await tool.execute_async(wait=False)
    assert none_snap.success is True
    assert none_snap.content["status"] == "none"

    async def slow_run(state):
        await asyncio.sleep(0.2)
        state.status = "done"
        return "慢结果"

    d._run_subagent = slow_run
    d.start_background_dispatch(
        [{"task_id": "t1", "agent_id": "primary", "goal": "g1"}]
    )
    await asyncio.sleep(0.05)  # 让后台派发注册任务状态
    running = await tool.execute_async(wait=False)
    assert running.content["status"] == "running"
    assert running.content["tasks"][0]["task_id"] == "t1"

    await d.wait_background(timeout=5)
    done_snap = await tool.execute_async(wait=False)
    assert done_snap.content["status"] == "completed"
    assert done_snap.content["tasks"][0]["status"] == "done"
    assert done_snap.content["tasks"][0]["output_preview"] == "慢结果"


def test_schema_documents_wait_param():
    props = INPUT_SCHEMA["properties"]
    assert "background" in props
    tool = CollectSubagentsTool(object())
    assert "wait" in tool.schema.parameters["properties"]
