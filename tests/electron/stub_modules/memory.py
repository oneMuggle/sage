"""Memory stub routes (Task 5): 4 endpoints for three-tier memory.

Routes registered here:

- POST   /api/v1/memory/(episodic|semantic|working) — write to layer,
                                                       return {id, layer}
- GET    /api/v1/memory/search                      — unified three-tier
                                                       search (q / layer
                                                       query params),
                                                       return {episodic,
                                                       semantic, working}
- GET    /api/v1/memory/profile/{uid}               — return user profile
- POST   /api/v1/memory/consolidate                 — return
                                                       {status: "pending"}

Contract:
    register_memory_routes(registry: dict) -> None

    ``registry`` is the shared route dict keyed by ``(method, path_regex)``
    tuples, values are callables with signature
    ``fn(ctx: StubContext, body: dict, **path_groups) -> None``.
"""
from __future__ import annotations

import time
import uuid
from urllib.parse import urlparse, parse_qs

from .common import send_json


def register_memory_routes(registry: dict) -> None:
    registry[("POST", r"^/api/v1/memory/(?P<layer>episodic|semantic|working)$")] = _write
    registry[("GET", r"^/api/v1/memory/search$")] = _search
    registry[("GET", r"^/api/v1/memory/profile/(?P<uid>[^/]+)$")] = _profile
    registry[("POST", r"^/api/v1/memory/consolidate$")] = _consolidate


def _ensure_tables(ctx):
    ctx.db.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_episodic(
            id TEXT PRIMARY KEY, content TEXT, session_id TEXT, created_at INTEGER);
        CREATE TABLE IF NOT EXISTS memory_semantic(
            id TEXT PRIMARY KEY, content TEXT, session_id TEXT, created_at INTEGER);
        CREATE TABLE IF NOT EXISTS memory_working(
            id TEXT PRIMARY KEY, content TEXT, session_id TEXT, created_at INTEGER);
        CREATE TABLE IF NOT EXISTS memory_profile(
            user_id TEXT PRIMARY KEY, facts TEXT, updated_at INTEGER);
    """
    )


def _write(ctx, body, layer, **_):
    _ensure_tables(ctx)
    mid = "mem_" + uuid.uuid4().hex[:8]
    table = f"memory_{layer}"
    ctx.db.execute(
        f"INSERT INTO {table} VALUES (?,?,?,?)",
        (mid, body.get("content", ""), body.get("session_id", ""), int(time.time() * 1000)),
    )
    ctx.db.commit()
    send_json(ctx, 200, {"id": mid, "layer": layer})


def _search(ctx, body, **_):
    _ensure_tables(ctx)
    parsed = urlparse(ctx.handler.path)
    params = parse_qs(parsed.query)
    q = params.get("q", [""])[0]
    layer_filter = params.get("layer", [None])[0]
    result = {"episodic": [], "semantic": [], "working": []}
    for layer, table in [("episodic", "memory_episodic"),
                         ("semantic", "memory_semantic"),
                         ("working",  "memory_working")]:
        if layer_filter and layer_filter != layer:
            continue
        rows = ctx.db.execute(
            f"SELECT id, content, session_id, created_at FROM {table} WHERE content LIKE ?",
            (f"%{q}%",),
        ).fetchall()
        for r in rows:
            result[layer].append({
                "id": r[0], "content": r[1], "session_id": r[2],
                "created_at_ms": r[3], "layer": layer,
            })
    send_json(ctx, 200, result)


def _profile(ctx, body, uid, **_):
    _ensure_tables(ctx)
    ctx.db.execute(
        "INSERT OR REPLACE INTO memory_profile VALUES (?,?,?)",
        (uid, f"profile facts for {uid}", int(time.time() * 1000)),
    )
    ctx.db.commit()
    send_json(ctx, 200, {
        "user_id": uid,
        "facts": [{"content": f"user {uid} has 3 sessions", "ts": int(time.time() * 1000)}],
    })


def _consolidate(ctx, body, **_):
    send_json(ctx, 200, {"status": "pending"})
