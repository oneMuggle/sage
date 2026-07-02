"""
Core data models for multi-agent orchestration.

This module defines the fundamental abstractions for task coordination:
- Task: A unit of work with dependencies and execution constraints
- TaskPacket: Advanced task configuration (recovery/escalation policies)
- Lane: An execution unit with isolated lifecycle
- Team: A group of related tasks forming a workflow
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# ============================================================================
# Task Status & Model
# ============================================================================


class TaskStatus(str, Enum):
    """Task lifecycle states."""

    CREATED = "created"
    RUNNING = "running"
    BLOCKED = "blocked"  # Waiting for dependencies
    COMPLETED = "completed"  # Terminal state
    FAILED = "failed"  # Terminal state
    STOPPED = "stopped"  # Terminal state (cancelled)

    def is_terminal(self) -> bool:
        """Check if this is a terminal state."""
        return self in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.STOPPED)


@dataclass
class Task:
    """
    A unit of work in the orchestration system.

    Tasks can have dependencies (blocked_by) and dependents (blocks).
    A task is ready to execute when all its blocked_by tasks are completed.
    """

    task_id: str
    name: str
    description: str
    task_type: str = "general"  # "general" / "research" / "coding" / "analysis" / "testing"
    status: TaskStatus = TaskStatus.CREATED
    priority: int = 0  # Higher = more important
    executor_type: str = "agent"  # "agent" / "tool" / "script"
    parameters: dict[str, Any] = field(default_factory=dict)
    packet: Optional["TaskPacket"] = None  # Advanced configuration

    # Dependency management
    blocks: list[str] = field(default_factory=list)  # Tasks this task unblocks
    blocked_by: list[str] = field(default_factory=list)  # Tasks that block this task

    # Execution metadata
    result: Any | None = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    started_at: int | None = None
    completed_at: int | None = None
    team_id: str | None = None

    def mark_running(self) -> None:
        """Transition to RUNNING state."""
        if self.status != TaskStatus.CREATED:
            raise ValueError(f"Cannot mark running: task is {self.status}")
        self.status = TaskStatus.RUNNING
        self.started_at = int(time.time() * 1000)

    def mark_completed(self, result: Any = None) -> None:
        """Transition to COMPLETED state."""
        if self.status != TaskStatus.RUNNING:
            raise ValueError(f"Cannot complete: task is {self.status}")
        self.status = TaskStatus.COMPLETED
        self.completed_at = int(time.time() * 1000)
        self.result = result

    def mark_failed(self, error: str | None = None) -> None:
        """Transition to FAILED state."""
        if self.status != TaskStatus.RUNNING:
            raise ValueError(f"Cannot fail: task is {self.status}")
        self.status = TaskStatus.FAILED
        self.completed_at = int(time.time() * 1000)
        if error:
            self.parameters["error"] = error

    def mark_blocked(self) -> None:
        """Transition to BLOCKED state."""
        if self.status not in (TaskStatus.CREATED, TaskStatus.RUNNING):
            raise ValueError(f"Cannot block: task is {self.status}")
        self.status = TaskStatus.BLOCKED

    def mark_stopped(self) -> None:
        """Transition to STOPPED state (cancelled)."""
        if self.status.is_terminal():
            raise ValueError(f"Cannot stop: task is already {self.status}")
        self.status = TaskStatus.STOPPED
        self.completed_at = int(time.time() * 1000)


# ============================================================================
# Task Packet (Advanced Configuration)
# ============================================================================


@dataclass
class RecoveryPolicy:
    """Defines how to handle task failures."""

    on_failure: str = "retry"  # "retry" / "skip" / "abort-siblings" / "ask-human"
    retry_backoff_secs: list[int] = field(default_factory=lambda: [30, 120, 600])
    max_retries: int = 2


@dataclass
class EscalationPolicy:
    """Defines how to escalate unresolved issues."""

    after_retries: str = "notify-human"  # "notify-human" / "mark-blocked" / "fail-fast"
    notify_channels: list[str] = field(default_factory=list)  # ["discord", "email"]


@dataclass
class TaskPacket:
    """
    Advanced task configuration.

    Encapsulates execution constraints, recovery strategies, and acceptance criteria.
    """

    objective: str
    scope: list[str] = field(default_factory=list)  # Allowed file paths
    acceptance_tests: list[str] = field(default_factory=list)  # Tests that must pass

    # Execution constraints
    model: str | None = None  # LLM model to use
    permission_profile: str = "workspace-write"  # "read-only" / "workspace-write" / "full"
    timeout_secs: int = 600

    # Failure handling
    recovery_policy: RecoveryPolicy = field(default_factory=RecoveryPolicy)
    escalation_policy: EscalationPolicy = field(default_factory=EscalationPolicy)


# ============================================================================
# Lane Status & Model
# ============================================================================


class LaneStatus(str, Enum):
    """Lane lifecycle states."""

    CREATED = "created"
    READY = "ready"  # Dependencies satisfied, waiting for agent
    QUEUED = "queued"  # Waiting in execution queue
    RUNNING = "running"
    BLOCKED = "blocked"  # Waiting for external condition (e.g., human approval)
    SUCCEEDED = "succeeded"  # Terminal state
    FAILED = "failed"  # Terminal state
    STOPPED = "stopped"  # Terminal state (cancelled)
    CANCELLED = "cancelled"  # Alias for STOPPED

    def is_terminal(self) -> bool:
        """Check if this is a terminal state."""
        return self in (
            LaneStatus.SUCCEEDED,
            LaneStatus.FAILED,
            LaneStatus.STOPPED,
            LaneStatus.CANCELLED,
        )


class HeartbeatStatus(str, Enum):
    """Lane heartbeat health states."""

    HEALTHY = "healthy"
    STALLED = "stalled"
    TRANSPORT_DEAD = "transport_dead"


@dataclass
class LaneHeartbeat:
    """Tracks lane execution health."""

    last_ping_at: int  # Last activity timestamp (ms)
    transport_alive: bool = True  # Communication channel health
    status: HeartbeatStatus = HeartbeatStatus.HEALTHY

    def update_ping(self) -> None:
        """Update last ping timestamp."""
        self.last_ping_at = int(time.time() * 1000)
        self.status = HeartbeatStatus.HEALTHY


@dataclass
class Lane:
    """
    An execution unit with isolated lifecycle.

    Lanes decouple task definition from execution. A task can have multiple lanes
    (e.g., retries), and each lane is bound to a specific agent.
    """

    lane_id: str
    task_id: str
    agent_id: str | None = None
    status: LaneStatus = LaneStatus.CREATED
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    started_at: int | None = None
    completed_at: int | None = None

    # Execution context
    worktree: str | None = None  # Isolated filesystem workspace
    heartbeat: LaneHeartbeat | None = None
    error: str | None = None
    permission_preset: str = "implement"  # "audit" / "explain" / "implement"
    metadata: dict[str, Any] = field(default_factory=dict)

    def bind_agent(self, agent_id: str) -> None:
        """Bind an agent to this lane."""
        if self.status != LaneStatus.CREATED:
            raise ValueError(f"Cannot bind agent: lane is {self.status}")
        self.agent_id = agent_id

    def mark_ready(self) -> None:
        """Transition to READY state."""
        if self.status != LaneStatus.CREATED:
            raise ValueError(f"Cannot mark ready: lane is {self.status}")
        self.status = LaneStatus.READY

    def mark_running(self) -> None:
        """Transition to RUNNING state."""
        if self.status != LaneStatus.READY:
            raise ValueError(f"Cannot mark running: lane is {self.status}")
        self.status = LaneStatus.RUNNING
        self.started_at = int(time.time() * 1000)
        self.heartbeat = LaneHeartbeat(last_ping_at=self.started_at)

    def mark_succeeded(self) -> None:
        """Transition to SUCCEEDED state."""
        if self.status != LaneStatus.RUNNING:
            raise ValueError(f"Cannot succeed: lane is {self.status}")
        self.status = LaneStatus.SUCCEEDED
        self.completed_at = int(time.time() * 1000)

    def mark_failed(self, error: str | None = None) -> None:
        """Transition to FAILED state."""
        if self.status != LaneStatus.RUNNING:
            raise ValueError(f"Cannot fail: lane is {self.status}")
        self.status = LaneStatus.FAILED
        self.completed_at = int(time.time() * 1000)
        self.error = error

    def mark_blocked(self) -> None:
        """Transition to BLOCKED state."""
        if self.status != LaneStatus.RUNNING:
            raise ValueError(f"Cannot block: lane is {self.status}")
        self.status = LaneStatus.BLOCKED

    def mark_stopped(self) -> None:
        """Transition to STOPPED state (cancelled)."""
        if self.status.is_terminal():
            raise ValueError(f"Cannot stop: lane is already {self.status}")
        self.status = LaneStatus.STOPPED
        self.completed_at = int(time.time() * 1000)


# ============================================================================
# Team Status & Model
# ============================================================================


class TeamStatus(str, Enum):
    """Team lifecycle states."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"  # All tasks completed
    FAILED = "failed"  # One or more tasks failed
    CANCELLED = "cancelled"

    def is_terminal(self) -> bool:
        """Check if this is a terminal state."""
        return self in (TeamStatus.COMPLETED, TeamStatus.FAILED, TeamStatus.CANCELLED)


