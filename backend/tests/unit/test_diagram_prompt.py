"""HIGH-4 regression — drawio tool rename fallout.

M3 renamed MCP tools to ``mcp__<server>__<tool>``. The diagram prompt
text must instruct the LLM to call the NEW name, and the prompt
injection gate in the legacy chat route must detect the new namespace
(a prefix scan, resilient to future server-side renames).
"""

import re

from backend.core.diagram_prompt import (
    DIAGRAM_TOOL_PROMPT,
    DRAWIO_RENDER_TOOL,
    registry_has_drawio_tool,
)
from backend.mcp.pool import McpServerPool
from backend.tools.registry import ToolRegistry


def _drawio_tool():
    """A real McpTool whose registry name is mcp__drawio__render_diagram."""
    from backend.mcp.tool import McpTool

    pool = McpServerPool()  # never started — only used for name routing
    spec = {
        "name": "render_diagram",
        "description": "render mxGraph XML",
        "inputSchema": {"type": "object"},
    }
    return McpTool(pool, "drawio", spec)


class TestPromptText:
    def test_prompt_instructs_new_tool_name(self):
        assert DRAWIO_RENDER_TOOL == "mcp__drawio__render_diagram"
        assert "mcp__drawio__render_diagram" in DIAGRAM_TOOL_PROMPT

    def test_prompt_has_no_stale_pre_m3_name(self):
        # The old name must not appear unless as the suffix of the new
        # (mcp__-prefixed) one — otherwise the LLM emits tool calls for
        # a tool that no longer exists.
        stale = re.findall(r"(?<!mcp__)drawio__render_diagram", DIAGRAM_TOOL_PROMPT)
        assert stale == []


class TestInjectionGate:
    def test_empty_registry_has_no_drawio_tool(self):
        assert registry_has_drawio_tool(ToolRegistry()) is False

    def test_mcp_prefixed_drawio_tool_detected(self):
        registry = ToolRegistry()
        registry.register(_drawio_tool())
        assert registry.exists("mcp__drawio__render_diagram")
        assert registry_has_drawio_tool(registry) is True

    def test_other_server_tools_do_not_trigger_gate(self):
        from backend.mcp.tool import McpTool

        pool = McpServerPool()
        registry = ToolRegistry()
        registry.register(
            McpTool(pool, "other", {"name": "render_diagram", "inputSchema": {}})
        )
        assert registry_has_drawio_tool(registry) is False

    def test_gate_survives_broken_registry(self):
        class BrokenRegistry:
            def list_names(self):
                raise RuntimeError("registry exploded")

        assert registry_has_drawio_tool(BrokenRegistry()) is False
