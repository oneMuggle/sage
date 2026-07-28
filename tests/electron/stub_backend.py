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

M1 tool security hardening (permission-approval E2E):
- GET /api/v1/permissions/pending
- POST /api/v1/permissions/{request_id}/answer
- GET /api/v1/_test/permission_answers (inspection endpoint for tests)

M2 part B AskUserQuestion (question-answer E2E):
- GET /api/v1/questions/pending
- POST /api/v1/questions/{request_id}/answer
- GET /api/v1/_test/question_answers (inspection endpoint for tests)

When the chat/stream POST message contains the marker ``__PERM_TEST__``,
the attach stream emits ``acting`` → ``permission_request`` and BLOCKS
(up to 25s) until the matching answer POST resolves the request — mimicking
the real backend ApprovalGate (backend/services/permission_gate.py).
After resolution it emits ``observing`` → ``content_delta`` → ``done``.

When the message contains ``__QUESTION_TEST__`` instead, the attach stream
emits ``acting`` → ``ask_user_question`` and BLOCKS (up to 25s) until the
matching answer POST resolves — mimicking UserQuestionGate
(backend/services/question_gate.py), including empty-answer timeout
semantics ("用户未回答" soft result).

Supports Task 6 office_refs authorization checks in chat/stream.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

#: Marker in the chat message that makes the stub stream emit a
#: permission_request event and block until answered (M1 E2E).
PERM_TEST_MARKER = "__PERM_TEST__"

#: How long the gated stream waits for an answer before failing closed
#: (mirrors backend default-deny semantics; real backend waits 300s).
PERM_WAIT_TIMEOUT_S = 25.0

#: Marker in the chat message that makes the stub stream emit an
#: ask_user_question event and block until answered (M2 part B E2E).
QUESTION_TEST_MARKER = "__QUESTION_TEST__"

#: How long the question-gated stream waits for an answer before resolving
#: to an empty answer (mirrors UserQuestionGate timeout; real: 300s).
QUESTION_WAIT_TIMEOUT_S = 25.0


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
        self._server = None  # type: Optional[ThreadingHTTPServer]
        self._thread = None  # type: Optional[threading.Thread]
        self._db = None  # type: Optional[sqlite3.Connection]
        # M1 permission-gate state (in-memory; threads share it):
        #   streams:  stream_id → message (POST /chat/stream 记录的原始消息)
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
        """Start the HTTP server in a background daemon thread.

        ThreadingHTTPServer（而非 HTTPServer）：M1 审批流在 GET 流请求里
        阻塞等待 answer POST 到达 — 单线程服务器会死锁。每个请求一个
        线程；sqlite 连接已开 check_same_thread=False。
        """
        handler_factory = _make_handler(self._db, self._lock, self._state)
        self._server = ThreadingHTTPServer((self._host, self._port), handler_factory)
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

    @property
    def state(self):
        # type: () -> Dict[str, Any]
        """Return the in-memory permission-gate state (for test inspection)."""
        return self._state