@dataclass
class Team:
    """
    A group of related tasks forming a workflow.

    Teams are the output of the Planner and represent a complete execution plan.
    """

    team_id: str
    name: str
    task_ids: list[str] = field(default_factory=list)
    status: TeamStatus = TeamStatus.CREATED
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at: int = field(default_factory=lambda: int(time.time() * 1000))
    metadata: dict[str, Any] = field(default_factory=dict)  # Trigger source, session, user intent

    def add_task(self, task_id: str) -> None:
        """Add a task to this team."""
        if task_id not in self.task_ids:
            self.task_ids.append(task_id)
            self.updated_at = int(time.time() * 1000)

    def remove_task(self, task_id: str) -> None:
        """Remove a task from this team."""
        if task_id in self.task_ids:
            self.task_ids.remove(task_id)
            self.updated_at = int(time.time() * 1000)

    def mark_running(self) -> None:
        """Transition to RUNNING state."""
        if self.status != TeamStatus.CREATED:
            raise ValueError(f"Cannot mark running: team is {self.status}")
        self.status = TeamStatus.RUNNING
        self.updated_at = int(time.time() * 1000)

    def mark_completed(self) -> None:
        """Transition to COMPLETED state."""
        self.status = TeamStatus.COMPLETED
        self.updated_at = int(time.time() * 1000)

    def mark_failed(self) -> None:
        """Transition to FAILED state."""
        self.status = TeamStatus.FAILED
        self.updated_at = int(time.time() * 1000)

    def mark_cancelled(self) -> None:
        """Transition to CANCELLED state."""
        if self.status.is_terminal():
            raise ValueError(f"Cannot cancel: team is already {self.status}")
        self.status = TeamStatus.CANCELLED
        self.updated_at = int(time.time() * 1000)


