"""Adapters from legacy lane lifecycle events to canonical RunEvent."""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.domain.orch_events import RunEvent, TaskEventType, make_event
from backend.orchestration.events import EventProvenance, LaneEvent
from backend.orchestration.models import Lane


class RunEventSink:
    """Protocol-like base for the async canonical event publisher."""

    async def publish(self, event: RunEvent) -> RunEvent:
        raise NotImplementedError


def lane_event_to_run_event(
    *,
    run_id: str,
    lane: Lane,
    event: LaneEvent,
    provenance: EventProvenance,
    metadata: Optional[Dict[str, Any]] = None,
    producer_generation: int = 0,
) -> RunEvent:
    """Translate one legacy lane event without changing lane state."""
    metadata = dict(metadata or {})
    event_type = {
        LaneEvent.READY: TaskEventType.TASK_QUEUED.value,
        LaneEvent.RUNNING: TaskEventType.TASK_STARTED.value,
        LaneEvent.SUCCEEDED: TaskEventType.TASK_SUCCEEDED.value,
        LaneEvent.FAILED: TaskEventType.TASK_FAILED.value,
        LaneEvent.STOPPED: TaskEventType.TASK_CANCELLED.value,
    }.get(event, "task.progress")
    if event == LaneEvent.RUNNING and provenance == EventProvenance.RETRY:
        event_type = TaskEventType.TASK_RETRYING.value
    payload = {"provenance": provenance.value, **metadata}
    if event == LaneEvent.SUCCEEDED:
        payload.setdefault("output_preview", metadata.get("output_preview"))
    return make_event(
        run_id=run_id,
        seq=0,
        event_type=event_type,
        producer="lane-executor",
        producer_generation=producer_generation,
        entity={
            "task_id": lane.task_id,
            "lane_id": lane.lane_id,
            "agent_id": lane.agent_id,
        },
        payload=payload,
    )


__all__ = ["RunEventSink", "lane_event_to_run_event"]
