"""ChatDispatcher 单元测试 —— 轻量子 agent 调度器。

- 并发执行 + task_status 事件顺序 queued→running→done
- 单任务失败错误隔离，其余继续
- 并发上限 4 生效（5 个任务最大并行 ≤4）
- 单子结果截断 50KB
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from backend.orchestration.chat_dispatcher import (
    MAX_CONCURRENT_SUBAGENTS,
    MAX_SUBAGENT_RESULT_CHARS,
    ChatDispatcher,
)


class _FakeSageAgent:
    """可编程子 agent：记录并发数 + 每次调用注入延迟。"""

    def __init__(self, results, delay: float = 0.0):
        self.results = list(results)
        self.delay = delay
        self.active = 0
        self.max_active = 0

    async def run_loop(self, messages, max_iterations=None, llm_config=None):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            content = self.results.pop(0) if self.results else "ok"
            yield self._event("DONE", content)
        finally:
            self.active -= 1

    @staticmethod
    def _event(state: str, content: str):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        return AgentEvent(state=AgentState.DONE, content=content)


def _make_queue():
    return asyncio.Queue()


def _collect_events(queue: asyncio.Queue, n: int) -> list[dict]:
    return [queue.get_nowait() for _ in range(n)]


@pytest.mark.asyncio()
async def test_dispatch_parallel_runs_and_pushes_statuses():
    """2 个子任务 → 事件序 queued→running→done 各 2 次，聚合含两子结果。"""
    queue = _make_queue()
    dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
    fake = _FakeSageAgent(results=["研究结果 A", "研究结果 B"])

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=fake):
        aggregated = await dispatcher.dispatch(
            [
                {"agent_id": "researcher", "goal": "搜集资料 A"},
                {"agent_id": "researcher", "goal": "搜集资料 B"},
            ]
        )

    events = _collect_events(queue, 6)
    statuses = [e["status"] for e in events]
    assert statuses == ["queued", "queued", "running", "running", "done", "done"]
    assert {e["state"] for e in events} == {"task_status"}
    assert all(e["run_id"] == "orch-test" for e in events)
    assert [e["task_id"] for e in events] == ["t1", "t2", "t1", "t2", "t1", "t2"]

    assert "研究结果 A" in aggregated
    assert "研究结果 B" in aggregated
    assert fake.max_active <= 2


@pytest.mark.asyncio()
async def test_dispatch_single_failure_isolated():
    """子任务 2 抛异常 → failed + 错误进聚合，子任务 1 正常 done，不整体崩溃。"""
    queue = _make_queue()

    class _FailSecond:
        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            from backend.core.legacy.agent_state import AgentEvent, AgentState

            goal = messages[-1]["content"]
            if "崩溃" in goal:
                raise RuntimeError("调研网络失败")
            yield AgentEvent(state=AgentState.DONE, content="正常结果")

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=_FailSecond()):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        aggregated = await dispatcher.dispatch(
            [
                {"agent_id": "researcher", "goal": "正常任务"},
                {"agent_id": "researcher", "goal": "这个会崩溃"},
            ]
        )

    events = _collect_events(queue, 6)
    done = {e["task_id"] for e in events if e["status"] == "done"}
    failed = {e["task_id"] for e in events if e["status"] == "failed"}
    assert done == {"t1"}
    assert failed == {"t2"}
    assert "正常结果" in aggregated
    assert "调研网络失败" in aggregated


@pytest.mark.asyncio()
async def test_dispatch_concurrency_capped_at_four():
    """5 个任务，并发上限 4 —— 最大同时 active ≤ 4。"""
    queue = _make_queue()
    fake = _FakeSageAgent(results=["r"] * 5, delay=0.02)

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        await dispatcher.dispatch([{"agent_id": "researcher", "goal": f"g{i}"} for i in range(5)])

    assert fake.max_active == MAX_CONCURRENT_SUBAGENTS


@pytest.mark.asyncio()
async def test_dispatch_truncates_results_to_50kb():
    """单子结果超长 → 聚合截断到 MAX_SUBAGENT_RESULT_CHARS。"""
    queue = _make_queue()
    big = "x" * (MAX_SUBAGENT_RESULT_CHARS + 10_000)
    fake = _FakeSageAgent(results=[big])

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        aggregated = await dispatcher.dispatch([{"agent_id": "researcher", "goal": "g"}])

    body = aggregated.split("## 子任务 t1")[-1]
    assert len(body) <= MAX_SUBAGENT_RESULT_CHARS + 100
    assert "xxxxx" in body


@pytest.mark.asyncio()
async def test_dispatch_no_done_content_raises():
    """子 agent 未产出 DONE content → 该任务 failed，其余继续。"""
    queue = _make_queue()

    class _NoOutput:
        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            from backend.core.legacy.agent_state import AgentEvent, AgentState

            yield AgentEvent(state=AgentState.THINKING, iteration=0)
            yield AgentEvent(state=AgentState.DONE, iteration=0, content=None)

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=_NoOutput()):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        aggregated = await dispatcher.dispatch([{"agent_id": "researcher", "goal": "g"}])

    events = _collect_events(queue, 3)
    assert events[-1]["status"] == "failed"
    assert "未产出 DONE content" in aggregated


@pytest.mark.asyncio()
async def test_dispatch_task_ids_are_t_indexed():
    """dispatch 按传入顺序编号 t1/t2/t3 —— 与 producer task_plan 契约一致。"""
    queue = _make_queue()
    fake = _FakeSageAgent(results=["a", "b", "c"])

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": f"g{i}"} for i in range(3)]
        )

    events = _collect_events(queue, 9)
    assert {e["task_id"] for e in events} == {"t1", "t2", "t3"}


@pytest.mark.asyncio()
async def test_dispatch_unknown_agent_fails_fast():
    """agent_id 不存在/禁用 → 快速失败（spec §5.1），不构造无身份 child。"""
    queue = _make_queue()

    class _ShouldNotRun:
        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            raise AssertionError("未知 agent 不应被构造")

    with patch(
        "backend.agents.profiles.get_enabled_agent", return_value=None
    ), patch(
        "backend.orchestration.chat_dispatcher.SageAgent",
        return_value=_ShouldNotRun(),
    ):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        aggregated = await dispatcher.dispatch(
            [{"agent_id": "ghost_agent", "goal": "g"}]
        )

    events = _collect_events(queue, 3)
    assert events[0]["status"] == "queued"
    assert events[-1]["status"] == "failed"
    assert "ghost_agent" in aggregated
    # 修复前：child 被构造、run_loop 抛 AssertionError → 错误信息不符 → 本断言 RED
    assert "不存在或已禁用" in aggregated