"""R102 — HttpClientMcpClient OAuth 注入/刷新/自愈单测（httpx.MockTransport 注入）。

覆盖：无 token 直连、OAuth 覆盖静态 Authorization 头、过期 token 同步刷新
回存、不可刷新按无 token 继续、401 带 token 清除记录并点名重授权、404 会话
过期识别、initialize 握手的 Mcp-Session-Id 回传。

注意：initialize 握手是两次 POST（initialize + notifications/initialized
通知），responder 按 JSON-RPC method 键控响应，不做按序消费。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from backend.mcp.client import McpClientError
from backend.mcp.config import ServerConfig
from backend.mcp.http_client import HttpClientMcpClient

pytestmark = pytest.mark.unit


def _config(**overrides) -> ServerConfig:
    fields = {"name": "http-mcp", "url": "https://mcp.example/rpc", "timeout_seconds": 5.0}
    fields.update(overrides)
    return ServerConfig(**fields)


def _record(expires_at=0.0, refresh_token="", **extra) -> SimpleNamespace:
    base = {
        "access_token": "tok-live",
        "token_type": "Bearer",
        "refresh_token": refresh_token,
        "client_id": "sage-client",
        "token_endpoint": "https://auth.example/token",
        "scope": "mcp",
        "expires_at": expires_at,
    }
    base.update(extra)
    return SimpleNamespace(**base)


class _FakeStore:
    def __init__(self, record=None):
        self.record = record
        self.saved = []
        self.deleted = []

    def load(self, name):
        return self.record

    def save(self, rec):
        self.saved.append(rec)
        self.record = rec

    def delete(self, name):
        self.deleted.append(name)
        self.record = None


def _make_client(config, store, responder):
    """responder(method, request, seen) -> httpx.Response；seen 收 (method, request)。"""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        try:
            method = json.loads(request.content).get("method")
        except ValueError:  # OAuth 刷新请求为 form 编码，非 JSON-RPC
            method = "(oauth/token)"
        seen.append((method, request))
        return responder(method, request, seen)

    transport = httpx.MockTransport(handler)
    return HttpClientMcpClient(
        config, http_client=httpx.Client(transport=transport), oauth_store=store
    ), seen


def _by_method(seen, method):
    return [req for m, req in seen if m == method]


def _rpc(result: dict, session_id: str | None = None) -> httpx.Response:
    headers = {"mcp-session-id": session_id} if session_id else {}
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result}, headers=headers)


def _handshake_responses():
    """initialize → 带 serverInfo 的正常响应（捕获会话 ID）；通知 → 200 空体。"""
    return {
        "initialize": _rpc({"serverInfo": {"name": "srv"}}, session_id="SID-1"),
        "notifications/initialized": httpx.Response(200),
    }


def test_initialize_handshake_captures_and_replays_session_id():
    store = _FakeStore()

    def responder(method, request, seen):
        scripted = _handshake_responses()
        if method in scripted:
            return scripted[method]
        return _rpc({"tools": [{"name": "t1"}]})

    client, seen = _make_client(_config(), store, responder)
    client.start()
    client.list_tools()

    assert client.is_running
    init_req = _by_method(seen, "initialize")[0]
    tools_req = _by_method(seen, "tools/list")[0]
    assert "Mcp-Session-Id" not in init_req.headers
    assert tools_req.headers["Mcp-Session-Id"] == "SID-1"
    assert tools_req.headers["Accept"] == "application/json, text/event-stream"


def test_expired_token_refreshes_then_uses_new_token():
    expired = _record(expires_at=1.0, refresh_token="rt-1")
    store = _FakeStore(record=expired)
    refresh_requests = []

    def responder(method, request, seen):
        if request.url.host == "auth.example":
            refresh_requests.append(request)
            return httpx.Response(
                200, json={"access_token": "tok-new", "token_type": "Bearer", "expires_in": 3600}
            )
        return _handshake_responses().get(method, _rpc({"tools": []}))

    config = _config(headers={"Authorization": "Bearer stale-static"})
    client, seen = _make_client(config, store, responder)
    client.start()

    # 过期 → 刷新端点（form 编码）→ 新 token 覆盖静态 Authorization 头
    assert len(refresh_requests) == 1
    assert "application/x-www-form-urlencoded" in refresh_requests[0].headers["content-type"]
    init_req = _by_method(seen, "initialize")[0]
    assert init_req.headers["Authorization"] == "Bearer tok-new"
    assert store.saved, "刷新后应回存新记录"
    assert store.saved[-1].access_token == "tok-new"
    # 刷新令牌轮换：响应未带 refresh_token → 保留原值
    assert store.saved[-1].refresh_token == "rt-1"


def test_expired_token_not_refreshable_proceeds_anonymous():
    store = _FakeStore(record=_record(expires_at=1.0, refresh_token=""))

    def responder(method, request, seen):
        return _handshake_responses().get(method, _rpc({"tools": []}))

    client, seen = _make_client(_config(), store, responder)
    client.start()
    assert "Authorization" not in _by_method(seen, "initialize")[0].headers
    assert store.saved == []


def test_401_with_token_clears_record_and_names_reauth():
    store = _FakeStore(record=_record())

    def responder(method, request, seen):
        if method == "initialize":
            return _rpc({"serverInfo": {}}, session_id="SID-1")
        if method == "notifications/initialized":
            return httpx.Response(200)
        return httpx.Response(401, json={"error": "unauthorized"})

    client, _ = _make_client(_config(), store, responder)
    client.start()
    with pytest.raises(McpClientError, match="重新授权"):
        client.list_tools()
    assert store.deleted == ["http-mcp"]


def test_401_without_token_is_generic_error():
    store = _FakeStore(record=None)

    def responder(method, request, seen):
        return httpx.Response(401, json={"error": "unauthorized"})

    client, _ = _make_client(_config(), store, responder)
    with pytest.raises(McpClientError) as exc_info:
        client.start()
    assert "重新授权" not in str(exc_info.value)
    assert store.deleted == []


def test_static_authorization_used_when_no_oauth_record():
    store = _FakeStore(record=None)

    def responder(method, request, seen):
        return _handshake_responses().get(method, _rpc({"serverInfo": {}}))

    client, seen = _make_client(
        _config(headers={"Authorization": "Bearer pat-123"}), store, responder
    )
    client.start()
    assert _by_method(seen, "initialize")[0].headers["Authorization"] == "Bearer pat-123"


def test_404_on_established_session_raises_expired():
    store = _FakeStore(record=None)

    def responder(method, request, seen):
        if method == "initialize":
            return _rpc({"serverInfo": {}}, session_id="SID-1")
        if method == "notifications/initialized":
            return httpx.Response(200)
        return httpx.Response(404, json={"error": "gone"})

    client, _ = _make_client(_config(), store, responder)
    client.start()
    with pytest.raises(McpClientError, match="session expired"):
        client.list_tools()
    assert not client.is_running
