"""
MCP Server configuration.
"""

from __future__ import annotations
from typing import Dict, List

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class McpServerConfig:
    """Configuration for a single MCP server."""

    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True


def _project_root() -> Path:
    """Return the sage project root directory."""
    return Path(__file__).resolve().parent.parent.parent


def get_mcp_server_configs() -> List[McpServerConfig]:
    """
    Return the list of configured MCP servers.

    Reads from environment / project conventions:
    - drawio: uses packages/drawio-mcp-server from the project
    """
    root = _project_root()
    mcp_server_entry = root / "packages" / "drawio-mcp-server" / "dist" / "index.js"

    servers: List[McpServerConfig] = []

    # draw.io MCP server
    drawio_base_url = os.environ.get("DRAWIO_BASE_URL", "http://localhost:8080")
    chrome_path = os.environ.get("CHROME_PATH", "")
    if mcp_server_entry.exists():
        env = {"DRAWIO_BASE_URL": drawio_base_url}
        if chrome_path:
            env["CHROME_PATH"] = chrome_path
        servers.append(
            McpServerConfig(
                name="drawio",
                command="node",
                args=[str(mcp_server_entry)],
                env=env,
            )
        )

    return servers
