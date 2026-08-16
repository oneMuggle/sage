"""Orchestration REST API (Phase 4).

Mount under ``/api/v1`` from ``backend/main.py``. Provides:

- ``POST /orchestration/lanes`` — M5: decompose a goal via the Planner and
  create tasks + lanes (planner-created lanes carry ``metadata.source =
  "planner"`` for the LaneBoard).
- ``GET /orchestration/lanes`` / ``GET /orchestration/lanes/{id}`` — lane
  listing/detail (state, agent, metadata, heartbeat).
- ``GET /orchestration/lanes/{id}/events`` — lane event history.
- ``POST /orchestration/lanes/{id}/cancel`` — manual cancellation.
- ``GET /orchestration/board`` — LaneBoard 监控快照（active/blocked/finished +
  freshness_summary，Wave 3 B3 暴露 HTTP）。

Registries are constructed per-request (they are thin SQLite wrappers over
the shared ``get_database()`` singleton) so test fixtures that swap the DB
see fresh state, and no import-time singleton is captured.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.orchestration.events import EventProvenance, EventRecorder, EventStream, LaneEvent
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.llm_factory import load_llm_config_from_settings
from backend.orchestration.models import HeartbeatStatus, Lane, LaneStatus, Task

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
    # Wave 3 B2 (2026-08-14): wait=true 时携带验证环结果（可选）。
    review: Optional[Dict[str, Any]] = None


class CancelIn(BaseModel):
    reason: str = Field(default="user_cancelled", max_length=200)


# ---------- serialization helpers ----------


def _to_lane_out(lane: Lane) -> LaneOut:
    hb = None
    if lane.heartbeat:
        # Wave 3 B2: 真实执行后 lane 会 RUNNING → heartbeat 落库，_row_to_lane
        # 用 LaneHeartbeat(**json) 重建，status 是 str 而非 HeartbeatStatus 枚举 ——
        # 这里防御归一，避免 `.value` 抛 AttributeError。
        raw_status = lane.heartbeat.status
        status_val = (
            raw_status.value
            if isinstance(raw_status, HeartbeatStatus)
            else str(raw_status)
        )
        hb = LaneHeartbeatOut(
            last_ping_at=lane.heartbeat.last_ping_at,
            transport_alive=lane.heartbeat.transport_alive,
            status=status_val,
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
    """Build orchestration router with fresh registry instances.

    Returns an APIRouter exposing /orchestration/* endpoints.
    """
    router = APIRouter(prefix="/orchestration", tags=["orchestration"])
    lane_registry = LaneRegistry()
    event_stream = EventStream()

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

    @router.get("/lanes/{lane_id}/events", response_model=List[LaneEventOut])
    async def list_lane_events(
        lane_id: str,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> List[LaneEventOut]:
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

    @router.post("/lanes", response_model=CreateLanesOut, status_code=200)
    async def create_lanes(body: CreateLanesIn, wait: bool = False) -> CreateLanesOut:
        """Decompose a goal and create planner tasks + execution lanes (M5).

        Flow: Planner (LLM if configured, single-task fallback otherwise)
        decomposes the goal into a task DAG → each task gets a lane via the
        capability Router (or an explicit / hinted seeded agent) → a
        ``lane.started`` event is recorded so the board and event history
        reflect the new lanes immediately.

        Wave 3 B2 (2026-08-14): ``wait=true`` additionally executes the
        created lanes synchronously (P2-10 API lane execution — scripts/CI
        use this to get terminal states + the review verdict in one round
        trip); ``wait=false`` (default) fires execution in the background.

        Args:
            body: ``{goal, agent?}`` — goal is the natural-language objective;
                optional agent pins all lanes to one seeded agent id.
            wait: ``true`` → await execution to terminal state and return the
                review outcome; ``false`` (default) → background task.

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
        created_lanes: List[Lane] = []
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
            created_lanes.append(refreshed)
            lanes_out.append(_to_lane_out(refreshed))

        # Wave 3 B2 (2026-08-14): P2-10 API lane 可执行 —— 默认后台异步，wait=true
        # 同步等终态（脚本/CI 用）。复用 ChatDispatcher 同款 LaneExecutor 语义。
        # 注意 llm_config 必须传 config dict（load_llm_config_from_settings），
        # 而非 LLMClient 实例（build_llm_client_from_settings）—— SubagentRunner
        # 会把它透传给 SageAgent.run_loop → LLMConfig(**llm_config)，实例展开会抛
        # TypeError。
        # 另注意：plan.tasks 是 Task（无 lane_id），lane→task 映射必须来自上面
        # 实际创建的 created_lanes，不能从 plan.tasks 反推（brief 原文有该 bug）。
        review: Optional[Dict[str, Any]] = None
        if wait:
            review = await _execute_plan_lanes(
                plan=plan,
                lanes=[lane_registry.get_lane(item.lane_id) or item for item in created_lanes],
                lane_registry=lane_registry,
                task_registry=task_registry,
                event_recorder=event_recorder,
                llm_config=load_llm_config_from_settings(),
            )
            # 刷新 lanes 终态
            lanes_out = [
                _to_lane_out(lane_registry.get_lane(item.lane_id) or item)
                for item in lanes_out
            ]
        else:
            asyncio.create_task(
                _execute_plan_lanes(
                    plan=plan,
                    lanes=[lane_registry.get_lane(item.lane_id) or item for item in created_lanes],
                    lane_registry=lane_registry,
                    task_registry=task_registry,
                    event_recorder=event_recorder,
                    llm_config=load_llm_config_from_settings(),
                )
            )

        logger.info(
            "Orchestration: created %d lane(s) for team %s (goal=%r, wait=%s)",
            len(lanes_out),
            plan.team_id,
            goal[:60],
            wait,
        )
        return CreateLanesOut(
            ok=True,
            team_id=plan.team_id,
            lanes=lanes_out,
            tasks=[_to_task_out(t) for t in plan.tasks],
            review=review,
        )

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

    @router.get("/board")
    async def board() -> Dict[str, Any]:
        """LaneBoard 监控快照（M4 交付但未暴露 HTTP — P2-10 补暴露）。"""
        from backend.orchestration.lane_board import LaneBoardBuilder

        builder = LaneBoardBuilder(lane_registry=LaneRegistry())
        return builder.build_snapshot(actor="http-api").to_dict()

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


async def _execute_plan_lanes(
    *,
    plan: Any,
    lanes: List[Any],
    lane_registry: Any,
    task_registry: Any,
    event_recorder: Any,
    llm_config: Any,
) -> Optional[Dict[str, Any]]:
    """并行执行 plan 的 lanes（ChatDispatcher._run_subagent 同款语义）。

    - 不强制 DAG 拓扑（与 ChatDispatcher 并行语义一致；spec §7.4 同）。
    - 每 lane 隔离 scratch 目录；run_lane_with_retry + max_lane_iterations 防御。
    - 全部终态后对聚合跑 review（B1 run_review），落 ReviewReport。
    返回 review outcome（wait=true 时携带），后台路径返回 None。
    """
    from pathlib import Path

    from backend.data.database import get_database
    from backend.orchestration.executor import LaneExecutor
    from backend.orchestration.models import RecoveryPolicy, TaskPacket
    from backend.orchestration.orch_settings import load_orch_settings
    from backend.orchestration.review import run_review

    # run_lane_with_retry 必须 lazy import（模块顶部无此符号）—— 单测 patch
    # backend.orchestration.subagent_runner.run_lane_with_retry 即在调用时截获。
    from backend.orchestration.subagent_runner import SubagentRunner, run_lane_with_retry

    settings = load_orch_settings()
    sem = asyncio.Semaphore(settings.max_concurrent_subagents)
    data_dir = Path(get_database().db_path).parent
    scratch_root_dir = data_dir / settings.scratch_root / f"api-{plan.team_id}"

    async def run_one(lane: Any) -> None:
        async with sem:
            task = task_registry.get_task(lane.task_id)
            if task is None:  # 防御：task 缺失 → lane failed
                lane_registry.mark_failed(lane.lane_id, error="task not found")
                return
            goal = task.description or ""
            task.packet = TaskPacket(
                objective=goal,
                recovery_policy=RecoveryPolicy(
                    on_failure="retry", max_retries=settings.max_retries
                ),
            )
            scratch_dir = scratch_root_dir / lane.lane_id
            scratch_dir.mkdir(parents=True, exist_ok=True)
            # P0-3 工作区隔离接线：SubagentRunner 只读
            # task.parameters["goal"] / ["scratch_dir"]（chat_dispatcher.py
            # 同款写法）。不写则子 agent 收空 user message 且拿不到 scratch
            # 根，隔离静默失效。必须与 packet 一起落库，故 repo.update 挪到
            # scratch 目录创建之后。
            task.parameters["goal"] = goal
            task.parameters["scratch_dir"] = str(scratch_dir)
            task_registry.repo.update(task)
            task_registry.mark_running(lane.task_id)
            lane_registry.mark_running(lane.lane_id)
            executor = LaneExecutor(
                lane_registry=lane_registry,
                task_registry=task_registry,
                event_recorder=event_recorder,
                agent_runner=SubagentRunner(llm_config),
            )
            result = await run_lane_with_retry(executor, lane, lane.agent_id)
            iterations = 0
            while result.get("status") == "retrying":
                iterations += 1
                if iterations >= settings.max_lane_iterations:
                    lane_registry.mark_failed(
                        lane.lane_id,
                        error=(
                            f"MAX_ITERATIONS_EXCEEDED: retry loop exceeded "
                            f"max_iterations={settings.max_lane_iterations}"
                        ),
                    )
                    task_registry.mark_failed(lane.task_id, error="max iterations")
                    return
                result = await run_lane_with_retry(executor, lane, lane.agent_id)
            if result.get("status") == "succeeded":
                lane_registry.mark_completed(lane.lane_id, result=result.get("result"))
                task_registry.mark_completed(lane.task_id, result=result.get("result"))
            else:
                err = result.get("error", "lane failed")
                lane_registry.mark_failed(lane.lane_id, error=err)
                task_registry.mark_failed(lane.task_id, error=err)

    await asyncio.gather(*(run_one(lane_obj) for lane_obj in lanes if lane_obj is not None))

    # 全部终态后聚合 + 验证环（ChatDispatcher 同款）。
    outputs = []
    for lane in lanes:
        if lane is None:
            continue
        task = task_registry.get_task(lane.task_id)
        if task is not None and getattr(task, "result", None) is not None:
            outputs.append(str(task.result))
        elif task is not None and task.parameters.get("error"):
            # Task 无 .error 字段 —— mark_failed 把失败证据写进
            # parameters["error"]（brief 原文 getattr(task, "error") 恒 None，
            # 该分支死代码，失败 lane 的错误从不进聚合）。
            outputs.append(f"[failed] {task.parameters['error']}")
    aggregated = "\n\n".join(outputs)
    if not aggregated:
        return None
    try:
        return await run_review(
            run_id=f"api-{plan.team_id}",
            aggregated=aggregated,
            task_registry=task_registry,
            lane_registry=lane_registry,
            event_recorder=event_recorder,
            llm_config=llm_config,
        )
    except Exception as exc:  # noqa: BLE001 — 复核失败降级不阻塞
        logger.warning("API lane review 失败: %s", exc)
        return None
