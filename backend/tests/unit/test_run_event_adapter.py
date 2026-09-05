"""Tests for the lane-event → canonical RunEvent adapter."""

from __future__ import annotations

from backend.domain.orch_events import TaskEventType
from backend.orchestration.events import EventProvenance, LaneEvent
from backend.orchestration.models import Lane, LaneStatus
from backend.orchestration.run_event_adapter import lane_event_to_run_event


def _lane(task_id: str = "task-1", agent_id: str = "agent-a") -> Lane:
    return Lane(
        lane_id="lane-1",
        task_id=task_id,
        agent_id=agent_id,
        status=LaneStatus.CREATED,
    )


def test_ready_maps_to_task_queued():
    event = lane_event_to_run_event(
        run_id="run-1",
        lane=_lane(),
        event=LaneEvent.READY,
        provenance=EventProvenance.LIVE_LANE,
        metadata={"agent_id": "agent-a"},
    )
    assert event.event_type == TaskEventType.TASK_QUEUED.value
    assert event.run_id == "run-1"
    assert event.entity == {
        "task_id": "task-1",
        "lane_id": "lane-1",
        "agent_id": "agent-a",
    }
    assert event.payload["provenance"] == "LiveLane"
    assert event.payload["agent_id"] == "agent-a"
    assert event.seq == 0  # caller (EventHub) assigns the real seq
    assert event.producer == "lane-executor"


def test_running_live_lane_maps_to_task_started():
    event = lane_event_to_run_event(
        run_id="run-1",
        lane=_lane(),
        event=LaneEvent.RUNNING,
        provenance=EventProvenance.LIVE_LANE,
    )
    assert event.event_type == TaskEventType.TASK_STARTED.value


def test_running_retry_maps_to_task_retrying():
    event = lane_event_to_run_event(
        run_id="run-1",
        lane=_lane(),
        event=LaneEvent.RUNNING,
        provenance=EventProvenance.RETRY,
        metadata={"retry_count": 2, "error": "timeout"},
    )
    assert event.event_type == TaskEventType.TASK_RETRYING.value
    assert event.payload["retry_count"] == 2
    assert event.payload["error"] == "timeout"


def test_succeeded_maps_to_task_succeeded():
    event = lane_event_to_run_event(
        run_id="run-1",
        lane=_lane(),
        event=LaneEvent.SUCCEEDED,
        provenance=EventProvenance.LIVE_LANE,
        metadata={"output_preview": "short summary"},
    )
    assert event.event_type == TaskEventType.TASK_SUCCEEDED.value
    assert event.payload["output_preview"] == "short summary"


def test_failed_maps_to_task_failed():
    event = lane_event_to_run_event(
        run_id="run-1",
        lane=_lane(),
        event=LaneEvent.FAILED,
        provenance=EventProvenance.LIVE_LANE,
        metadata={"error": "boom", "error_code": "TASK_NOT_FOUND"},
    )
    assert event.event_type == TaskEventType.TASK_FAILED.value
    assert event.payload["error"] == "boom"
    assert event.payload["error_code"] == "TASK_NOT_FOUND"


def test_stopped_maps_to_task_cancelled():
    event = lane_event_to_run_event(
        run_id="run-1",
        lane=_lane(),
        event=LaneEvent.STOPPED,
        provenance=EventProvenance.MANUAL,
        metadata={"reason": "user_cancelled"},
    )
    assert event.event_type == TaskEventType.TASK_CANCELLED.value
    assert event.payload["reason"] == "user_cancelled"


def test_unknown_lane_event_falls_back_to_task_progress():
    event = lane_event_to_run_event(
        run_id="run-1",
        lane=_lane(),
        event=LaneEvent.REVIEW_SUBMITTED,
        provenance=EventProvenance.LIVE_LANE,
    )
    assert event.event_type == "task.progress"


def test_producer_generation_propagates():
    event = lane_event_to_run_event(
        run_id="run-1",
        lane=_lane(),
        event=LaneEvent.READY,
        provenance=EventProvenance.LIVE_LANE,
        producer_generation=7,
    )
    assert event.producer_generation == 7


def test_metadata_is_copied_not_mutated():
    original = {"agent_id": "agent-a"}
    lane_event_to_run_event(
        run_id="run-1",
        lane=_lane(),
        event=LaneEvent.SUCCEEDED,
        provenance=EventProvenance.LIVE_LANE,
        metadata=original,
    )
    # Original must remain unchanged even though adapter inserts output_preview.
    assert set(original.keys()) == {"agent_id"}
