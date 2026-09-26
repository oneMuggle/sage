"""
Workspace scope isolation for MCP servers.

This module provides the WorkspaceScopeManager for managing workspace-level
MCP configurations, ensuring each workspace has its own isolated set of
MCP servers and settings.

Author: Claude
Date: 2026-09-26
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field

from .discovery import DiscoveredMcpServer, McpServerDiscoveryService

logger = logging.getLogger(__name__)


class WorkspaceMcpConfig(BaseModel):
    """Workspace-level MCP configuration."""

    workspace_path: str = Field(..., description="工作区路径")
    enabled_servers: List[str] = Field(
        default_factory=list, description="启用的服务器名称列表"
    )
    disabled_servers: List[str] = Field(
        default_factory=list, description="禁用的服务器名称列表"
    )
    custom_servers: List[DiscoveredMcpServer] = Field(
        default_factory=list, description="工作区自定义服务器"
    )
    auto_discover: bool = Field(default=True, description="是否自动发现服务器")

    @property
    def all_server_names(self) -> List[str]:
        """Get all server names (enabled + disabled)."""
        return self.enabled_servers + self.disabled_servers


class WorkspaceScopeError(Exception):
    """Base exception for workspace scope errors."""

    pass


class WorkspaceScopeManager:
    """
    Manage workspace-level MCP configurations.

    Each workspace can have:
    - Its own set of enabled/disabled servers
    - Custom workspace-specific servers
    - Auto-discovery settings

    Configurations are persisted to SQLite for reliability.

    Usage:
        manager = WorkspaceScopeManager()
        config = manager.get_workspace_config("/path/to/workspace")
        manager.set_server_enabled("/path/to/workspace", "server-name", True)
    """

    def __init__(self, db_path: Optional[[Path, str]] = None) -> None:
        """
        Initialize workspace scope manager.

        Args:
            db_path: Optional path to SQLite database. Defaults to ~/.sage/workspace_mcp.db
        """
        if db_path is None:
            db_path = Path.home() / ".sage" / "workspace_mcp.db"

        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, WorkspaceMcpConfig] = {}

        self._init_database()

    def _init_database(self) -> None:
        """Initialize the SQLite database schema."""
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()

            # Create workspace_mcp_config table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_mcp_config (
                    workspace_path TEXT PRIMARY KEY,
                    enabled_servers TEXT NOT NULL DEFAULT '[]',
                    disabled_servers TEXT NOT NULL DEFAULT '[]',
                    custom_servers TEXT NOT NULL DEFAULT '[]',
                    auto_discover INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            conn.commit()
            logger.debug("Workspace MCP database initialized")

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to initialize workspace MCP database: {e}")
            raise WorkspaceScopeError(f"Database initialization failed: {e}") from e
        finally:
            conn.close()

    def get_workspace_config(
        self, workspace_path: Union[Path, str]
    ) -> WorkspaceMcpConfig:
        """
        Get workspace MCP configuration.

        Args:
            workspace_path: Workspace directory path

        Returns:
            WorkspaceMcpConfig
        """
        workspace_str = str(workspace_path)

        # Check cache first
        if workspace_str in self._cache:
            return self._cache[workspace_str]

        # Load from database
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT enabled_servers, disabled_servers, custom_servers, auto_discover
                FROM workspace_mcp_config
                WHERE workspace_path = ?
            """,
                (workspace_str,),
            )

            row = cursor.fetchone()

            if row is None:
                # Create default config
                config = WorkspaceMcpConfig(workspace_path=workspace_str)
                self._save_workspace_config(config)
                return config

            enabled_json, disabled_json, custom_json, auto_discover = row

            config = WorkspaceMcpConfig(
                workspace_path=workspace_str,
                enabled_servers=json.loads(enabled_json),
                disabled_servers=json.loads(disabled_json),
                custom_servers=[
                    DiscoveredMcpServer(**s) for s in json.loads(custom_json)
                ],
                auto_discover=bool(auto_discover),
            )

            # Cache it
            self._cache[workspace_str] = config

            return config

        except Exception as e:
            logger.error(f"Failed to load workspace config: {e}")
            raise WorkspaceScopeError(f"Failed to load config: {e}") from e
        finally:
            conn.close()

    def _save_workspace_config(self, config: WorkspaceMcpConfig) -> None:
        """
        Save workspace configuration to database.

        Args:
            config: WorkspaceMcpConfig to save
        """
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()

            # Serialize custom servers
            custom_servers_json = json.dumps(
                [s.model_dump() for s in config.custom_servers]
            )

            cursor.execute(
                """
                INSERT OR REPLACE INTO workspace_mcp_config
                (workspace_path, enabled_servers, disabled_servers, custom_servers, auto_discover, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
                (
                    config.workspace_path,
                    json.dumps(config.enabled_servers),
                    json.dumps(config.disabled_servers),
                    custom_servers_json,
                    int(config.auto_discover),
                ),
            )

            conn.commit()

            # Update cache
            self._cache[config.workspace_path] = config

            logger.debug(f"Saved workspace config: {config.workspace_path}")

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to save workspace config: {e}")
            raise WorkspaceScopeError(f"Failed to save config: {e}") from e
        finally:
            conn.close()

    def set_server_enabled(
        self, workspace_path: Union[Path, str], server_name: str, enabled: bool
    ) -> None:
        """
        Enable or disable a server for a workspace.

        Args:
            workspace_path: Workspace directory path
            server_name: Server name
            enabled: Whether to enable or disable
        """
        config = self.get_workspace_config(workspace_path)

        # Remove from both lists first
        if server_name in config.enabled_servers:
            config.enabled_servers.remove(server_name)
        if server_name in config.disabled_servers:
            config.disabled_servers.remove(server_name)

        # Add to appropriate list
        if enabled:
            config.enabled_servers.append(server_name)
        else:
            config.disabled_servers.append(server_name)

        self._save_workspace_config(config)
        logger.info(
            f"Server {server_name} {'enabled' if enabled else 'disabled'} for workspace {workspace_path}"
        )

    def add_custom_server(
        self, workspace_path: Union[Path, str], server: DiscoveredMcpServer
    ) -> None:
        """
        Add a custom server to a workspace.

        Args:
            workspace_path: Workspace directory path
            server: DiscoveredMcpServer to add
        """
        config = self.get_workspace_config(workspace_path)

        # Set workspace path
        server.workspace_path = str(workspace_path)

        # Check for duplicates
        existing = next(
            (s for s in config.custom_servers if s.name == server.name), None
        )
        if existing:
            # Replace existing
            config.custom_servers = [
                s if s.name != server.name else server for s in config.custom_servers
            ]
        else:
            config.custom_servers.append(server)

        # Auto-enable
        if server.name not in config.enabled_servers:
            config.enabled_servers.append(server.name)

        self._save_workspace_config(config)
        logger.info(f"Added custom server {server.name} to workspace {workspace_path}")

    def remove_custom_server(
        self, workspace_path: Union[Path, str], server_name: str
    ) -> None:
        """
        Remove a custom server from a workspace.

        Args:
            workspace_path: Workspace directory path
            server_name: Server name to remove
        """
        config = self.get_workspace_config(workspace_path)

        config.custom_servers = [
            s for s in config.custom_servers if s.name != server_name
        ]

        # Remove from enabled/disabled lists
        if server_name in config.enabled_servers:
            config.enabled_servers.remove(server_name)
        if server_name in config.disabled_servers:
            config.disabled_servers.remove(server_name)

        self._save_workspace_config(config)
        logger.info(
            f"Removed custom server {server_name} from workspace {workspace_path}"
        )

    def set_auto_discover(
        self, workspace_path: Union[Path, str], auto_discover: bool
    ) -> None:
        """
        Set auto-discovery setting for a workspace.

        Args:
            workspace_path: Workspace directory path
            auto_discover: Whether to auto-discover servers
        """
        config = self.get_workspace_config(workspace_path)
        config.auto_discover = auto_discover
        self._save_workspace_config(config)
        logger.info(
            f"Auto-discover {'enabled' if auto_discover else 'disabled'} for workspace {workspace_path}"
        )

    def get_enabled_servers(
        self,
        workspace_path: Union[Path, str],
        discovery_service: Optional[McpServerDiscoveryService] = None,
    ) -> List[DiscoveredMcpServer]:
        """
        Get all enabled servers for a workspace.

        Args:
            workspace_path: Workspace directory path
            discovery_service: Optional discovery service for auto-discovery

        Returns:
            List of enabled DiscoveredMcpServer
        """
        config = self.get_workspace_config(workspace_path)
        enabled = []

        # Add custom servers that are enabled
        for server in config.custom_servers:
            if server.name in config.enabled_servers:
                enabled.append(server)

        # Auto-discover if enabled
        if config.auto_discover and discovery_service:
            discovered = discovery_service.discover_workspace_servers(workspace_path)
            for server in discovered:
                # Include if not explicitly disabled
                if server.name not in config.disabled_servers:
                    enabled.append(server)

        return enabled

    def list_workspaces(self) -> List[str]:
        """
        List all configured workspaces.

        Returns:
            List of workspace paths
        """
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT workspace_path FROM workspace_mcp_config")

            return [row[0] for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"Failed to list workspaces: {e}")
            return []
        finally:
            conn.close()

    def delete_workspace(self, workspace_path: Union[Path, str]) -> None:
        """
        Delete workspace configuration.

        Args:
            workspace_path: Workspace directory path
        """
        workspace_str = str(workspace_path)

        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM workspace_mcp_config WHERE workspace_path = ?",
                (workspace_str,),
            )
            conn.commit()

            # Remove from cache
            if workspace_str in self._cache:
                del self._cache[workspace_str]

            logger.info(f"Deleted workspace config: {workspace_path}")

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete workspace config: {e}")
            raise WorkspaceScopeError(f"Failed to delete config: {e}") from e
        finally:
            conn.close()

    def invalidate_cache(self) -> None:
        """Invalidate the configuration cache."""
        self._cache.clear()
        logger.debug("Workspace scope cache invalidated")


# Global instance
_scope_manager: Optional[WorkspaceScopeManager] = None


def get_workspace_scope_manager() -> WorkspaceScopeManager:
    """Get global workspace scope manager instance."""
    global _scope_manager
    if _scope_manager is None:
        _scope_manager = WorkspaceScopeManager()
    return _scope_manager
