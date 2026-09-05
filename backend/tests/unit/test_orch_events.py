"""Tests for backend/domain/orch_events.py — state machines and event envelope."""

from __future__ import annotations

import pytest

from backend.domain.orch_events import (
    RunEvent,
    RunEventType,
    RunSnapshot,
    RunStatus,
    SCHEMA_VERSION,
    StepEventType,
    StepStatus,
    TaskEventType,
    TaskStatus,
    TaskSummary,
    make_event,
    validate_run_transition,
    validate_step_transition,
    validate_task_transition,
)


# ---------------------------------------------------------------------------
# Run status state machine
# ---------------------------------------------------------------------------


class TestRunStateMachine:
    """Run 状态机合法转移测试。"""

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            (RunStatus.DRAFT, RunStatus.QUEUED),
            (RunStatus.DRAFT, RunStatus.CANCELLED),
            (RunStatus.QUEUED, RunStatus.RUNNING),
            (RunStatus.QUEUED, RunStatus.CANCELLED),
            (RunStatus.RUNNING, RunStatus.PAUSED),
            (RunStatus.RUNNING, RunStatus.CANCELLING),
            (RunStatus.RUNNING, RunStatus.COMPLETED),
            (RunStatus.RUNNING, RunStatus.FAILED),
            (RunStatus.RUNNING, RunStatus.RECOVERY_REQUIRED),
            (RunStatus.PAUSED, RunStatus.RUNNING),
            (RunStatus.PAUSED, RunStatus.CANCELLING),
            (RunStatus.PAUSED, RunStatus.CANCELLED),
            (RunStatus.CANCELLING, RunStatus.CANCELLED),
            (RunStatus.CANCELLING, RunStatus.FAILED),
            (RunStatus.RECOVERY_REQUIRED, RunStatus.QUEUED),
            (RunStatus.RECOVERY_REQUIRED, RunStatus.CANCELLED),
        ],
    )
    def test_valid_run_transitions(self, from_status: RunStatus, to_status: RunStatus) -> None:
        """合法转移应返回 True。"""
        assert validate_run_transition(from_status, to_status) is True

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            # 终态不可转出
            (RunStatus.COMPLETED, RunStatus.RUNNING),
            (RunStatus.COMPLETED, RunStatus.FAILED),
            (RunStatus.FAILED, RunStatus.RUNNING),
            (RunStatus.CANCELLED, RunStatus.RUNNING),
            # 不能跳过中间状态
            (RunStatus.DRAFT, RunStatus.RUNNING),
            (RunStatus.DRAFT, RunStatus.COMPLETED),
            (RunStatus.QUEUED, RunStatus.COMPLETED),
            (RunStatus.QUEUED, RunStatus.FAILED),
            (RunStatus.PAUSED, RunStatus.COMPLETED),
            # 不能从 DRAFT 到 PAUSED
            (RunStatus.DRAFT, RunStatus.PAUSED),
            # 不能从 QUEUED 到 PAUSED
            (RunStatus.QUEUED, RunStatus.PAUSED),
        ],
    )
    def test_invalid_run_transitions(self, from_status: RunStatus, to_status: RunStatus) -> None:
        """非法转移应返回 False。"""
        assert validate_run_transition(from_status, to_status) is False

    def test_terminal_states(self) -> None:
        """终态集合正确。"""
        assert RunStatus.COMPLETED.is_terminal()
        assert RunStatus.FAILED.is_terminal()
        assert RunStatus.CANCELLED.is_terminal()
        assert not RunStatus.RUNNING.is_terminal()
        assert not RunStatus.PAUSED.is_terminal()
        assert not RunStatus.DRAFT.is_terminal()

    def test_active_states(self) -> None:
        """活跃状态集合正确。"""
        assert RunStatus.RUNNING.is_active()
        assert RunStatus.PAUSED.is_active()
        assert RunStatus.QUEUED.is_active()
        assert RunStatus.CANCELLING.is_active()
        assert not RunStatus.COMPLETED.is_active()
        assert not RunStatus.DRAFT.is_active()


# ---------------------------------------------------------------------------
# Task status state machine
# ---------------------------------------------------------------------------


