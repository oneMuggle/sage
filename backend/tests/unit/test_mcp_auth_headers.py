"""R34: MCP HTTP 鉴权头单元测试

- ServerConfig.headers: round-trip 序列化、键名校验
- HttpClientMcpClient: 每次 JSON-RPC 请求合并自定义鉴权头
- pool.update_server(headers=...): 持久化 + READY 重发现
"""

from __future__ import annotations

import json

import httpx
import pytest

from backend.mcp.config import validate_server_config
from backend.mcp.http_client import HttpClientMcpClient

pytestmark = pytest.mark.unit


def test_config_headers_roundtrip():
    cfg = validate_server_config(
        "srv",
        url="https://mcp.test/rpc",
        headers={"Authorization": "Bearer pat_123", "X-Trace": "on"},
    )
    assert cfg.headers["Authorization"] == "Bearer pat_123"
    d = cfg.to_dict()
    assert d["headers"]["X-Trace"] == "on"


def test_config_rejects_bad_header_names():
    from backend.mcp.config import McpConfigError

    with pytest.raises(McpConfigError):
        validate_server_config("srv", url="https://mcp.test", headers={"": "x"})
    with pytest.raises(McpConfigError):
        validate_server_config("srv", url="https://mcp.test", headers={"Authorization": 123})


class _Seen:
    def __init__(self):
        self.requests: list = []


def _make_client_with_headers(headers: dict):
    seen = _Seen()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen.requests.append(dict(request.headers))
        if body.get("method") == "initialize":
            return httpx.Response(
                200,
                headers={"content-type": "application/json", "Mcp-Session-Id": "sess-1"},
                json={"jsonrpc": "2.0", "id": body["id"], "result": {}},
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"jsonrpc": "2.0", "id": body.get("id"), "result": {}},
        )

    cfg = validate_server_config(
        "srv", url="https://mcp.test/rpc", headers=headers, timeout_seconds=5
    )
    client = HttpClientMcpClient(
        cfg, http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    return client, seen


def test_custom_headers_sent_on_every_request():
    client, seen = _make_client_with_headers({"Authorization": "Bearer pat_1"})
    client.start()
    init_headers = seen.requests[0]
    assert init_headers.get("authorization") == "Bearer pat_1"
    assert init_headers.get("anthropic-version") is None
    # tools/list（第二请求）同样携带
    client.list_tools()
    assert seen.requests[1].get("authorization") == "Bearer pat_1"


def test_session_header_not_overridden_by_custom_headers():
    client, seen = _make_client_with_headers({"Mcp-Session-Id": "evil"})
    client.start()
    # 会话头仍为传输真实值（自定义头不覆盖必需头）
    assert seen.requests[0].get("mcp-session-id") == "sess-1"
