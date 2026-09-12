"""Tests for LaneExecutor canonical RunEvent publishing via run_event_sink.

Verifies that the executor, when constructed with a run_event_sink and run_id,
translates each legacy lane lifecycle event into the corresponding canonical
RunEvent and publishes it, without breaking the legacy event_recorder flow.
"""

from __future__ import annotations

import asyncio
import tempfile

import pytest

from backend.data.database import Database
from backend.data.orchestration_repo import (
    LaneEventRepository,
    LaneRepository,
    TaskRepository,
)
from backend.domain.orch_events import RunEvent, TaskEventType
from backend.orchestration.events import EventRecorder
from backend.orchestration.executor import LaneExecutor
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.models import RecoveryPolicy, TaskPacket
from backend.orchestration.run_event_adapter import RunEventSink
from backend.orchestration.task_registry import TaskRegistry


class FakeSink(RunEventSink):
    """Captures every RunEvent published through it."""

    def __init__(self) -> None:
        self.published: list[RunEvent] = []
        self.fail_for_event: str | None = None  # optional: simulate sink error

    async def publish(self, event: RunEvent) -> RunEvent:
        if self.fail_for_event == event.event_type:
            raise RuntimeError("sink boom")
        self.published.append(event)
        return event


@pytest.fixture()
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    db = Database(db_path=tmp_path)
    db.init_db()
    yield db, tmp_path
    import os
    try:
        os.unlink(tmp_path)
    except PermissionError:
        pass  # Windows: sqlite 连接未显式关闭时文件仍被占用，交给系统临时目录回收


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
    }


@pytest.fixture()
def sample_task(registries):
    return registries["task_registry"].create_task(
        name="t1",
        description="d",
        task_type="general",
    )


@pytest.fixture()
def sample_lane(registries, sample_task):
    return registries["lane_registry"].create_lane(task_id=sample_task.task_id)


def test_no_sink_is_silent(registries, sample_lane):
    """Executor without a sink must not break the legacy lifecycle."""

    async def runner(task, agent_id):
        return {"ok": True}

    executor = LaneExecutor(
        lane_registry=registries["lane_registry"],
        task_registry=registries["task_registry"],
        event_recorder=registries["event_recorder"],
        agent_runner=runner,
    )
    result = asyncio.run(executor.execute_lane(sample_lane))
    assert result["status"] == "succeeded"


def test_no_run_id_is_silent(registries, sample_lane):
    """Executor with a sink but no run_id must also be a no-op for canonical."""
    sink = FakeSink()
    executor = LaneExecutor(
        lane_registry=registries["lane_registry"],
        task_registry=registries["task_registry"],
        event_recorder=registries["event_recorder"],
        run_event_sink=sink,
        # no run_id
    )

    async def runner(task, agent_id):
        return {"ok": True}

    executor.agent_runner = runner
    result = asyncio.run(executor.execute_lane(sample_lane))
    assert result["status"] == "succeeded"
    assert sink.published == []


def test_successful_run_publishes_queued_started_succeeded(registries, sample_lane):
    """Happy path publishes canonical task.queued -> task.started -> task.succeeded."""
    sink = FakeSink()

    async def runner(task, agent_id):
        return {"output": "done"}

    executor = LaneExecutor(
        lane_registry=registries["lane_registry"],
        task_registry=registries["task_registry"],
        event_recorder=registries["event_recorder"],
        agent_runner=runner,
        run_event_sink=sink,
        run_id="run-42",
    )
    result = asyncio.run(executor.execute_lane(sample_lane))
    assert result["status"] == "succeeded"

    types = [e.event_type for e in sink.published]
    assert types == [
        TaskEventType.TASK_QUEUED.value,
        TaskEventType.TASK_STARTED.value,
        TaskEventType.TASK_SUCCEEDED.value,
    ]
    # Each event should carry the correct run_id and entity task_id.
    for event in sink.published:
        assert event.run_id == "run-42"
        assert event.entity["task_id"] == sample_lane.task_id
        assert event.entity["lane_id"] == sample_lane.lane_id
    # Succeeded event should include result_keys in payload.
    succeeded = sink.published[-1]
    assert succeeded.payload.get("result_keys") == ["output"]


