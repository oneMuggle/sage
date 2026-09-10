"""RT9/RT10/RT11 (round7) — 失败恢复韧性测试。

- RT9: executor 重试时写 task.parameters["retry_hint"]；SubagentRunner
  把 hint 前置进子代理 prompt（盲重试 → 带失败上下文重试）。
- RT10: run_lane_with_retry 消费 retry_backoff_secs（此前字段无消费者）。
- RT11: refine_plan / get_plan_status 死桩已删除。
"""

from __future__ import annotations

import contextlib
from unittest.mock import patch

import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.orchestration.models import RecoveryPolicy, Task, TaskPacket

pytestmark = pytest.mark.unit

_DUMMY_PROFILE = {"system_prompt": "你是测试子 agent", "tools": []}


@pytest.fixture()
def temp_db():
    """临时 SQLite 库（与 test_orchestration_executor.py 同款）。"""
    import os
    import tempfile

    from backend.data.database import Database

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    db = Database(db_path=tmp_path)
    db.init_db()
    yield db, tmp_path
    with_close = getattr(db, "close", None)
    if callable(with_close):
        with contextlib.suppress(Exception):
            with_close()
    os.unlink(tmp_path)


# ---- RT9: SubagentRunner 消费 retry_hint -------------------------------------


def _make_task(goal: str = "调研 X", **extra_params) -> Task:
    return Task(
        task_id="task-t1",
        name="T1",
        description=goal,
        parameters={"goal": goal, **extra_params},
    )


@pytest.mark.asyncio()
async def test_runner_prepends_retry_hint_to_goal():
    """带 retry_hint 的任务 → user 消息前置失败说明 + 原 goal 保留。"""
    from backend.orchestration.subagent_runner import SubagentRunner

    task = _make_task(
        goal="调研 X",
        retry_hint={"attempt": 2, "last_error": "依赖文件缺失"},
    )
    captured = {}

    class _CaptureAgent:
        def __init__(self, agent_id=None, policy=None):
            pass

        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            captured["user_contents"] = [
                m["content"] for m in messages if m["role"] == "user"
            ]
            yield AgentEvent(state=AgentState.DONE, content="done")

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch("backend.orchestration.subagent_runner.SageAgent", _CaptureAgent):
        runner = SubagentRunner()
        await runner(task, "t3")

    content = captured["user_contents"][-1]
    assert "【重试 · 第 2 次】" in content
    assert "依赖文件缺失" in content
    assert content.endswith("调研 X")


@pytest.mark.asyncio()
async def test_runner_without_retry_hint_keeps_prompt_unchanged():
    """首次执行（无 retry_hint 键）→ prompt 与旧版逐字一致。"""
    from backend.orchestration.subagent_runner import SubagentRunner

    task = _make_task(goal="调研 X")
    captured = {}

    class _CaptureAgent:
        def __init__(self, agent_id=None, policy=None):
            pass

        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            captured["user_contents"] = [
                m["content"] for m in messages if m["role"] == "user"
            ]
            yield AgentEvent(state=AgentState.DONE, content="done")

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch("backend.orchestration.subagent_runner.SageAgent", _CaptureAgent):
        runner = SubagentRunner()
        await runner(task, "t3")

    assert captured["user_contents"] == ["调研 X"]


@pytest.mark.asyncio()
async def test_executor_writes_retry_hint_on_lane_retry(temp_db):
    """lane 首败重试 → task.parameters["retry_hint"] 带 attempt/last_error。"""

    from backend.data.orchestration_repo import (
        LaneEventRepository,
        LaneRepository,
        TaskRepository,
    )
    from backend.orchestration.events import EventRecorder
    from backend.orchestration.executor import LaneExecutor
    from backend.orchestration.lane_registry import LaneRegistry
    from backend.orchestration.task_registry import TaskRegistry

    db, _ = temp_db
    lane_repo = LaneRepository()
    lane_repo.db = db
    task_repo = TaskRepository()
    task_repo.db = db
    event_repo = LaneEventRepository()
    event_repo.db = db
    registries = {
        "lane_registry": LaneRegistry(repo=lane_repo),
        "task_registry": TaskRegistry(repo=task_repo),
        "event_recorder": EventRecorder(repo=event_repo),
    }

    packet_policy = RecoveryPolicy(on_failure="retry", max_retries=2)
    task = Task(
        task_id="task-rh-1",
        name="rh",
        description="rh",
        parameters={"goal": "做点事"},
        packet=TaskPacket(objective="做点事", recovery_policy=packet_policy),
    )
    registries["task_repo"] = task_repo
    registries["task_registry"].create_task(task)
    lane = registries["lane_registry"].create_lane(task_id=task.task_id)

    seen_hints = []

    async def flaky_runner(t, agent_id):
        seen_hints.append(t.parameters.get("retry_hint"))
        if len(seen_hints) < 2:
            raise ValueError("transient boom")
        return {"output": "recovered"}

    executor = LaneExecutor(
        lane_registry=registries["lane_registry"],
        task_registry=registries["task_registry"],
        event_recorder=registries["event_recorder"],
        agent_runner=flaky_runner,
    )

    # 首次执行失败 → retrying；再调 execute_lane 触发重试（调度器模型）
    result1 = await executor.execute_lane(lane, "t3")
    assert result1.get("status") == "retrying"
    result = await executor.execute_lane(lane, "t3")
    assert result.get("status") == "succeeded"
    assert seen_hints[0] is None  # 首次执行无 hint
    assert seen_hints[1] == {"attempt": 1, "last_error": "transient boom"}


