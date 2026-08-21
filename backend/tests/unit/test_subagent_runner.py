"""SubagentRunner + run_lane_with_retry 单元测试。"""

from __future__ import annotations

from unittest.mock import patch

import pytest


class _FakeSageAgent:
    """可编程子 agent：run_loop 产出 DONE；可注入失败次数。"""

    def __init__(self, fail_times: int = 0, content: str = "子任务输出"):
        self.fail_times = fail_times
        self.content = content
        self.calls = 0

    async def run_loop(self, messages, max_iterations=None, llm_config=None):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient failure")
        yield AgentEvent(state=AgentState.DONE, content=self.content)


_DUMMY_PROFILE = {"system_prompt": "你是测试子 agent", "tools": []}


def _make_task(goal: str = "调研 X", scratch: str | None = None):
    from backend.orchestration.models import Task

    params = {"goal": goal}
    if scratch:
        params["scratch_dir"] = scratch
    return Task(task_id="t1", name="T1", description=goal, parameters=params)


@pytest.mark.asyncio()
async def test_runner_returns_succeeded_dict():
    from backend.orchestration.subagent_runner import SubagentRunner

    fake = _FakeSageAgent(content="调研结果")
    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch("backend.orchestration.subagent_runner.SageAgent", return_value=fake):
        result = await SubagentRunner()(_make_task(goal="调研 X"), "researcher")

    assert result == {"status": "succeeded", "output": "调研结果"}
    assert fake.calls == 1


@pytest.mark.asyncio()
async def test_runner_invalid_agent_raises():
    from backend.orchestration.subagent_runner import SubagentRunner

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent", return_value=None
    ), pytest.raises(RuntimeError, match="不存在或已禁用"):
        await SubagentRunner()(_make_task(), "ghost_agent")


@pytest.mark.asyncio()
async def test_run_lane_with_retry_loops_until_terminal():
    from backend.orchestration.models import Lane, LaneStatus
    from backend.orchestration.subagent_runner import run_lane_with_retry

    class _FakeExecutor:
        def __init__(self):
            self.calls = 0

        async def execute_lane(self, lane, agent_id=None):
            self.calls += 1
            if self.calls < 3:
                return {"status": "retrying", "retry_count": self.calls}
            return {"status": "succeeded", "lane_id": "lane-t1", "result": {"output": "ok"}}

    lane = Lane(lane_id="lane-t1", task_id="t1", status=LaneStatus.READY)
    result = await run_lane_with_retry(_FakeExecutor(), lane, "researcher")

    assert result["status"] == "succeeded"
    assert result["result"]["output"] == "ok"


@pytest.mark.asyncio()
async def test_run_lane_with_retry_returns_failed_terminal():
    from backend.orchestration.models import Lane, LaneStatus
    from backend.orchestration.subagent_runner import run_lane_with_retry

    class _FakeExecutor:
        def __init__(self):
            self.calls = 0

        async def execute_lane(self, lane, agent_id=None):
            self.calls += 1
            if self.calls < 3:
                return {"status": "retrying", "retry_count": self.calls}
            return {"status": "failed", "error": "MAX_RETRIES_EXCEEDED"}

    lane = Lane(lane_id="lane-t1", task_id="t1", status=LaneStatus.READY)
    result = await run_lane_with_retry(_FakeExecutor(), lane, "researcher")

    assert result["status"] == "failed"
    assert "MAX_RETRIES_EXCEEDED" in result["error"]


@pytest.mark.asyncio()
async def test_lane_executor_runs_real_subagent_runner():
    """LaneExecutor + SubagentRunner 集成（spec §5.4）：真实 runner 产出
    DONE content → 任务 COMPLETED、lane SUCCEEDED。"""
    from backend.orchestration.executor import LaneExecutor
    from backend.orchestration.lane_registry import LaneRegistry
    from backend.orchestration.models import (
        Lane,
        RecoveryPolicy,
        Task,
        TaskPacket,
    )
    from backend.orchestration.subagent_runner import SubagentRunner
    from backend.orchestration.task_registry import TaskRegistry

    lane_registry = LaneRegistry()
    task_registry = TaskRegistry()
    fake = _FakeSageAgent(content="调研完成")

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch("backend.orchestration.subagent_runner.SageAgent", return_value=fake):
        task_registry.create_task(
            Task(
                task_id="task-it",
                name="集成测试",
                description="go",
                parameters={"goal": "调研 X"},
                packet=TaskPacket(
                    objective="调研 X",
                    recovery_policy=RecoveryPolicy(on_failure="retry", max_retries=2),
                ),
            )
        )
        task_registry.mark_running("task-it")
        lane = Lane(lane_id="lane-it", task_id="task-it", agent_id="researcher")
        lane_registry.create_lane(lane)

        executor = LaneExecutor(
            lane_registry=lane_registry,
            task_registry=task_registry,
            agent_runner=SubagentRunner(),
        )
        result = await executor.execute_lane(lane, "researcher")

    assert result["status"] == "succeeded"
    assert result["result"]["output"] == "调研完成"
    assert lane_registry.get_lane("lane-it").status.value == "succeeded"
    assert task_registry.get_task("task-it").status.value == "completed"
    assert fake.calls == 1


@pytest.mark.asyncio()
async def test_runner_interrupt_event_stops_child():
    """P0-3: interrupt_event 置位 → watcher 调 child.interrupt() → 抛 interrupted。"""
    import asyncio

    from backend.orchestration.subagent_runner import SubagentRunner

    interrupt_seen = asyncio.Event()

    class _FakeInterruptibleAgent:
        def __init__(self):
            self._flag = False

        def interrupt(self):
            self._flag = True
            interrupt_seen.set()

        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            from backend.core.legacy.agent_state import AgentEvent, AgentState

            yield AgentEvent(state=AgentState.THINKING, iteration=0)
            await interrupt_seen.wait()  # 阻塞直到 watcher 调到 interrupt()
            yield AgentEvent(
                state=AgentState.FAILED, iteration=1, error="interrupted by user"
            )

    fake = _FakeInterruptibleAgent()
    event = asyncio.Event()
    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch("backend.orchestration.subagent_runner.SageAgent", return_value=fake):
        runner = SubagentRunner(interrupt_event=event)
        run_task = asyncio.create_task(runner(_make_task(goal="长任务"), "researcher"))
        await asyncio.sleep(0)  # 让 runner 进入 run_loop 并挂起在 wait()
        event.set()
        with pytest.raises(RuntimeError, match="interrupted by user"):
            await run_task


@pytest.mark.asyncio()
async def test_runner_surfaces_last_failed_event_error():
    """P0-3: 子 agent FAILED（非中断）→ RuntimeError 携带事件 error 而非笼统文案。"""
    from backend.orchestration.subagent_runner import SubagentRunner

    class _FakeFailingAgent:
        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            from backend.core.legacy.agent_state import AgentEvent, AgentState

            yield AgentEvent(
                state=AgentState.FAILED, iteration=0, error="max_iterations_exceeded"
            )

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch(
        "backend.orchestration.subagent_runner.SageAgent",
        return_value=_FakeFailingAgent(),
    ), pytest.raises(RuntimeError, match="max_iterations_exceeded"):
        await SubagentRunner()(_make_task(), "researcher")
