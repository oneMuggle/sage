"""Orchestration REST API (Phase 4 + M5).

Mount under ``/api/v1`` from ``backend/main.py``. Provides:

- ``POST /orchestration/lanes`` — M5: decompose a goal via the Planner and
  create tasks + lanes (planner-created lanes carry ``metadata.source =
  "planner"`` for the LaneBoard).
- ``GET /orchestration/lanes`` / ``GET /orchestration/lanes/{id}`` — lane
  listing/detail (state, agent, metadata, heartbeat).
- ``GET /orchestration/lanes/{id}/events`` — lane event history.
- ``POST /orchestration/lanes/{id}/cancel`` — manual cancellation.

Registries are constructed per-request (they are thin SQLite wrappers over
the shared ``get_database()`` singleton) so test fixtures that swap the DB
see fresh state, and no import-time singleton is captured.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.orchestration.events import EventProvenance, EventRecorder, EventStream, LaneEvent
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.models import Lane, LaneStatus, Task

logger = logging.getLogger(__name__)

# Goal length guard — long enough for real objectives, bounded for sanity.
MAX_GOAL_LENGTH = 4000


# ---------- response models ----------


class LaneHeartbeatOut(BaseModel):
    last_ping_at: int
    transport_alive: bool
    status: str


class LaneOut(BaseModel):
    lane_id: str
    task_id: str
    agent_id: Optional[str] = None
    status: LaneStatus
    created_at: int
    started_at: Optional[int] = None
    completed_at: Optional[int] = None
    worktree: Optional[str] = None
    heartbeat: Optional[LaneHeartbeatOut] = None
    error: Optional[str] = None
    permission_preset: str
    metadata: dict


class TaskOut(BaseModel):
    task_id: str
    name: str
    description: str
    task_type: str
    status: str
    blocked_by: List[str]
    team_id: Optional[str] = None
    agent_hint: Optional[str] = None


class LaneEventOut(BaseModel):
    event_id: str
    event_type: str
    lane_id: str
    task_id: str
    agent_id: Optional[str] = None
    timestamp: int
    provenance: str
    metadata: dict


class CreateLanesIn(BaseModel):
    goal: str = Field(max_length=MAX_GOAL_LENGTH)
    agent: Optional[str] = Field(default=None, max_length=100)


class CreateLanesOut(BaseModel):
    ok: bool
    team_id: str
    lanes: List[LaneOut]
    tasks: List[TaskOut]


class CancelIn(BaseModel):
    reason: str = Field(default="user_cancelled", max_length=200)


# ---------- serialization helpers ----------


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
        metadata=dict(lane.metadata or {}),
    )


def _to_task_out(task: Task) -> TaskOut:
    agent_hint = task.parameters.get("agent_hint") if task.parameters else None
    return TaskOut(
        task_id=task.task_id,
        name=task.name,
        description=task.description,
        task_type=task.task_type,
        status=task.status.value,
        blocked_by=list(task.blocked_by or []),
        team_id=task.team_id,
        agent_hint=agent_hint if isinstance(agent_hint, str) else None,
    )


# ---------- router factory ----------


def build_router() -> APIRouter:
    """Build orchestration router.

    Returns an APIRouter exposing /orchestration/* endpoints.
    """
    router = APIRouter(prefix="/orchestration", tags=["orchestration"])

    @router.get("/lanes", response_model=List[LaneOut])
    async def list_lanes(
        status: Optional[LaneStatus] = Query(default=None),
        team_id: Optional[str] = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> List[LaneOut]:
        """List lanes with optional filters.

        Args:
            status: Filter by lane status
            team_id: Filter by team ID (via task join)
            limit: Max results (1-500)

        Returns:
            List of matching lanes
        """
        lane_registry = LaneRegistry()
        if status is not None:
            lanes = lane_registry.list_lanes_by_status(status, limit=limit)
        else:
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

        Raises:
            HTTPException 404: Lane not found
        """
        lane = LaneRegistry().get_lane(lane_id)
        if lane is None:
            raise HTTPException(status_code=404, detail=f"Lane {lane_id} not found")
        return _to_lane_out(lane)

    @router.get("/lanes/{lane_id}/events", response_model=List[LaneEventOut])
    async def list_lane_events(
        lane_id: str,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> List[LaneEventOut]:
        """Get event history for a lane.

        Raises:
            HTTPException 404: Lane not found
        """
        lane_registry = LaneRegistry()
        lane = lane_registry.get_lane(lane_id)
        if lane is None:
            raise HTTPException(status_code=404, detail=f"Lane {lane_id} not found")

        events = EventStream().get_lane_events(lane_id, limit=limit)
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

    @router.post("/lanes", response_model=CreateLanesOut, status_code=200)
    async def create_lanes(body: CreateLanesIn) -> CreateLanesOut:
        """Decompose a goal and create planner tasks + execution lanes (M5).

        Flow: Planner (LLM if configured, single-task fallback otherwise)
        decomposes the goal into a task DAG → each task gets a lane via the
        capability Router (or an explicit / hinted seeded agent) → a
        ``lane.started`` event is recorded so the board and event history
        reflect the new lanes immediately.

        Args:
            body: ``{goal, agent?}`` — goal is the natural-language objective;
                optional agent pins all lanes to one seeded agent id.

        Raises:
            HTTPException 400: Empty goal, or unknown explicit agent.
        """
        # Lazy imports keep module import cheap and avoid cycles.
        from backend.orchestration.agent_adapter import SeededAgentRegistry
        from backend.orchestration.planner import Planner
        from backend.orchestration.router import Router
        from backend.orchestration.task_registry import TaskRegistry
        from backend.orchestration.team_registry import TeamRegistry

        goal = (body.goal or "").strip()
        if not goal:
            raise HTTPException(status_code=400, detail="goal must not be empty")

        lane_registry = LaneRegistry()
        task_registry = TaskRegistry()
        team_registry = TeamRegistry()
        event_recorder = EventRecorder()
        agent_registry = SeededAgentRegistry()

        # Validate an explicitly requested agent up-front.
        if body.agent is not None and agent_registry.get_agent(body.agent) is None:
            raise HTTPException(
                status_code=400, detail=f"unknown or disabled agent: {body.agent}"
            )

        planner = Planner(task_registry=task_registry, team_registry=team_registry)
        plan = await planner.decompose_request(goal, context={"source": "api"})

        capability_router = Router(
            lane_registry=lane_registry,
            agent_registry=agent_registry,
        )

        lanes_out: List[LaneOut] = []
        for task in plan.tasks:
            lane = await _create_lane_for_task(
                task=task,
                goal=goal,
                explicit_agent=body.agent,
                lane_registry=lane_registry,
                capability_router=capability_router,
            )
            event_recorder.record(
                LaneEvent.STARTED,
                lane_id=lane.lane_id,
                task_id=task.task_id,
                agent_id=lane.agent_id,
                provenance=EventProvenance.MANUAL,
                metadata={"source": "planner", "team_id": plan.team_id},
            )
            refreshed = lane_registry.get_lane(lane.lane_id) or lane
            lanes_out.append(_to_lane_out(refreshed))

        logger.info(
            "Orchestration: created %d lane(s) for team %s (goal=%r)",
            len(lanes_out),
            plan.team_id,
            goal[:60],
        )
        return CreateLanesOut(
            ok=True,
            team_id=plan.team_id,
            lanes=lanes_out,
            tasks=[_to_task_out(t) for t in plan.tasks],
        )

    @router.post("/lanes/{lane_id}/cancel", response_model=LaneOut)
    async def cancel_lane(lane_id: str, body: CancelIn) -> LaneOut:
        """Cancel a running or queued lane.

        Raises:
            HTTPException 404: Lane not found
            HTTPException 409: Lane already in terminal state
        """
        lane_registry = LaneRegistry()
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

        refreshed = lane_registry.get_lane(lane_id)
        assert refreshed is not None  # Just updated, should exist
        return _to_lane_out(refreshed)

    return router


async def _create_lane_for_task(
    task: Task,
    goal: str,
    explicit_agent: Optional[str],
    lane_registry: LaneRegistry,
    capability_router,
) -> Lane:
    """Create (and agent-bind) one lane for a planner task.

    Agent selection priority: explicit request agent > task agent_hint
    matching a seeded agent id > Router capability dispatch. The Router
    fallback never raises out: with no available agents the lane is still
    created unbound (status CREATED) so the board shows the plan.
    """
    lane_metadata = {
        "source": "planner",
        "task_name": task.name,
        "goal": goal[:200],
    }

    hint = task.parameters.get("agent_hint") if task.parameters else None
    target_agent = explicit_agent
    if (
        target_agent is None
        and isinstance(hint, str)
        and hint
        and capability_router.agent_registry.get_agent(hint) is not None
    ):
        target_agent = hint

    if target_agent is not None:
        lane = lane_registry.create_lane(task.task_id, metadata=lane_metadata)
        lane_registry.bind_agent(lane.lane_id, target_agent)
        bound = lane_registry.get_lane(lane.lane_id)
        return bound or lane

    try:
        decision = await capability_router.route_task(task)
    except ValueError as exc:
        logger.warning("Router could not dispatch task %s: %s", task.task_id, exc)
        return lane_registry.create_lane(task.task_id, metadata=lane_metadata)

    lane = lane_registry.get_lane(decision.lane_id)
    if lane is None:  # pragma: no cover — route_task just created it
        return lane_registry.create_lane(task.task_id, metadata=lane_metadata)
    lane.metadata.update(lane_metadata)
    lane_registry.update_lane(lane)
    return lane
