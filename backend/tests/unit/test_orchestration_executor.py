"""
Unit tests for LaneExecutor (Phase 3).

Tests cover:
- Lane lifecycle: CREATED -> READY -> RUNNING -> SUCCEEDED
- Permission validation and rejection
- Recovery policies: retry, skip, abort-siblings, max-retries
- Event recording at every state transition
- Cancellation
"""

import asyncio
import tempfile

import pytest

from backend.data.database import Database
from backend.data.orchestration_repo import (
    LaneEventRepository,
    LaneRepository,
    TaskRepository,
)
from backend.orchestration.events import EventRecorder, EventStream
from backend.orchestration.executor import LaneExecutionError, LaneExecutor
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.models import (
    Lane,
    LaneStatus,
    RecoveryPolicy,
    Task,
    TaskPacket,
)
from backend.orchestration.task_registry import TaskRegistry


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    db = Database(db_path=tmp_path)
    db.init_db()
    yield db, tmp_path
    import os

    os.unlink(tmp_path)


@pytest.fixture
def registries(temp_db):
    """Create registries wired to the temp database."""
    db, _ = temp_db

    lane_repo = LaneRepository()
    lane_repo.db = db
    task_repo = TaskRepository()
    task_repo.db = db
    event_repo = LaneEventRepository()
    event_repo.db = db

    lane_registry = LaneRegistry(repo=lane_repo)
    task_registry = TaskRegistry(repo=task_repo)

    return {
        "lane_registry": lane_registry,
        "task_registry": task_registry,
        "lane_repo": lane_repo,
        "task_repo": task_repo,
        "event_recorder": EventRecorder(repo=event_repo),
        "event_stream": EventStream(repo=event_repo),
    }


@pytest.fixture
def sample_task(registries):
    """Create a sample task in the registry."""
    return registries["task_registry"].create_task(
        name="test-task",
        description="Sample task for executor tests",
        task_type="general",
    )


@pytest.fixture
def sample_lane(registries, sample_task):
    """Create a sample lane bound to the sample task."""
    return registries["lane_registry"].create_lane(task_id=sample_task.task_id)


# ============================================================================
# Lifecycle Tests
# ============================================================================


class TestLaneLifecycle:
    """Test LaneExecutor lifecycle management."""

    def test_executor_initialization(self, registries):
        """LaneExecutor can be initialized."""
        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
        )
        assert executor.lane_registry is not None
        assert executor.task_registry is not None

    def test_execute_lane_succeeds(self, registries, sample_lane):
        """Lane executes successfully with a custom runner."""

        async def runner(task, agent_id):
            return {"output": "ok", "task_id": task.task_id}

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=runner,
        )

        result = asyncio.run(executor.execute_lane(sample_lane))
        assert result["status"] == "succeeded"
        assert result["lane_id"] == sample_lane.lane_id
        assert result["result"]["output"] == "ok"

        # Lane should now be in SUCCEEDED state
        updated = registries["lane_repo"].get(sample_lane.lane_id)
        assert updated.status == LaneStatus.SUCCEEDED

    def test_execute_lane_emits_events(self, registries, sample_lane):
        """Lane execution emits READY, RUNNING, SUCCEEDED events."""

        async def runner(task, agent_id):
            return {"output": "ok"}

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=runner,
        )

        asyncio.run(executor.execute_lane(sample_lane))

        # Query events
        events = registries["event_stream"].get_lane_events(sample_lane.lane_id)
        event_types = [e["event_type"] for e in events]
        assert "lane.ready" in event_types
        assert "lane.running" in event_types
        assert "lane.succeeded" in event_types

    def test_execute_lane_default_runner_raises(self, registries, sample_lane):
        """Default runner raises LaneExecutionError when no agent_runner set."""
        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            # No agent_runner passed
        )

        result = asyncio.run(executor.execute_lane(sample_lane))
        # Failure path is triggered
        assert result["status"] == "failed"
        assert result["error_code"] == "NO_RUNNER"