# ---- RT10: backoff 消费 -------------------------------------------------------


class _RetryThenSucceedExecutor:
    def __init__(self):
        self.calls = 0

    async def execute_lane(self, lane, agent_id):
        self.calls += 1
        if self.calls == 1:
            return {"status": "retrying", "retry_count": 1}
        if self.calls == 2:
            return {"status": "retrying", "retry_count": 2}
        return {"status": "succeeded", "result": {"output": "ok"}}


class _SimpleLane:
    lane_id = "lane-x"


@pytest.mark.asyncio()
async def test_run_lane_with_retry_honors_backoff(monkeypatch):
    from backend.orchestration import subagent_runner as sr

    sleeps = []

    async def _fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(sr.asyncio, "sleep", _fake_sleep)
    executor = _RetryThenSucceedExecutor()
    result = await sr.run_lane_with_retry(
        executor, _SimpleLane(), "t3", backoff_secs=[5, 15, 30]
    )

    assert result["status"] == "succeeded"
    assert sleeps == [5, 15]  # 索引按 retry_count-1


@pytest.mark.asyncio()
async def test_run_lane_with_retry_without_backoff_no_sleep(monkeypatch):
    from backend.orchestration import subagent_runner as sr

    sleeps = []

    async def _fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(sr.asyncio, "sleep", _fake_sleep)
    executor = _RetryThenSucceedExecutor()
    result = await sr.run_lane_with_retry(executor, _SimpleLane(), "t3")

    assert result["status"] == "succeeded"
    assert sleeps == []


def test_recovery_policy_default_backoff_is_interactive_friendly():
    """默认退避 [5,15,30]（原占位 [30,120,600] 无消费者的历史遗留）。"""
    assert RecoveryPolicy().retry_backoff_secs == [5, 15, 30]


# ---- RT11: 死桩删除 -----------------------------------------------------------


def test_planner_dead_stubs_removed():
    """refine_plan / get_plan_status 死桩（零调用方）已删除，防误用。"""
    from backend.orchestration.planner import Planner

    assert not hasattr(Planner, "refine_plan")
    assert not hasattr(Planner, "get_plan_status")


def test_run_lane_accepts_backoff_penetrates_mock_patch_wrapper():
    """mock.patch(side_effect=三参fake) 包装下必须穿透探测——MagicMock 的
    signature 恒为 (*args, **kwargs)，直接探测会误判（CI 实证）。"""
    from unittest.mock import patch

    from backend.orchestration.subagent_runner import (
        run_lane_accepts_backoff,
        run_lane_with_retry,
    )

    # 原生实现：接受
    assert run_lane_accepts_backoff(run_lane_with_retry) is True

    def fake_three_arg(executor, lane, agent_id):
        return {}

    with patch(
        "backend.orchestration.chat_dispatcher.run_lane_with_retry",
        side_effect=fake_three_arg,
    ) as patched:
        import backend.orchestration.chat_dispatcher as cd

        assert run_lane_accepts_backoff(patched) is False
        assert run_lane_accepts_backoff(cd.run_lane_with_retry) is False

    # side_effect 为不可调用（返回值列表）→ 按原对象探测（Mock 吞任意 kwarg）
    with patch(
        "backend.orchestration.chat_dispatcher.run_lane_with_retry",
        side_effect=[{"status": "retrying"}],
    ) as patched_list:
        assert run_lane_accepts_backoff(patched_list) is True
