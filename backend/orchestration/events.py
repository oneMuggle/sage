"""
Lane Event System - lifecycle event recording and streaming.

Provides event-driven observability for the orchestration layer:
- LaneEvent: Enum of all lane lifecycle events
- LaneEventPayload: Structured event data with provenance tracking
- EventRecorder: Records events to SQLite
- EventStream: Queries events by lane/task/time range

Events are the primary mechanism for:
- Real-time frontend updates (via NDJSON stream)
- Audit trail and debugging
- Recovery policy triggers
- Performance monitoring
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from backend.data.orchestration_repo import LaneEventRepository


class LaneEvent(str, Enum):
    """Lane lifecycle events."""
    # Execution lifecycle
    STARTED = "lane.started"             # Lane created
    READY = "lane.ready"                 # Dependencies satisfied, waiting for agent
    RUNNING = "lane.running"             # Agent started execution
    BLOCKED = "lane.blocked"             # Blocked (waiting for external condition)
    SUCCEEDED = "lane.succeeded"         # Successfully completed
    FAILED = "lane.failed"               # Failed
    STOPPED = "lane.stopped"             # Cancelled

    # Git integration (if supported)
    COMMIT_CREATED = "lane.commit.created"
    PR_OPENED = "lane.pr.opened"
    MERGED = "lane.merged"


class EventProvenance(str, Enum):
    """Event source classification."""
    LIVE_LANE = "LiveLane"               # Normal execution
    RECOVERY = "Recovery"                # Recovery from failure
    RETRY = "Retry"                      # Retry attempt
    HEARTBEAT = "Heartbeat"              # Heartbeat monitor
    MANUAL = "Manual"                    # Manual intervention


@dataclass
class LaneEventPayload:
    """
    Structured event data.

    Attributes:
        event: Event type
        lane_id: Lane that generated the event
        task_id: Task associated with the lane
        agent_id: Agent executing the lane (if bound)
        timestamp: Event timestamp (milliseconds)
        provenance: Event source classification
        metadata: Additional event-specific data
    """
    event: LaneEvent
    lane_id: str
    task_id: str
    agent_id: str | None = None
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))
    provenance: EventProvenance = EventProvenance.LIVE_LANE
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event": self.event.value,
            "lane_id": self.lane_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "provenance": self.provenance.value,
            "metadata": self.metadata,
        }


class EventRecorder:
    """
    Records lane events to SQLite.

    The recorder is called by registries whenever a lane state transition occurs.
    Each event is persisted with full context for audit and replay.
    """

    def __init__(self, repo: LaneEventRepository | None = None) -> None:
        self.repo = repo or LaneEventRepository()

    def record(
        self,
        event: LaneEvent,
        lane_id: str,
        task_id: str,
        agent_id: str | None = None,
        provenance: EventProvenance = EventProvenance.LIVE_LANE,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Record a lane event.

        Args:
            event: Event type
            lane_id: Lane that generated the event
            task_id: Task associated with the lane
            agent_id: Agent executing the lane (if bound)
            provenance: Event source classification
            metadata: Additional event-specific data

        Returns:
            Event ID
        """
        return self.repo.append(
            event_type=event.value,
            lane_id=lane_id,
            task_id=task_id,
            agent_id=agent_id,
            provenance=provenance.value,
            metadata=metadata or {},
        )

    def record_payload(self, payload: LaneEventPayload) -> str:
        """Record a pre-constructed event payload."""
        return self.record(
            event=payload.event,
            lane_id=payload.lane_id,
            task_id=payload.task_id,
            agent_id=payload.agent_id,
            provenance=payload.provenance,
            metadata=payload.metadata,
        )


class EventStream:
    """
    Queries lane events for replay and observability.

    The stream provides read-only access to the event log, supporting:
    - Query by lane_id (single lane history)
    - Query by task_id (cross-lane task history)
    - Time-range queries (for monitoring dashboards)
    """

    def __init__(self, repo: LaneEventRepository | None = None) -> None:
        self.repo = repo or LaneEventRepository()

    def get_lane_events(
        self, lane_id: str, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """
        Get all events for a lane, ordered by timestamp.

        Args:
            lane_id: Lane to query
            limit: Max events to return
            offset: Skip first N events

        Returns:
            List of event dicts
        """
        return self.repo.list_by_lane(lane_id, limit=limit, offset=offset)

    def get_task_events(
        self, task_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Get all events for a task (across all lanes).

        Args:
            task_id: Task to query
            limit: Max events to return

        Returns:
            List of event dicts
        """
        return self.repo.list_by_task(task_id, limit=limit)

    def replay_lane(self, lane_id: str) -> list[LaneEventPayload]:
        """
        Replay a lane's event history as structured payloads.

        Useful for debugging and understanding lane execution flow.

        Args:
            lane_id: Lane to replay

        Returns:
            List of LaneEventPayload objects
        """
        events = self.repo.list_by_lane(lane_id, limit=1000)
        payloads = []

        for evt in events:
            payload = LaneEventPayload(
                event=LaneEvent(evt["event_type"]),
                lane_id=evt["lane_id"],
                task_id=evt["task_id"],
                agent_id=evt["agent_id"],
                timestamp=evt["timestamp"],
                provenance=EventProvenance(evt["provenance"]),
                metadata=evt["metadata"],
            )
            payloads.append(payload)

        return payloads
