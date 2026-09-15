"""ChatDispatcher 子任务 wall-clock 超时（O2）单测。

- 超时 → 任务 failed 且 error 含 task_timeout 前缀
- 下游依赖任务级联 failed（复用既有闭包）
- timeout=0 关闭时不包装 wait_for（慢任务正常完成）
"""

from __future__ import annotations

import asyncio

import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.orchestration.orch_settings import OrchSettings
from backend.tests.unit.test_chat_dispatcher import (
    _collect_events,
    _make_queue,
    _patch_subagents,
)
from backend.tests.unit.test_chat_dispatcher_topology import _inject_plan

pytestmark = pytest.mark.unit

_DUMMY_PROFILE = {"system_prompt": "你是测试子 agent", "tools": []}


class _SlowAgent:
    """THINKING 后长眠 —— 模拟卡死的子代理（等 wait_for 取消）。"""

    def __init__(self) -> None:
        self.cancelled = False

    async def run_loop(self, messages, max_iterations=None, llm_config=None):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        yield AgentEvent(state=AgentState.DONE, content="late")


@pytest.mark.asyncio()
async def test_task_timeout_marks_failed():
    """超时任务置 failed，error 带 task_timeout 前缀；协程被真正取消。"""
    queue = _make_queue()
    settings = OrchSettings(subagent_task_timeout_s=0.05, max_retries=0)
    dispatcher = ChatDispatcher(
        stream_id="s1", entry_queue=queue, run_id="orch-timeout", settings=settings,
    )
    slow = _SlowAgent()

    with _patch_subagents(slow):
        aggregated = await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": "慢任务"}]
        )

    assert slow.cancelled is True
    assert "task_timeout" in aggregated
    events = _collect_events(queue, 3)
    assert events[-1]["status"] == "failed"
    assert "task_timeout" in events[-1]["error"]


@pytest.mark.asyncio()
async def test_task_timeout_cascades_to_downstream():
    """t1 超时 → 依赖 t1 的 t2 级联 failed（blocked_by_failed 前缀）。"""
    queue = _make_queue()
    settings = OrchSettings(subagent_task_timeout_s=0.05, max_retries=0)
    dispatcher = ChatDispatcher(
        stream_id="s1", entry_queue=queue, run_id="orch-cascade", settings=settings,
    )
    _inject_plan(
        dispatcher,
        [("t1", "慢任务", "researcher", []),
         ("t2", "下游任务", "writer", ["t1"])],
    )

    with _patch_subagents(_SlowAgent()):
        aggregated = await dispatcher.dispatch(
            [
                {"task_id": "t1", "agent_id": "researcher", "goal": "慢任务"},
                {"task_id": "t2", "agent_id": "writer", "goal": "下游任务"},
            ]
        )

    assert "task_timeout" in aggregated
    assert "blocked_by_failed" in aggregated
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    status_by_task = {}
    for e in events:
        if e.get("state") == "task_status":
            status_by_task[e["task_id"]] = e
    assert status_by_task["t1"]["status"] == "failed"
    assert status_by_task["t2"]["status"] == "failed"
    assert status_by_task["t2"]["error"].startswith("blocked_by_failed:")


@pytest.mark.asyncio()
async def test_task_timeout_disabled_when_zero():
    """timeout=0 → 不包装 wait_for，慢任务跑完正常 done。"""
    queue = _make_queue()
    settings = OrchSettings(subagent_task_timeout_s=0)
    dispatcher = ChatDispatcher(
        stream_id="s1", entry_queue=queue, run_id="orch-nolimit", settings=settings,
    )

    class _BrieflySlowAgent:
        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            yield AgentEvent(state=AgentState.THINKING, iteration=0)
            await asyncio.sleep(0.15)
            yield AgentEvent(state=AgentState.DONE, content="最终完成")

    with _patch_subagents(_BrieflySlowAgent()):
        aggregated = await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": "正常任务"}]
        )

    assert "最终完成" in aggregated
    events = _collect_events(queue, 3)
    assert events[-1]["status"] == "done"
