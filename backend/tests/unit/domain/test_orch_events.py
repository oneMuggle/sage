"""R144 — 编排事件协议（orch_events）单元测试。

覆盖：三级生命周期状态判定（terminal/active/waiting）、三张转移表全
封闭断言（以实现表为 oracle，任何改动当场报警）、关键边 spot-check、
事件枚举计数、RunEvent 工厂/序列化往返/command_id 条件键、TaskSummary
与 RunSnapshot 快照契约。
"""

from __future__ import annotations

import itertools

import pytest

from backend.domain import orch_events as oe
from backend.domain.orch_events import (
    SCHEMA_VERSION,
    RunEvent,
    RunEventType,
    RunSnapshot,
    RunStatus,
    StepEventType,
    StepStatus,
    TaskEventType,
    TaskStatus,
    TaskSummary,
    Visibility,
    make_event,
    validate_run_transition,
    validate_step_transition,
    validate_task_transition,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 状态判定
# ---------------------------------------------------------------------------


def test_run_status_memberships():
    assert RunStatus.COMPLETED.is_terminal()
    assert RunStatus.FAILED.is_terminal()
    assert RunStatus.CANCELLED.is_terminal()
    assert RunStatus.RECOVERY_REQUIRED.is_terminal() is False
    assert RunStatus.RUNNING.is_active()
    assert RunStatus.QUEUED.is_active()
    assert RunStatus.PAUSED.is_active()
    assert RunStatus.CANCELLING.is_active()
    assert RunStatus.DRAFT.is_active() is False


def test_task_status_memberships():
    for t in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        assert t.is_terminal()
    for t in (TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.WAITING_INPUT,
              TaskStatus.WAITING_APPROVAL, TaskStatus.RETRYING, TaskStatus.CANCELLING):
        assert t.is_active()
    assert TaskStatus.WAITING_INPUT.is_waiting()
    assert TaskStatus.WAITING_APPROVAL.is_waiting()
    assert TaskStatus.RETRYING.is_waiting() is False
    assert TaskStatus.BLOCKED.is_active() is False


def test_step_status_memberships():
    for s in (StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.CANCELLED,
              StepStatus.SKIPPED):
        assert s.is_terminal()
    assert StepStatus.RUNNING.is_terminal() is False
    # Step 无 active 判定（实现未提供），仅验证枚举齐全
    assert {s.value for s in StepStatus} == {
        "pending", "running", "waiting_input", "waiting_approval",
        "succeeded", "failed", "cancelled", "skipped",
    }


# ---------------------------------------------------------------------------
# 转移表全封闭断言
# ---------------------------------------------------------------------------


def _assert_table_closed(table, validate, status_cls):
    """对全部枚举对逐对校验：validate 结果必须与模块级转移表完全一致。"""
    for frm, to in itertools.product(status_cls, repeat=2):
        expected = to in table.get(frm, frozenset())
        assert validate(frm, to) == expected


def test_run_transition_table_matches_oracle():
    _assert_table_closed(oe._RUN_TRANSITIONS, validate_run_transition, RunStatus)


def test_task_transition_table_matches_oracle():
    _assert_table_closed(oe._TASK_TRANSITIONS, validate_task_transition, TaskStatus)


def test_step_transition_table_matches_oracle():
    _assert_table_closed(oe._STEP_TRANSITIONS, validate_step_transition, StepStatus)


def test_key_transition_edges():
    assert validate_run_transition(RunStatus.RUNNING, RunStatus.COMPLETED)
    assert validate_run_transition(RunStatus.DRAFT, RunStatus.QUEUED)
    assert not validate_run_transition(RunStatus.DRAFT, RunStatus.RUNNING)
    assert validate_run_transition(RunStatus.RECOVERY_REQUIRED, RunStatus.QUEUED)
    assert validate_run_transition(RunStatus.PAUSED, RunStatus.CANCELLED)
    assert validate_task_transition(TaskStatus.INTERRUPTED, TaskStatus.QUEUED)
    assert validate_task_transition(TaskStatus.BLOCKED, TaskStatus.QUEUED)
    assert validate_step_transition(StepStatus.PENDING, StepStatus.SKIPPED)


def test_terminal_states_closed_for_all_levels():
    for terminal in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        for other in RunStatus:
            assert not validate_run_transition(terminal, other)
    for terminal in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        for other in TaskStatus:
            assert not validate_task_transition(terminal, other)
    for terminal in (StepStatus.SUCCEEDED, StepStatus.FAILED,
                     StepStatus.CANCELLED, StepStatus.SKIPPED):
        for other in StepStatus:
            assert not validate_step_transition(terminal, other)


# ---------------------------------------------------------------------------
# 事件枚举
# ---------------------------------------------------------------------------


def test_event_type_enum_counts_and_samples():
    assert len(RunEventType) == 11
    assert RunEventType.RUN_RECOVERED == "run.recovered"
    assert len(TaskEventType) == 11
    assert TaskEventType.TASK_WAITING_APPROVAL == "task.waiting_approval"
    assert len(StepEventType) == 7
    assert StepEventType.STEP_OUTPUT_DELTA == "task.step.output_delta"
    assert len(oe.ControlEventType) == 7
    assert oe.ControlEventType.TASK_APPROVAL_RESOLVED == "task.approval_resolved"


def test_visibility_and_context_enums():
    assert Visibility.USER == "user"
    assert Visibility.REDACTED == "redacted"
    assert {c.value for c in oe.ContextSource} == {"user", "parent_agent", "system"}
    assert {c.value for c in oe.ContextStatus} == {
        "pending", "delivered", "acknowledged", "rejected",
    }


def test_schema_version():
    assert SCHEMA_VERSION == "run-events@1.0"


# ---------------------------------------------------------------------------
# RunEvent / make_event
# ---------------------------------------------------------------------------


def _make(**overrides):
    kwargs = {
        "run_id": "run-1",
        "seq": 3,
        "event_type": RunEventType.RUN_STARTED.value,
        "producer": "chat-dispatcher",
    }
    kwargs.update(overrides)
    return make_event(**kwargs)


def test_make_event_factory_defaults():
    event = _make()
    assert event.event_id.startswith("evt-")
    assert len(event.event_id) == len("evt-") + 16
    assert isinstance(event.occurred_at, int)  # 毫秒时间戳
    assert event.entity == {}
    assert event.payload == {}
    assert event.visibility == Visibility.USER.value
    assert event.schema_version == SCHEMA_VERSION
    assert event.command_id is None
    assert event.producer_generation == 0


def test_to_dict_keys_and_command_id_conditional():
    minimal = _make().to_dict()
    assert "command_id" not in minimal  # None 时不写键
    assert set(minimal) == {
        "event_id", "run_id", "seq", "event_type", "occurred_at",
        "producer", "producer_generation", "entity", "payload",
        "visibility", "schema_version",
    }
    with_cmd = _make(command_id="cmd-9").to_dict()
    assert with_cmd["command_id"] == "cmd-9"


def test_to_dict_from_dict_roundtrip():
    event = _make(
        entity={"task_id": "t1"},
        payload={"text": "你好"},
        visibility=Visibility.INTERNAL.value,
        command_id="cmd-1",
        producer_generation=2,
    )
    restored = RunEvent.from_dict(event.to_dict())
    assert restored == event


def test_from_dict_fills_defaults():
    raw = {
        "event_id": "evt-x",
        "run_id": "run-2",
        "seq": 0,
        "event_type": "run.created",
        "occurred_at": 1,
        "producer": "user",
        "producer_generation": 0,
    }
    restored = RunEvent.from_dict(raw)
    assert restored.entity == {}
    assert restored.payload == {}
    assert restored.visibility == Visibility.USER.value
    assert restored.schema_version == SCHEMA_VERSION
    assert restored.command_id is None


# ---------------------------------------------------------------------------
# 快照
# ---------------------------------------------------------------------------


def test_task_summary_defaults():
    summary = TaskSummary(task_id="t1", agent_id="a1", status="running")
    assert summary.current_step_id is None
    assert summary.retry_count == 0
    assert summary.revision == 0
    assert summary.error is None


def test_run_snapshot_to_dict_structure():
    tasks = [
        TaskSummary(task_id="t1", agent_id="a1", status="running",
                    current_step_id="s1", current_step_name="计划",
                    current_step_status="running", retry_count=1),
        TaskSummary(task_id="t2", agent_id=None, status="queued",
                    output_preview="预览"),
    ]
    snapshot = RunSnapshot(
        run_id="run-1",
        status="running",
        summary={"total": 2, "queued": 1, "running": 1},
        tasks=list(tasks),
        last_event_seq=7,
        updated_at=1234,
    )
    d = snapshot.to_dict()
    assert d["run_id"] == "run-1"
    assert d["summary"] == {"total": 2, "queued": 1, "running": 1}
    assert [t["task_id"] for t in d["tasks"]] == ["t1", "t2"]
    assert d["tasks"][0]["retry_count"] == 1
    assert d["tasks"][1]["output_preview"] == "预览"
    assert d["last_event_seq"] == 7
    assert d["updated_at"] == 1234
