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
