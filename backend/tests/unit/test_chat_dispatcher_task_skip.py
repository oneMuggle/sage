"""ChatDispatcher 单任务跳过（B3, 2026-09-09）单测。

- queued 任务跳过 → acquire 后短路 cancelled（"skipped by user"）
- running 任务跳过 → interrupt 事件置位（软中断通道），终态 cancelled
- 终态/未知任务 → cancel_task 返回 False
- 跳过的任务 → 下游依赖级联 failed（复用既有闭包）
"""

from __future__ import annotations

import asyncio

import pytest

from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.tests.unit.test_chat_dispatcher import (
    _collect_events,
    _make_queue,
)
from backend.tests.unit.test_chat_dispatcher_topology import _inject_plan


def _init_tmp_db(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "skip.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


def _drain(queue):
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


@pytest.mark.asyncio()
async def test_skip_queued_task_short_circuits(tmp_path, monkeypatch):
    """queued 任务跳过 → 不执行、状态 cancelled、error=skipped by user。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-skip-q")
    d._semaphore = asyncio.Semaphore(1)
    started = asyncio.Event()
    ran = []

    async def fake_run(state):
        ran.append(state.task_id)
        started.set()
        # t1 占住槽期间,用户跳过排队中的 t2
        if state.task_id == "t1":
            await asyncio.sleep(0.05)
            assert d.cancel_task("t2") is True
            await asyncio.sleep(0.05)
        state.status = "done"
        state.output = "ok"

    d._run_subagent = fake_run
    await d.dispatch(
        [
            {"task_id": "t1", "agent_id": "r", "goal": "g1"},
            {"task_id": "t2", "agent_id": "r", "goal": "g2"},
        ]
    )
    assert ran == ["t1"]  # t2 从未执行
    assert d._states["t2"].status == "cancelled"
    assert d._states["t2"].error == "skipped by user"


@pytest.mark.asyncio()
async def test_skip_running_task_interrupts(tmp_path, monkeypatch):
    """running 任务跳过 → 该任务事件置位（软中断通道），run 级取消不受影响。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-skip-r")

    seen = {}

    async def fake_run(state):
        merged = d._task_cancel_events.get(state.task_id)
        seen[state.task_id] = merged
        if state.task_id == "t1":
            # runner 已拿到 merged 事件档案后,用户跳过 t1
            await asyncio.sleep(0.02)
            assert d.cancel_task("t1") is True
            await asyncio.wait_for(merged.wait(), timeout=1)
            # 真实路径：SubagentRunner 中断后 raise RuntimeError
            raise RuntimeError("subtask interrupted by user")
        state.status = "done"
        state.output = "ok"

    d._run_subagent = fake_run
    await d.dispatch(
        [
            {"task_id": "t1", "agent_id": "r", "goal": "g1"},
            {"task_id": "t2", "agent_id": "r", "goal": "g2"},
        ]
    )
    # merged 置位（软中断通道收到信号），run 级取消未置位
    assert seen["t1"] is not None and seen["t1"].is_set()
    assert d._cancelled.is_set() is False
    assert d._states["t1"].status == "cancelled"
    assert d._states["t2"].status == "done"  # 其余任务不受影响


@pytest.mark.asyncio()
async def test_cancel_task_terminal_or_unknown_returns_false(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-x")
    # 未知任务 / 无事件档案
    assert d.cancel_task("t-ghost") is False

    async def fake_run(state):
        state.status = "done"
        state.output = "ok"

    d._run_subagent = fake_run
    await d.dispatch([{"task_id": "t1", "agent_id": "r", "goal": "g"}])
    # 已终态
    assert d.cancel_task("t1") is False


@pytest.mark.asyncio()
async def test_skip_cascades_to_downstream(tmp_path, monkeypatch):
    """跳过 t1 → 依赖 t1 的 t2 级联 failed（blocked_by_failed 前缀）。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-skip-c")
    _inject_plan(
        d,
        [("t1", "上游", "researcher", []), ("t2", "下游", "writer", ["t1"])],
    )

    async def fake_run(state):
        if state.task_id == "t1":
            await asyncio.sleep(0.02)
            d.cancel_task("t1")
            await asyncio.sleep(0.05)
            raise RuntimeError("subtask interrupted by user")
        state.status = "done"
        state.output = "ok"

    d._run_subagent = fake_run
    await d.dispatch(
        [
            {"task_id": "t1", "agent_id": "researcher", "goal": "上游"},
            {"task_id": "t2", "agent_id": "writer", "goal": "下游"},
        ]
    )
    events = _drain(queue)
    status_by_task = {
        e["task_id"]: e for e in events if e.get("state") == "task_status"
    }
    assert status_by_task["t1"]["status"] == "cancelled"
    assert status_by_task["t2"]["status"] == "failed"
    assert status_by_task["t2"]["error"].startswith("blocked_by_failed:")
