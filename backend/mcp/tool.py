"""
MCP tool wrapper — exposes MCP server tools as sage BaseTool instances.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.mcp.client import McpClient, McpClientError
from backend.mcp.config import McpServerConfig, get_mcp_server_configs
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

# Global registry of active MCP clients (server_name -> client)
_mcp_clients: dict[str, McpClient] = {}


def _get_or_create_client(config: McpServerConfig) -> McpClient:
    """Get an existing client or create and start a new one."""
    if config.name in _mcp_clients:
        client = _mcp_clients[config.name]
        if client.is_running:
            return client
        # Client died, remove it
        del _mcp_clients[config.name]

    client = McpClient(config)
    client.start()
    _mcp_clients[config.name] = client
    return client


class McpTool(BaseTool):
    """
    Wraps a single MCP server tool as a sage BaseTool.

    The MCP tool's inputSchema is converted to a sage ToolSchema.
    execute() calls the MCP server via the shared client.
    """

    def __init__(self, client: McpClient, tool_spec: dict[str, Any]):
        """
        Args:
            client: The MCP client for this tool's server
            tool_spec: Tool spec from MCP tools/list response
                       {"name": str, "description": str, "inputSchema": dict}
        """
        self._client = client
        self._tool_spec = tool_spec
        super().__init__()

    def _build_schema(self) -> ToolSchema:
        """Convert MCP tool spec to sage ToolSchema."""
        name = self._tool_spec["name"]
        description = self._tool_spec.get("description", "")
        input_schema = self._tool_spec.get("inputSchema", {})

        # Prefix tool name with server name to avoid conflicts
        # e.g., "drawio__render_diagram"
        prefixed_name = f"{self._client.server_name}__{name}"

        return ToolSchema(
            name=prefixed_name,
            description=f"[MCP:{self._client.server_name}] {description}",
            parameters=input_schema,
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        """Call the MCP tool and return the result."""
        # Strip the server prefix from the tool name for the MCP call
        mcp_tool_name = self._tool_spec["name"]

        try:
            response = self._client.call_tool(mcp_tool_name, kwargs)
        except McpClientError as exc:
            logger.error(f"MCP tool '{mcp_tool_name}' failed: {exc}")
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:
            logger.error(f"Unexpected error calling MCP tool '{mcp_tool_name}': {exc}")
            return ToolResult(success=False, error=f"{type(exc).__name__}: {exc}")

        # Check for MCP-level error
        is_error = response.get("isError", False)

        # Extract content
        content_parts = response.get("content", [])
        text_parts = []
        metadata: dict[str, Any] = {}

        for part in content_parts:
            if part.get("type") == "text":
                text_parts.append(part.get("text", ""))
            elif part.get("type") == "image":
                # Store image data in metadata
                metadata["imageData"] = part.get("data", "")
                metadata["imageFormat"] = part.get("format", "png")

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
    """
    Discover tools from all configured MCP servers and register them.

    Each MCP tool is wrapped as a McpTool and added to the registry.
    Tool names are prefixed with the server name (e.g., "drawio__render_diagram").
    """
    configs = get_mcp_server_configs()
    if not configs:
        logger.info("No MCP servers configured")
        return

    for config in configs:
        if not config.enabled:
            continue

        try:
            client = _get_or_create_client(config)
            tool_specs = client.list_tools()

            for spec in tool_specs:
                tool = McpTool(client, spec)
                registry.register(tool)
                logger.info(
                    f"Registered MCP tool: {tool.schema.name} "
                    f"(server={config.name})"
                )

            logger.info(
                f"Registered {len(tool_specs)} tools from MCP server '{config.name}'"
            )

        except McpClientError as exc:
            logger.error(f"Failed to connect to MCP server '{config.name}': {exc}")
        except Exception as exc:
            logger.error(
                f"Unexpected error registering MCP server '{config.name}': {exc}"
            )


def shutdown_mcp_clients() -> None:
    """Stop all active MCP server processes."""
    for name, client in _mcp_clients.items():
        try:
            client.stop()
        except Exception as exc:
            logger.error(f"Error stopping MCP client '{name}': {exc}")
    _mcp_clients.clear()
