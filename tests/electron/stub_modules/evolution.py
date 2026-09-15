"""Evolution stub routes (Task 6): 5 endpoints for autonomous evolution.

Routes registered here:

- GET    /api/v1/evolution/signals           — return seeded signal list
- POST   /api/v1/evolution/draft             — accept signal ids, return
                                               {id, status: "pending"}
- GET    /api/v1/evolution/queue             — return draft queue
- POST   /api/v1/evolution/approve/{did}     — set draft status to approved
- GET    /api/v1/evolution/scheduler/status  — return scheduler state/timing

Contract:
    register_evolution_routes(registry: dict) -> None

    ``registry`` is the shared route dict keyed by ``(method, path_regex)``
    tuples, values are callables with signature
    ``fn(ctx: StubContext, body: dict, **path_groups) -> None``.
"""
from __future__ import annotations

import time
import uuid

from .common import send_json

DEFAULT_SIGNALS = [
    {"id": "sig_seed_pattern_repeat_001", "type": "pattern_repeat", "strength": 0.8,
     "created_at_ms": 1700000000000, "session_id": "s1"},
    {"id": "sig_seed_tool_failure_001", "type": "tool_failure", "strength": 0.5,
     "created_at_ms": 1700000001000, "session_id": "s2"},
    {"id": "sig_seed_user_correction_001", "type": "user_correction", "strength": 0.9,
     "created_at_ms": 1700000002000, "session_id": "s1"},
]


def register_evolution_routes(registry: dict) -> None:
    registry[("GET", r"^/api/v1/evolution/signals$")] = _signals
    registry[("POST", r"^/api/v1/evolution/draft$")] = _draft
    registry[("GET", r"^/api/v1/evolution/queue$")] = _queue
    registry[("POST", r"^/api/v1/evolution/approve/(?P<did>[^/]+)$")] = _approve
    registry[("GET", r"^/api/v1/evolution/scheduler/status$")] = _scheduler_status


def _ensure_tables(ctx):
    ctx.db.executescript(
        """
        CREATE TABLE IF NOT EXISTS evolution_signals(
            id TEXT PRIMARY KEY, type TEXT, strength REAL,
            session_id TEXT, created_at_ms INTEGER);
        CREATE TABLE IF NOT EXISTS evolution_drafts(
            id TEXT PRIMARY KEY, signal_ids TEXT, status TEXT,
            created_at_ms INTEGER, updated_at_ms INTEGER);
    """
    )


def _seed(ctx):
    for s in DEFAULT_SIGNALS:
        ctx.db.execute(
            "INSERT OR IGNORE INTO evolution_signals VALUES (?,?,?,?,?)",
            (s["id"], s["type"], s["strength"], s.get("session_id", ""), s["created_at_ms"]),
        )
    ctx.db.commit()


def _signals(ctx, body, **_):
    _ensure_tables(ctx)
    _seed(ctx)
    rows = ctx.db.execute(
        "SELECT id, type, strength, session_id, created_at_ms FROM evolution_signals"
    ).fetchall()
    signals = [
        {"id": r[0], "type": r[1], "strength": r[2], "session_id": r[3], "created_at_ms": r[4]}
        for r in rows
    ]
    send_json(ctx, 200, {"signals": signals})


def _draft(ctx, body, **_):
    _ensure_tables(ctx)
    did = "draft_" + uuid.uuid4().hex[:8]
    signal_ids = body.get("signal_ids", [])
    now = int(time.time() * 1000)
    ctx.db.execute(
        "INSERT INTO evolution_drafts VALUES (?,?,?,?,?)",
        (did, ",".join(signal_ids), "pending", now, now),
    )
    ctx.db.commit()
    send_json(ctx, 200, {"id": did, "status": "pending"})


def _queue(ctx, body, **_):
    _ensure_tables(ctx)
    rows = ctx.db.execute(
        "SELECT id, signal_ids, status, created_at_ms, updated_at_ms FROM evolution_drafts"
    ).fetchall()
    drafts = [
        {"id": r[0], "signal_ids": r[1].split(",") if r[1] else [],
         "status": r[2], "created_at_ms": r[3], "updated_at_ms": r[4]}
        for r in rows
    ]
    send_json(ctx, 200, {"drafts": drafts})


def _approve(ctx, body, did, **_):
    _ensure_tables(ctx)
    now = int(time.time() * 1000)
    ctx.db.execute(
        "UPDATE evolution_drafts SET status = 'approved', updated_at_ms = ? WHERE id = ?",
        (now, did),
    )
    ctx.db.commit()
    send_json(ctx, 200, {"id": did, "status": "approved"})


def _scheduler_status(ctx, body, **_):
    now = int(time.time() * 1000)
    send_json(ctx, 200, {
        "state": "idle",
        "last_run_at_ms": now - 3600_000,
        "next_run_at_ms": now + 3600_000,
    })
