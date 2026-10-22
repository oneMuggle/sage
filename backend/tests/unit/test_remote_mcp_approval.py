"""Workspace MCP Server M5a：审批模式 + token 静态加密。"""

from __future__ import annotations

import asyncio
import json
import threading

import pytest

from backend.remote_mcp.approval import GateApprover, needs_approval
from backend.remote_mcp.audit import AuditLog
from backend.remote_mcp.protocol import RemoteMcpService
from backend.remote_mcp.store import StoreError, WorkspaceStore


class FakeApprover:
    def __init__(self, decision=(True, ""), on_call=None):
        self.decision = decision
        self.calls = []
        self.on_call = on_call

    def __call__(self, workspace, tool_name, args, risk):
        self.calls.append((workspace["id"], tool_name, risk))
        if self.on_call:
            self.on_call()
        return self.decision


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path / "userdata"))
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    store = WorkspaceStore(str(tmp_path / "userdata" / "remote_workspaces.json"))
    ws = store.create("proj", str(root))
    store.update(ws["id"], permissions={"write": True, "shell": True})
    approver = FakeApprover()
    service = RemoteMcpService(store, AuditLog(str(tmp_path / "userdata" / "audit.jsonl")), approver=approver)
    token = store.connection_token(ws["id"])
    yield service, store, ws, token, root, approver
    service.pause()


def _post(service, token, payload, session=None):
    h = {"content-type": "application/json"}
    if session:
        h["mcp-session-id"] = session
    return service.handle("POST", token, h, json.dumps(payload).encode())


def _init(service, token):
    status, headers, body = _post(service, token, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                                   "params": {"protocolVersion": "2025-03-26"}})
    assert status == 200, body
    return headers["mcp-session-id"]


def _call(service, token, session, name, args=None):
    status, _, body = _post(service, token, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                             "params": {"name": name, "arguments": args or {}}}, session)
    assert status == 200
    result = body["result"]
    return result["isError"], result["content"][0]["text"]


def _version(service, token, session, path):
    err, text = _call(service, token, session, "read_file", {"path": path})
    assert not err, text
    return json.loads(text)["version"]


# ── needs_approval 规则 ───────────────────────────────────────────


def test_rules_auto_mode():
    ws = {"approval": "auto"}
    assert needs_approval(ws, "read_file", {}) is None
    assert needs_approval(ws, "write_file", {}) is None
    assert needs_approval(ws, "run_command", {"command": "echo hi"}) is None
    assert needs_approval(ws, "run_command", {"command": "rm -rf /"}) == "destructive"
    assert needs_approval(ws, "run_command", {"command": 123}) == "unknown"


def test_rules_ask_mode():
    ws = {"approval": "ask"}
    assert needs_approval(ws, "list_directory", {}) is None
    assert needs_approval(ws, "get_command_output", {}) is None
    assert needs_approval(ws, "edit_file", {}) == "write"
    assert needs_approval(ws, "apply_patch", {}) == "write"
    assert needs_approval(ws, "run_command", {"command": "echo hi"}) == "safe"


# ── 协议集成 ─────────────────────────────────────────────────────


def test_auto_mode_write_does_not_ask(env):
    service, _store, _ws, token, root, approver = env
    session = _init(service, token)
    err, text = _call(service, token, session, "write_file",
                      {"path": "new.txt", "content": "a", "expected_version": "new"})
    assert not err, text
    assert approver.calls == []
    assert (root / "new.txt").read_text(encoding="utf-8") == "a"


def test_ask_mode_write_approved(env):
    service, store, ws, token, root, approver = env
    store.update(ws["id"], approval="ask")
    session = _init(service, token)
    version = _version(service, token, session, "src/app.py")
    err, text = _call(service, token, session, "edit_file",
                      {"path": "src/app.py", "old_string": "x = 1", "new_string": "x = 2",
                       "expected_version": version})
    assert not err, text
    assert approver.calls == [(ws["id"], "edit_file", "write")]
    assert "x = 2" in (root / "src" / "app.py").read_text(encoding="utf-8")


