"""Orchestration REST API (Phase 4).

Mount under ``/api/v1`` from ``backend/main.py``. Provides read access
to lanes and lane events, plus cancellation endpoint for manual control.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.orchestration.events import EventStream
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.models import Lane, LaneStatus

logger = logging.getLogger(__name__)


# ---------- response models ----------


class LaneHeartbeatOut(BaseModel):
    last_ping_at: int
    transport_alive: bool
    status: str


class LaneOut(BaseModel):
    lane_id: str
    task_id: str
    agent_id: str | None = None
    status: LaneStatus
    created_at: int
    started_at: int | None = None
    completed_at: int | None = None
    worktree: str | None = None
    heartbeat: LaneHeartbeatOut | None = None
    error: str | None = None
    permission_preset: str
    metadata: dict


class LaneEventOut(BaseModel):
    event_id: str
    event_type: str
    lane_id: str
    task_id: str
    agent_id: str | None = None
    timestamp: int
    provenance: str
    metadata: dict


class CancelIn(BaseModel):
    reason: str = Field(default="user_cancelled", max_length=200)


# ---------- router factory ----------


def build_router() -> APIRouter:
    """Build orchestration router with fresh registry instances.

    Returns an APIRouter exposing /orchestration/* endpoints.
    """
    router = APIRouter(prefix="/orchestration", tags=["orchestration"])
    lane_registry = LaneRegistry()
    event_stream = EventStream()

    def _to_lane_out(lane: Lane) -> LaneOut:
        hb = None
        if lane.heartbeat:
            hb = LaneHeartbeatOut(
                last_ping_at=lane.heartbeat.last_ping_at,
                transport_alive=lane.heartbeat.transport_alive,
                status=lane.heartbeat.status.value,
            )
        return LaneOut(
            lane_id=lane.lane_id,
            task_id=lane.task_id,
            agent_id=lane.agent_id,
            status=lane.status,
            created_at=lane.created_at,
            started_at=lane.started_at,
            completed_at=lane.completed_at,
            worktree=lane.worktree,
            heartbeat=hb,
            error=lane.error,
            permission_preset=lane.permission_preset,
            metadata=dict(lane.metadata),
        )

    @router.get("/lanes", response_model=list[LaneOut])
    async def list_lanes(
        status: Optional[LaneStatus] = Query(default=None),
        team_id: Optional[str] = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[LaneOut]:
        """List lanes with optional filters.

        Args:
            status: Filter by lane status
            team_id: Filter by team ID (via task join)
            limit: Max results (1-500)

        Returns:
            List of matching lanes
        """
        if status is not None:
            lanes = lane_registry.list_lanes_by_status(status, limit=limit)
        else:
            # All lanes — use list_all if available, else list by each status
            try:
                lanes = lane_registry.list_all_lanes()
            except AttributeError:
                lanes = []
                for s in LaneStatus:
                    lanes.extend(lane_registry.list_lanes_by_status(s, limit=limit))

        return [_to_lane_out(lane) for lane in lanes[:limit]]

    @router.get("/lanes/{lane_id}", response_model=LaneOut)
    async def get_lane(lane_id: str) -> LaneOut:
        """Get a single lane by ID.

        Args:
            lane_id: Lane ID

        Raises:
            HTTPException 404: Lane not found
        """
        lane = lane_registry.get_lane(lane_id)
        if lane is None:
            raise HTTPException(status_code=404, detail=f"Lane {lane_id} not found")
        return _to_lane_out(lane)

    @router.get("/lanes/{lane_id}/events", response_model=list[LaneEventOut])
    async def list_lane_events(
        lane_id: str,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[LaneEventOut]:
        """Get event history for a lane.

        Args:
            lane_id: Lane ID
            limit: Max events to return

        Raises:
            HTTPException 404: Lane not found
        """
        # Verify lane exists
        lane = lane_registry.get_lane(lane_id)
        if lane is None:
            raise HTTPException(status_code=404, detail=f"Lane {lane_id} not found")

        events = event_stream.get_lane_events(lane_id, limit=limit)
        return [
            LaneEventOut(
                event_id=evt["event_id"],
                event_type=evt["event_type"],
                lane_id=evt["lane_id"],
                task_id=evt["task_id"],
                agent_id=evt["agent_id"],
                timestamp=evt["timestamp"],
                provenance=evt["provenance"],
                metadata=evt["metadata"],
            )
            for evt in events
        ]

    @router.post("/lanes/{lane_id}/cancel", response_model=LaneOut)
    async def cancel_lane(lane_id: str, body: CancelIn) -> LaneOut:
        """Cancel a running or queued lane.

        Args:
            lane_id: Lane ID
            body: Cancellation reason

        Raises:
            HTTPException 404: Lane not found
            HTTPException 409: Lane already in terminal state
        """
        lane = lane_registry.get_lane(lane_id)
        if lane is None:
            raise HTTPException(status_code=404, detail=f"Lane {lane_id} not found")

        if lane.status.is_terminal():
            raise HTTPException(
                status_code=409,
                detail=f"Lane {lane_id} already in terminal state: {lane.status}",
            )

        updated = lane_registry.update_lane_status(lane_id, LaneStatus.STOPPED)
        if not updated:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to cancel lane {lane_id}",
            )

        # Refresh from registry to get updated state
        refreshed = lane_registry.get_lane(lane_id)
        assert refreshed is not None  # Just updated, should exist
        return _to_lane_out(refreshed)

    return router