# ============================================================================
# Permission Tests
# ============================================================================


class TestPermissionValidation:
    """Test permission validation in LaneExecutor."""

    def test_audit_permission_denies_execute_lane(self, registries, sample_task):
        """AUDIT preset rejects execute_lane actions."""
        # Lane with audit permission
        lane = Lane(
            lane_id="lane-audit-001",
            task_id=sample_task.task_id,
            permission_preset="audit",
        )
        registries["lane_repo"].create(lane)

        async def runner(task, agent_id):
            return {"output": "ok"}

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=runner,
        )

        result = asyncio.run(executor.execute_lane(lane))
        assert result["status"] == "failed"
        assert result["error_code"] == "PERMISSION_DENIED"

    def test_implement_permission_allows_execute_lane(self, registries, sample_task):
        """IMPLEMENT preset allows execute_lane actions."""
        lane = Lane(
            lane_id="lane-impl-001",
            task_id=sample_task.task_id,
            permission_preset="implement",
        )
        registries["lane_repo"].create(lane)

        async def runner(task, agent_id):
            return {"output": "ok"}

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=runner,
        )

        result = asyncio.run(executor.execute_lane(lane))
        assert result["status"] == "succeeded"


# ============================================================================
# Recovery Policy Tests
# ============================================================================


class TestRecoveryPolicy:
    """Test recovery policy application on failure."""

    def _create_task_with_policy(
        self,
        registries,
        on_failure: str,
        max_retries: int = 2,
    ) -> Task:
        """Helper: create a task with a specific recovery policy."""
        packet = TaskPacket(
            objective="Test task",
            recovery_policy=RecoveryPolicy(on_failure=on_failure, max_retries=max_retries),
        )
        task = Task(
            task_id=f"task-{on_failure}-001",
            name="test-task",
            description="Task with recovery policy",
            packet=packet,
        )
        registries["task_repo"].create(task)
        return task

    def test_retry_policy(self, registries):
        """Retry policy retries the lane up to max_retries times."""
        task = self._create_task_with_policy(registries, "retry", max_retries=2)
        lane = registries["lane_registry"].create_lane(task_id=task.task_id)

        call_count = {"n": 0}

        async def flaky_runner(task, agent_id):
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise ValueError("transient error")
            return {"output": "recovered", "calls": call_count["n"]}

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=flaky_runner,
        )

        # First attempt: should fail and trigger retry
        result1 = asyncio.run(executor.execute_lane(lane))
        assert result1["status"] == "retrying"
        assert result1["retry_count"] == 1

        # Reset lane to READY for next attempt (simulating retry dispatch)
        lane.status = LaneStatus.READY
        registries["lane_repo"].update(lane)

        # Second attempt: should succeed
        result2 = asyncio.run(executor.execute_lane(lane))
        assert result2["status"] == "succeeded"
        assert result2["result"]["calls"] == 2

    def test_max_retries_exceeded(self, registries):
        """Lane fails after max_retries is exceeded."""
        task = self._create_task_with_policy(registries, "retry", max_retries=1)
        lane = registries["lane_registry"].create_lane(task_id=task.task_id)

        async def always_fails(task, agent_id):
            raise ValueError("permanent error")

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=always_fails,
        )

        # First attempt: retry
        result1 = asyncio.run(executor.execute_lane(lane))
        assert result1["status"] == "retrying"

        # Reset for second attempt
        lane.status = LaneStatus.READY
        registries["lane_repo"].update(lane)

        # Second attempt: should fail (max retries exceeded)
        result2 = asyncio.run(executor.execute_lane(lane))
        assert result2["status"] == "failed"
        assert result2["error_code"] == "MAX_RETRIES_EXCEEDED"

    def test_skip_policy(self, registries):
        """Skip policy fails the lane without retrying."""
        task = self._create_task_with_policy(registries, "skip")
        lane = registries["lane_registry"].create_lane(task_id=task.task_id)

        async def failing_runner(task, agent_id):
            raise ValueError("error")

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=failing_runner,
        )

        result = asyncio.run(executor.execute_lane(lane))
        assert result["status"] == "failed"
        assert result["error_code"] == "SKIPPED"

    def test_default_policy_fails_immediately(self, registries):
        """Default policy (no packet) fails on first error."""
        task = registries["task_registry"].create_task(
            name="no-packet-task", description="No recovery policy"
        )
        lane = registries["lane_registry"].create_lane(task_id=task.task_id)

        async def failing_runner(task, agent_id):
            raise ValueError("error")

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=failing_runner,
        )

        result = asyncio.run(executor.execute_lane(lane))
        assert result["status"] == "failed"
        assert result["error_code"] == "EXECUTION_ERROR"


