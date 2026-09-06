"""
MCP tool wrapper — exposes MCP server tools as sage BaseTool instances.

M3: tools bind to the shared :class:`~backend.mcp.pool.McpServerPool`
(not a per-tool client), so reconnection and failure isolation are
centralized. Tool names are namespaced ``mcp__<server>__<tool>``
(pre-M3: ``<server>__<tool>`` — the ``mcp__`` prefix is an LLM-visible
change that disambiguates MCP tools from built-ins).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from backend.mcp.client import McpClientError
from backend.mcp.pool import McpServerPool, get_pool, namespaced_tool_name
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


class McpTool(BaseTool):
    """Wraps a single MCP server tool as a sage BaseTool.

    The MCP tool's inputSchema becomes the sage ToolSchema; execute()
    routes through the pool so a dead server yields a clean per-server
    error without affecting other servers' tools.
    """

    def __init__(self, pool: McpServerPool, server_name: str, tool_spec: Dict[str, Any]):
        """
        Args:
            pool: The shared MCP server pool (client lifecycle owner).
            server_name: Owning MCP server config name.
            tool_spec: Tool spec from MCP tools/list response
                       {"name": str, "description": str, "inputSchema": dict}
        """
        self._pool = pool
        self._server_name = server_name
        self._tool_spec = tool_spec
        super().__init__()

    def _build_schema(self) -> ToolSchema:
        """Convert MCP tool spec to sage ToolSchema."""
        name = self._tool_spec["name"]
        description = self._tool_spec.get("description", "")
        input_schema = self._tool_spec.get("inputSchema", {})

        return ToolSchema(
            name=namespaced_tool_name(self._server_name, name),
            description=f"[MCP:{self._server_name}] {description}",
            parameters=input_schema,
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        """Call the MCP tool via the pool and return the result."""
        mcp_tool_name = self._tool_spec["name"]

        try:
            response = self._pool.call_tool(self._server_name, mcp_tool_name, kwargs)
        except McpClientError as exc:
            logger.error(
                "MCP tool '%s' (server=%s) failed: %s",
                mcp_tool_name,
                self._server_name,
                exc,
            )
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — tool errors must not crash the agent
            logger.error(
                "Unexpected error calling MCP tool '%s' (server=%s): %s",
                mcp_tool_name,
                self._server_name,
                exc,
            )
            return ToolResult(
                success=False,
                error=f"MCP 服务器 {self._server_name} 不可用: {type(exc).__name__}: {exc}",
            )

        # Check for MCP-level error
        is_error = response.get("isError", False)

        # Extract content
        content_parts = response.get("content", [])
        text_parts = []
        metadata: Dict[str, Any] = {}

        for part in content_parts:
            if part.get("type") == "text":
                text_parts.append(part.get("text", ""))
            elif part.get("type") == "image":
                # MCP standard uses "mimeType", fall back to "format"
                raw_data = part.get("data", "")
                mime = part.get("mimeType") or part.get("format", "png")
                # Normalize mime type
                if mime == "image/svg+xml":
                    image_format = "svg"
                    mime_full = "image/svg+xml"
                elif mime == "image/png":
                    image_format = "png"
                    mime_full = "image/png"
                else:
                    image_format = "png"
                    mime_full = mime
                # Reconstruct full data URL with prefix if missing
                if raw_data.startswith("data:"):
                    metadata["imageData"] = raw_data
                else:
                    metadata["imageData"] = f"data:{mime_full};base64,{raw_data}"
                metadata["imageFormat"] = image_format

        # Also check for metadata at the response level
        if "metadata" in response:
            metadata.update(response["metadata"])

        text_output = "\n".join(text_parts) if text_parts else ""

        if is_error:
            return ToolResult(
                success=False,
                content={"text": text_output, "metadata": metadata} if metadata else text_output,
                error=text_output or "MCP tool returned error",
            )

        # Return with metadata for frontend to handle images
        result_content: Any = text_output
        if metadata:
            result_content = {"text": text_output, "metadata": metadata}

        return ToolResult(success=True, content=result_content)


def register_mcp_tools(registry: Any) -> None:
    """Discover configured MCP servers (once) and register their tools.

    Startup discovery runs in parallel inside the pool and is idempotent;
    the registry is tracked (weak ref) so servers added later via the
    REST API fan their tools out to live registries without a restart.
    """
    pool = get_pool()
    try:
        pool.ensure_discovered()
        pool.track_registry(registry)
        count = pool.register_tools_into(registry)
    except Exception as exc:  # noqa: BLE001 — MCP must never break startup
        logger.error("MCP tool registration failed: %s", exc)
        return
    if count:
        logger.info("Registered %d MCP tools into registry", count)
    else:
        logger.info("No MCP tools available (no READY servers)")


def shutdown_mcp_clients() -> None:
    """Stop all MCP server processes held by the global pool."""
    get_pool().shutdown_all()


class McpResourceTool(BaseTool):
    """L10 (批次 C-3): 读取 MCP 服务器资源的合成工具。

    spec 由 ``pool.synthesize_extra_specs`` 生成 (uri 枚举限定在
    resources/list 结果内), execute 走 pool.read_resource。
    """

    def __init__(self, pool: McpServerPool, server_name: str, tool_spec: Dict[str, Any]):
        self._pool = pool
        self._server_name = server_name
        self._tool_spec = tool_spec
        super().__init__()

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=namespaced_tool_name(self._server_name, self._tool_spec["name"]),
            description=f"[MCP:{self._server_name}] {self._tool_spec.get('description', '')}",
            parameters=self._tool_spec.get("inputSchema", {}),
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        uri = str(kwargs.get("uri", ""))
        if not uri:
            return ToolResult(success=False, error="uri 必填")
        try:
            result = self._pool.read_resource(self._server_name, uri)
        except McpClientError as exc:
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — 工具错误不崩溃 agent
            return ToolResult(success=False, error=f"读取资源失败: {exc}")
        contents = result.get("contents") if isinstance(result, dict) else None
        texts = [
            str(item.get("text", ""))
            for item in (contents or [])
            if isinstance(item, dict) and item.get("text") is not None
        ]
        return ToolResult(success=True, content={"uri": uri, "texts": texts})


def _render_prompt_result(result: Dict[str, Any]) -> str:
    """把 prompts/get 结果渲染为纯文本 (messages 列表)。"""
    parts = []
    for message in result.get("messages", []):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, dict):
            parts.append(str(content.get("text", "")))
        elif isinstance(content, list):
            parts.extend(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return "\n".join(part for part in parts if part)


class McpPromptTool(BaseTool):
    """L10 (批次 C-3): MCP prompt 模板的合成工具。

    execute → pool.get_prompt → 把模板消息渲染为纯文本返回。
    """

    def __init__(self, pool: McpServerPool, server_name: str, tool_spec: Dict[str, Any]):
        self._pool = pool
        self._server_name = server_name
        self._tool_spec = tool_spec
        super().__init__()

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=namespaced_tool_name(self._server_name, self._tool_spec["name"]),
            description=f"[MCP:{self._server_name}] {self._tool_spec.get('description', '')}",
            parameters={
                "type": "object",
                "properties": self._tool_spec.get("inputSchema", {}).get("properties", {}),
            },
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        prompt_name = str(self._tool_spec.get("_sage_prompt_name", ""))
        if not prompt_name:
            return ToolResult(success=False, error="prompt name missing")
        try:
            result = self._pool.get_prompt(self._server_name, prompt_name, kwargs)
        except McpClientError as exc:
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — 工具错误不崩溃 agent
            return ToolResult(success=False, error=f"获取 prompt 失败: {exc}")
        return ToolResult(success=True, content=_render_prompt_result(result if isinstance(result, dict) else {}))
