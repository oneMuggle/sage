"""MCP Streamable HTTP 服务端协议核心（与 Web 框架无关，便于单测）。

口径：MCP 2025-03-26 Streamable HTTP，一律 ``application/json`` 响应（不开 SSE）。

- ``POST /mcp/<token>``：无 ``Mcp-Session-Id`` 时只接受 ``initialize``；
- ``GET``：不提供服务端推送流 → 405；``DELETE``：关闭会话；
- 带 ``Origin`` 头 → 403（MCP 为服务间调用，拒绝浏览器跨站）；
- token 不匹配 / 工作区停用 → 404；会话不属于该工作区或已过期 → 404 SESSION_NOT_FOUND；
- 每次 ``tools/call`` 重新校验：未急停、工作区仍启用、token 未轮换、权限仍开启。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import SERVER_NAME, SERVER_VERSION
from .audit import AuditLog
from .jobs import JobManager
from .store import WorkspaceStore
from .tools import TOOLS, TOOLS_BY_NAME, ToolContext, ToolFailure

SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL = "2025-03-26"
MAX_SESSIONS = 24
SESSION_IDLE_SECONDS = 30 * 60
MAX_BODY_BYTES = 768 * 1024
CALLS_PER_SECOND = 20

INSTRUCTIONS = (
    "You are connected to one local workspace shared from Sage. All paths are relative to the "
    "workspace root. Read before editing: write_file / edit_file / apply_patch REQUIRE the "
    'expected_version returned by read_file ("new" for new files); on version_conflict re-read '
    "instead of retrying. Check workspace_info before assuming write or shell is enabled. Shell, "
    "when enabled, runs with the local user's privileges and is NOT sandboxed. Never read or "
    "exfiltrate credentials. If a mutating call times out, inspect state first; never replay it "
    "blindly. Stop and ask the user when the scope is unclear."
)

Response = Tuple[int, Dict[str, str], Optional[Dict[str, Any]]]


@dataclass
class Session:
    id: str
    workspace_id: str
    token: str
    owner: str
    protocol: str
    last_active: float = field(default_factory=time.time)
    window_start: float = field(default_factory=time.time)
    window_calls: int = 0


def _error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _result(req_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


class RemoteMcpService:
    def __init__(self, store: WorkspaceStore, audit: Optional[AuditLog] = None,
                 jobs: Optional[JobManager] = None) -> None:
        self.store = store
        self.audit = audit or AuditLog()
        self.jobs = jobs or JobManager()
        self.paused = False
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.Lock()

    # ── 会话生命周期 ────────────────────────────────────────────────

    def session_count(self, workspace_id: Optional[str] = None) -> int:
        with self._lock:
            return sum(1 for s in self._sessions.values()
                       if workspace_id is None or s.workspace_id == workspace_id)

    def _prune(self) -> None:
        cutoff = time.time() - SESSION_IDLE_SECONDS
        with self._lock:
            expired = [sid for sid, s in self._sessions.items() if s.last_active < cutoff]
        for sid in expired:
            self.close_session(sid, reason="idle")

    def close_session(self, session_id: str, reason: str = "closed") -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            self.jobs.stop_where(owner=session.owner)
            self.audit.record("session.closed", session.workspace_id, reason=reason)

    def revoke(self, workspace_id: str, reason: str = "revoked") -> None:
        """权限关闭 / 停用 / 轮换 / 移除：关闭该工作区全部会话并终止其命令。"""
        with self._lock:
            ids = [sid for sid, s in self._sessions.items() if s.workspace_id == workspace_id]
        for sid in ids:
            self.close_session(sid, reason=reason)
        self.jobs.stop_where(workspace_id=workspace_id)

    def pause(self) -> None:
        """急停：拒绝一切请求、关闭全部会话、终止全部命令。"""
        self.paused = True
        with self._lock:
            ids = list(self._sessions)
        for sid in ids:
            self.close_session(sid, reason="emergency")
        self.jobs.stop_where()
        self.audit.record("bridge.emergency_stop")

    def resume(self) -> None:
        self.paused = False
        self.audit.record("bridge.resumed")

    # ── HTTP 入口 ───────────────────────────────────────────────────

    def handle(self, method: str, token: str, headers: Dict[str, str], body: bytes) -> Response:  # noqa: PLR0911 — 逐项守卫早返回
        """``headers`` 键须为小写。返回 (状态码, 响应头, JSON 体或 None)。"""
        if headers.get("origin"):
            return 403, {}, {"error": "BROWSER_ORIGIN_DENIED"}
        if self.paused:
            return 503, {}, {"error": "BRIDGE_PAUSED"}
        workspace = self.store.find_by_token(token)
        if workspace is None:
            return 404, {}, {"error": "NOT_FOUND"}
        self._prune()
        session_id = headers.get("mcp-session-id")
        session: Optional[Session] = None
        if session_id:
            with self._lock:
                session = self._sessions.get(session_id)
            if session is None or session.workspace_id != workspace["id"] or session.token != token:
                return 404, {}, _error(None, -32001, "SESSION_NOT_FOUND: initialize a new session; "
                                       "do not replay mutating calls automatically")
            session.last_active = time.time()
        if method == "GET":
            return 405, {"allow": "POST, DELETE"}, {"error": "SSE_STREAM_NOT_SUPPORTED"}
        if method == "DELETE":
            if session is None:
                return 400, {}, {"error": "SESSION_REQUIRED"}
            self.close_session(session.id, reason="client_delete")
            return 200, {}, None
        if method != "POST":
            return 405, {"allow": "POST, DELETE"}, None
        if len(body) > MAX_BODY_BYTES:
            return 413, {}, {"error": "BODY_TOO_LARGE"}
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return 400, {}, _error(None, -32700, "Parse error")
        return self._dispatch(workspace, token, session, payload)

    def _dispatch(self, workspace: Dict[str, Any], token: str, session: Optional[Session],
                  payload: Any) -> Response:
        messages = payload if isinstance(payload, list) else [payload]
        if not messages or not all(isinstance(m, dict) for m in messages):
            return 400, {}, _error(None, -32600, "Invalid Request")
        if session is None:
            if len(messages) != 1 or messages[0].get("method") != "initialize":
                return 400, {}, {"error": "INITIALIZE_REQUIRED"}
            return self._initialize(workspace, token, messages[0])
        responses: List[Dict[str, Any]] = []
        for message in messages:
            reply = self._handle_message(workspace, session, message)
            if reply is not None:
                responses.append(reply)
        if not responses:
            return 202, {}, None
        body = responses if isinstance(payload, list) else responses[0]
        return 200, {}, body  # type: ignore[return-value]

    def _initialize(self, workspace: Dict[str, Any], token: str, message: Dict[str, Any]) -> Response:
        with self._lock:
            if len(self._sessions) >= MAX_SESSIONS:
                return 429, {}, {"error": "SESSION_LIMIT"}
            requested = (message.get("params") or {}).get("protocolVersion")
            protocol = requested if requested in SUPPORTED_PROTOCOLS else DEFAULT_PROTOCOL
            session = Session(id=str(uuid.uuid4()), workspace_id=workspace["id"], token=token,
                              owner=str(uuid.uuid4()), protocol=protocol)
            self._sessions[session.id] = session
        self.audit.record("session.connected", workspace["id"])
        result = {
            "protocolVersion": protocol,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS,
        }
        return 200, {"mcp-session-id": session.id}, _result(message.get("id"), result)

    def _handle_message(self, workspace: Dict[str, Any], session: Session,
                        message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = message.get("method")
        req_id = message.get("id")
        if "id" not in message:  # 通知 / 响应：不回复
            return None
        if method == "ping":
            return _result(req_id, {})
        if method == "tools/list":
            return _result(req_id, {"tools": [t.descriptor() for t in TOOLS]})
        if method == "tools/call":
            return self._call_tool(workspace, session, req_id, message.get("params") or {})
        if method == "initialize":
            return _error(req_id, -32600, "Session already initialized")
        return _error(req_id, -32601, f"Method not found: {method}")

    def _rate_limited(self, session: Session) -> bool:
        now = time.time()
        if now - session.window_start >= 1.0:
            session.window_start = now
            session.window_calls = 0
        session.window_calls += 1
        return session.window_calls > CALLS_PER_SECOND

    def _call_tool(self, workspace: Dict[str, Any], session: Session, req_id: Any,  # noqa: PLR0911
                   params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = TOOLS_BY_NAME.get(name) if isinstance(name, str) else None
        if tool is None:
            return _error(req_id, -32602, f"Unknown tool: {name}")
        if not isinstance(args, dict):
            return _error(req_id, -32602, "arguments must be an object")
        if self._rate_limited(session):
            return self._tool_error(req_id, "RATE_LIMITED: too many calls, slow down")
        active = self.store.find_by_token(session.token)
        if self.paused or active is None or active["id"] != workspace["id"]:
            return self._tool_error(req_id, "ACCESS_REVOKED")
        if tool.permission and not active.get("permissions", {}).get(tool.permission):
            return self._tool_error(
                req_id, f"PERMISSION_DENIED: '{tool.permission}' is disabled for this workspace "
                "(enable it locally in Sage)")
        started = time.time()
        try:
            data = tool.handler(ToolContext(active, session.owner, self.jobs), args)
        except ToolFailure as exc:
            self.audit.record("tool.error", active["id"], tool=tool.name,
                              ms=int((time.time() - started) * 1000), code=str(exc).split(":", 1)[0][:40])
            return self._tool_error(req_id, str(exc))
        except Exception as exc:  # noqa: BLE001 — 协议层兜底，不泄露栈
            self.audit.record("tool.error", active["id"], tool=tool.name, code="INTERNAL_ERROR")
            return self._tool_error(req_id, f"INTERNAL_ERROR: {type(exc).__name__}")
        self.audit.record("tool.ok", active["id"], tool=tool.name, ms=int((time.time() - started) * 1000))
        text = json.dumps(data, ensure_ascii=False, indent=2)
        return _result(req_id, {"content": [{"type": "text", "text": text}], "isError": False})

    @staticmethod
    def _tool_error(req_id: Any, message: str) -> Dict[str, Any]:
        return _result(req_id, {"content": [{"type": "text", "text": message}], "isError": True})


__all__ = ["INSTRUCTIONS", "MAX_SESSIONS", "RemoteMcpService", "Session"]