# ============================================================================
# Cancellation Tests
# ============================================================================


class TestCancellation:
    """Test lane cancellation."""

    def test_cancel_running_lane(self, registries, sample_lane):
        """Running lane can be cancelled."""
        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
        )

        # Move to RUNNING
        sample_lane.mark_ready()
        registries["lane_repo"].update(sample_lane)
        sample_lane.mark_running()
        registries["lane_repo"].update(sample_lane)

        result = asyncio.run(executor.cancel_lane(sample_lane, reason="user"))
        assert result["status"] == "cancelled"
        assert result["reason"] == "user"

        updated = registries["lane_repo"].get(sample_lane.lane_id)
        assert updated.status == LaneStatus.STOPPED

    def test_cancel_terminal_lane_is_noop(self, registries, sample_lane):
        """Cancelling a terminal lane returns noop."""
        # Transition through READY -> RUNNING -> SUCCEEDED
        sample_lane.mark_ready()
        registries["lane_repo"].update(sample_lane)
        sample_lane.mark_running()
        registries["lane_repo"].update(sample_lane)
        sample_lane.mark_succeeded()
        registries["lane_repo"].update(sample_lane)

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
        )

        result = asyncio.run(executor.cancel_lane(sample_lane))
        assert result["status"] == "noop"


# ============================================================================
# Event Recording Tests
# ============================================================================


class TestEventRecording:
    """Test event recording during lane execution."""

    def test_failed_lane_records_failed_event(self, registries, sample_lane):
        """Failed lane records lane.failed event with error code."""

        async def failing_runner(task, agent_id):
            raise ValueError("test error")

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=failing_runner,
        )

        # Set retry policy
        sample_task = registries["task_registry"].get_task(sample_lane.task_id)
        sample_task.packet = TaskPacket(
            objective="test",
            recovery_policy=RecoveryPolicy(on_failure="skip"),
        )
        registries["task_repo"].update(sample_task)

        asyncio.run(executor.execute_lane(sample_lane))

        events = registries["event_stream"].get_lane_events(sample_lane.lane_id)
        failed_event = next((e for e in events if e["event_type"] == "lane.failed"), None)
        assert failed_event is not None
        assert failed_event["metadata"]["error_code"] == "SKIPPED"

    def test_retry_event_uses_retry_provenance(self, registries):
        """Retry events are tagged with RETRY provenance."""
        packet = TaskPacket(
            objective="test",
            recovery_policy=RecoveryPolicy(on_failure="retry", max_retries=3),
        )
        task = Task(
            task_id="task-retry-001",
            name="retry-task",
            description="Test retry",
            packet=packet,
        )
        registries["task_repo"].create(task)
        lane = registries["lane_registry"].create_lane(task_id=task.task_id)

        async def failing_runner(task, agent_id):
            raise ValueError("error")

        executor = LaneExecutor(
            lane_registry=registries["lane_registry"],
            task_registry=registries["task_registry"],
            event_recorder=registries["event_recorder"],
            agent_runner=failing_runner,
        )

        asyncio.run(executor.execute_lane(lane))

        events = registries["event_stream"].get_lane_events(lane.lane_id)
        retry_event = next((e for e in events if e["provenance"] == "Retry"), None)
        assert retry_event is not None
        assert retry_event["metadata"]["retry_count"] == 1
