"""Workspace MCP Server：协议 / 会话 / 权限 / 工具 / 管理 API / 契约测试。"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

import pytest

from backend.remote_mcp.audit import AuditLog
from backend.remote_mcp.protocol import MAX_SESSIONS, RemoteMcpService
from backend.remote_mcp.store import StoreError, WorkspaceStore


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path / "userdata"))
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=1", encoding="utf-8")
    store = WorkspaceStore(str(tmp_path / "userdata" / "remote_workspaces.json"))
    ws = store.create("proj", str(root))
    service = RemoteMcpService(store, AuditLog(str(tmp_path / "userdata" / "audit.jsonl")))
    token = store.connection_token(ws["id"])
    yield service, store, ws, token, root
    service.pause()


def post(service, token, payload, session=None, headers=None):
    h = {"content-type": "application/json"}
    if session:
        h["mcp-session-id"] = session
    h.update(headers or {})
    return service.handle("POST", token, h, json.dumps(payload).encode())


def init(service, token):
    status, headers, body = post(service, token, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                                  "params": {"protocolVersion": "2025-03-26"}})
    assert status == 200, body
    return headers["mcp-session-id"], body


def call(service, token, session, name, args=None):
    status, _, body = post(service, token, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                            "params": {"name": name, "arguments": args or {}}}, session)
    assert status == 200
    result = body["result"]
    text = result["content"][0]["text"]
    return result["isError"], (text if result["isError"] else json.loads(text))


# ── 协议与会话 ─────────────────────────────────────────────────────


def test_initialize_and_list_tools(env):
    service, _, _, token, _ = env
    session, body = init(service, token)
    assert body["result"]["protocolVersion"] == "2025-03-26"
    assert "expected_version" in body["result"]["instructions"]
    status, _, listed = post(service, token, {"jsonrpc": "2.0", "id": 5, "method": "tools/list"}, session)
    names = {t["name"] for t in listed["result"]["tools"]}
    assert {"read_file", "write_file", "run_command", "search_files"} <= names
    assert post(service, token, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session)[0] == 202


def test_origin_denied_and_bad_token(env):
    service, _, _, token, _ = env
    assert post(service, token, {}, headers={"origin": "https://evil.example"})[0] == 403
    assert post(service, "0" * 64, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})[0] == 404
    assert post(service, "short", {"jsonrpc": "2.0", "id": 1, "method": "initialize"})[0] == 404


def test_initialize_required_and_unknown_session(env):
    service, _, _, token, _ = env
    status, _, body = post(service, token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert status == 400
    assert body["error"] == "INITIALIZE_REQUIRED"
    status, _, body = post(service, token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "nope")
    assert status == 404
    assert "SESSION_NOT_FOUND" in body["error"]["message"]


def test_get_not_supported_delete_closes(env):
    service, _, _, token, _ = env
    session, _ = init(service, token)
    assert service.handle("GET", token, {"mcp-session-id": session}, b"")[0] == 405
    assert service.handle("DELETE", token, {"mcp-session-id": session}, b"")[0] == 200
    assert post(service, token, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, session)[0] == 404


def test_session_limit(env):
    service, _, _, token, _ = env
    for _ in range(MAX_SESSIONS):
        init(service, token)
    status, _, _ = post(service, token, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert status == 429


def test_unknown_method_and_parse_error(env):
    service, _, _, token, _ = env
    session, _ = init(service, token)
    _, _, body = post(service, token, {"jsonrpc": "2.0", "id": 9, "method": "resources/list"}, session)
    assert body["error"]["code"] == -32601
    assert service.handle("POST", token, {"mcp-session-id": session}, b"{bad")[0] == 400


# ── 只读工具 ───────────────────────────────────────────────────────


def test_read_tools(env):
    service, _, _, token, _ = env
    session, _ = init(service, token)
    err, listing = call(service, token, session, "list_directory", {"path": "."})
    assert not err
    names = [e["name"] for e in listing["entries"]]
    assert "src" in names
    assert ".env" not in names
    err, data = call(service, token, session, "read_file", {"path": "src/app.py"})
    assert not err
    assert data["content"] == "x = 1\n"
    assert data["path"] == "src/app.py"
    assert data["version"].startswith("sha256:")
    err, found = call(service, token, session, "find_files", {"pattern": "*.py"})
    assert found["files"] == ["src/app.py"]
    err, hits = call(service, token, session, "search_files", {"query": "X = 1"})
    assert hits["matches"][0] == {"path": "src/app.py", "line": 1, "text": "x = 1"}


@pytest.mark.parametrize("path", [".env", "../x", "/etc/hosts", "src/app.py:ads", ".git/config"])
def test_read_denied_paths(env, path):
    service, _, _, token, _ = env
    session, _ = init(service, token)
    err, text = call(service, token, session, "read_file", {"path": path})
    assert err
    assert text.startswith("PATH_DENIED")


# ── 写入（M2）────────────────────────────────────────────────────────


def test_write_requires_permission_and_version(env):
    service, store, ws, token, root = env
    session, _ = init(service, token)
    err, text = call(service, token, session, "write_file", {"path": "src/n.py", "content": "", "expected_version": "new"})
    assert err
    assert text.startswith("PERMISSION_DENIED")
    store.update(ws["id"], permissions={"write": True})
    err, text = call(service, token, session, "write_file", {"path": "src/n.py", "content": "y = 2\n"})
    assert err
    assert text.startswith("VERSION_REQUIRED")
    err, data = call(service, token, session, "write_file",
                     {"path": "src/n.py", "content": "y = 2\n", "expected_version": "new"})
    assert not err
    assert (root / "src" / "n.py").exists()
    err, read = call(service, token, session, "read_file", {"path": "src/app.py"})
    err, edited = call(service, token, session, "edit_file",
                       {"path": "src/app.py", "old_string": "x = 1", "new_string": "x = 3",
                        "expected_version": read["version"]})
    assert not err, edited
    err, text = call(service, token, session, "edit_file",
                     {"path": "src/app.py", "old_string": "x = 3", "new_string": "x = 4",
                      "expected_version": read["version"]})
    assert err
    assert "version_conflict" in text


def test_apply_patch_remote(env):
    service, store, ws, token, root = env
    store.update(ws["id"], permissions={"write": True})
    session, _ = init(service, token)
    _, read = call(service, token, session, "read_file", {"path": "src/app.py"})
    err, data = call(service, token, session, "apply_patch", {"patches": [
        {"path": "src/app.py", "old_string": "x = 1", "new_string": "x = 9", "expected_version": read["version"]}]})
    assert not err, data
    assert data["files_changed"][0]["path"] == "src/app.py"
    assert (root / "src" / "app.py").read_text(encoding="utf-8") == "x = 9\n"


# ── 命令（M3）────────────────────────────────────────────────────────


def _echo_cmd():
    return "Write-Output 'hello 你好'" if os.name == "nt" else "echo 'hello 你好'"


def test_run_command_permission_and_output(env):
    service, store, ws, token, _ = env
    session, _ = init(service, token)
    err, text = call(service, token, session, "run_command", {"command": _echo_cmd()})
    assert err
    assert text.startswith("PERMISSION_DENIED")
    store.update(ws["id"], permissions={"shell": True})
    err, data = call(service, token, session, "run_command", {"command": _echo_cmd(), "timeoutSeconds": 60})
    assert not err, data
    for _ in range(100):
        if data["status"] != "running":
            break
        time.sleep(0.2)
        _, data = call(service, token, session, "get_command_output", {"jobId": data["jobId"]})
    assert data["status"] == "completed"
    assert "hello 你好" in data["output"]
    other, _ = init(service, token)
    err, text = call(service, token, other, "get_command_output", {"jobId": data["jobId"]})
    assert err
    assert text.startswith("JOB_NOT_FOUND")


# ── 撤销 / 急停 ─────────────────────────────────────────────────────


def test_rotate_and_disable_revoke_sessions(env):
    service, store, ws, token, _ = env
    session, _ = init(service, token)
    store.rotate(ws["id"])
    service.revoke(ws["id"])
    assert post(service, token, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, session)[0] == 404


def test_permission_checked_per_call(env):
    service, store, ws, token, _ = env
    store.update(ws["id"], permissions={"write": True})
    session, _ = init(service, token)
    store.update(ws["id"], permissions={"write": False})
    err, text = call(service, token, session, "write_file", {"path": "a.txt", "content": "", "expected_version": "new"})
    assert err
    assert text.startswith("PERMISSION_DENIED")


def test_emergency_stop(env):
    service, _, _, token, _ = env
    init(service, token)
    service.pause()
    assert service.session_count() == 0
    assert post(service, token, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})[0] == 503
    service.resume()
    init(service, token)


def test_audit_has_no_arguments_or_token(env, tmp_path):
    service, _, _, token, _ = env
    session, _ = init(service, token)
    call(service, token, session, "read_file", {"path": "src/app.py"})
    call(service, token, session, "search_files", {"query": "TOPSECRETQUERY"})
    log = (tmp_path / "userdata" / "audit.jsonl").read_text(encoding="utf-8")
    assert token not in log
    assert "TOPSECRETQUERY" not in log
    assert "src/app.py" not in log
    assert '"tool": "read_file"' in log


# ── 存储 ───────────────────────────────────────────────────────────


def test_store_rejects_home_and_hides_token(tmp_path):
    store = WorkspaceStore(str(tmp_path / "w.json"))
    with pytest.raises(StoreError):
        store.create("home", str(Path.home()))
    ws = store.create("p", str(tmp_path))
    assert "token" not in ws
    assert all("token" not in w for w in store.list_public())
    with pytest.raises(StoreError):
        store.update(ws["id"], permissions={"read": False})
    reloaded = WorkspaceStore(str(tmp_path / "w.json"))
    assert reloaded.get(ws["id"])["permissions"] == {"read": True, "write": False, "shell": False,
                                                    "office": False, "memory": False}


def test_store_corrupt_file_not_overwritten(tmp_path):
    path = tmp_path / "w.json"
    path.write_text('{"oops": 1}', encoding="utf-8")
    with pytest.raises(StoreError):
        WorkspaceStore(str(path))
    assert path.read_text(encoding="utf-8") == '{"oops": 1}'


# ── 管理 API ───────────────────────────────────────────────────────


def test_admin_routes(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.remote_mcp import admin_routes
    from backend.remote_mcp.listener import Listener

    service, _, ws, _, root = env
    listener = Listener(service)
    admin_routes.configure_for_tests(service, listener)
    app = FastAPI()
    app.include_router(admin_routes.router, prefix="/api/v1")
    client = TestClient(app)
    try:
        state = client.get("/api/v1/remote-mcp/state").json()
        assert "token" not in json.dumps(state)
        assert client.post(f"/api/v1/remote-mcp/workspaces/{ws['id']}/connection-url", json={}).status_code == 409
        bad = client.post(f"/api/v1/remote-mcp/workspaces/{ws['id']}/connection-url",
                          json={"public_base": "https://evil.example.com"})
        assert bad.status_code == 400
        ok = client.post(f"/api/v1/remote-mcp/workspaces/{ws['id']}/connection-url",
                         json={"public_base": "https://abc-def.trycloudflare.com"}).json()
        assert ok["url"].startswith("https://abc-def.trycloudflare.com/mcp/")
        patched = client.patch(f"/api/v1/remote-mcp/workspaces/{ws['id']}", json={"permissions": {"write": True}})
        assert patched.json()["workspaces"][0]["permissions"]["write"] is True
        assert client.post("/api/v1/remote-mcp/emergency-stop").json()["paused"] is True
        assert client.post("/api/v1/remote-mcp/resume").json()["paused"] is False
    finally:
        listener.stop()
        admin_routes.configure_for_tests(None, None)


# ── 契约：Sage 自带 MCP 客户端 ↔ 真实监听器 ─────────────────────────


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_contract_with_sage_http_client(env):
    from backend.mcp.config import ServerConfig
    from backend.mcp.http_client import HttpClientMcpClient
    from backend.remote_mcp.listener import Listener

    service, _, _, token, _ = env
    listener = Listener(service)
    port = listener.start(_free_port())
    client = HttpClientMcpClient(ServerConfig(name="sage-remote", url=f"http://127.0.0.1:{port}/mcp/{token}"))
    try:
        client.start()
        names = {t["name"] for t in client.list_tools()}
        assert "read_file" in names
        result = client.call_tool("read_file", {"path": "src/app.py"})
        assert result["isError"] is False
        assert json.loads(result["content"][0]["text"])["content"] == "x = 1\n"
    finally:
        client.stop()
        listener.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only junction check")
def test_windows_junction_rejected(env):
    import subprocess

    from backend.remote_mcp.remote_path import RemotePathError, resolve

    _, _, _, _, root = env
    target = root / "src"
    junction = root / "jn"
    proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)],
                          capture_output=True, check=False)
    if proc.returncode != 0:
        pytest.skip("mklink /J unavailable")
    with pytest.raises(RemotePathError):
        resolve(str(root), "jn/app.py")