def test_ask_mode_write_denied_does_not_write(env):
    service, store, ws, token, root, approver = env
    store.update(ws["id"], approval="ask")
    approver.decision = (False, "denied")
    session = _init(service, token)
    err, text = _call(service, token, session, "write_file",
                      {"path": "new.txt", "content": "a", "expected_version": "new"})
    assert err
    assert text.startswith("APPROVAL_DENIED")
    assert not (root / "new.txt").exists()
    events = [row["event"] for row in service.audit.recent()]
    assert "approval.requested" in events
    assert "approval.denied" in events


def test_destructive_command_asks_even_in_auto(env):
    service, _store, _ws, token, _root, approver = env
    approver.decision = (False, "timeout")
    session = _init(service, token)
    err, text = _call(service, token, session, "run_command", {"command": "rm -rf /"})
    assert err
    assert "APPROVAL_DENIED: timeout" in text
    assert approver.calls[0][1:] == ("run_command", "destructive")


def test_emergency_stop_during_approval_blocks_execution(env):
    service, store, ws, token, root, _ = env
    store.update(ws["id"], approval="ask")
    service.approver = FakeApprover(on_call=service.pause)
    session = _init(service, token)
    err, text = _call(service, token, session, "write_file",
                      {"path": "new.txt", "content": "a", "expected_version": "new"})
    assert err
    assert text == "ACCESS_REVOKED"
    assert not (root / "new.txt").exists()


def test_permission_revoked_during_approval(env):
    service, store, ws, token, root, _ = env
    store.update(ws["id"], approval="ask")
    service.approver = FakeApprover(on_call=lambda: store.update(ws["id"], permissions={"write": False}))
    session = _init(service, token)
    err, text = _call(service, token, session, "write_file",
                      {"path": "new.txt", "content": "a", "expected_version": "new"})
    assert err
    assert text == "ACCESS_REVOKED"
    assert not (root / "new.txt").exists()


def test_missing_approver_fails_closed(env):
    service, store, ws, token, root, _ = env
    store.update(ws["id"], approval="ask")
    service.approver = None
    session = _init(service, token)
    err, text = _call(service, token, session, "write_file",
                      {"path": "new.txt", "content": "a", "expected_version": "new"})
    assert err
    assert text.startswith("APPROVAL_UNAVAILABLE")
    assert not (root / "new.txt").exists()


# ── GateApprover（真实 ApprovalGate + 独立事件循环线程） ───────────


@pytest.fixture()
def loop_thread():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


def _answer_when_pending(gate, loop, approved, seen):
    def worker():
        for _ in range(200):
            pending = gate.pending()
            if pending:
                seen.append(pending[0])
                loop.call_soon_threadsafe(gate.answer, pending[0].request_id, approved)
                return
            threading.Event().wait(0.01)
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


@pytest.mark.parametrize("approved", [True, False])
def test_gate_approver_round_trip(loop_thread, tmp_path, approved):
    from backend.services.permission_gate import ApprovalGate

    (tmp_path / "a.txt").write_text("old\n", encoding="utf-8")
    gate = ApprovalGate()
    seen = []
    worker = _answer_when_pending(gate, loop_thread, approved, seen)
    approver = GateApprover(gate_getter=lambda: gate, loop_getter=lambda: loop_thread, timeout=5)
    ws = {"id": "w1", "name": "proj", "root": str(tmp_path)}
    decision = approver(ws, "write_file", {"path": "a.txt", "content": "new\n"}, "write")
    worker.join(timeout=5)
    assert decision == ((True, "") if approved else (False, "denied"))
    req = seen[0]
    assert req.tool_name == "remote_mcp.write_file"
    assert "proj" in req.message
    assert req.diff_preview
    assert "+new" in req.diff_preview


