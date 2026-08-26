"""Orchestration stub routes (Task 3): 5 endpoints for orchestration runs.

Routes registered here:

- POST   /api/v1/orchestration/runs                 — create run (3 lanes)
- GET    /api/v1/orchestration/runs/{rid}           — run status
- POST   /api/v1/orchestration/runs/{rid}/approve   — record approval token
- POST   /api/v1/orchestration/runs/{rid}/cancel    — set cancelled flag
- GET    /api/v1/orchestration/runs/{rid}/events    — NDJSON event stream

Contract:
    register_orchestration_routes(registry: dict) -> None

    ``registry`` is the shared route dict keyed by ``(method, path_regex)``
    tuples, values are callables with signature
    ``fn(ctx: StubContext, body: dict, **path_groups) -> None``.
"""
from __future__ import annotations

import time
import uuid

from .common import send_json, send_ndjson


def register_orchestration_routes(registry: dict) -> None:
    registry[("POST", r"^/api/v1/orchestration/runs$")] = _create_run
    registry[("GET", r"^/api/v1/orchestration/runs/(?P<rid>[^/]+)$")] = _get_run
    registry[("POST", r"^/api/v1/orchestration/runs/(?P<rid>[^/]+)/approve$")] = _approve
    registry[("POST", r"^/api/v1/orchestration/runs/(?P<rid>[^/]+)/cancel$")] = _cancel
    registry[("GET", r"^/api/v1/orchestration/runs/(?P<rid>[^/]+)/events$")] = _events
    # Phase 4 / M5 IPC contract (commands.ts:359,385):
    # frontend orchestrationClient.{listLanes,createLane} → /api/v1/orchestration/lanes
    registry[("GET", r"^/api/v1/orchestration/lanes$")] = _list_lanes
    registry[("POST", r"^/api/v1/orchestration/lanes$")] = _create_lanes
    # P2-5 board snapshot endpoint (commands.ts:391) — keeps refresh() healthy.
    registry[("GET", r"^/api/v1/orchestration/board$")] = _board_snapshot


def _ensure_table(ctx):
    ctx.db.executescript(
        """
        CREATE TABLE IF NOT EXISTS orchestration_runs(
            run_id TEXT PRIMARY KEY, session_id TEXT, plan TEXT,
            status TEXT, cancelled INTEGER, approval_token TEXT,
            created_at INTEGER);
    """
    )


def _create_run(ctx, body, **_):
    _ensure_table(ctx)
    rid = "run_" + uuid.uuid4().hex[:8]
    ctx.db.execute(
        "INSERT INTO orchestration_runs VALUES (?,?,?,?,?,?,?)",
        (rid, body["session_id"], body["plan"], "running", 0, None, int(time.time() * 1000)),
    )
    ctx.db.commit()
    send_json(
        ctx,
        200,
        {
            "run_id": rid,
            "status": "running",
            "lanes": [
                {"name": "planner", "agent_id": "planner_" + rid, "status": "pending"},
                {"name": "executor", "agent_id": "executor_" + rid, "status": "pending"},
                {"name": "reviewer", "agent_id": "reviewer_" + rid, "status": "pending"},
            ],
        },
    )


def _get_run(ctx, body, rid, **_):
    _ensure_table(ctx)
    row = ctx.db.execute(
        "SELECT run_id, session_id, plan, status, cancelled, approval_token"
        " FROM orchestration_runs WHERE run_id = ?",
        (rid,),
    ).fetchone()
    if not row:
        send_json(ctx, 404, {"error": "run_not_found", "run_id": rid})
        return
    send_json(
        ctx,
        200,
        {
            "run_id": row[0],
            "session_id": row[1],
            "plan": row[2],
            "status": row[3],
            "cancelled": bool(row[4]),
            "approval_token": row[5],
        },
    )


def _cancel(ctx, body, rid, **_):
    _ensure_table(ctx)
    ctx.db.execute(
        "UPDATE orchestration_runs SET cancelled = 1, status = 'cancelled' WHERE run_id = ?",
        (rid,),
    )
    ctx.db.commit()
    send_json(ctx, 200, {"run_id": rid, "cancelled": True})


