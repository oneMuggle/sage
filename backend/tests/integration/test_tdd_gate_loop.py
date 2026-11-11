"""TDD 门控循环集成测试。

验证 executor 的 TDD 循环行为：
- acceptance 失败 + tdd 模式 → 进入循环（reviewer 被调用）
- acceptance 通过 → 不循环
- 最多 3 轮后 TDD_LOOP_EXHAUSTED
- fast 模式 → acceptance 失败不阻塞（建议性）
- 无 reviewer → 退化为仅记录 acceptance（不循环）
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile

import pytest

from backend.data.database import Database
from backend.data.orchestration_repo import (
    LaneEventRepository,
    LaneRepository,
    TaskRepository,
)
from backend.orchestration.events import EventRecorder, EventStream
from backend.orchestration.executor import (
    LaneExecutor,
    TddLoopState,
    _resolve_lane_workflow_mode,
)
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.models import Lane, Task, TaskPacket
from backend.orchestration.task_registry import TaskRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    db = Database(db_path=tmp_path)
    db.init_db()
    yield db, tmp_path
    with contextlib.suppress(PermissionError):
        os.unlink(tmp_path)


@pytest.fixture()
def registries(temp_db):
    db, _ = temp_db
    lane_repo = LaneRepository()
    lane_repo.db = db
    task_repo = TaskRepository()
    task_repo.db = db
    event_repo = LaneEventRepository()
    event_repo.db = db

    return {
        "lane_registry": LaneRegistry(repo=lane_repo),
        "task_registry": TaskRegistry(repo=task_repo),
        "lane_repo": lane_repo,
        "task_repo": task_repo,
        "event_recorder": EventRecorder(repo=event_repo),
        "event_stream": EventStream(repo=event_repo),
    }


def _make_task(registries, *, workflow_mode=None):
    """创建任务，可选 workflow_mode。"""
    packet = None
    if workflow_mode is not None:
        packet = TaskPacket(objective="test", workflow_mode=workflow_mode)
    task = Task(
        task_id=f"task-tdd-{id(object()):x}",
        name="tdd-test",
        description="TDD loop test",
        packet=packet,
    )
    registries["task_repo"].create(task)
    return task


def _make_lane(registries, task, *, worktree=None, acceptance_checks=None):
    """创建 lane。"""
    lane = registries["lane_registry"].create_lane(task_id=task.task_id)
    if worktree is not None:
        lane.worktree = worktree
    if acceptance_checks is not None:
        lane.metadata = lane.metadata or {}
        lane.metadata["acceptance_checks"] = acceptance_checks
    if worktree is not None or acceptance_checks is not None:
        registries["lane_repo"].update(lane)
    return lane


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTddGateLoop:
    """TDD 循环核心行为。"""

    def test_acceptance_failure_triggers_tdd_loop(self, registries, tmp_path):
        """acceptance 失败 + tdd 模式 + reviewer 判 fail → agent_runner 被多次调用。"""
        task = _make_task(registries, workflow_mode="tdd")
        lane = _make_lane(
            registries, task,
            worktree=str(tmp_path),
            acceptance_checks=[["false"]],
        )

        agent_calls = []

        async def agent_runner(task_obj, agent_id):
            agent_calls.append(1)
            return {"output": f"attempt-{len(agent_calls)}"}

        async def task_reviewer(**_kwargs):
            return {"verdict": "fail", "reason": "not good enough"}

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=agent_runner,
            task_reviewer=task_reviewer,
        )

        result = asyncio.run(executor.execute_lane(lane))
        assert result["status"] == "failed"
        assert result["error_code"] == "TDD_LOOP_EXHAUSTED"
        assert len(agent_calls) == 3

    def test_acceptance_pass_exits_loop(self, registries, tmp_path):
        """acceptance 通过 → agent_runner 只调用一次。"""
        task = _make_task(registries, workflow_mode="tdd")
        lane = _make_lane(registries, task, worktree=str(tmp_path))

        agent_calls = []

        async def agent_runner(task_obj, agent_id):
            agent_calls.append(1)
            return {"output": "ok"}

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=agent_runner,
        )

        result = asyncio.run(executor.execute_lane(lane))
        assert result["status"] == "succeeded"
        assert len(agent_calls) == 1

    def test_tdd_loop_max_rounds_respected(self, registries, tmp_path):
        """TDD 循环最多 3 轮（agent_runner 恰好被调用 3 次）。"""
        task = _make_task(registries, workflow_mode="tdd")
        lane = _make_lane(
            registries, task,
            worktree=str(tmp_path),
            acceptance_checks=[["false"]],
        )

        agent_calls = []

        async def agent_runner(task_obj, agent_id):
            agent_calls.append(1)
            return {"output": f"attempt-{len(agent_calls)}"}

        async def task_reviewer(**_kwargs):
            return {"verdict": "fail", "reason": "still failing"}

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=agent_runner,
            task_reviewer=task_reviewer,
        )

        result = asyncio.run(executor.execute_lane(lane))
        assert result["status"] == "failed"
        assert result["error_code"] == "TDD_LOOP_EXHAUSTED"
        assert len(agent_calls) == 3

    def test_fast_mode_no_gate(self, registries, tmp_path):
        """fast 模式 acceptance 失败不阻塞 → succeeded。"""
        task = _make_task(registries, workflow_mode="fast")
        lane = _make_lane(
            registries, task,
            worktree=str(tmp_path),
            acceptance_checks=[["false"]],
        )

        agent_calls = []

        async def agent_runner(task_obj, agent_id):
            agent_calls.append(1)
            return {"output": "ok"}

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=agent_runner,
        )

        result = asyncio.run(executor.execute_lane(lane))
        assert result["status"] == "succeeded"
        assert len(agent_calls) == 1
        acceptance = result.get("acceptance") or {}
        assert not acceptance.get("all_passed")

    def test_reviewer_pass_exits_loop_early(self, registries, tmp_path):
        """reviewer 判 pass → 即使 acceptance 失败也立即跳出。"""
        task = _make_task(registries, workflow_mode="tdd")
        lane = _make_lane(
            registries, task,
            worktree=str(tmp_path),
            acceptance_checks=[["false"]],
        )

        agent_calls = []

        async def agent_runner(task_obj, agent_id):
            agent_calls.append(1)
            return {"output": "ok"}

        async def task_reviewer(**_kwargs):
            return {"verdict": "pass", "reason": "looks good"}

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=agent_runner,
            task_reviewer=task_reviewer,
        )

        result = asyncio.run(executor.execute_lane(lane))
        assert result["status"] == "succeeded"
        assert len(agent_calls) == 1

    def test_no_reviewer_short_circuits(self, registries, tmp_path):
        """无 reviewer → acceptance 失败仅记录，不循环。"""
        task = _make_task(registries, workflow_mode="tdd")
        lane = _make_lane(
            registries, task,
            worktree=str(tmp_path),
            acceptance_checks=[["false"]],
        )

        agent_calls = []

        async def agent_runner(task_obj, agent_id):
            agent_calls.append(1)
            return {"output": "ok"}

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=agent_runner,
        )

        result = asyncio.run(executor.execute_lane(lane))
        assert result["status"] == "succeeded"
        assert len(agent_calls) == 1


class TestResolveLaneWorkflowMode:
    """workflow_mode 解析优先级。"""

    def test_lane_metadata_highest_priority(self):
        """lane.metadata > packet > parameters。"""
        lane = Lane(lane_id="l1", task_id="t1", metadata={"workflow_mode": "fast"})
        task = Task(
            task_id="t1", name="t", description="d",
            packet=TaskPacket(objective="o", workflow_mode="tdd"),
        )
        task.parameters["workflow_mode"] = "tdd"
        assert _resolve_lane_workflow_mode(lane, task) == "fast"

    def test_packet_second_priority(self):
        """packet > parameters。"""
        lane = Lane(lane_id="l2", task_id="t2")
        task = Task(
            task_id="t2", name="t", description="d",
            packet=TaskPacket(objective="o", workflow_mode="fast"),
        )
        task.parameters["workflow_mode"] = "tdd"
        assert _resolve_lane_workflow_mode(lane, task) == "fast"

    def test_parameters_third(self):
        """parameters fallback。"""
        lane = Lane(lane_id="l3", task_id="t3")
        task = Task(task_id="t3", name="t", description="d")
        task.parameters["workflow_mode"] = "fast"
        assert _resolve_lane_workflow_mode(lane, task) == "fast"

    def test_default_is_tdd(self):
        """无显式配置 → 默认 tdd。"""
        lane = Lane(lane_id="l4", task_id="t4")
        task = Task(task_id="t4", name="t", description="d")
        assert _resolve_lane_workflow_mode(lane, task) == "tdd"

    def test_env_var_fallback(self, monkeypatch):
        """所有显式路径为 None → 回退到 SAGE_TDD_MODE 环境变量。"""
        monkeypatch.setenv("SAGE_TDD_MODE", "fast")
        lane = Lane(lane_id="l5", task_id="t5")
        task = Task(task_id="t5", name="t", description="d")
        assert _resolve_lane_workflow_mode(lane, task) == "fast"

    def test_env_var_invalid_ignored(self, monkeypatch):
        """SAGE_TDD_MODE 非法值 → 忽略，回退到默认 tdd。"""
        monkeypatch.setenv("SAGE_TDD_MODE", "bogus")
        lane = Lane(lane_id="l6", task_id="t6")
        task = Task(task_id="t6", name="t", description="d")
        assert _resolve_lane_workflow_mode(lane, task) == "tdd"


class TestTddLoopState:
    """TddLoopState 数据结构。"""

    def test_defaults(self):
        state = TddLoopState()
        assert state.max_rounds == 3
        assert state.round == 0
        assert state.last_failure == ""