def test_gate_approver_timeout(loop_thread):
    from backend.services.permission_gate import ApprovalGate

    approver = GateApprover(gate_getter=ApprovalGate, loop_getter=lambda: loop_thread, timeout=0.05)
    assert approver({"id": "w", "root": "."}, "run_command", {"command": "x"}, "safe") == (False, "timeout")


def test_gate_approver_unavailable():
    assert GateApprover(gate_getter=lambda: None, loop_getter=lambda: None)(
        {"id": "w"}, "write_file", {}, "write") == (False, "APPROVAL_UNAVAILABLE")


# ── token 静态加密 ───────────────────────────────────────────────


def test_token_is_encrypted_at_rest(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")
    path = tmp_path / "w.json"
    store = WorkspaceStore(str(path))
    ws = store.create("p", str(tmp_path))
    token = store.connection_token(ws["id"])
    raw = path.read_text(encoding="utf-8")
    assert token not in raw
    assert '"token_enc": "enc:test:' in raw
    reloaded = WorkspaceStore(str(path))
    assert reloaded.connection_token(ws["id"]) == token
    assert reloaded.find_by_token(token)["id"] == ws["id"]


def test_legacy_plaintext_token_is_migrated(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")
    path = tmp_path / "w.json"
    token = "a" * 64
    path.write_text(json.dumps({"version": 1, "workspaces": [{
        "id": "w1", "name": "p", "root": str(tmp_path), "token": token, "enabled": True,
        "permissions": {"read": True, "write": False, "shell": False}, "approval": "auto"}]}),
        encoding="utf-8")
    store = WorkspaceStore(str(path))
    assert store.find_by_token(token)["id"] == "w1"
    raw = path.read_text(encoding="utf-8")
    assert token not in raw
    assert "token_enc" in raw


def test_undecryptable_token_resets_and_disables(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")
    path = tmp_path / "w.json"
    path.write_text(json.dumps({"version": 2, "workspaces": [{
        "id": "w1", "name": "p", "root": str(tmp_path), "token_enc": "enc:test:v1:!!!not-base64",
        "enabled": True, "permissions": {"read": True}, "approval": "auto"}]}), encoding="utf-8")
    store = WorkspaceStore(str(path))
    public = store.list_public()[0]
    assert public["enabled"] is False
    assert public["token_reset"] is True
    with pytest.raises(StoreError):
        store.connection_token("w1")
    store.rotate("w1")
    assert "token_reset" not in store.list_public()[0]


def test_approval_mode_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")
    store = WorkspaceStore(str(tmp_path / "w.json"))
    ws = store.create("p", str(tmp_path))
    assert ws["approval"] == "auto"
    assert store.update(ws["id"], approval="ask")["approval"] == "ask"
    with pytest.raises(StoreError):
        store.update(ws["id"], approval="never")


def test_admin_patch_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.remote_mcp import admin_routes, approval as approval_mod
    from backend.remote_mcp.listener import Listener

    store = WorkspaceStore(str(tmp_path / "w.json"))
    ws = store.create("p", str(tmp_path))
    service = RemoteMcpService(store, AuditLog(str(tmp_path / "a.jsonl")))
    admin_routes.configure_for_tests(service, Listener(service))
    approval_mod.set_main_loop(None)
    app = FastAPI()
    app.include_router(admin_routes.router, prefix="/api/v1")
    try:
        with TestClient(app) as client:
            r = client.patch(f"/api/v1/remote-mcp/workspaces/{ws['id']}", json={"approval": "ask"})
            assert r.status_code == 200, r.text
            assert r.json()["workspaces"][0]["approval"] == "ask"
            assert client.patch(f"/api/v1/remote-mcp/workspaces/{ws['id']}",
                                json={"approval": "x"}).status_code == 400
        # router 级 async 依赖已捕获主循环
        assert approval_mod._get_main_loop() is not None
    finally:
        admin_routes.configure_for_tests(None, None)
        approval_mod.set_main_loop(None)