def _approve(ctx, body, rid, **_):
    _ensure_table(ctx)
    token = body.get("token", "auto_token_" + uuid.uuid4().hex[:6])
    ctx.db.execute(
        "UPDATE orchestration_runs SET approval_token = ?, status = 'approved' WHERE run_id = ?",
        (token, rid),
    )
    ctx.db.commit()
    send_json(ctx, 200, {"run_id": rid, "approval_token": token})


def _events(ctx, body, rid, **_):
    _ensure_table(ctx)
    now_ms = int(time.time() * 1000)
    events = [
        {"run_id": rid, "event_type": "run_started", "ts": now_ms, "lane": "planner"},
        {"run_id": rid, "event_type": "lane_progress", "ts": now_ms + 100, "lane": "planner", "progress": 0.5},
        {"run_id": rid, "event_type": "lane_complete", "ts": now_ms + 200, "lane": "planner"},
    ]
    send_ndjson(ctx, events)


# ─────────────────────────────────────────────────────────────────────────
# Phase 4 / M5 IPC contract: /orchestration/lanes + /orchestration/board
#
# Stub for the M5 lane board. Frontend LaneBoard.tsx renders testids
# `lane-{lane.lane_id}`, so every returned lane MUST have a `lane_id` field.
# `lane_lane_ids` is an in-memory dict keyed by `team_id` so /list shows the
# lanes created via /create (backend stores them in SQLite, stub keeps it
# simple in-memory).
# ─────────────────────────────────────────────────────────────────────────


_LANE_STATE: dict[str, list] = {}


def _new_lane(team_id: str, name: str) -> dict:
    suffix = uuid.uuid4().hex[:8]
    return {
        "lane_id": f"lane_{suffix}",
        "task_id": f"task_{suffix}",
        "agent_id": f"{name}_{suffix}",
        "status": "ready",
        "created_at": int(time.time() * 1000),
        "started_at": None,
        "completed_at": None,
        "worktree": None,
        "heartbeat": None,
        "error": None,
        "permission_preset": "default",
        "metadata": {"source": name, "team_id": team_id},
    }


def _list_lanes(ctx, body, **_):
    all_lanes: [dict] = []
    for lanes in _LANE_STATE.values():
        all_lanes.extend(lanes)
    send_json(ctx, 200, all_lanes)


def _create_lanes(ctx, body, **_):
    team_id = body.get("team_id") or "team_" + uuid.uuid4().hex[:6]
    goal = body.get("goal", "")
    # M5 planner decomposition → 3 lanes (planner / executor / reviewer).
    lanes = [_new_lane(team_id, "planner"),
             _new_lane(team_id, "executor"),
             _new_lane(team_id, "reviewer")]
    # Stash the goal text in planner metadata so deep specs can introspect it.
    if goal and lanes:
        lanes[0]["metadata"] = {**(lanes[0].get("metadata") or {}), "goal": goal}
    _LANE_STATE.setdefault(team_id, []).extend(lanes)
    send_json(ctx, 200, {"ok": True, "team_id": team_id, "lanes": lanes})


def _board_snapshot(ctx, body, **_):
    now_ms = int(time.time() * 1000)
    active = []
    blocked = []
    finished = []
    for lanes in _LANE_STATE.values():
        for lane in lanes:
            entry = {
                "lane_id": lane["lane_id"],
                "task_id": lane["task_id"],
                "agent_id": lane.get("agent_id"),
                "status": lane["status"],
                "created_at": lane["created_at"],
                "started_at": lane.get("started_at"),
                "completed_at": lane.get("completed_at"),
            }
            status = lane["status"]
            if status in ("created", "ready", "running"):
                active.append(entry)
            elif status == "blocked":
                blocked.append(entry)
            else:
                finished.append(entry)
    send_json(ctx, 200, {
        "schema_version": "1.0.0",
        "generated_at": now_ms,
        "generated_by": "stub-orch",
        "active": active,
        "blocked": blocked,
        "finished": finished,
        "freshness_summary": {
            "overall_level": "fresh",
            "total": len(active) + len(blocked) + len(finished),
            "fresh": len(active),
            "stale": 0,
            "dead": 0,
        },
    })
