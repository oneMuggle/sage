"""浏览器扩展桥 HTTP 契约测试（不启动真实浏览器 / 长轮询）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.api.browser_extension_routes as routes
from backend.api.local_auth import is_public_path
from backend.services.browser_extension_bridge import (
    ExtensionAuthError,
    PairingError,
    SharedTabError,
)

pytestmark = pytest.mark.unit


class _BridgeStub:
    """Small monkeypatch helper for the singleton bridge instance."""

    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch

    def replace(self, name, value):
        self._monkeypatch.setattr(routes.browser_extension_bridge, name, value)


@pytest.fixture()
def bridge_stub(monkeypatch):
    return _BridgeStub(monkeypatch)


def _tab_payload():
    return {"id": 7, "url": "https://kns.cnki.net/kns8s/defaultresult/index", "title": "知网"}


async def test_pair_returns_device_token(client, bridge_stub):
    captured = {}

    def fake_pair(code, label):
        captured.update({"code": code, "label": label})
        return {"device_id": "dev_1", "device_token": "token-value", "label": label or "扩展"}

    bridge_stub.replace("pair", fake_pair)
    resp = await client.post(
        "/api/v1/web-access/extension/pair",
        json={"code": "ABCDE23456", "label": "Chrome"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["device_token"] == "token-value"
    assert data["base_url"].startswith("http://127.0.0.1:")
    assert captured == {"code": "ABCDE23456", "label": "Chrome"}


async def test_pair_rejects_invalid_code(client, bridge_stub):
    def fake_pair(code, label):
        raise PairingError("配对码无效或已过期")

    bridge_stub.replace("pair", fake_pair)
    resp = await client.post(
        "/api/v1/web-access/extension/pair", json={"code": "WRONG"}
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "invalid_pairing_code"


async def test_poll_without_token_is_401(client, bridge_stub):
    def fake_poll(token, tab):
        raise ExtensionAuthError("缺少扩展设备凭据")

    bridge_stub.replace("poll", fake_poll)
    resp = await client.post("/api/v1/web-access/extension/poll", json={})
    assert resp.status_code == 401
    assert resp.json()["error"] == "extension_unauthorized"


async def test_poll_returns_command_and_tab(client, bridge_stub):
    captured = {}

    def fake_poll(token, tab):
        captured.update({"token": token, "tab": tab})
        return {"id": "cmd-1", "method": "Runtime.evaluate", "params": {}}

    bridge_stub.replace("poll", fake_poll)
    resp = await client.post(
        "/api/v1/web-access/extension/poll",
        json={"tab": _tab_payload()},
        headers={"X-Sage-Extension-Token": "device-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["command"]["id"] == "cmd-1"
    assert captured["token"] == "device-token"
    assert captured["tab"]["id"] == 7


async def test_poll_returns_null_on_long_poll_timeout(client, bridge_stub):
    bridge_stub.replace("poll", lambda token, tab: None)
    resp = await client.post(
        "/api/v1/web-access/extension/poll",
        json={},
        headers={"X-Sage-Extension-Token": "device-token"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "command": None}


async def test_poll_conflict_returns_409(client, bridge_stub):
    def fake_poll(token, tab):
        raise SharedTabError("另一个设备已在共享标签页")

    bridge_stub.replace("poll", fake_poll)
    resp = await client.post(
        "/api/v1/web-access/extension/poll",
        json={"tab": _tab_payload()},
        headers={"X-Sage-Extension-Token": "device-token"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"] == "shared_tab_error"


async def test_result_accepts_and_rejects_oversize(client, bridge_stub, monkeypatch):
    captured = {}

    def fake_submit(token, command_id, ok, result, error):
        captured.update(
            {"token": token, "command_id": command_id, "ok": ok, "result": result}
        )
        return True

    bridge_stub.replace("submit_result", fake_submit)
    resp = await client.post(
        "/api/v1/web-access/extension/result",
        json={"command_id": "cmd-1", "ok": True, "result": {"result": {"value": 2}}},
        headers={"X-Sage-Extension-Token": "device-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True
    assert captured["command_id"] == "cmd-1"

    monkeypatch.setattr(routes, "MAX_RESULT_BYTES", 8)
    resp = await client.post(
        "/api/v1/web-access/extension/result",
        json={"command_id": "cmd-1", "ok": True, "result": {"value": "x" * 32}},
        headers={"X-Sage-Extension-Token": "device-token"},
    )
    assert resp.status_code == 413


async def test_detach_and_sync_session(client, bridge_stub):
    captured = {}
    bridge_stub.replace(
        "detach", lambda token, reason="user": captured.update({"detach": reason})
    )
    resp = await client.post(
        "/api/v1/web-access/extension/detach",
        json={"reason": "tab_closed"},
        headers={"X-Sage-Extension-Token": "device-token"},
    )
    assert resp.status_code == 200
    assert captured["detach"] == "tab_closed"

    def fake_sync(token, payload):
        captured.update({"sync": (token, payload)})
        return {"saved": [{"domain": ".cnki.net", "count": 2}], "total_cookies": 2}

    bridge_stub.replace("sync_session", fake_sync)
    resp = await client.post(
        "/api/v1/web-access/extension/sync-session",
        json={
            "url": "https://kns.cnki.net/kns8s/defaultresult/index",
            "cookies": [{"name": "SID", "domain": ".cnki.net"}],
            "origins": [{"origin": "https://kns.cnki.net", "localStorage": {"vtoken": "x"}}],
        },
        headers={"X-Sage-Extension-Token": "device-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["total_cookies"] == 2
    assert captured["sync"][0] == "device-token"
    assert captured["sync"][1]["url"].startswith("https://kns.cnki.net")


async def test_status_and_pairing_code_are_masked(client, bridge_stub, monkeypatch):
    monkeypatch.setenv("PYTHON_BACKEND_PORT", "8834")
    bridge_stub.replace(
        "list_devices",
        lambda: [
            {
                "device_id": "dev_1",
                "label": "Chrome",
                "created_at": 1737000000,
                "last_seen_at": 1737000100,
                "connected": True,
                "sharing": True,
            }
        ],
    )
    bridge_stub.replace(
        "shared_summary",
        lambda: {
            "device_id": "dev_1",
            "origin": "https://kns.cnki.net",
            "host": "kns.cnki.net",
            "title": "知网",
            "shared_at": 1737000100,
        },
    )
    monkeypatch.setattr(routes, "extension_directory", lambda: "/tmp/agent-bridge")

    resp = await client.get("/api/v1/web-access/browser-extension/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    assert data["shared"]["host"] == "kns.cnki.net"
    assert data["extension_dir"] == "/tmp/agent-bridge"
    assert data["base_url"] == "http://127.0.0.1:8834"

    bridge_stub.replace(
        "issue_pairing_code",
        lambda: {"code": "ABCDE23456", "expires_at": 1737000300},
    )
    resp = await client.post("/api/v1/web-access/browser-extension/pairing-code")
    assert resp.status_code == 200
    assert resp.json()["code"] == "ABCDE23456"
    assert resp.json()["base_url"] == "http://127.0.0.1:8834"


async def test_revoke_device(client, bridge_stub):
    bridge_stub.replace("revoke_device", lambda device_id: device_id == "dev_1")
    resp = await client.delete("/api/v1/web-access/browser-extension/devices/dev_1")
    assert resp.status_code == 200
    resp = await client.delete("/api/v1/web-access/browser-extension/devices/dev_2")
    assert resp.status_code == 404


async def test_management_origin_guard(client):
    resp = await client.get(
        "/api/v1/web-access/browser-extension/status",
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403


async def test_extension_io_rejects_web_page_origin(client, bridge_stub):
    bridge_stub.replace(
        "pair", lambda code, label: {"device_id": "dev_1", "device_token": "t", "label": ""}
    )
    resp = await client.post(
        "/api/v1/web-access/extension/pair",
        json={"code": "ABCDE23456"},
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "forbidden_origin"

    resp = await client.post(
        "/api/v1/web-access/extension/pair",
        json={"code": "ABCDE23456"},
        headers={"Origin": "chrome-extension://abcdefghijklmnop"},
    )
    assert resp.status_code == 200


def test_extension_prefix_is_public_but_management_is_not():
    assert is_public_path("/api/v1/web-access/extension/pair")
    assert is_public_path("/api/v1/web-access/extension/poll")
    assert not is_public_path("/api/v1/web-access/browser-extension/status")
    assert not is_public_path("/api/v1/web-access/credentials")


def test_extension_endpoints_bypass_local_auth_but_management_requires_it(monkeypatch):
    from backend.main import app
    from backend.services import browser_extension_bridge as bridge_module

    monkeypatch.setattr(
        bridge_module.browser_extension_bridge,
        "pair",
        lambda code, label: {"device_id": "dev_1", "device_token": "t", "label": ""},
    )
    unauthenticated = TestClient(app, headers={})
    pair = unauthenticated.post(
        "/api/v1/web-access/extension/pair", json={"code": "ABCDE23456"}
    )
    assert pair.status_code == 200
    status = unauthenticated.get("/api/v1/web-access/browser-extension/status")
    assert status.status_code == 401