# ============================================================================
# Agent Model
# ============================================================================


@dataclass
class Agent:
    """
    An agent that can execute tasks in lanes.

    Agents have capabilities, specializations, and resource constraints.
    """

    agent_id: str
    name: str
    status: str = "active"  # "active" / "busy" / "offline"
    capabilities: list[str] = field(default_factory=list)  # ["coding", "research", "analysis"]
    specializations: list[str] = field(default_factory=list)  # ["python", "testing", "docs"]
    max_concurrent_tasks: int = 1
    default_permission: str = "implement"  # "audit" / "explain" / "implement"
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Task Graph
# ============================================================================


@dataclass
class TaskGraph:
    """
    A directed acyclic graph of tasks with dependencies.

    Used by the Planner to represent task decomposition results.
    """

    tasks: list[Task] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_task(self, task: Task) -> None:
        """Add a task to the graph."""
        self.tasks.append(task)

    def get_ready_tasks(self) -> list[Task]:
        """Get tasks that are ready to execute (all dependencies satisfied)."""
        completed_ids = {t.task_id for t in self.tasks if t.status == TaskStatus.COMPLETED}
        ready = []
        for task in self.tasks:
            if task.status == TaskStatus.CREATED and all(
                dep_id in completed_ids for dep_id in task.blocked_by
            ):
                ready.append(task)
        return ready

    def is_completed(self) -> bool:
        """Check if all tasks are completed."""
        return all(t.status.is_terminal() for t in self.tasks)
