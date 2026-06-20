"""
MCP (Model Context Protocol) client module for sage backend.

Enables sage's AI agent to call external MCP servers (like draw.io)
through the standard tool registry.
"""

from backend.mcp.client import McpClient, McpClientError
from backend.mcp.config import McpServerConfig, get_mcp_server_configs
from backend.mcp.tool import McpTool, register_mcp_tools

__all__ = [
    "McpClient",
    "McpClientError",
    "McpServerConfig",
    "get_mcp_server_configs",
    "McpTool",
    "register_mcp_tools",
]
