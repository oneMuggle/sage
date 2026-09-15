"""Shared utilities for stub backend feature modules.

Provides:
- StubContext: per-request context object passed to every route handler
- send_json: serialize a dict to JSON and write it to the response
- send_ndjson: write a sequence of dicts as NDJSON streaming response

These helpers carry behavior identical to the inline versions in the
original 948-line stub_backend.py (same Content-Type, same encoding,
same flushing strategy).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional


class StubContext:
    """Per-request context object passed to every route handler.

    Exposes the BaseHTTPRequestHandler (for low-level writes / header access),
    the shared SQLite connection (for sessions/workspace_bindings tables),
    and the threading primitives + state dict shared across requests so that
    gated stream flows (M1 permission_request / M2 part B ask_user_question)
    can coordinate between the attach stream thread and the answer POST thread.

    ``lock`` and ``state`` are optional so future modules (orchestration /
    wiki / memory / evolution) added by Tasks 3-6 can ignore them when they
    don't need the shared gate state.
    """

    def __init__(
        self,
        handler: BaseHTTPRequestHandler,
        db: sqlite3.Connection,
        lock: Optional[threading.Lock] = None,
        state: Optional[Dict[str, Any]] = None,
    ):
        # type: (BaseHTTPRequestHandler, sqlite3.Connection, Optional[threading.Lock], Optional[Dict[str, Any]]) -> None
        self.handler = handler
        self.db = db
        self.lock = lock
        self.state = state


def send_json(ctx: StubContext, status: int, payload: dict):
    # type: (StubContext, int, dict) -> None
    """Send a JSON response.

    Mirrors the original ``_send_json`` method on StubHandler: ``ensure_ascii=False``
    so Chinese strings (会话不存在, etc.) survive a round-trip untouched.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ctx.handler.send_response(status)
    ctx.handler.send_header("Content-Type", "application/json")
    ctx.handler.send_header("Content-Length", str(len(body)))
    ctx.handler.end_headers()
    ctx.handler.wfile.write(body)


def send_ndjson(ctx: StubContext, events: List[Dict[str, Any]]) -> None:
    """Send a non-gated NDJSON streaming response (pre-M1 default path).

    Mirrors the original ``_send_ndjson`` method on StubHandler. Used only by the
    default (non-gated) attach stream branch — gated streams use
    ``_write_ndjson_line`` for incremental flush semantics so each event is
    pushed to the client the moment it is emitted.
    """
    ctx.handler.send_response(200)
    ctx.handler.send_header("Content-Type", "application/x-ndjson")
    ctx.handler.end_headers()
    for ev in events:
        line = (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")
        ctx.handler.wfile.write(line)
    ctx.handler.wfile.flush()