def _make_handler(db, lock, state):
    # type: (sqlite3.Connection, threading.Lock, Dict[str, Any]) -> type
    """Create a request handler class with access to the shared database
    and the in-memory permission-gate state (M1)."""

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

        def _write_ndjson_line(self, evt):
            # type: (Dict[str, Any]) -> None
            """Write + flush a single NDJSON line (for gated streams)."""
            line = json.dumps(evt, ensure_ascii=False) + "\n"
            self.wfile.write(line.encode("utf-8"))
            self.wfile.flush()

        def _handle_chat_stream_attach(self, stream_id):
            # type: (str) -> None
            """Emit the NDJSON stream for an attached chat stream.

            Default: thinking → content_delta → done (pre-M1 behavior).
            When the POSTed message contains PERM_TEST_MARKER: emit
            acting → permission_request, BLOCK until the answer POST
            resolves the gate event (or PERM_WAIT_TIMEOUT_S), then emit
            observing → content_delta → done — mimicking backend
            ApprovalGate fail-closed semantics.
            """
            with lock:
                message = state["streams"].get(stream_id, "")

            if QUESTION_TEST_MARKER in message:
                self._handle_gated_question_stream()
                return

            if PERM_TEST_MARKER not in message:
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

            # ── M1 gated flow ─────────────────────────────────────────
            request_id = "perm-{}".format(uuid.uuid4().hex[:12])
            gate_event = threading.Event()
            perm_request = {
                "request_id": request_id,
                "tool_name": "terminal",
                "args_summary": json.dumps({"command": "ls -la"}),
                "risk": "suspicious",
                "message": "stub gate: execute 能力工具 terminal 需要用户逐次确认",
                "created_at": time.time(),
            }
            with lock:
                state["pending"][request_id] = perm_request
                state["events"][request_id] = gate_event

            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()

            base = {"iteration": 1, "agent_id": "stub-agent"}
            self._write_ndjson_line(
                dict(
                    base,
                    state="acting",
                    content=None,
                    reasoning=None,
                    tool_call={
                        "id": "call-stub-1",
                        "type": "function",
                        "function": {
                            "name": "terminal",
                            "arguments": json.dumps({"command": "ls -la"}),
                        },
                    },
                    tool_result=None,
                    error=None,
                )
            )
            self._write_ndjson_line(
                {
                    "state": "permission_request",
                    "iteration": 1,
                    "agent_id": None,
                    "content": None,
                    "reasoning": None,
                    "tool_call": None,
                    "tool_result": None,
                    "error": None,
                    "permission_request": perm_request,
                }
            )

            answered = gate_event.wait(PERM_WAIT_TIMEOUT_S)
            with lock:
                approved = bool(state["verdicts"].get(request_id, False))
                state["pending"].pop(request_id, None)
                state["events"].pop(request_id, None)

            if answered and approved:
                tool_content = "total 8\ndrwxr-xr-x 2 stub stub 4096 ."
                final = "已执行 terminal，结果如上。"
            elif answered:
                tool_content = "权限拒绝: 用户拒绝了工具调用"
                final = "好的，已跳过该操作。"
            else:
                tool_content = "权限拒绝: 审批超时（fail-closed）"
                final = "审批超时，已跳过该操作。"

            self._write_ndjson_line(
                dict(
                    base,
                    state="observing",
                    content=None,
                    reasoning=None,
                    tool_call=None,
                    tool_result={
                        "tool_call_id": "call-stub-1",
                        "role": "tool",
                        "content": tool_content,
                    },
                    error=None,
                )
            )
            self._write_ndjson_line(
                dict(
                    base,
                    state="content_delta",
                    content=final,
                    reasoning=None,
                    tool_call=None,
                    tool_result=None,
                    error=None,
                )
            )
            self._write_ndjson_line(
                dict(
                    base,
                    state="done",
                    content=final,
                    reasoning=None,
                    tool_call=None,
                    tool_result=None,
                    error=None,
                )
            )

        def _handle_gated_question_stream(self):
            # type: () -> None
            """Emit the M2 part B gated question stream.

            acting → ask_user_question, BLOCK until the answer POST
            resolves the gate event (or QUESTION_WAIT_TIMEOUT_S → empty
            answer), then observing → content_delta → done — mimicking
            UserQuestionGate (backend/services/question_gate.py).
            """
            request_id = "q-{}".format(uuid.uuid4().hex[:12])
            gate_event = threading.Event()
            user_question = {
                "request_id": request_id,
                "question": "选择输出格式?",
                "header": "输出格式",
                "options": [
                    {"label": "Markdown", "description": "纯文本报告"},
                    {"label": "PDF", "description": "排版文档"},
                ],
                "multi_select": False,
                "created_at": time.time(),
            }
            with lock:
                state["questions"][request_id] = user_question
                state["question_events"][request_id] = gate_event

            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()

            base = {"iteration": 1, "agent_id": "stub-agent"}
            self._write_ndjson_line(
                dict(
                    base,
                    state="acting",
                    content=None,
                    reasoning=None,
                    tool_call={
                        "id": "call-stub-q1",
                        "type": "function",
                        "function": {
                            "name": "ask_user_question",
                            "arguments": json.dumps(
                                {
                                    "question": user_question["question"],
                                    "options": user_question["options"],
                                },
                                ensure_ascii=False,
                            ),
                        },
                    },
                    tool_result=None,
                    error=None,
                )
            )
            self._write_ndjson_line(
                {
                    "state": "ask_user_question",
                    "iteration": 1,
                    "agent_id": None,
                    "content": None,
                    "reasoning": None,
                    "tool_call": None,
                    "tool_result": None,
                    "error": None,
                    "user_question": user_question,
                }
            )

            answered = gate_event.wait(QUESTION_WAIT_TIMEOUT_S)
            with lock:
                verdict = state["question_verdicts"].get(request_id) or {}
                answers = list(verdict.get("answers") or [])
                custom = verdict.get("custom")
                state["questions"].pop(request_id, None)
                state["question_events"].pop(request_id, None)

            if answers or custom:
                parts = list(answers)
                if custom:
                    parts.append(custom)
                tool_content = "用户已回答:\n" + "\n".join("- " + p for p in parts)
                final = "已回答: {}".format(", ".join(parts))
            else:
                # 超时 / 空提交 → 与真实后端一致的软结果
                tool_content = "用户未回答，请自行决定合理默认值"
                final = "未收到回答，已按默认 Markdown 输出。"

            self._write_ndjson_line(
                dict(
                    base,
                    state="observing",
                    content=None,
                    reasoning=None,
                    tool_call=None,
                    tool_result={
                        "tool_call_id": "call-stub-q1",
                        "role": "tool",
                        "content": tool_content,
                    },
                    error=None,
                )
            )
            self._write_ndjson_line(
                dict(
                    base,
                    state="content_delta",
                    content=final,
                    reasoning=None,
                    tool_call=None,
                    tool_result=None,
                    error=None,
                )
            )
            self._write_ndjson_line(
                dict(
                    base,
                    state="done",
                    content=final,
                    reasoning=None,
                    tool_call=None,
                    tool_result=None,
                    error=None,
                )
            )

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
                self._handle_chat_stream_attach(m.group(1))
                return

            # GET /api/v1/permissions/pending (M1)
            if path == "/api/v1/permissions/pending":
                with lock:
                    pending = list(state["pending"].values())
                self._send_json(200, pending)
                return

            # GET /api/v1/_test/permission_answers (M1 — test inspection only)
            if path == "/api/v1/_test/permission_answers":
                with lock:
                    answers = list(state["answers"])
                self._send_json(200, {"answers": answers})
                return

            # GET /api/v1/questions/pending (M2 part B)
            if path == "/api/v1/questions/pending":
                with lock:
                    pending = list(state["questions"].values())
                self._send_json(200, pending)
                return

            # GET /api/v1/_test/question_answers (M2 part B — test inspection)
            if path == "/api/v1/_test/question_answers":
                with lock:
                    answers = list(state["question_answers"])
                self._send_json(200, {"answers": answers})
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
                # M1: remember the message so the attach handler can decide
                # whether to emit the gated permission_request flow.
                with lock:
                    state["streams"][stream_id] = data.get("message", "")
                self._send_json(200, {"streamId": stream_id})
                return

            # POST /api/v1/permissions/{request_id}/answer (M1)
            m = _match(r"^/api/v1/permissions/([^/]+)/answer$", path)
            if m:
                request_id = m.group(1)
                # 与后端 ApprovalAnswerBody extra="forbid" 对齐:
                # 只接受 approved(bool, 必填) / remember(bool, 可选)
                extra_keys = set(data.keys()) - {"approved", "remember"}
                remember = data.get("remember", False)
                if extra_keys or not isinstance(data.get("approved"), bool) or not isinstance(
                    remember, bool
                ):
                    self._send_json(
                        422, {"detail": "body must be {approved: bool, remember?: bool}"}
                    )
                    return
                approved = data["approved"]
                with lock:
                    known = request_id in state["pending"]
                    if known:
                        state["verdicts"][request_id] = approved
                        state["answers"].append(
                            {
                                "request_id": request_id,
                                "approved": approved,
                                "remember": remember,
                            }
                        )
                        gate_event = state["events"].get(request_id)
                    else:
                        gate_event = None
                if not known:
                    self._send_json(200, {"ok": False, "error": "unknown_or_expired"})
                    return
                if gate_event is not None:
                    gate_event.set()
                self._send_json(200, {"ok": True})
                return

            # POST /api/v1/questions/{request_id}/answer (M2 part B)
            m = _match(r"^/api/v1/questions/([^/]+)/answer$", path)
            if m:
                request_id = m.group(1)
                # 与后端 QuestionAnswerBody extra="forbid" 对齐:
                # 只接受 answers(list[str], 可选) / custom(str|None, 可选)
                extra_keys = set(data.keys()) - {"answers", "custom"}
                answers = data.get("answers", [])
                custom = data.get("custom")
                if (
                    extra_keys
                    or not isinstance(answers, list)
                    or not all(isinstance(a, str) for a in answers)
                    or not (custom is None or isinstance(custom, str))
                ):
                    self._send_json(
                        422,
                        {"detail": "body must be {answers?: list[str], custom?: str|null}"},
                    )
                    return
                with lock:
                    known = request_id in state["questions"]
                    if known:
                        state["question_verdicts"][request_id] = {
                            "answers": answers,
                            "custom": custom,
                        }
                        state["question_answers"].append(
                            {
                                "request_id": request_id,
                                "answers": answers,
                                "custom": custom,
                            }
                        )
                        gate_event = state["question_events"].get(request_id)
                    else:
                        gate_event = None
                if not known:
                    self._send_json(200, {"ok": False, "error": "unknown_or_expired"})
                    return
                if gate_event is not None:
                    gate_event.set()
                self._send_json(200, {"ok": True})
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
