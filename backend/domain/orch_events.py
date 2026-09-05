"""统一编排事件 envelope 与状态机定义。

Phase 0 (2026-09-06): 为 run/task/step 级可观测性建立统一事件协议。
所有编排事件（chat dispatcher、lane executor、subagent runner）都应产生
符合本模块 envelope 的事件，经 EventHub 广播后持久化到 orch_events 表。

设计原则:
- seq 在 run 内单调递增，是排序和断点续传的唯一依据
- timestamp 只用于展示，不用于排序
- visibility 控制哪些事件可以暴露给前端/主 agent
- producer_generation 防止旧 worker 迟到事件覆盖新状态
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# 状态枚举
# ---------------------------------------------------------------------------


class RunStatus(str, Enum):
    """Run 生命周期状态。"""

    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RECOVERY_REQUIRED = "recovery_required"

    def is_terminal(self) -> bool:
        return self in (
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        )

    def is_active(self) -> bool:
        return self in (
            RunStatus.QUEUED,
            RunStatus.RUNNING,
            RunStatus.PAUSED,
            RunStatus.CANCELLING,
        )


class TaskStatus(str, Enum):
    """Task 生命周期状态。"""

    PLANNED = "planned"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    WAITING_APPROVAL = "waiting_approval"
    RETRYING = "retrying"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    INTERRUPTED = "interrupted"

    def is_terminal(self) -> bool:
        return self in (
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )

    def is_active(self) -> bool:
        return self in (
            TaskStatus.QUEUED,
            TaskStatus.RUNNING,
            TaskStatus.WAITING_INPUT,
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.RETRYING,
            TaskStatus.CANCELLING,
        )

    def is_waiting(self) -> bool:
        return self in (TaskStatus.WAITING_INPUT, TaskStatus.WAITING_APPROVAL)


class StepStatus(str, Enum):
    """Step 生命周期状态。"""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"

    def is_terminal(self) -> bool:
        return self in (
            StepStatus.SUCCEEDED,
            StepStatus.FAILED,
            StepStatus.CANCELLED,
            StepStatus.SKIPPED,
        )


class StepKind(str, Enum):
    """Step 类型。"""

    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    SYNTHESIZE = "synthesize"
    EMIT_RESULT = "emit_result"
    PREPARE_CONTEXT = "prepare_context"


class Visibility(str, Enum):
    """事件可见性级别。"""

    USER = "user"          # 可暴露给前端用户
    INTERNAL = "internal"  # 仅主 agent / ops 可见
    REDACTED = "redacted"  # 脱敏后仅审计可见


class ContextSource(str, Enum):
    """追加信息的来源。"""

    USER = "user"
    PARENT_AGENT = "parent_agent"
    SYSTEM = "system"


class ContextStatus(str, Enum):
    """追加信息的投递状态。"""

    PENDING = "pending"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# 合法状态转移表
# ---------------------------------------------------------------------------

_RUN_TRANSITIONS: Dict[RunStatus, frozenset] = {
    RunStatus.DRAFT: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED}),
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset({
        RunStatus.PAUSED, RunStatus.CANCELLING, RunStatus.COMPLETED,
        RunStatus.FAILED, RunStatus.RECOVERY_REQUIRED,
    }),
    RunStatus.PAUSED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLING, RunStatus.CANCELLED}),
    RunStatus.CANCELLING: frozenset({RunStatus.CANCELLED, RunStatus.FAILED}),
    RunStatus.RECOVERY_REQUIRED: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED}),
    # 终态不可转出
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}

_TASK_TRANSITIONS: Dict[TaskStatus, frozenset] = {
    TaskStatus.PLANNED: frozenset({TaskStatus.QUEUED, TaskStatus.BLOCKED, TaskStatus.CANCELLED}),
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset({
        TaskStatus.WAITING_INPUT, TaskStatus.WAITING_APPROVAL, TaskStatus.RETRYING,
        TaskStatus.CANCELLING, TaskStatus.SUCCEEDED, TaskStatus.FAILED,
        TaskStatus.INTERRUPTED,
    }),
    TaskStatus.WAITING_INPUT: frozenset({
        TaskStatus.RUNNING, TaskStatus.CANCELLING, TaskStatus.CANCELLED,
    }),
    TaskStatus.WAITING_APPROVAL: frozenset({
        TaskStatus.RUNNING, TaskStatus.CANCELLING, TaskStatus.CANCELLED,
    }),
    TaskStatus.RETRYING: frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLING, TaskStatus.CANCELLED}),
    TaskStatus.CANCELLING: frozenset({TaskStatus.CANCELLED, TaskStatus.FAILED}),
    TaskStatus.BLOCKED: frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLED}),
    TaskStatus.INTERRUPTED: frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLED}),
    TaskStatus.SUCCEEDED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

_STEP_TRANSITIONS: Dict[StepStatus, frozenset] = {
    StepStatus.PENDING: frozenset({StepStatus.RUNNING, StepStatus.SKIPPED, StepStatus.CANCELLED}),
    StepStatus.RUNNING: frozenset({
        StepStatus.WAITING_INPUT, StepStatus.WAITING_APPROVAL,
        StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.CANCELLED,
    }),
    StepStatus.WAITING_INPUT: frozenset({StepStatus.RUNNING, StepStatus.CANCELLED}),
    StepStatus.WAITING_APPROVAL: frozenset({StepStatus.RUNNING, StepStatus.CANCELLED}),
    StepStatus.SUCCEEDED: frozenset(),
    StepStatus.FAILED: frozenset(),
    StepStatus.CANCELLED: frozenset(),
    StepStatus.SKIPPED: frozenset(),
}


def validate_run_transition(from_status: RunStatus, to_status: RunStatus) -> bool:
    """校验 run 状态转移是否合法。"""
    return to_status in _RUN_TRANSITIONS.get(from_status, frozenset())


def validate_task_transition(from_status: TaskStatus, to_status: TaskStatus) -> bool:
    """校验 task 状态转移是否合法。"""
    return to_status in _TASK_TRANSITIONS.get(from_status, frozenset())


def validate_step_transition(from_status: StepStatus, to_status: StepStatus) -> bool:
    """校验 step 状态转移是否合法。"""
    return to_status in _STEP_TRANSITIONS.get(from_status, frozenset())


# ---------------------------------------------------------------------------
# 事件类型枚举
# ---------------------------------------------------------------------------


class RunEventType(str, Enum):
    """Run 级事件类型。"""

    RUN_CREATED = "run.created"
    RUN_PLAN_UPDATED = "run.plan.updated"
    RUN_QUEUED = "run.queued"
    RUN_STARTED = "run.started"
    RUN_PAUSED = "run.paused"
    RUN_RESUMED = "run.resumed"
    RUN_CANCEL_REQUESTED = "run.cancel_requested"
    RUN_CANCELLED = "run.cancelled"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_RECOVERED = "run.recovered"


class TaskEventType(str, Enum):
    """Task 级事件类型。"""

    TASK_PLANNED = "task.planned"
    TASK_QUEUED = "task.queued"
    TASK_STARTED = "task.started"
    TASK_WAITING_INPUT = "task.waiting_input"
    TASK_WAITING_APPROVAL = "task.waiting_approval"
    TASK_RETRYING = "task.retrying"
    TASK_SUCCEEDED = "task.succeeded"
    TASK_FAILED = "task.failed"
    TASK_CANCEL_REQUESTED = "task.cancel_requested"
    TASK_CANCELLED = "task.cancelled"
    TASK_BLOCKED = "task.blocked"


class StepEventType(str, Enum):
    """Step 级事件类型。"""

    STEP_CREATED = "task.step.created"
    STEP_STARTED = "task.step.started"
    STEP_PROGRESS = "task.step.progress"
    STEP_OUTPUT_DELTA = "task.step.output_delta"
    STEP_WAITING = "task.step.waiting"
    STEP_COMPLETED = "task.step.completed"
    STEP_FAILED = "task.step.failed"


class ControlEventType(str, Enum):
    """控制命令事件类型。"""

    CONTEXT_APPEND_REQUESTED = "task.context.append_requested"
    CONTEXT_APPENDED = "task.context.appended"
    CONTEXT_DELIVERED = "task.context.delivered"
    CONTEXT_ACKNOWLEDGED = "task.context.acknowledged"
    TASK_RUN_REQUESTED = "task.run_requested"
    TASK_APPROVAL_REQUESTED = "task.approval_requested"
    TASK_APPROVAL_RESOLVED = "task.approval_resolved"


# ---------------------------------------------------------------------------
# 事件 Envelope
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "run-events@1.0"


@dataclass(frozen=True)
class RunEvent:
    """统一编排事件 envelope。

    所有编排事件（无论来自 ChatDispatcher、LaneExecutor 还是 SubagentRunner）
    都应序列化为本结构后经 EventHub 广播。

    Fields:
        event_id: 全局唯一 ID (uuid4)
        run_id: 所属 run
        seq: run 内单调递增序号（断点续传依据）
        event_type: 事件类型字符串
        occurred_at: 毫秒时间戳（仅展示用）
        producer: 事件来源 ("chat-dispatcher" / "subagent-runner" / "user" / ...)
        producer_generation: worker 代数（防迟到事件）
        entity: 关联实体 ID dict（task_id/lane_id/step_id/agent_id，按需填写）
        payload: 事件专属数据 dict
        visibility: 可见性级别
        schema_version: 协议版本
        command_id: 幂等 key（可选）
    """

    event_id: str
    run_id: str
    seq: int
    event_type: str
    occurred_at: int
    producer: str
    producer_generation: int
    entity: Dict[str, Any]
    payload: Dict[str, Any]
    visibility: str = Visibility.USER.value
    schema_version: str = SCHEMA_VERSION
    command_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict（用于 JSON 持久化和 NDJSON 传输）。"""
        d: Dict[str, Any] = {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "seq": self.seq,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "producer": self.producer,
            "producer_generation": self.producer_generation,
            "entity": dict(self.entity),
            "payload": dict(self.payload),
            "visibility": self.visibility,
            "schema_version": self.schema_version,
        }
        if self.command_id is not None:
            d["command_id"] = self.command_id
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RunEvent:
        """从 dict 反序列化。"""
        return cls(
            event_id=data["event_id"],
            run_id=data["run_id"],
            seq=data["seq"],
            event_type=data["event_type"],
            occurred_at=data["occurred_at"],
            producer=data["producer"],
            producer_generation=data["producer_generation"],
            entity=data.get("entity", {}),
            payload=data.get("payload", {}),
            visibility=data.get("visibility", Visibility.USER.value),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            command_id=data.get("command_id"),
        )


