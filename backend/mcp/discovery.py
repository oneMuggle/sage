"""
MCP server discovery service.

This module provides the McpServerDiscoveryService for automatically
discovering MCP servers from various sources:
- Workspace configuration files (.mcp.json, mcp-config.json)
- Environment variables
- Plugin-provided MCP servers

Author: Claude
Date: 2026-09-26
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Set, Optional, Union

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DiscoveredMcpServer(BaseModel):
    """Metadata for a discovered MCP server."""

    name: str = Field(..., description="服务器名称")
    source: str = Field(..., description="发现来源 (workspace/env/plugin/builtin)")
    command: str = Field(default="", description="启动命令")
    args: List[str] = Field(default_factory=list, description="命令参数")
    url: Optional[str] = Field(default=None, description="HTTP URL (streamable-http)")
    env: Dict[str, str] = Field(default_factory=dict, description="环境变量")
    enabled: bool = Field(default=True, description="是否启用")
    description: str = Field(default="", description="服务器描述")
    workspace_path: Optional[str] = Field(default=None, description="工作区路径")


class McpDiscoveryError(Exception):
    """Base exception for MCP discovery errors."""

    pass


class McpServerDiscoveryService:
    """
    Discover MCP servers from various sources.

    Scans for MCP server configurations in:
    - Workspace config files (.mcp.json, mcp-config.json)
    - Environment variables (MCP_SERVER_*)
    - Plugin-provided servers
    - Built-in servers

    Usage:
        service = McpServerDiscoveryService()
        servers = service.discover_all()
        servers = service.discover_workspace_servers("/path/to/workspace")
    """

    # 配置文件名
    CONFIG_FILENAMES = [
        ".mcp.json",
        "mcp-config.json",
        "mcp.json",
    ]

    def __init__(self, workspace_dir: Optional[[Path, str]] = None) -> None:
        """
        Initialize discovery service.

        Args:
            workspace_dir: Optional workspace directory to scan
        """
        self._workspace_dir = Path(workspace_dir) if workspace_dir else None
        self._cache: Dict[str, DiscoveredMcpServer] = {}
        self._cache_valid = False

    @property
    def workspace_dir(self) -> Optional[Path]:
        """Get workspace directory."""
        return self._workspace_dir

    def discover_all(self, use_cache: bool = True) -> List[DiscoveredMcpServer]:
        """
        Discover all MCP servers from all sources.

        Args:
            use_cache: Whether to use cached results

        Returns:
            List of DiscoveredMcpServer
        """
        if use_cache and self._cache_valid:
            return list(self._cache.values())

        discovered = []

        # Discover from workspace config
        if self._workspace_dir:
            workspace_servers = self.discover_workspace_servers(self._workspace_dir)
            discovered.extend(workspace_servers)

        # Discover from environment variables
        env_servers = self.discover_environment_servers()
        discovered.extend(env_servers)

        # Update cache
        for server in discovered:
            self._cache[server.name] = server

        self._cache_valid = True

        logger.info(f"发现 {len(discovered)} 个 MCP 服务器")

        return discovered

    def discover_workspace_servers(
        self, workspace_dir: Union[Path, str]
    ) -> List[DiscoveredMcpServer]:
        """
        Discover MCP servers from workspace configuration files.

        Args:
            workspace_dir: Workspace directory path

        Returns:
            List of DiscoveredMcpServer
        """
        workspace_path = Path(workspace_dir)
        discovered = []

        if not workspace_path.exists():
            logger.warning(f"工作区目录不存在: {workspace_path}")
            return []

        # Scan for config files
        for config_filename in self.CONFIG_FILENAMES:
            config_path = workspace_path / config_filename
            if not config_path.exists():
                continue

            try:
                servers = self._parse_config_file(config_path)
                for server in servers:
                    server.workspace_path = str(workspace_path)
                discovered.extend(servers)
                logger.info(
                    f"从 {config_filename} 发现 {len(servers)} 个 MCP 服务器"
                )
            except Exception as e:
                logger.error(f"解析 MCP 配置失败 {config_path}: {e}")

        return discovered

    def _parse_config_file(self, config_path: Path) -> List[DiscoveredMcpServer]:
        """
        Parse MCP configuration file.

        Args:
            config_path: Path to config file

        Returns:
            List of DiscoveredMcpServer
        """
        content = config_path.read_text(encoding="utf-8")
        data = json.loads(content)

        discovered = []

        # Support both flat and nested formats
        # Format 1: {"server-name": {...}, ...}
        # Format 2: {"servers": {"server-name": {...}, ...}}
        # Format 3: {"servers": [{"name": "...", ...}, ...]}

        if "servers" in data:
            servers_data = data["servers"]
            if isinstance(servers_data, dict):
                # Format 2
                for name, config in servers_data.items():
                    server = self._parse_server_config(name, config)
                    discovered.append(server)
            elif isinstance(servers_data, list):
                # Format 3
                for config in servers_data:
                    name = config.get("name", "")
                    server = self._parse_server_config(name, config)
                    discovered.append(server)
        else:
            # Format 1
            for name, config in data.items():
                if name in ("version", "metadata", "$schema"):
                    continue
                server = self._parse_server_config(name, config)
                discovered.append(server)

        return discovered

    def _parse_server_config(
        self, name: str, config: Dict[str, Any]
    ) -> DiscoveredMcpServer:
        """
        Parse a single server configuration.

        Args:
            name: Server name
            config: Server configuration dict

        Returns:
            DiscoveredMcpServer
        """
        return DiscoveredMcpServer(
            name=name,
            source="workspace",
            command=config.get("command", ""),
            args=config.get("args", []),
            url=config.get("url"),
            env=config.get("env", {}),
            enabled=config.get("enabled", True),
            description=config.get("description", ""),
        )

    def discover_environment_servers(self) -> List[DiscoveredMcpServer]:
        """
        Discover MCP servers from environment variables.

        Environment variables format:
        - MCP_SERVER_<NAME>_COMMAND: Command to run
        - MCP_SERVER_<NAME>_URL: HTTP URL (for streamable-http)
        - MCP_SERVER_<NAME>_ARGS: JSON array of arguments
        - MCP_SERVER_<NAME>_ENV: JSON object of environment variables

        Returns:
            List of DiscoveredMcpServer
        """
        discovered = []
        server_names: Set[str] = set()

        # Scan environment for MCP_SERVER_* variables
        for key in os.environ:
            if key.startswith("MCP_SERVER_") and key.endswith("_COMMAND"):
                # Extract server name
                name = key[len("MCP_SERVER_") : -len("_COMMAND")].lower()
                server_names.add(name)
            elif key.startswith("MCP_SERVER_") and key.endswith("_URL"):
                name = key[len("MCP_SERVER_") : -len("_URL")].lower()
                server_names.add(name)

        # Build server configs
        for name in server_names:
            prefix = f"MCP_SERVER_{name.upper()}"

            command = os.environ.get(f"{prefix}_COMMAND", "")
            url = os.environ.get(f"{prefix}_URL")

            # Parse args
            args_json = os.environ.get(f"{prefix}_ARGS", "[]")
            try:
                args = json.loads(args_json)
            except json.JSONDecodeError:
                args = []

            # Parse env
            env_json = os.environ.get(f"{prefix}_ENV", "{}")
            try:
                env = json.loads(env_json)
            except json.JSONDecodeError:
                env = {}

            server = DiscoveredMcpServer(
                name=name,
                source="environment",
                command=command,
                args=args if isinstance(args, list) else [],
                url=url,
                env=env if isinstance(env, dict) else {},
                enabled=True,
                description=f"从环境变量 {prefix}_* 发现",
            )
            discovered.append(server)

        if discovered:
            logger.info(f"从环境变量发现 {len(discovered)} 个 MCP 服务器")

        return discovered

    def invalidate_cache(self) -> None:
        """Invalidate the discovery cache."""
        self._cache.clear()
        self._cache_valid = False
        logger.debug("MCP 发现缓存已失效")

    def list_server_names(self) -> List[str]:
        """
        List all discovered server names.

        Returns:
            List of server names
        """
        servers = self.discover_all()
        return [server.name for server in servers]

    def get_server(self, name: str) -> Optional[DiscoveredMcpServer]:
        """
        Get a specific server by name.

        Args:
            name: Server name

        Returns:
            DiscoveredMcpServer or None
        """
        servers = self.discover_all()
        for server in servers:
            if server.name == name:
                return server
        return None


# Global instance
_discovery_service: Optional[McpServerDiscoveryService] = None


def get_mcp_discovery_service() -> McpServerDiscoveryService:
    """Get global MCP discovery service instance."""
    global _discovery_service
    if _discovery_service is None:
        _discovery_service = McpServerDiscoveryService()
    return _discovery_service
