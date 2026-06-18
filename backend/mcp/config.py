"""
MCP Server configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class McpServerConfig:
    """Configuration for a single MCP server."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


def _project_root() -> Path:
    """Return the sage project root directory."""
    return Path(__file__).resolve().parent.parent.parent


def get_mcp_server_configs() -> list[McpServerConfig]:
    """
    Return the list of configured MCP servers.

    Reads from environment / project conventions:
    - drawio: uses packages/drawio-mcp-server from the project
    """
    root = _project_root()
    mcp_server_entry = root / "packages" / "drawio-mcp-server" / "dist" / "index.js"

    servers: list[McpServerConfig] = []

    # draw.io MCP server
    drawio_base_url = os.environ.get("DRAWIO_BASE_URL", "http://localhost:8080")
    if mcp_server_entry.exists():
        servers.append(
            McpServerConfig(
                name="drawio",
                command="node",
                args=[str(mcp_server_entry)],
                env={
                    "DRAWIO_BASE_URL": drawio_base_url,
                },
            )
        )

    return servers