def make_event(
    *,
    run_id: str,
    seq: int,
    event_type: str,
    producer: str,
    producer_generation: int = 0,
    entity: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
    visibility: str = Visibility.USER.value,
    command_id: Optional[str] = None,
) -> RunEvent:
    """便捷构造函数，自动生成 event_id 和 occurred_at。"""
    return RunEvent(
        event_id=f"evt-{uuid.uuid4().hex[:16]}",
        run_id=run_id,
        seq=seq,
        event_type=event_type,
        occurred_at=int(time.time() * 1000),
        producer=producer,
        producer_generation=producer_generation,
        entity=entity or {},
        payload=payload or {},
        visibility=visibility,
        command_id=command_id,
    )


# ---------------------------------------------------------------------------
# 运行快照
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskSummary:
    """Task 摘要（用于 RunSnapshot 和 observe_subagents 返回）。"""

    task_id: str
    agent_id: Optional[str]
    status: str
    current_step_id: Optional[str] = None
    current_step_name: Optional[str] = None
    current_step_status: Optional[str] = None
    last_progress_at: Optional[int] = None
    output_preview: Optional[str] = None
    retry_count: int = 0
    error: Optional[str] = None


@dataclass(frozen=True)
class RunSnapshot:
    """Run 级快照（用于 REST API 和 observe_subagents 返回）。"""

    run_id: str
    status: str
    summary: Dict[str, int]  # {"total": N, "queued": N, "running": N, ...}
    tasks: list  # List[TaskSummary]
    last_event_seq: int = 0
    updated_at: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "summary": dict(self.summary),
            "tasks": [
                {
                    "task_id": t.task_id,
                    "agent_id": t.agent_id,
                    "status": t.status,
                    "current_step_id": t.current_step_id,
                    "current_step_name": t.current_step_name,
                    "current_step_status": t.current_step_status,
                    "last_progress_at": t.last_progress_at,
                    "output_preview": t.output_preview,
                    "retry_count": t.retry_count,
                    "error": t.error,
                }
                for t in self.tasks
            ],
            "last_event_seq": self.last_event_seq,
            "updated_at": self.updated_at,
        }


__all__ = [
    "RunStatus",
    "TaskStatus",
    "StepStatus",
    "StepKind",
    "Visibility",
    "ContextSource",
    "ContextStatus",
    "RunEventType",
    "TaskEventType",
    "StepEventType",
    "ControlEventType",
    "RunEvent",
    "make_event",
    "TaskSummary",
    "RunSnapshot",
    "SCHEMA_VERSION",
    "validate_run_transition",
    "validate_task_transition",
    "validate_step_transition",
]