class TestTaskStateMachine:
    """Task 状态机合法转移测试。"""

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            (TaskStatus.PLANNED, TaskStatus.QUEUED),
            (TaskStatus.PLANNED, TaskStatus.BLOCKED),
            (TaskStatus.PLANNED, TaskStatus.CANCELLED),
            (TaskStatus.QUEUED, TaskStatus.RUNNING),
            (TaskStatus.QUEUED, TaskStatus.CANCELLED),
            (TaskStatus.RUNNING, TaskStatus.WAITING_INPUT),
            (TaskStatus.RUNNING, TaskStatus.WAITING_APPROVAL),
            (TaskStatus.RUNNING, TaskStatus.RETRYING),
            (TaskStatus.RUNNING, TaskStatus.CANCELLING),
            (TaskStatus.RUNNING, TaskStatus.SUCCEEDED),
            (TaskStatus.RUNNING, TaskStatus.FAILED),
            (TaskStatus.RUNNING, TaskStatus.INTERRUPTED),
            (TaskStatus.WAITING_INPUT, TaskStatus.RUNNING),
            (TaskStatus.WAITING_INPUT, TaskStatus.CANCELLED),
            (TaskStatus.WAITING_APPROVAL, TaskStatus.RUNNING),
            (TaskStatus.WAITING_APPROVAL, TaskStatus.CANCELLED),
            (TaskStatus.RETRYING, TaskStatus.QUEUED),
            (TaskStatus.RETRYING, TaskStatus.CANCELLED),
            (TaskStatus.CANCELLING, TaskStatus.CANCELLED),
            (TaskStatus.CANCELLING, TaskStatus.FAILED),
            (TaskStatus.BLOCKED, TaskStatus.QUEUED),
            (TaskStatus.BLOCKED, TaskStatus.CANCELLED),
            (TaskStatus.INTERRUPTED, TaskStatus.QUEUED),
            (TaskStatus.INTERRUPTED, TaskStatus.CANCELLED),
        ],
    )
    def test_valid_task_transitions(self, from_status: TaskStatus, to_status: TaskStatus) -> None:
        """合法转移应返回 True。"""
        assert validate_task_transition(from_status, to_status) is True

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            # 终态不可转出
            (TaskStatus.SUCCEEDED, TaskStatus.RUNNING),
            (TaskStatus.FAILED, TaskStatus.RUNNING),
            (TaskStatus.CANCELLED, TaskStatus.RUNNING),
            # 不能跳过状态
            (TaskStatus.PLANNED, TaskStatus.RUNNING),
            (TaskStatus.PLANNED, TaskStatus.SUCCEEDED),
            (TaskStatus.QUEUED, TaskStatus.SUCCEEDED),
            (TaskStatus.WAITING_INPUT, TaskStatus.SUCCEEDED),
            # 不能从 RUNNING 直接到 BLOCKED
            (TaskStatus.RUNNING, TaskStatus.BLOCKED),
            # 不能从 QUEUED 直接到 WAITING_INPUT
            (TaskStatus.QUEUED, TaskStatus.WAITING_INPUT),
        ],
    )
    def test_invalid_task_transitions(self, from_status: TaskStatus, to_status: TaskStatus) -> None:
        """非法转移应返回 False。"""
        assert validate_task_transition(from_status, to_status) is False

    def test_waiting_states(self) -> None:
        """等待状态集合正确。"""
        assert TaskStatus.WAITING_INPUT.is_waiting()
        assert TaskStatus.WAITING_APPROVAL.is_waiting()
        assert not TaskStatus.RUNNING.is_waiting()
        assert not TaskStatus.SUCCEEDED.is_waiting()


# ---------------------------------------------------------------------------
# Step status state machine
# ---------------------------------------------------------------------------


class TestStepStateMachine:
    """Step 状态机合法转移测试。"""

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            (StepStatus.PENDING, StepStatus.RUNNING),
            (StepStatus.PENDING, StepStatus.SKIPPED),
            (StepStatus.PENDING, StepStatus.CANCELLED),
            (StepStatus.RUNNING, StepStatus.WAITING_INPUT),
            (StepStatus.RUNNING, StepStatus.WAITING_APPROVAL),
            (StepStatus.RUNNING, StepStatus.SUCCEEDED),
            (StepStatus.RUNNING, StepStatus.FAILED),
            (StepStatus.RUNNING, StepStatus.CANCELLED),
            (StepStatus.WAITING_INPUT, StepStatus.RUNNING),
            (StepStatus.WAITING_INPUT, StepStatus.CANCELLED),
            (StepStatus.WAITING_APPROVAL, StepStatus.RUNNING),
            (StepStatus.WAITING_APPROVAL, StepStatus.CANCELLED),
        ],
    )
    def test_valid_step_transitions(self, from_status: StepStatus, to_status: StepStatus) -> None:
        """合法转移应返回 True。"""
        assert validate_step_transition(from_status, to_status) is True

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            # 终态不可转出
            (StepStatus.SUCCEEDED, StepStatus.RUNNING),
            (StepStatus.FAILED, StepStatus.RUNNING),
            (StepStatus.CANCELLED, StepStatus.RUNNING),
            (StepStatus.SKIPPED, StepStatus.RUNNING),
            # 不能跳过状态
            (StepStatus.PENDING, StepStatus.SUCCEEDED),
            (StepStatus.PENDING, StepStatus.FAILED),
        ],
    )
    def test_invalid_step_transitions(self, from_status: StepStatus, to_status: StepStatus) -> None:
        """非法转移应返回 False。"""
        assert validate_step_transition(from_status, to_status) is False

    def test_step_terminal_states(self) -> None:
        """Step 终态集合正确。"""
        assert StepStatus.SUCCEEDED.is_terminal()
        assert StepStatus.FAILED.is_terminal()
        assert StepStatus.CANCELLED.is_terminal()
        assert StepStatus.SKIPPED.is_terminal()
        assert not StepStatus.RUNNING.is_terminal()
        assert not StepStatus.PENDING.is_terminal()


# ---------------------------------------------------------------------------
# RunEvent envelope
# ---------------------------------------------------------------------------


