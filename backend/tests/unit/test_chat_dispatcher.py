"""ChatDispatcher 单元测试 —— 经 LaneExecutor 执行（P0-1 lane 镜像 + 重试）。

- 并发执行 + task_status 事件顺序 queued→running→done
- 单任务重试耗尽 → failed 错误隔离，其余继续
- 并发上限 4 生效（5 个任务最大并行 ≤4）
- lane 镜像：每子任务在 lane_registry 产生 SUCCEEDED lane
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from backend.orchestration.chat_dispatcher import (
    MAX_CONCURRENT_SUBAGENTS,
    ChatDispatcher,
)

_DUMMY_PROFILE = {"system_prompt": "你是测试子 agent", "tools": []}


class _FakeSageAgent:
    """可编程子 agent：记录并发数 + 可注入失败次数。"""

    def __init__(
        self,
        results=("ok",),
        delay: float = 0.0,
        fail_times: int = 0,
        fail_goal: str | None = None,
    ):
        self.results = list(results)
        self.delay = delay
        self.fail_times = fail_times
        self.fail_goal = fail_goal
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def run_loop(self, messages, max_iterations=None, llm_config=None):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        self.calls += 1
        goal = messages[-1]["content"] if messages else ""
        if (self.fail_goal is not None and self.fail_goal in goal) or (
            self.calls <= self.fail_times
        ):
            raise RuntimeError("transient failure")
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            content = self.results.pop(0) if self.results else "ok"
            yield AgentEvent(state=AgentState.DONE, content=content)
        finally:
            self.active -= 1


def _make_queue():
    return asyncio.Queue()


def _collect_events(queue: asyncio.Queue, n: int) -> list[dict]:
    return [queue.get_nowait() for _ in range(n)]


def _patch_subagents(fake):
    """Enter both subagent patches on an ExitStack so the returned object can be
    used directly as ``with _patch_subagents(fake):``（py3.10 元组不可直接作 CM）。"""
    stack = ExitStack()
    stack.enter_context(
        patch(
            "backend.orchestration.subagent_runner.get_enabled_agent",
            return_value=_DUMMY_PROFILE,
        )
    )
    stack.enter_context(
        patch("backend.orchestration.subagent_runner.SageAgent", return_value=fake)
    )
    return stack


@pytest.mark.asyncio()
async def test_dispatch_parallel_runs_and_pushes_statuses():
    """2 个子任务 → 事件序 queued→running→done 各 2 次，聚合含两子结果。"""
    queue = _make_queue()
    dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
    fake = _FakeSageAgent(results=["研究结果 A", "研究结果 B"])

    with _patch_subagents(fake):
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
    assert all(e["retry_count"] == 0 for e in events)

    assert "研究结果 A" in aggregated
    assert "研究结果 B" in aggregated
    assert fake.max_active <= 2


@pytest.mark.asyncio()
async def test_dispatch_retry_exhausted_isolated():
    """子任务 2 恒失败 → 重试 2 次后 failed + 错误进聚合，子任务 1 正常 done。"""
    queue = _make_queue()
    # brief 原用 fail_times=999（共享 fake 全局计数）——两个子任务并发共享同一
    # 计数器，999 会让 t1 也耗尽重试而 failed，无法验证"错误隔离"。改为按 goal
    # 定向失败：仅"崩溃任务"恒失败，其余子任务正常完成（assertions 不变）。
    fake = _FakeSageAgent(results=["正常结果", "失败结果"], fail_goal="崩溃")

    with _patch_subagents(fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        aggregated = await dispatcher.dispatch(
            [
                {"agent_id": "researcher", "goal": "正常任务"},
                {"agent_id": "researcher", "goal": "崩溃任务"},
            ]
        )

    events = _collect_events(queue, 6)
    done = {e["task_id"] for e in events if e["status"] == "done"}
    failed = {e["task_id"] for e in events if e["status"] == "failed"}
    assert done == {"t1"}
    assert failed == {"t2"}
    assert "正常结果" in aggregated
    assert "MAX_RETRIES_EXCEEDED" in aggregated or "transient failure" in aggregated
    assert fake.calls >= 3  # t2: 首次 + retry_count=1 + retry_count=2


@pytest.mark.asyncio()
async def test_dispatch_concurrency_capped_at_four():
    """5 个任务，并发上限 4 —— 最大同时 active ≤ 4。"""
    queue = _make_queue()
    fake = _FakeSageAgent(results=["ok"] * 5, delay=0.01)

    with _patch_subagents(fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": f"任务{i}"} for i in range(5)]
        )

    assert fake.max_active <= MAX_CONCURRENT_SUBAGENTS


@pytest.mark.asyncio()
async def test_dispatch_lane_mirrored_with_retry_count():
    """lane 镜像：子任务 lane 落库且 SUCCEEDED；重试后 retry_count 进事件。"""
    from backend.orchestration.lane_registry import LaneRegistry
    from backend.orchestration.task_registry import TaskRegistry

    queue = _make_queue()
    lane_registry = LaneRegistry()
    task_registry = TaskRegistry()
    fake = _FakeSageAgent(results=["最终成功"], fail_times=1)

    with _patch_subagents(fake):
        dispatcher = ChatDispatcher(
            stream_id="s1",
            entry_queue=queue,
            run_id="orch-retry",
            lane_registry=lane_registry,
            task_registry=task_registry,
        )
        aggregated = await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": "一次失败后成功"}]
        )

    events = _collect_events(queue, 3)
    assert events[-1]["status"] == "done"
    assert events[-1]["retry_count"] == 1  # fail 1 次 → 重试 1 次

    lane = lane_registry.get_lane("lane-t1")
    assert lane is not None
    assert lane.status.value == "succeeded"
    assert lane.metadata["retry_count"] == 1
    assert lane.metadata["task_id"] == "t1"
    assert "最终成功" in aggregated
