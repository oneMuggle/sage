"""R20: MCP 生态补强单元测试

- A: stdio McpClient 的 resources/prompts 四方法请求路由
- A: synthesize_extra_specs 对带能力的 stdio fake 客户端合成工具 spec
- B: disabled_tools 过滤（原始名 + namespaced 名）、config round-trip、
  update_server patch 与 re-discovery 触发
"""

from __future__ import annotations

import pytest

from backend.mcp.client import McpClient
from backend.mcp.config import (
    ServerConfig,
    _config_from_dict,
    validate_server_config,
)
from backend.mcp.pool import synthesize_extra_specs
from backend.mcp.tool import namespaced_tool_name

pytestmark = pytest.mark.unit


# ==================== A: stdio 四方法 ====================


class _RecordingStdioClient(McpClient):
    """拦截 _send_request，校验 JSON-RPC 方法路由（不起真进程）。"""

    def __init__(self):
        McpClient.__init__(self, ServerConfig(name="s", command="node"))
        self.calls = []

    def _ensure_started(self):
        return None

    def _send_request(self, method, params):
        self.calls.append((method, params))
        return {
            "resources/list": {"resources": [{"uri": "file:///a"}]},
            "resources/read": {"contents": [{"uri": "file:///a", "text": "hi"}]},
            "prompts/list": {"prompts": [{"name": "p1"}]},
            "prompts/get": {"messages": [{"content": {"type": "text", "text": "tpl"}}]},
        }[method]


def test_stdio_list_resources():
    c = _RecordingStdioClient()
    assert c.list_resources() == [{"uri": "file:///a"}]
    assert c.calls == [("resources/list", {})]


def test_stdio_read_resource():
    c = _RecordingStdioClient()
    result = c.read_resource("file:///a")
    assert result["contents"][0]["text"] == "hi"
    assert c.calls == [("resources/read", {"uri": "file:///a"})]


def test_stdio_list_prompts():
    c = _RecordingStdioClient()
    assert c.list_prompts() == [{"name": "p1"}]
    assert c.calls == [("prompts/list", {})]


def test_stdio_get_prompt():
    c = _RecordingStdioClient()
    result = c.get_prompt("p1", {"k": "v"})
    assert result["messages"][0]["content"]["text"] == "tpl"
    assert c.calls == [("prompts/get", {"name": "p1", "arguments": {"k": "v"}})]


# ==================== A: 合成覆盖 stdio ====================


class _CapableStdioClient:
    """带 resources/prompts 能力的 fake（模拟补齐后的 stdio 客户端）。"""

    def list_tools(self):
        return [{"name": "t", "description": "", "inputSchema": {"type": "object"}}]

    def list_resources(self):
        return [{"uri": "file:///x"}]

    def list_prompts(self):
        return [{"name": "greet", "description": "问好"}]


def test_synthesize_extra_specs_covers_stdio_client():
    specs = synthesize_extra_specs(_CapableStdioClient())
    names = [s["name"] for s in specs]
    assert "read_resource" in names
    assert "prompt_greet" in names
    resource_spec = next(s for s in specs if s["name"] == "read_resource")
    assert resource_spec["inputSchema"]["properties"]["uri"]["enum"] == ["file:///x"]


# ==================== B: per-tool 开关 ====================


def test_config_roundtrip_disabled_tools():
    cfg = validate_server_config(
        name="s", command="c", disabled_tools=["t1", "mcp__s__t2"]
    )
    assert cfg.disabled_tools == ("t1", "mcp__s__t2")
    d = cfg.to_dict()
    assert d["disabled_tools"] == ["t1", "mcp__s__t2"]
    parsed = _config_from_dict(d)
    assert parsed.disabled_tools == ("t1", "mcp__s__t2")


def test_config_disabled_tools_dedup_and_reject_blank():
    # 归一化去空白 + 去重（" t1 " 与 "t1" 视为同一工具）
    cfg = validate_server_config(name="s", command="c", disabled_tools=["t1", "t1", " t1 "])
    assert cfg.disabled_tools == ("t1",)
    from backend.mcp.config import McpConfigError

    with pytest.raises(McpConfigError):
        validate_server_config(name="s", command="c", disabled_tools=[""])


def _make_specs(*names):
    return [{"name": n, "description": "", "inputSchema": {"type": "object"}} for n in names]


def test_register_tools_into_filters_disabled(tmp_path):
    from backend.tests.unit.mcp.test_mcp_pool import FakeFactory, build_pool
    from backend.tools.registry import ToolRegistry

    pool = build_pool(
        FakeFactory({"s": {"tools": _make_specs("keep", "drop")}}),
        [validate_server_config(name="s", command="c", disabled_tools=["drop"])],
    )
    pool.discover_all()
    registry = ToolRegistry()
    pool.register_tools_into(registry)
    names = list(registry.list_names())
    assert namespaced_tool_name("s", "keep") in names
    assert namespaced_tool_name("s", "drop") not in names


def test_register_tools_into_filters_by_namespaced_name(tmp_path):
    from backend.tests.unit.mcp.test_mcp_pool import FakeFactory, build_pool
    from backend.tools.registry import ToolRegistry

    pool = build_pool(
        FakeFactory({"s": {"tools": _make_specs("keep", "drop")}}),
        [
            validate_server_config(
                name="s",
                command="c",
                disabled_tools=[namespaced_tool_name("s", "drop")],
            )
        ],
    )
    pool.discover_all()
    registry = ToolRegistry()
    pool.register_tools_into(registry)
    names = list(registry.list_names())
    assert namespaced_tool_name("s", "drop") not in names