class TestRunEvent:
    """事件 envelope 序列化/反序列化测试。"""

    def test_make_event_generates_id_and_timestamp(self) -> None:
        """make_event 自动生成 event_id 和 occurred_at。"""
        event = make_event(
            run_id="run-1",
            seq=1,
            event_type=RunEventType.RUN_CREATED.value,
            producer="test",
        )
        assert event.event_id.startswith("evt-")
        assert len(event.event_id) == 20  # evt- + 16 hex chars
        assert event.occurred_at > 0
        assert event.run_id == "run-1"
        assert event.seq == 1

    def test_run_event_roundtrip(self) -> None:
        """RunEvent 序列化/反序列化 roundtrip。"""
        original = make_event(
            run_id="run-42",
            seq=7,
            event_type=TaskEventType.TASK_STARTED.value,
            producer="subagent-runner",
            producer_generation=3,
            entity={"task_id": "task-1", "agent_id": "researcher"},
            payload={"status": "running", "iteration": 2},
            visibility="user",
            command_id="cmd-abc123",
        )
        data = original.to_dict()
        restored = RunEvent.from_dict(data)

        assert restored.event_id == original.event_id
        assert restored.run_id == original.run_id
        assert restored.seq == original.seq
        assert restored.event_type == original.event_type
        assert restored.occurred_at == original.occurred_at
        assert restored.producer == original.producer
        assert restored.producer_generation == original.producer_generation
        assert restored.entity == original.entity
        assert restored.payload == original.payload
        assert restored.visibility == original.visibility
        assert restored.schema_version == SCHEMA_VERSION
        assert restored.command_id == original.command_id

    def test_run_event_from_dict_defaults(self) -> None:
        """from_dict 在缺少可选字段时使用默认值。"""
        minimal = {
            "event_id": "evt-minimal",
            "run_id": "run-1",
            "seq": 1,
            "event_type": "run.created",
            "occurred_at": 1234567890000,
            "producer": "test",
            "producer_generation": 0,
        }
        event = RunEvent.from_dict(minimal)
        assert event.entity == {}
        assert event.payload == {}
        assert event.visibility == "user"
        assert event.schema_version == SCHEMA_VERSION
        assert event.command_id is None

    def test_run_event_frozen(self) -> None:
        """RunEvent 是不可变的 (frozen dataclass)。"""
        event = make_event(
            run_id="run-1",
            seq=1,
            event_type="run.created",
            producer="test",
        )
        with pytest.raises(AttributeError):
            event.seq = 2  # type: ignore[misc]

    def test_schema_version_constant(self) -> None:
        """SCHEMA_VERSION 格式正确。"""
        assert SCHEMA_VERSION == "run-events@1.0"
        assert "@" in SCHEMA_VERSION


# ---------------------------------------------------------------------------
# RunSnapshot / TaskSummary
# ---------------------------------------------------------------------------


class TestSnapshots:
    """快照序列化测试。"""

    def test_task_summary_fields(self) -> None:
        """TaskSummary 字段正确。"""
        ts = TaskSummary(
            task_id="task-1",
            agent_id="researcher",
            status="running",
            current_step_id="step-1",
            current_step_name="web_search",
            current_step_status="running",
            last_progress_at=1760000000100,
            retry_count=0,
        )
        assert ts.task_id == "task-1"
        assert ts.agent_id == "researcher"
        assert ts.error is None

    def test_run_snapshot_to_dict(self) -> None:
        """RunSnapshot.to_dict 结构正确。"""
        task = TaskSummary(
            task_id="task-1",
            agent_id="researcher",
            status="running",
        )
        snapshot = RunSnapshot(
            run_id="run-1",
            status="running",
            summary={"total": 2, "running": 1, "queued": 1},
            tasks=[task],
            last_event_seq=42,
            updated_at=1760000000100,
        )
        data = snapshot.to_dict()

        assert data["run_id"] == "run-1"
        assert data["status"] == "running"
        assert data["summary"]["total"] == 2
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["task_id"] == "task-1"
        assert data["last_event_seq"] == 42


# ---------------------------------------------------------------------------
# Event type enums
# ---------------------------------------------------------------------------


class TestEventTypes:
    """事件类型枚举值测试。"""

    def test_run_event_types(self) -> None:
        """RunEventType 值格式正确。"""
        assert RunEventType.RUN_CREATED.value == "run.created"
        assert RunEventType.RUN_COMPLETED.value == "run.completed"
        assert RunEventType.RUN_CANCELLED.value == "run.cancelled"

    def test_task_event_types(self) -> None:
        """TaskEventType 值格式正确。"""
        assert TaskEventType.TASK_STARTED.value == "task.started"
        assert TaskEventType.TASK_WAITING_INPUT.value == "task.waiting_input"
        assert TaskEventType.TASK_SUCCEEDED.value == "task.succeeded"

    def test_step_event_types(self) -> None:
        """StepEventType 值格式正确。"""
        assert StepEventType.STEP_CREATED.value == "task.step.created"
        assert StepEventType.STEP_PROGRESS.value == "task.step.progress"
