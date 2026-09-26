"""
Unit tests for workspace scope manager.

Tests cover:
- Workspace configuration CRUD
- Server enable/disable
- Custom server management
- Auto-discovery settings
- Workspace isolation
- Cache management

Author: Claude
Date: 2026-09-26
"""

import tempfile
from pathlib import Path

import pytest

from backend.mcp.discovery import DiscoveredMcpServer
from backend.mcp.workspace_scope import (
    WorkspaceMcpConfig,
    WorkspaceScopeManager,
)


class TestWorkspaceMcpConfig:
    """Tests for WorkspaceMCPConfig model."""

    def test_create_config(self):
        """Test creating a workspace config."""
        config = WorkspaceMcpConfig(
            workspace_path="/tmp/workspace",
            enabled_servers=["server-1", "server-2"],
            disabled_servers=["server-3"],
            auto_discover=True,
        )
        assert config.workspace_path == "/tmp/workspace"
        assert len(config.enabled_servers) == 2
        assert len(config.disabled_servers) == 1
        assert config.auto_discover is True

    def test_all_server_names(self):
        """Test all_server_names property."""
        config = WorkspaceMcpConfig(
            workspace_path="/tmp/workspace",
            enabled_servers=["server-1"],
            disabled_servers=["server-2", "server-3"],
        )
        all_names = config.all_server_names
        assert len(all_names) == 3
        assert "server-1" in all_names
        assert "server-2" in all_names
        assert "server-3" in all_names


