"""Stdlib HTTP server stubbing the Sage backend for Electron Playwright E2E tests.

Pure stdlib (http.server, sqlite3, json) — no FastAPI/Pydantic/uvicorn dependency.
Python 3.8+ compatible.

Implements key API endpoints used by Tasks 1-10:
- GET /health
- POST /api/v1/sessions (create session)
- GET /api/v1/sessions (list sessions)
- GET /api/v1/sessions/{id} (get session)
- PUT /api/v1/sessions/{id}/workspace (bind workspace)
- GET /api/v1/sessions/{id}/workspace (get binding)
- DELETE /api/v1/sessions/{id}/workspace (revoke)
- GET /api/v1/sessions/{id}/workspace/files (search)
- POST /api/v1/chat/stream (create stream)
- GET /api/v1/chat/stream/{stream_id} (attach NDJSON stream)

Supports Task 6 office_refs authorization checks in chat/stream.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse


class StubBackend:
    """Threaded stdlib HTTP server that stubs the Sage backend API.

    Usage:
        stub = StubBackend(port=0)  # random port
        stub.start()
        print(stub.url)  # http://127.0.0.1:12345
        # ... run tests ...
        stub.stop()
    """

    def __init__(self, host="127.0.0.1", port=0):
        # type: (str, int) -> None
        self._host = host
        self._port = port
        self._server = None  # type: Optional[HTTPServer]
        self._thread = None  # type: Optional[threading.Thread]
        self._db = None  # type: Optional[sqlite3.Connection]
        self._init_db()

    def _init_db(self):
        # type: () -> None
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

    def start(self):
        # type: () -> None
        """Start the HTTP server in a background daemon thread."""
        handler_factory = _make_handler(self._db)
        self._server = HTTPServer((self._host, self._port), handler_factory)
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        # type: () -> None
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
    def url(self):
        # type: () -> str
        """Return the base URL of the running server."""
        return "http://{}:{}".format(self._host, self._port)

    @property
    def db(self):
        # type: () -> Optional[sqlite3.Connection]
        """Return the database connection (for test inspection)."""
        return self._db


def _make_handler(db):
    # type: (sqlite3.Connection) -> type
    """Create a request handler class with access to the shared database."""

    class StubHandler(BaseHTTPRequestHandler):
        """HTTP request handler for the stub backend."""

        def log_message(self, format, *args):
            # type: (str, Any) -> None
            """Silence default stderr logging."""
            pass

        def _send_json(self, status, data):
            # type: (int, Any) -> None
            """Send a JSON response."""
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_ndjson(self, events):
            # type: (List[Dict[str, Any]]) -> None
            """Send an NDJSON streaming response."""
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for evt in events:
                line = json.dumps(evt, ensure_ascii=False) + "\n"
                self.wfile.write(line.encode("utf-8"))
                self.wfile.flush()

        def _read_body(self):
            # type: () -> bytes
            """Read the request body."""
            length = int(self.headers.get("Content-Length", 0))
            return self.rfile.read(length) if length else b""

        def _parse_json_body(self):
            # type: () -> Dict[str, Any]
            """Parse the request body as JSON."""
            body = self._read_body()
            if not body:
                return {}
            try:
                return json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}

        def do_GET(self):
            """Handle GET requests."""
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            qs = parse_qs(parsed.query)

            # GET /health
            if path == "/health":
                self._send_json(200, {"status": "ok", "version": "0.1.1-stub"})
                return

            # GET /api/v1/sessions
            if path == "/api/v1/sessions":
                limit = int(qs.get("limit", ["100"])[0])
                offset = int(qs.get("offset", ["0"])[0])
                rows = db.execute(
                    "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
                result = [_session_to_dict(r) for r in rows]
                self._send_json(200, result)
                return

            # GET /api/v1/sessions/{id}
            m = _match(r"^/api/v1/sessions/([^/]+)$", path)
            if m:
                sid = m.group(1)
                row = db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
                if not row:
                    self._send_json(404, {"detail": "会话不存在"})
                    return
                self._send_json(200, _session_to_dict(row))
                return

            # GET /api/v1/sessions/{id}/workspace
            m = _match(r"^/api/v1/sessions/([^/]+)/workspace$", path)
            if m:
                sid = m.group(1)
                row = db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
                if not row:
                    self._send_json(
                        404, {"code": "session_not_found", "message": "会话不存在"}
                    )
                    return
                binding = db.execute(
                    "SELECT * FROM workspace_bindings WHERE session_id = ? AND revoked_at IS NULL ORDER BY generation DESC LIMIT 1",
                    (sid,),
                ).fetchone()
                if not binding:
                    self._send_json(200, {"binding": None})
                else:
                    self._send_json(200, {"binding": _binding_to_dict(binding)})
                return

            # GET /api/v1/sessions/{id}/workspace/files
            m = _match(r"^/api/v1/sessions/([^/]+)/workspace/files$", path)
            if m:
                sid = m.group(1)
                row = db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
                if not row:
                    self._send_json(
                        404, {"code": "session_not_found", "message": "会话不存在"}
                    )
                    return
                binding = db.execute(
                    "SELECT * FROM workspace_bindings WHERE session_id = ? AND revoked_at IS NULL",
                    (sid,),
                ).fetchone()
                if not binding:
                    self._send_json(
                        403,
                        {
                            "code": "workspace_not_bound",
                            "message": "当前会话尚未绑定工作区",
                        },
                    )
                    return
                # Stub: return empty results (real impl does file search)
                self._send_json(200, {"results": [], "total": 0})
                return

            # GET /api/v1/chat/stream/{stream_id}
            m = _match(r"^/api/v1/chat/stream/([^/]+)$", path)
            if m:
                # Stub: return a simple NDJSON stream with thinking -> content -> done
                events = [
                    {
                        "state": "thinking",
                        "iteration": 0,
                        "content": None,
                        "reasoning": "Stub backend processing",
                        "tool_call": None,
                        "tool_result": None,
                        "error": None,
                        "agent_id": "stub-agent",
                    },
                    {
                        "state": "content_delta",
                        "iteration": 0,
                        "content": "Hello from stub backend",
                        "reasoning": None,
                        "tool_call": None,
                        "tool_result": None,
                        "error": None,
                        "agent_id": "stub-agent",
                    },
                    {
                        "state": "done",
                        "iteration": 0,
                        "content": "Hello from stub backend",
                        "reasoning": None,
                        "tool_call": None,
                        "tool_result": None,
                        "error": None,
                        "agent_id": "stub-agent",
                    },
                ]
                self._send_ndjson(events)
                return

            self._send_json(404, {"detail": "stub: no route for {}".format(path)})

        def do_POST(self):
            """Handle POST requests."""
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            data = self._parse_json_body()

            # POST /api/v1/sessions
            if path == "/api/v1/sessions":
                sid = str(uuid.uuid4())
                now = int(time.time() * 1000)
                title = data.get("title", "新对话")
                parent_id = data.get("parent_id")
                db.execute(
                    "INSERT INTO sessions (id, title, created_at, updated_at, parent_id) VALUES (?, ?, ?, ?, ?)",
                    (sid, title, now, now, parent_id),
                )
                db.commit()
                row = db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
                self._send_json(200, _session_to_dict(row))
                return

            # POST /api/v1/sessions/{id}/workspace (bind)
            m = _match(r"^/api/v1/sessions/([^/]+)/workspace$", path)
            if m:
                sid = m.group(1)
                # Accept both snake_case (real backend contract) and camelCase
                # (Electron IPC body fn sends workspacePath per commands.ts:64).
                workspace_path = data.get("workspace_path") or data.get("workspacePath", "")
                if not workspace_path:
                    self._send_json(
                        400,
                        {"code": "invalid_workspace_path", "message": "工作区路径无效"},
                    )
                    return
                row = db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
                if not row:
                    self._send_json(
                        404, {"code": "session_not_found", "message": "会话不存在"}
                    )
                    return
                # Revoke existing binding
                now = int(time.time() * 1000)
                db.execute(
                    "UPDATE workspace_bindings SET revoked_at = ? WHERE session_id = ? AND revoked_at IS NULL",
                    (now, sid),
                )
                # Get max generation
                max_gen_row = db.execute(
                    "SELECT COALESCE(MAX(generation), 0) as max_gen FROM workspace_bindings WHERE session_id = ?",
                    (sid,),
                ).fetchone()
                max_gen = max_gen_row["max_gen"] if max_gen_row else 0
                db.execute(
                    "INSERT INTO workspace_bindings (session_id, workspace_path, generation, activated_at) VALUES (?, ?, ?, ?)",
                    (sid, workspace_path, max_gen + 1, now),
                )
                db.commit()
                binding = db.execute(
                    "SELECT * FROM workspace_bindings WHERE session_id = ? AND revoked_at IS NULL",
                    (sid,),
                ).fetchone()
                self._send_json(200, {"binding": _binding_to_dict(binding)})
                return

            # POST /api/v1/chat/stream
            if path == "/api/v1/chat/stream":
                session_id = data.get("session_id", "")
                office_refs = data.get("office_refs", [])

                # Validate session exists
                row = db.execute(
                    "SELECT * FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
                if not row:
                    self._send_json(
                        404, {"type": "session_not_found", "message": "会话不存在"}
                    )
                    return

                # Validate office_refs if provided (Task 6 authorization)
                if office_refs:
                    binding = db.execute(
                        "SELECT * FROM workspace_bindings WHERE session_id = ? AND revoked_at IS NULL",
                        (session_id,),
                    ).fetchone()
                    if not binding:
                        self._send_json(
                            403,
                            {
                                "type": "workspace_not_bound",
                                "message": "当前会话尚未绑定工作区",
                            },
                        )
                        return
                    workspace_path = data.get("workspace_path") or data.get("workspacePath", "")
                    if workspace_path and binding["workspace_path"] != workspace_path:
                        self._send_json(
                            400,
                            {
                                "type": "workspace_path_mismatch",
                                "message": "工作区路径不匹配",
                            },
                        )
                        return

                stream_id = str(uuid.uuid4())
                self._send_json(200, {"streamId": stream_id})
                return

            self._send_json(404, {"detail": "stub: no route for {}".format(path)})

        def do_PUT(self):
            """Handle PUT requests (same as POST for workspace bind)."""
            self.do_POST()

        def do_DELETE(self):
            """Handle DELETE requests."""
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")

            # DELETE /api/v1/sessions/{id}/workspace
            m = _match(r"^/api/v1/sessions/([^/]+)/workspace$", path)
            if m:
                sid = m.group(1)
                row = db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
                if not row:
                    self._send_json(
                        404, {"code": "session_not_found", "message": "会话不存在"}
                    )
                    return
                binding = db.execute(
                    "SELECT * FROM workspace_bindings WHERE session_id = ? AND revoked_at IS NULL",
                    (sid,),
                ).fetchone()
                if not binding:
                    self._send_json(
                        403,
                        {
                            "code": "workspace_not_bound",
                            "message": "当前会话尚未绑定工作区",
                        },
                    )
                    return
                now = int(time.time() * 1000)
                db.execute(
                    "UPDATE workspace_bindings SET revoked_at = ? WHERE session_id = ?",
                    (now, sid),
                )
                db.commit()
                self._send_json(
                    200, {"revoked": True, "generation": binding["generation"]}
                )
                return

            self._send_json(404, {"detail": "stub: no route for {}".format(path)})

    return StubHandler


def _match(pattern, path):
    # type: (str, str) -> Optional[re.Match]
    """Match a regex pattern against a path."""
    return re.match(pattern, path)


def _session_to_dict(row):
    # type: (sqlite3.Row) -> Dict[str, Any]
    """Convert a session row to dict (matches Session.to_dict() contract)."""
    return {
        "id": row["id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_message_at": row["last_message_at"],
        "message_count": row["message_count"],
        "is_pinned": bool(row["is_pinned"]),
        "metadata": json.loads(row["metadata"]) if row["metadata"] else None,
    }


def _binding_to_dict(row):
    # type: (sqlite3.Row) -> Dict[str, Any]
    """Convert a workspace binding row to dict."""
    return {
        "session_id": row["session_id"],
        "workspace_path": row["workspace_path"],
        "generation": row["generation"],
        "activated_at": row["activated_at"],
        "revoked_at": row["revoked_at"],
    }


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    server = StubBackend(port=port)
    server.start()
    print("Stub backend running at {}".format(server.url))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.stop()
