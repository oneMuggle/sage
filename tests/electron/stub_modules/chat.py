"""Chat/stream + office_refs auth + permission/question gates + sessions/workspace/health.

Extracted verbatim from the original ``stub_backend.py`` (Task 2 refactor).
Behavior, response shapes, status codes, and edge-case semantics are all
preserved. The only structural change is that handlers now receive a
``StubContext`` (handler + db + lock + state) instead of closing over
the closure variables of the old ``_make_handler`` factory.

Routing in this module (17 routes):

- GET  /health
- GET  /api/v1/sessions
- POST /api/v1/sessions
- GET  /api/v1/sessions/{sid}
- GET  /api/v1/sessions/{sid}/workspace
- POST /api/v1/sessions/{sid}/workspace   (alias for PUT)
- PUT  /api/v1/sessions/{sid}/workspace
- DELETE /api/v1/sessions/{sid}/workspace
- GET  /api/v1/sessions/{sid}/workspace/files
- POST /api/v1/chat/stream
- GET  /api/v1/chat/stream/{stream_id}
- GET  /api/v1/permissions/pending
- POST /api/v1/permissions/{request_id}/answer
- GET  /api/v1/_test/permission_answers
- GET  /api/v1/questions/pending
- POST /api/v1/questions/{request_id}/answer
- GET  /api/v1/_test/question_answers

Note: only chat/stream is conceptually chat. The other 16 routes are
"scaffolding" routes that the existing 34-test safety net requires to
remain green. They live here until Tasks 3-6 land their own modules and
absorb the routes that are actually theirs (e.g. sessions/workspace could
move into a future "sessions" module). For now, all current routes are
registered by chat.py to keep stub_backend.py routing-only.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from .common import StubContext, send_json, send_ndjson


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


def register_chat_routes(registry: dict):
    """Populate the route registry with all chat/stream + scaffolding routes."""
    # Note on order: more-specific patterns (workspace/files) come BEFORE
    # less-specific ones (workspace) so the dispatcher hits the right match.
    registry[("GET", r"^/health$")] = _health
    registry[("GET", r"^/api/v1/sessions$")] = _list_sessions
    registry[("POST", r"^/api/v1/sessions$")] = _create_session
    registry[("GET", r"^/api/v1/sessions/(?P<sid>[^/]+)/workspace/files$")] = _search_workspace_files
    registry[("GET", r"^/api/v1/sessions/(?P<sid>[^/]+)/workspace$")] = _get_workspace
    registry[("POST", r"^/api/v1/sessions/(?P<sid>[^/]+)/workspace$")] = _bind_workspace
    registry[("PUT", r"^/api/v1/sessions/(?P<sid>[^/]+)/workspace$")] = _bind_workspace
    registry[("DELETE", r"^/api/v1/sessions/(?P<sid>[^/]+)/workspace$")] = _revoke_workspace
    registry[("GET", r"^/api/v1/sessions/(?P<sid>[^/]+)$")] = _get_session
    registry[("POST", r"^/api/v1/chat/stream$")] = _create_stream
    registry[("GET", r"^/api/v1/chat/stream/(?P<sid>[^/]+)$")] = _attach_stream
    registry[("GET", r"^/api/v1/permissions/pending$")] = _list_pending_permissions
    registry[("POST", r"^/api/v1/permissions/(?P<request_id>[^/]+)/answer$")] = _answer_permission
    registry[("GET", r"^/api/v1/_test/permission_answers$")] = _list_permission_answers
    registry[("GET", r"^/api/v1/questions/pending$")] = _list_pending_questions
    registry[("POST", r"^/api/v1/questions/(?P<request_id>[^/]+)/answer$")] = _answer_question
    registry[("GET", r"^/api/v1/_test/question_answers$")] = _list_question_answers


# ─────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────


def _health(ctx: StubContext, body: dict, **_):
    send_json(ctx, 200, {"status": "ok", "version": "0.1.1-stub"})


# ─────────────────────────────────────────────────────────────────────────
# Sessions
# ─────────────────────────────────────────────────────────────────────────


def _list_sessions(ctx: StubContext, body: dict, **_):
    qs = parse_qs(urlparse(ctx.handler.path).query)
    limit = int(qs.get("limit", ["100"])[0])
    offset = int(qs.get("offset", ["0"])[0])
    rows = ctx.db.execute(
        "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    result = [_session_to_dict(r) for r in rows]
    send_json(ctx, 200, result)


def _create_session(ctx: StubContext, body: dict, **_):
    sid = str(uuid.uuid4())
    now = int(time.time() * 1000)
    title = body.get("title", "新对话")
    parent_id = body.get("parent_id")
    ctx.db.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, parent_id) VALUES (?, ?, ?, ?, ?)",
        (sid, title, now, now, parent_id),
    )
    ctx.db.commit()
    row = ctx.db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    send_json(ctx, 200, _session_to_dict(row))


def _get_session(ctx: StubContext, body: dict, *, sid: str):
    row = ctx.db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    if not row:
        send_json(ctx, 404, {"detail": "会话不存在"})
        return
    send_json(ctx, 200, _session_to_dict(row))


# ─────────────────────────────────────────────────────────────────────────
# Workspace bindings
# ─────────────────────────────────────────────────────────────────────────


def _get_workspace(ctx: StubContext, body: dict, *, sid: str):
    row = ctx.db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    if not row:
        send_json(ctx, 404, {"code": "session_not_found", "message": "会话不存在"})
        return
    binding = ctx.db.execute(
        "SELECT * FROM workspace_bindings WHERE session_id = ? AND revoked_at IS NULL "
        "ORDER BY generation DESC LIMIT 1",
        (sid,),
    ).fetchone()
    if not binding:
        send_json(ctx, 200, {"binding": None})
    else:
        send_json(ctx, 200, {"binding": _binding_to_dict(binding)})


def _bind_workspace(ctx: StubContext, body: dict, *, sid: str):
    # Accept both snake_case (real backend contract) and camelCase
    # (Electron IPC body fn sends workspacePath per commands.ts:64).
    workspace_path = body.get("workspace_path") or body.get("workspacePath", "")
    if not workspace_path:
        send_json(
            ctx,
            400,
            {"code": "invalid_workspace_path", "message": "工作区路径无效"},
        )
        return
    row = ctx.db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    if not row:
        send_json(ctx, 404, {"code": "session_not_found", "message": "会话不存在"})
        return
    # Revoke existing binding
    now = int(time.time() * 1000)
    ctx.db.execute(
        "UPDATE workspace_bindings SET revoked_at = ? "
        "WHERE session_id = ? AND revoked_at IS NULL",
        (now, sid),
    )
    # Get max generation
    max_gen_row = ctx.db.execute(
        "SELECT COALESCE(MAX(generation), 0) as max_gen "
        "FROM workspace_bindings WHERE session_id = ?",
        (sid,),
    ).fetchone()
    max_gen = max_gen_row["max_gen"] if max_gen_row else 0
    ctx.db.execute(
        "INSERT INTO workspace_bindings (session_id, workspace_path, generation, activated_at) "
        "VALUES (?, ?, ?, ?)",
        (sid, workspace_path, max_gen + 1, now),
    )
    ctx.db.commit()
    binding = ctx.db.execute(
        "SELECT * FROM workspace_bindings WHERE session_id = ? AND revoked_at IS NULL",
        (sid,),
    ).fetchone()
    send_json(ctx, 200, {"binding": _binding_to_dict(binding)})


def _revoke_workspace(ctx: StubContext, body: dict, *, sid: str):
    row = ctx.db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    if not row:
        send_json(ctx, 404, {"code": "session_not_found", "message": "会话不存在"})
        return
    binding = ctx.db.execute(
        "SELECT * FROM workspace_bindings WHERE session_id = ? AND revoked_at IS NULL",
        (sid,),
    ).fetchone()
    if not binding:
        send_json(
            ctx,
            403,
            {"code": "workspace_not_bound", "message": "当前会话尚未绑定工作区"},
        )
        return
    now = int(time.time() * 1000)
    ctx.db.execute(
        "UPDATE workspace_bindings SET revoked_at = ? WHERE session_id = ?",
        (now, sid),
    )
    ctx.db.commit()
    send_json(
        ctx,
        200,
        {"revoked": True, "generation": binding["generation"]},
    )


def _search_workspace_files(ctx: StubContext, body: dict, *, sid: str):
    row = ctx.db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    if not row:
        send_json(ctx, 404, {"code": "session_not_found", "message": "会话不存在"})
        return
    binding = ctx.db.execute(
        "SELECT * FROM workspace_bindings WHERE session_id = ? AND revoked_at IS NULL",
        (sid,),
    ).fetchone()
    if not binding:
        send_json(
            ctx,
            403,
            {"code": "workspace_not_bound", "message": "当前会话尚未绑定工作区"},
        )
        return
    # Stub: return empty results (real impl does file search)
    send_json(ctx, 200, {"results": [], "total": 0})


# ─────────────────────────────────────────────────────────────────────────
# Chat stream — create + attach
# ─────────────────────────────────────────────────────────────────────────


def _create_stream(ctx: StubContext, body: dict, **_):
    session_id = body.get("session_id", "")
    office_refs = body.get("office_refs", [])

    # Validate session exists
    row = ctx.db.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        send_json(ctx, 404, {"type": "session_not_found", "message": "会话不存在"})
        return

    # Validate office_refs if provided (Task 6 authorization)
    if office_refs:
        binding = ctx.db.execute(
            "SELECT * FROM workspace_bindings WHERE session_id = ? AND revoked_at IS NULL",
            (session_id,),
        ).fetchone()
        if not binding:
            send_json(
                ctx,
                403,
                {"type": "workspace_not_bound", "message": "当前会话尚未绑定工作区"},
            )
            return
        workspace_path = body.get("workspace_path") or body.get("workspacePath", "")
        if workspace_path and binding["workspace_path"] != workspace_path:
            send_json(
                ctx,
                400,
                {"type": "workspace_path_mismatch", "message": "工作区路径不匹配"},
            )
            return

    stream_id = str(uuid.uuid4())
    # M1: remember the message so the attach handler can decide
    # whether to emit the gated permission_request flow.
    with ctx.lock:
        ctx.state["streams"][stream_id] = body.get("message", "")
    send_json(ctx, 200, {"streamId": stream_id})


def _attach_stream(ctx: StubContext, body: dict, *, sid: str):
    """Emit the NDJSON stream for an attached chat stream.

    Default: thinking → content_delta → done (pre-M1 behavior).
    When the POSTed message contains PERM_TEST_MARKER: emit
    acting → permission_request, BLOCK until the answer POST
    resolves the gate event (or PERM_WAIT_TIMEOUT_S), then emit
    observing → content_delta → done — mimicking backend
    ApprovalGate fail-closed semantics.
    """
    stream_id = sid
    with ctx.lock:
        message = ctx.state["streams"].get(stream_id, "")

    if QUESTION_TEST_MARKER in message:
        _handle_gated_question_stream(ctx)
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
        send_ndjson(ctx, events)
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
    with ctx.lock:
        ctx.state["pending"][request_id] = perm_request
        ctx.state["events"][request_id] = gate_event

    ctx.handler.send_response(200)
    ctx.handler.send_header("Content-Type", "application/x-ndjson")
    ctx.handler.end_headers()

    base = {"iteration": 1, "agent_id": "stub-agent"}
    _write_ndjson_line(
        ctx,
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
        ),
    )
    _write_ndjson_line(
        ctx,
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
        },
    )

    answered = gate_event.wait(PERM_WAIT_TIMEOUT_S)
    with ctx.lock:
        approved = bool(ctx.state["verdicts"].get(request_id, False))
        ctx.state["pending"].pop(request_id, None)
        ctx.state["events"].pop(request_id, None)

    if answered and approved:
        tool_content = "total 8\ndrwxr-xr-x 2 stub stub 4096 ."
        final = "已执行 terminal，结果如上。"
    elif answered:
        tool_content = "权限拒绝: 用户拒绝了工具调用"
        final = "好的，已跳过该操作。"
    else:
        tool_content = "权限拒绝: 审批超时（fail-closed）"
        final = "审批超时，已跳过该操作。"

    _write_ndjson_line(
        ctx,
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
        ),
    )
    _write_ndjson_line(
        ctx,
        dict(
            base,
            state="content_delta",
            content=final,
            reasoning=None,
            tool_call=None,
            tool_result=None,
            error=None,
        ),
    )
    _write_ndjson_line(
        ctx,
        dict(
            base,
            state="done",
            content=final,
            reasoning=None,
            tool_call=None,
            tool_result=None,
            error=None,
        ),
    )


def _handle_gated_question_stream(ctx: StubContext) -> None:
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
    with ctx.lock:
        ctx.state["questions"][request_id] = user_question
        ctx.state["question_events"][request_id] = gate_event

    ctx.handler.send_response(200)
    ctx.handler.send_header("Content-Type", "application/x-ndjson")
    ctx.handler.end_headers()

    base = {"iteration": 1, "agent_id": "stub-agent"}
    _write_ndjson_line(
        ctx,
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
        ),
    )
    _write_ndjson_line(
        ctx,
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
        },
    )

    answered = gate_event.wait(QUESTION_WAIT_TIMEOUT_S)
    with ctx.lock:
        verdict = ctx.state["question_verdicts"].get(request_id) or {}
        answers = list(verdict.get("answers") or [])
        custom = verdict.get("custom")
        ctx.state["questions"].pop(request_id, None)
        ctx.state["question_events"].pop(request_id, None)

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

    _write_ndjson_line(
        ctx,
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
        ),
    )
    _write_ndjson_line(
        ctx,
        dict(
            base,
            state="content_delta",
            content=final,
            reasoning=None,
            tool_call=None,
            tool_result=None,
            error=None,
        ),
    )
    _write_ndjson_line(
        ctx,
        dict(
            base,
            state="done",
            content=final,
            reasoning=None,
            tool_call=None,
            tool_result=None,
            error=None,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────
# Permission gate (M1) — REST endpoints + test inspection
# ─────────────────────────────────────────────────────────────────────────


def _list_pending_permissions(ctx: StubContext, body: dict, **_):
    with ctx.lock:
        pending = list(ctx.state["pending"].values())
    send_json(ctx, 200, pending)


def _list_permission_answers(ctx: StubContext, body: dict, **_):
    with ctx.lock:
        answers = list(ctx.state["answers"])
    send_json(ctx, 200, {"answers": answers})


def _answer_permission(ctx: StubContext, body: dict, *, request_id: str):
    # 与后端 ApprovalAnswerBody extra="forbid" 对齐:
    # 只接受 approved(bool, 必填) / remember(bool, 可选)
    extra_keys = set(body.keys()) - {"approved", "remember"}
    remember = body.get("remember", False)
    if (
        extra_keys
        or not isinstance(body.get("approved"), bool)
        or not isinstance(remember, bool)
    ):
        send_json(
            ctx,
            422,
            {"detail": "body must be {approved: bool, remember?: bool}"},
        )
        return
    approved = body["approved"]
    with ctx.lock:
        known = request_id in ctx.state["pending"]
        if known:
            ctx.state["verdicts"][request_id] = approved
            ctx.state["answers"].append(
                {
                    "request_id": request_id,
                    "approved": approved,
                    "remember": remember,
                }
            )
            gate_event = ctx.state["events"].get(request_id)
        else:
            gate_event = None
    if not known:
        send_json(ctx, 200, {"ok": False, "error": "unknown_or_expired"})
        return
    if gate_event is not None:
        gate_event.set()
    send_json(ctx, 200, {"ok": True})


# ─────────────────────────────────────────────────────────────────────────
# Question gate (M2 part B) — REST endpoints + test inspection
# ─────────────────────────────────────────────────────────────────────────


def _list_pending_questions(ctx: StubContext, body: dict, **_):
    with ctx.lock:
        pending = list(ctx.state["questions"].values())
    send_json(ctx, 200, pending)


def _list_question_answers(ctx: StubContext, body: dict, **_):
    with ctx.lock:
        answers = list(ctx.state["question_answers"])
    send_json(ctx, 200, {"answers": answers})


def _answer_question(ctx: StubContext, body: dict, *, request_id: str):
    # 与后端 QuestionAnswerBody extra="forbid" 对齐:
    # 只接受 answers(list[str], 可选) / custom(str|None, 可选)
    extra_keys = set(body.keys()) - {"answers", "custom"}
    answers = body.get("answers", [])
    custom = body.get("custom")
    if (
        extra_keys
        or not isinstance(answers, list)
        or not all(isinstance(a, str) for a in answers)
        or not (custom is None or isinstance(custom, str))
    ):
        send_json(
            ctx,
            422,
            {"detail": "body must be {answers?: list[str], custom?: str|null}"},
        )
        return
    with ctx.lock:
        known = request_id in ctx.state["questions"]
        if known:
            ctx.state["question_verdicts"][request_id] = {
                "answers": answers,
                "custom": custom,
            }
            ctx.state["question_answers"].append(
                {
                    "request_id": request_id,
                    "answers": answers,
                    "custom": custom,
                }
            )
            gate_event = ctx.state["question_events"].get(request_id)
        else:
            gate_event = None
    if not known:
        send_json(ctx, 200, {"ok": False, "error": "unknown_or_expired"})
        return
    if gate_event is not None:
        gate_event.set()
    send_json(ctx, 200, {"ok": True})


# ─────────────────────────────────────────────────────────────────────────
# Internal helpers (private)
# ─────────────────────────────────────────────────────────────────────────


def _write_ndjson_line(ctx: StubContext, evt: Dict[str, Any]) -> None:
    """Write + flush a single NDJSON line (for gated streams that emit incrementally)."""
    line = json.dumps(evt, ensure_ascii=False) + "\n"
    ctx.handler.wfile.write(line.encode("utf-8"))
    ctx.handler.wfile.flush()


def _session_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
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


def _binding_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a workspace binding row to dict."""
    return {
        "session_id": row["session_id"],
        "workspace_path": row["workspace_path"],
        "generation": row["generation"],
        "activated_at": row["activated_at"],
        "revoked_at": row["revoked_at"],
    }