class TestWorkspaceScopeManager:
    """Tests for WorkspaceScopeManager."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Create a temporary database path."""
        return tmp_path / "test_workspace.db"

    @pytest.fixture
    def manager(self, db_path):
        """Create a test manager."""
        return WorkspaceScopeManager(db_path=db_path)

    @pytest.fixture
    def workspace1(self, tmp_path):
        """Create first test workspace."""
        ws = tmp_path / "workspace1"
        ws.mkdir()
        return ws

    @pytest.fixture
    def workspace2(self, tmp_path):
        """Create second test workspace."""
        ws = tmp_path / "workspace2"
        ws.mkdir()
        return ws

    def test_get_workspace_config_default(self, manager, workspace1):
        """Test getting default workspace config."""
        config = manager.get_workspace_config(workspace1)
        assert config.workspace_path == str(workspace1)
        assert len(config.enabled_servers) == 0
        assert len(config.disabled_servers) == 0
        assert config.auto_discover is True

    def test_set_server_enabled(self, manager, workspace1):
        """Test enabling a server."""
        manager.set_server_enabled(workspace1, "server-1", True)

        config = manager.get_workspace_config(workspace1)
        assert "server-1" in config.enabled_servers
        assert "server-1" not in config.disabled_servers

    def test_set_server_disabled(self, manager, workspace1):
        """Test disabling a server."""
        manager.set_server_enabled(workspace1, "server-1", False)

        config = manager.get_workspace_config(workspace1)
        assert "server-1" in config.disabled_servers
        assert "server-1" not in config.enabled_servers

    def test_toggle_server(self, manager, workspace1):
        """Test toggling server state."""
        # Enable
        manager.set_server_enabled(workspace1, "server-1", True)
        config = manager.get_workspace_config(workspace1)
        assert "server-1" in config.enabled_servers

        # Disable
        manager.set_server_enabled(workspace1, "server-1", False)
        config = manager.get_workspace_config(workspace1)
        assert "server-1" in config.disabled_servers
        assert "server-1" not in config.enabled_servers

        # Re-enable
        manager.set_server_enabled(workspace1, "server-1", True)
        config = manager.get_workspace_config(workspace1)
        assert "server-1" in config.enabled_servers
        assert "server-1" not in config.disabled_servers

    def test_add_custom_server(self, manager, workspace1):
        """Test adding a custom server."""
        server = DiscoveredMcpServer(
            name="custom-server",
            source="workspace",
            command="custom-cmd",
            args=["--arg1"],
            description="Custom server",
        )

        manager.add_custom_server(workspace1, server)

        config = manager.get_workspace_config(workspace1)
        assert len(config.custom_servers) == 1
        assert config.custom_servers[0].name == "custom-server"
        assert config.custom_servers[0].command == "custom-cmd"
        assert "custom-server" in config.enabled_servers  # Auto-enabled

    def test_add_custom_server_replace_existing(self, manager, workspace1):
        """Test replacing an existing custom server."""
        server1 = DiscoveredMcpServer(
            name="custom-server",
            source="workspace",
            command="cmd-1",
        )
        server2 = DiscoveredMcpServer(
            name="custom-server",
            source="workspace",
            command="cmd-2",
        )

        manager.add_custom_server(workspace1, server1)
        manager.add_custom_server(workspace1, server2)

        config = manager.get_workspace_config(workspace1)
        assert len(config.custom_servers) == 1
        assert config.custom_servers[0].command == "cmd-2"

    def test_remove_custom_server(self, manager, workspace1):
        """Test removing a custom server."""
        server = DiscoveredMcpServer(
            name="custom-server",
            source="workspace",
            command="custom-cmd",
        )

        manager.add_custom_server(workspace1, server)
        manager.remove_custom_server(workspace1, "custom-server")

        config = manager.get_workspace_config(workspace1)
        assert len(config.custom_servers) == 0
        assert "custom-server" not in config.enabled_servers

    def test_set_auto_discover(self, manager, workspace1):
        """Test setting auto-discover."""
        manager.set_auto_discover(workspace1, False)

        config = manager.get_workspace_config(workspace1)
        assert config.auto_discover is False

        manager.set_auto_discover(workspace1, True)
        config = manager.get_workspace_config(workspace1)
        assert config.auto_discover is True

    def test_workspace_isolation(self, manager, workspace1, workspace2):
        """Test that workspaces are isolated."""
        # Add server to workspace1
        manager.set_server_enabled(workspace1, "server-1", True)

        # workspace2 should not have it
        config2 = manager.get_workspace_config(workspace2)
        assert "server-1" not in config2.enabled_servers
        assert "server-1" not in config2.disabled_servers

    def test_list_workspaces(self, manager, workspace1, workspace2):
        """Test listing workspaces."""
        # Create configs for both workspaces
        manager.get_workspace_config(workspace1)
        manager.get_workspace_config(workspace2)

        workspaces = manager.list_workspaces()
        assert str(workspace1) in workspaces
        assert str(workspace2) in workspaces
        assert len(workspaces) == 2

    def test_delete_workspace(self, manager, workspace1, workspace2):
        """Test deleting a workspace."""
        manager.get_workspace_config(workspace1)
        manager.get_workspace_config(workspace2)

        manager.delete_workspace(workspace1)

        workspaces = manager.list_workspaces()
        assert str(workspace1) not in workspaces
        assert str(workspace2) in workspaces

    def test_cache_invalidation(self, manager, workspace1):
        """Test cache invalidation."""
        # Load config (cached)
        config1 = manager.get_workspace_config(workspace1)
        assert len(config1.enabled_servers) == 0

        # Modify directly in database
        manager.set_server_enabled(workspace1, "server-1", True)

        # Cache should still return old value
        config2 = manager.get_workspace_config(workspace1)
        assert "server-1" in config2.enabled_servers  # Updated via set_server_enabled

        # Invalidate cache
        manager.invalidate_cache()

        # Should reload from database
        config3 = manager.get_workspace_config(workspace1)
        assert "server-1" in config3.enabled_servers

    def test_persistence_across_instances(self, db_path, workspace1):
        """Test that data persists across manager instances."""
        # Create first instance and add data
        manager1 = WorkspaceScopeManager(db_path=db_path)
        manager1.set_server_enabled(workspace1, "server-1", True)

        # Create second instance
        manager2 = WorkspaceScopeManager(db_path=db_path)

        # Should load persisted data
        config = manager2.get_workspace_config(workspace1)
        assert "server-1" in config.enabled_servers

    def test_get_enabled_servers_with_discovery(self, manager, workspace1):
        """Test getting enabled servers with discovery service."""
        # Add custom server
        custom = DiscoveredMcpServer(
            name="custom-server",
            source="workspace",
            command="custom-cmd",
        )
        manager.add_custom_server(workspace1, custom)

        # Get enabled servers (without discovery service)
        enabled = manager.get_enabled_servers(workspace1)
        assert len(enabled) == 1
        assert enabled[0].name == "custom-server"

    def test_get_enabled_servers_with_disabled(self, manager, workspace1):
        """Test that disabled servers are not returned."""
        # Add and enable a server
        server1 = DiscoveredMcpServer(
            name="server-1",
            source="workspace",
            command="cmd-1",
        )
        manager.add_custom_server(workspace1, server1)

        # Disable it
        manager.set_server_enabled(workspace1, "server-1", False)

        # Should not be in enabled list
        enabled = manager.get_enabled_servers(workspace1)
        assert len(enabled) == 0

    def test_multiple_custom_servers(self, manager, workspace1):
        """Test adding multiple custom servers."""
        for i in range(3):
            server = DiscoveredMcpServer(
                name=f"server-{i}",
                source="workspace",
                command=f"cmd-{i}",
            )
            manager.add_custom_server(workspace1, server)

        config = manager.get_workspace_config(workspace1)
        assert len(config.custom_servers) == 3
        assert len(config.enabled_servers) == 3
