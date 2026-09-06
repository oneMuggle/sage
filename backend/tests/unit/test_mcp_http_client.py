# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""L10 (批次 C-3): MCP streamable-HTTP 传输 + resources/prompts 合成工具测试。"""

from __future__ import annotations

import json

import httpx
import pytest

from backend.mcp.config import validate_server_config
from backend.mcp.http_client import HttpClientMcpClient
from backend.mcp.pool import default_client_factory, synthesize_extra_specs
from backend.mcp.tool import McpPromptTool, McpResourceTool

pytestmark = pytest.mark.unit


# ---- config: url/command 二选一 ----


def test_config_url_transport():
    config = validate_server_config("srv", url="https://mcp.example.com/rpc", timeout_seconds=5)
    assert config.url == "https://mcp.example.com/rpc"
    assert "url" in config.to_dict()


def test_config_rejects_bad_url():
    from backend.mcp.config import McpConfigError

    with pytest.raises(McpConfigError):
        validate_server_config("srv", url="ftp://x")


def test_config_command_still_required_without_url():
    from backend.mcp.config import McpConfigError

    with pytest.raises(McpConfigError):
        validate_server_config("srv", command="")


# ---- factory 分流 ----


def test_factory_dispatch():
    http_cfg = validate_server_config("http-srv", url="https://x/rpc")
    assert isinstance(default_client_factory(http_cfg), HttpClientMcpClient)

    stdio_cfg = validate_server_config("stdio-srv", command="uvx", args=("srv",))
    from backend.mcp.client import McpClient

    assert isinstance(default_client_factory(stdio_cfg), McpClient)


# ---- HttpClientMcpClient (httpx.MockTransport) ----


def _rpc_handler(routes, seen_headers):
    """构造 MockTransport handler: method → result 映射 + 会话头捕获。"""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        method = body.get("method")
        seen_headers.requests.append(dict(request.headers))
        if method == "initialize":
            seen_headers.init_count = getattr(seen_headers, "init_count", 0) + 1
            return httpx.Response(
                200,
                headers={
                    "content-type": "application/json",
                    "Mcp-Session-Id": "sess-123",
                },
                json={"jsonrpc": "2.0", "id": body["id"], "result": {"serverInfo": {"name": "fake"}}},
            )
        result = routes.get(method)
        if isinstance(result, Exception):
            raise result
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"jsonrpc": "2.0", "id": body.get("id"), "result": result},
        )

    return handler


class _Seen:
    def __init__(self):
        self.requests = []


def _make_client(routes):
    seen = _Seen()
    transport = httpx.MockTransport(_rpc_handler(routes, seen))
    config = validate_server_config("srv", url="https://mcp.test/rpc", timeout_seconds=5)
    client = HttpClientMcpClient(config, http_client=httpx.Client(transport=transport))
    return client, seen


def test_http_client_handshake_tools_call():
    routes = {
        "tools/list": {"tools": [{"name": "render", "description": "d", "inputSchema": {}}]},
        "tools/call": {"content": [{"type": "text", "text": "svg"}], "isError": False},
    }
    client, seen = _make_client(routes)
    client.start()  # 显式握手 (与 stdio 版契约一致)

    tools = client.list_tools()
    assert [t["name"] for t in tools] == ["render"]
    result = client.call_tool("render", {"xml": "<x/>"})
    assert result["content"][0]["text"] == "svg"
    # initialize 下发的会话头被后续请求回传
    assert any(h.get("mcp-session-id") == "sess-123" for h in seen.requests)


def test_http_client_resources_and_prompts():
    routes = {
        "resources/list": {"resources": [{"uri": "file:///a.md", "name": "a"}]},
        "resources/read": {"contents": [{"uri": "file:///a.md", "text": "hello"}]},
        "prompts/list": {"prompts": [{"name": "review", "description": "code review"}]},
        "prompts/get": {"messages": [{"role": "user", "content": {"type": "text", "text": "review this"}}]},
    }
    client, _seen = _make_client(routes)
    client.start()
    assert client.list_resources()[0]["uri"] == "file:///a.md"
    read = client.read_resource("file:///a.md")
    assert read["contents"][0]["text"] == "hello"
    assert client.list_prompts()[0]["name"] == "review"
    prompt = client.get_prompt("review", {})
    assert "review this" in json.dumps(prompt)


# ---- 合成 specs ----


class _CapableClient:
    def list_resources(self):
        return [{"uri": "file:///a.md"}, {"uri": "file:///b.md"}]

    def list_prompts(self):
        return [{"name": "review", "description": "code review", "arguments": []}]


class _BareClient:
    """无 resources/prompts 能力。"""


def test_synthesize_extra_specs_full():
    specs = synthesize_extra_specs(_CapableClient())
    names = [s["name"] for s in specs]
    assert "read_resource" in names
    assert "prompt_review" in names
    resource_spec = next(s for s in specs if s["name"] == "read_resource")
    assert resource_spec["_sage_synthetic"] == "resource"
    assert set(resource_spec["inputSchema"]["properties"]["uri"]["enum"]) == {
        "file:///a.md",
        "file:///b.md",
    }


def test_synthesize_extra_specs_bare_client():
    assert synthesize_extra_specs(_BareClient()) == []


# ---- 合成工具适配器 ----


class _FakePool:
    def read_resource(self, server, uri):
        return {"contents": [{"uri": uri, "text": "hello resource"}]}

    def get_prompt(self, server, name, arguments):
        return {"messages": [{"role": "user", "content": {"type": "text", "text": f"prompt {name}"}}]}


def test_resource_tool_execute():
    spec = {
        "name": "read_resource",
        "description": "d",
        "inputSchema": {"type": "object", "properties": {"uri": {"type": "string"}}},
        "_sage_synthetic": "resource",
    }
    tool = McpResourceTool(_FakePool(), "srv", spec)
    assert tool.schema.name == "mcp__srv__read_resource"
    result = tool.execute(uri="file:///a.md")
    assert result.success
    assert result.content["texts"] == ["hello resource"]


def test_prompt_tool_execute():
    spec = {
        "name": "prompt_review",
        "description": "code review",
        "inputSchema": {"properties": {}},
        "_sage_synthetic": "prompt",
        "_sage_prompt_name": "review",
    }
    tool = McpPromptTool(_FakePool(), "srv", spec)
    assert tool.schema.name == "mcp__srv__prompt_review"
    result = tool.execute()
    assert result.success
    assert "prompt review" in result.content
