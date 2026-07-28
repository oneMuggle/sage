"""
MCP (Model Context Protocol) client module for sage backend.

Enables sage's AI agent to call external MCP servers (like draw.io)
through the standard tool registry.

M3: multi-server config (JSON file + built-in merge), hardened sync
pool with parallel discovery / per-server isolation / degraded status
reporting. The dead async lifecycle package was removed — see the
decision note at the top of :mod:`backend.mcp.pool`.
"""

from backend.mcp.client import McpClient, McpClientError
from backend.mcp.config import (
    McpConfigError,
    McpServerConfig,
    ServerConfig,
    get_mcp_server_configs,
    load_server_configs,
)
from backend.mcp.pool import (
    McpServerPool,
    McpStatusReport,
    ServerRecord,
    ServerState,
    ServerStatusEntry,
    get_pool,
    namespaced_tool_name,
    reset_pool,
)
from backend.mcp.tool import McpTool, register_mcp_tools, shutdown_mcp_clients

__all__ = [
    "McpClient",
    "McpClientError",
    "McpConfigError",
    "McpServerConfig",
    "ServerConfig",
    "get_mcp_server_configs",
    "load_server_configs",
    "McpServerPool",
    "McpStatusReport",
    "ServerRecord",
    "ServerState",
    "ServerStatusEntry",
    "get_pool",
    "namespaced_tool_name",
    "reset_pool",
    "McpTool",
    "register_mcp_tools",
    "shutdown_mcp_clients",
]
