"""ChatDispatcher depends_on 分波执行 + 级联取消 单测。"""

from __future__ import annotations

import pytest

from backend.orchestration.chat_dispatcher import (
    _CASCADE_ERROR_PREFIX,
    ChatDispatcher,
)
from backend.tests.unit.test_chat_dispatcher import (
    _collect_events,
    _FakeSageAgent,
    _make_queue,
    _patch_subagents,
)

pytestmark = pytest.mark.unit


def _inject_plan(dispatcher, tasks_with_deps):
    """注入计划权威索引（绕过 DB）。tasks_with_deps: [(task_id, goal, agent_id, deps)]"""
    dispatcher._plan_by_id = {
        tid: {
            "task_id": tid,
            "agent_id": aid,
            "goal": goal,
            "depends_on": list(deps),
        }
        for tid, goal, aid, deps in tasks_with_deps
    }
    dispatcher._plan_loaded = True


def _drain_events(queue) -> list[dict]:
    """排空队列取全部事件 —— 事件数由场景决定，写死 n 会因 QueueEmpty 崩。"""
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


@pytest.mark.asyncio()
async def test_dependent_task_starts_after_upstream_done():
    """t2 依赖 t1 → t2 的首个 running 事件必须在 t1 done 之后（分波串行）。"""
    queue = _make_queue()
    fake = _FakeSageAgent(results=["结果一", "结果二"])
    dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-t")
    _inject_plan(
        dispatcher,
        [("t1", "第一步", "researcher", []),
         ("t2", "第二步", "writer", ["t1"])],
    )

    with _patch_subagents(fake):
        aggregated = await dispatcher.dispatch(
            [
                {"task_id": "t1", "agent_id": "researcher", "goal": "第一步"},
                {"task_id": "t2", "agent_id": "writer", "goal": "第二步"},
            ]
        )

    events = _collect_events(queue, 6)  # 2 任务 × queued/running/done
    seq = [(e["task_id"], e["status"]) for e in events]
    assert seq.index(("t1", "done")) < seq.index(("t2", "running")), seq
    assert seq.count(("t2", "done")) == 1
    assert "结果二" in aggregated


@pytest.mark.asyncio()
async def test_same_wave_tasks_still_parallel():
    """同波任务仍并行（max_active ≥ 2）。"""
    queue = _make_queue()
    fake = _FakeSageAgent(results=["ok"] * 3, delay=0.05)
    dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-p")
    _inject_plan(
        dispatcher,
        [
            ("t1", "根", "researcher", []),
            ("t2", "左", "researcher", ["t1"]),
            ("t3", "右", "researcher", ["t1"]),
        ],
    )

    with _patch_subagents(fake):
        await dispatcher.dispatch(
            [
                {"task_id": "t1", "agent_id": "researcher", "goal": "根"},
                {"task_id": "t2", "agent_id": "researcher", "goal": "左"},
                {"task_id": "t3", "agent_id": "researcher", "goal": "右"},
            ]
        )

    assert fake.max_active >= 2  # t2/t3 同波并行


@pytest.mark.asyncio()
async def test_upstream_failure_cascades_without_running_downstream():
    """上游失败 → 下游直接置 failed（error=blocked_by_failed:t1），子代理不跑。"""
    queue = _make_queue()
    fake = _FakeSageAgent(results=["正常结果"], fail_goal="崩溃")
    dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-c")
    # fail_goal 关键词必须落在【上游】t1 的 goal 上 —— 分波后 t2 依赖 t1，
    # t1 失败 → t2 走级联置 failed，子代理根本不派遣（这正是被测路径）。
    _inject_plan(
        dispatcher,
        [("t1", "崩溃任务", "researcher", []),
         ("t2", "正常任务", "writer", ["t1"])],
    )

    with _patch_subagents(fake):
        aggregated = await dispatcher.dispatch(
            [
                {"task_id": "t1", "agent_id": "researcher", "goal": "崩溃任务"},
                {"task_id": "t2", "agent_id": "writer", "goal": "正常任务"},
            ]
        )

    events = _drain_events(queue)
    by_task = {}
    for e in events:
        by_task.setdefault(e["task_id"], []).append(e["status"])

    assert by_task["t2"][-1] == "failed"
    t2_events = [e for e in events if e["task_id"] == "t2"]
    t2_error = next(e["error"] for e in t2_events if e["status"] == "failed")
    assert t2_error.startswith(_CASCADE_ERROR_PREFIX)
    assert "t1" in t2_error
    assert "blocked_by_failed" in aggregated
    # t2 从未进入 running（未派发子代理）
    assert "running" not in by_task["t2"]
    # fail_goal 定向失败只影响 t1 —— t2 根本不该被派遣，
    # calls 全部来自 t1 的重试链（1 首次 + 2 重试）
    assert fake.calls <= 3


@pytest.mark.asyncio()
async def test_cycle_rejected_before_any_dispatch():
    """环依赖 → dispatch 抛 ValueError（含环路径），无任何子代理运行。"""
    queue = _make_queue()
    fake = _FakeSageAgent(results=["x", "x"])
    dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-y")
    _inject_plan(
        dispatcher,
        [("t1", "g", "a", ["t2"]), ("t2", "g", "a", ["t1"])],
    )

    with _patch_subagents(fake), pytest.raises(ValueError, match="环|cycle") as ei:
        await dispatcher.dispatch(
            [
                {"task_id": "t1", "agent_id": "a", "goal": "g"},
                {"task_id": "t2", "agent_id": "a", "goal": "g"},
            ]
        )
    assert "环" in str(ei.value) or "cycle" in str(ei.value)
    assert fake.calls == 0


@pytest.mark.asyncio()
async def test_no_deps_batch_backward_compatible():
    """无依赖批次退化为原全并行行为：queued×N → running×N → done×N。"""
    queue = _make_queue()
    fake = _FakeSageAgent(results=["A", "B"])
    dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-z")

    with _patch_subagents(fake):
        await dispatcher.dispatch(
            [
                {"agent_id": "researcher", "goal": "A 任务"},
                {"agent_id": "researcher", "goal": "B 任务"},
            ]
        )

    events = _collect_events(queue, 6)
    statuses = [e["status"] for e in events]
    assert statuses == ["queued", "queued", "running", "running", "done", "done"]
