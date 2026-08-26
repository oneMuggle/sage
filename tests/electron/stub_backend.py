"""Stdlib HTTP server stubbing the Sage backend for Electron Playwright E2E tests.

Pure stdlib (http.server, sqlite3, json, threading) — no FastAPI/Pydantic/
uvicorn dependency. Python 3.8+ compatible.

This module is a thin **lifespan + dispatch skeleton**. All HTTP route
handlers live in ``stub_modules/`` (one module per feature area):

    stub_modules.chat           — chat/stream + office_refs auth + permission
                                   /question gates + sessions/workspace/health
                                   (currently hosts all 17 working routes;
                                   Tasks 3-6 will redistribute)
    stub_modules.orchestration  — placeholder (Task 3 fills it in)
    stub_modules.wiki           — placeholder (Task 4 fills it in)
    stub_modules.memory         — placeholder (Task 5 fills it in)
    stub_modules.evolution      — placeholder (Task 6 fills it in)

Public contract:

    stub = StubBackend(port=0)         # random port
    stub.start()                       # spawns daemon thread
    stub.url                           # 'http://127.0.0.1:<port>'
    stub.db                            # shared sqlite3 connection
    stub.state                         # shared gate-state dict
    stub.stop()                        # shutdown + join

The handler is **ThreadingHTTPServer** (not HTTPServer): M1's gated stream
emits a ``permission_request`` then BLOCKS waiting for the matching answer
POST — a single-threaded server would deadlock. The in-memory SQLite is
opened with ``check_same_thread=False`` so worker threads can share it.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from stub_modules import common
from stub_modules.chat import register_chat_routes
from stub_modules.evolution import register_evolution_routes
from stub_modules.memory import register_memory_routes
from stub_modules.orchestration import register_orchestration_routes
from stub_modules.settings import register_settings_routes
from stub_modules.wiki import register_wiki_routes


class StubBackend:
    """Threaded stdlib HTTP server that stubs the Sage backend API.

    Each ``StubBackend()`` instance owns:
      * a daemon thread serving HTTP requests on a random port
      * an in-memory SQLite database (sessions + workspace_bindings)
      * a threading.lock + state dict for cross-thread gate coordination
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._host = host
        self._port = port
        self._server = None  # type: Optional[ThreadingHTTPServer]
        self._thread = None  # type: Optional[threading.Thread]
        self._db = None  # type: Optional[sqlite3.Connection]
        # M1 permission-gate state (in-memory; threads share it):
        #   streams:  stream_id → message (POST /chat/stream 记录原始消息)
        #   pending:  request_id → permission_request dict
        #   events:   request_id → threading.Event (answer 到达时 set)
        #   verdicts: request_id → bool (approved?) — 供流恢复时读
        #   answers:  按到达顺序记录所有成功应答 (测试断言用)
        self._lock = threading.Lock()
        self._state = {
            "streams": {},
            "pending": {},
            "events": {},
            "verdicts": {},
            "answers": [],
            # M2 part B question-gate state (mirrors the M1 permission gate):
            #   questions:          request_id → user_question dict
            #   question_events:    request_id → threading.Event
            #   question_verdicts:  request_id → {answers, custom}
            #   question_answers:   ordered record of successful answers
            "questions": {},
            "question_events": {},
            "question_verdicts": {},
            "question_answers": [],
        }  # type: Dict[str, Any]
        self._init_db()
        # Build the route registry. Each module contributes its own routes.
        self.routes = {}
        register_chat_routes(self.routes)
        register_orchestration_routes(self.routes)
        register_wiki_routes(self.routes)
        register_memory_routes(self.routes)
        register_evolution_routes(self.routes)
        register_settings_routes(self.routes)

    def _init_db(self) -> None:
        """Initialize in-memory SQLite database with schema."""
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                last_message_at INTEGER,
                message_count INTEGER DEFAULT 0,
                metadata TEXT,
                total_tokens INTEGER DEFAULT 0,
                total_cost REAL DEFAULT 0.0,
                is_pinned INTEGER DEFAULT 0,
                is_archived INTEGER DEFAULT 0,
                parent_id TEXT
            );
            CREATE TABLE IF NOT EXISTS workspace_bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                workspace_path TEXT NOT NULL,
                generation INTEGER NOT NULL,
                activated_at INTEGER NOT NULL,
                revoked_at INTEGER,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
        """
        )
        conn.commit()
        self._db = conn

    def start(self) -> None:
        """Start the HTTP server in a background daemon thread.

        ThreadingHTTPServer (rather than HTTPServer): M1's gated stream blocks
        in GET /chat/stream/{id} until POST /permissions/{id}/answer resolves
        the gate event — a single-threaded server would deadlock. One thread
        per request; the shared SQLite connection is opened with
        ``check_same_thread=False``.
        """
        handler_cls = self._make_handler()
        self._server = ThreadingHTTPServer((self._host, self._port), handler_cls)
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the HTTP server and clean up resources."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        if self._db:
            self._db.close()
            self._db = None

    @property
    def url(self) -> str:
        """Return the base URL of the running server."""
        return "http://{}:{}".format(self._host, self._port)

    @property
    def db(self) -> Optional[sqlite3.Connection]:
        """Return the database connection (for test inspection)."""
        return self._db

    @property
    def state(self) -> Dict[str, Any]:
        """Return the in-memory permission-gate state (for test inspection)."""
        return self._state

    def _make_handler(self):
        """Create a request handler class bound to this instance's routes/db/lock/state."""
        routes = self.routes
        db = self._db
        lock = self._lock
        state = self._state

        class _Handler(BaseHTTPRequestHandler):
            """HTTP request handler that dispatches via regex route table."""

            def log_message(self, format, *args):  # noqa: A002 - signature mandated by stdlib
                """Silence default stderr logging."""
                pass

            def do_GET(self):  # noqa: N802 - signature mandated by stdlib
                self._dispatch("GET")

            def do_POST(self):  # noqa: N802 - signature mandated by stdlib
                self._dispatch("POST")

            def do_PUT(self):  # noqa: N802 - signature mandated by stdlib
                self._dispatch("PUT")

            def do_DELETE(self):  # noqa: N802 - signature mandated by stdlib
                self._dispatch("DELETE")

            def _dispatch(self, method: str) -> None:
                ctx = common.StubContext(self, db, lock, state)
                # Strip query string + trailing slash before regex match so
                # routes anchored with $ don't see query noise.
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/")
                for (m, pattern), fn in routes.items():
                    if m != method:
                        continue
                    match = re.match(pattern, path)
                    if not match:
                        continue
                    body: Dict[str, Any] = {}
                    if method in ("POST", "PUT"):
                        length = int(self.headers.get("Content-Length", 0))
                        if length > 0:
                            body = json.loads(
                                self.rfile.read(length).decode("utf-8")
                            )
                    fn(ctx, body, **match.groupdict())
                    return
                common.send_json(
                    ctx,
                    404,
                    {"error": "not_found", "path": self.path},
                )

        return _Handler


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    server = StubBackend(port=port)
    server.start()
    # Task 9: emit STUB_URL handshake so the Playwright helper can parse
    # the bound URL from stdout. The older "Stub backend running at ..."
    # line is kept for human readability; the helper matches STUB_URL=.
    print("STUB_URL={}".format(server.url), flush=True)
    print("Stub backend running at {}".format(server.url))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.stop()