def test_failure_publishes_queued_started_failed(registries, sample_lane):
    """Failure path publishes task.failed with error metadata."""
    sink = FakeSink()

    async def runner(task, agent_id):
        raise RuntimeError("boom")

    executor = LaneExecutor(
        lane_registry=registries["lane_registry"],
        task_registry=registries["task_registry"],
        event_recorder=registries["event_recorder"],
        agent_runner=runner,
        run_event_sink=sink,
        run_id="run-99",
    )
    result = asyncio.run(executor.execute_lane(sample_lane))
    assert result["status"] == "failed"

    types = [e.event_type for e in sink.published]
    assert types == [
        TaskEventType.TASK_QUEUED.value,
        TaskEventType.TASK_STARTED.value,
        TaskEventType.TASK_FAILED.value,
    ]
    failed = sink.published[-1]
    assert failed.payload["error"] == "boom"


def test_retry_publishes_retrying(registries):
    """Retry path emits task.retrying."""
    # Create a task with a retry recovery policy via TaskPacket.
    task = registries["task_registry"].create_task(
        name="retry-task",
        description="retryable",
        task_type="general",
    )
    task.packet = TaskPacket(
        objective="retryable",
        recovery_policy=RecoveryPolicy(on_failure="retry", max_retries=2),
    )
    registries["task_repo"].update(task)
    lane = registries["lane_registry"].create_lane(task_id=task.task_id)

    sink = FakeSink()
    attempts = {"n": 0}

    async def flaky_runner(task, agent_id):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("transient")
        return {"ok": True}

    executor = LaneExecutor(
        lane_registry=registries["lane_registry"],
        task_registry=registries["task_registry"],
        event_recorder=registries["event_recorder"],
        agent_runner=flaky_runner,
        run_event_sink=sink,
        run_id="run-retry",
    )
    result = asyncio.run(executor.execute_lane(lane))
    # First call fails with retry policy; the executor returns 'retrying'.
    assert result["status"] == "retrying"

    types = [e.event_type for e in sink.published]
    # queued -> started -> (failed attempt triggers) retrying
    assert TaskEventType.TASK_RETRYING.value in types
    # The retry event should carry the retry_count.
    retry_event = next(
        e for e in sink.published if e.event_type == TaskEventType.TASK_RETRYING.value
    )
    assert retry_event.payload["retry_count"] == 1
    assert retry_event.payload["error"] == "transient"


def test_cancel_publishes_cancelled(registries, sample_lane):
    """cancel_lane emits task.cancelled."""
    sink = FakeSink()
    executor = LaneExecutor(
        lane_registry=registries["lane_registry"],
        task_registry=registries["task_registry"],
        event_recorder=registries["event_recorder"],
        run_event_sink=sink,
        run_id="run-cancel",
    )
    result = asyncio.run(executor.cancel_lane(sample_lane, reason="user_stop"))
    assert result["status"] == "cancelled"
    assert len(sink.published) == 1
    assert sink.published[0].event_type == TaskEventType.TASK_CANCELLED.value
    assert sink.published[0].payload["reason"] == "user_stop"


def test_sink_exception_does_not_break_lane(registries, sample_lane, caplog):
    """A sink error must not fail the lane — observability is best-effort."""
    sink = FakeSink()
    sink.fail_for_event = TaskEventType.TASK_STARTED.value

    async def runner(task, agent_id):
        return {"ok": True}

    executor = LaneExecutor(
        lane_registry=registries["lane_registry"],
        task_registry=registries["task_registry"],
        event_recorder=registries["event_recorder"],
        agent_runner=runner,
        run_event_sink=sink,
        run_id="run-err",
    )
    import logging
    with caplog.at_level(logging.ERROR, logger="backend.orchestration.executor"):
        result = asyncio.run(executor.execute_lane(sample_lane))
    # Lane still succeeds — observability failure is swallowed.
    assert result["status"] == "succeeded"
    assert any("Failed to publish canonical RunEvent" in msg for msg in caplog.messages)
