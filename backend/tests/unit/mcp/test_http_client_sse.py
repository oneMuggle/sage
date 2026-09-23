"""R104 — HttpClientMcpClient SSE 解析路径单测（_parse_sse + SSE 响应端到端）。

MCP Streamable-HTTP 允许服务器回 JSON 或 SSE。r102 覆盖了 JSON 路径，
本批补 SSE：data: 行解析、按 id 匹配、错误行聚合、非 data 行忽略。
"""

from __future__ import annotations

import httpx
import pytest

from backend.mcp.client import McpClientError
from backend.mcp.config import ServerConfig
from backend.mcp.http_client import HttpClientMcpClient

pytestmark = pytest.mark.unit


def _config() -> ServerConfig:
    return ServerConfig(name="http-mcp", url="https://mcp.example/rpc", timeout_seconds=5.0)


def _sse_client(responder):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responder(request, seen)

    transport = httpx.MockTransport(handler)
    return HttpClientMcpClient(
        _config(), http_client=httpx.Client(transport=transport), oauth_store=_FakeStore()
    ), seen


class _FakeStore:
    def load(self, name):
        return None

    def save(self, rec):
        pass

    def delete(self, name):
        pass


def _sse(body: str, session_id: str | None = "SID-1") -> httpx.Response:
    return httpx.Response(
        200,
        text=body,
        headers={"content-type": "text/event-stream", "mcp-session-id": session_id} if session_id
        else {"content-type": "text/event-stream"},
    )


def _json(result: dict) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


# ---------------------------------------------------------------------------
# _parse_sse 纯函数面
# ---------------------------------------------------------------------------


def test_parse_sse_extracts_matching_id_result():
    body = 'event: message\ndata: {"jsonrpc": "2.0", "id": 1, "result": {"tools": [1, 2]}}\n\n'
    assert HttpClientMcpClient._parse_sse(body, 1) == {"tools": [1, 2]}


def test_parse_sse_ignores_other_ids():
    body = (
        'data: {"jsonrpc": "2.0", "id": 99, "result": {"other": true}}\n'
        'data: {"jsonrpc": "2.0", "id": 1, "result": {"mine": true}}\n'
    )
    assert HttpClientMcpClient._parse_sse(body, 1) == {"mine": True}


def test_parse_sse_skips_non_data_and_malformed_lines():
    body = (
        ": keep-alive comment\n"
        "event: ping\n"
        "data: not-json\n"
        "data: [1, 2]\n"
        "\n"
        'data: {"jsonrpc": "2.0", "id": 1, "result": {"ok": 1}}\n'
    )
    assert HttpClientMcpClient._parse_sse(body, 1) == {"ok": 1}


def test_parse_sse_error_without_result_raises():
    body = 'data: {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "boom"}}\n'
    with pytest.raises(McpClientError, match="boom"):
        HttpClientMcpClient._parse_sse(body, 1)


def test_parse_sse_last_matching_error_wins_when_no_result():
    body = (
        'data: {"jsonrpc": "2.0", "id": 1, "error": {"message": "first"}}\n'
        'data: {"jsonrpc": "2.0", "id": 1, "error": {"message": "second"}}\n'
    )
    with pytest.raises(McpClientError, match="second"):
        HttpClientMcpClient._parse_sse(body, 1)


def test_parse_sse_no_matching_id_returns_none():
    body = 'data: {"jsonrpc": "2.0", "id": 42, "result": {"x": 1}}\n'
    assert HttpClientMcpClient._parse_sse(body, 1) is None


# ---------------------------------------------------------------------------
# _post → SSE content-type 端到端
# ---------------------------------------------------------------------------


def test_tools_list_parses_sse_response():
    sse_body = (
        'event: message\n'
        'data: {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "t1"}]}}\n\n'
    )

    def responder(request, seen):
        return _sse(sse_body)

    client, _ = _sse_client(responder)
    client.start()
    tools = client.list_tools()
    assert tools == [{"name": "t1"}]
    assert client.is_running


def test_json_response_still_works_alongside_sse():
    def responder(request, seen):
        if not seen:  # initialize
            return _json({"serverInfo": {"name": "srv"}})
        return _sse(
            'data: {"jsonrpc": "2.0", "id": 1, "result": {"resources": []}}\n\n',
            session_id=None,
        )

    client, _ = _sse_client(responder)
    client.start()
    assert client.list_resources() == []
