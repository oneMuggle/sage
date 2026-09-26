"""
Unit tests for MCP server discovery service.

Tests cover:
- Workspace config file discovery
- Environment variable discovery
- Multiple config formats
- Cache management

Author: Claude
Date: 2026-09-26
"""

import json
import tempfile
from pathlib import Path

import pytest

from backend.mcp.discovery import (
    DiscoveredMcpServer,
    McpServerDiscoveryService,
)


class TestDiscoveredMcpServer:
    """Tests for DiscoveredMcpServer model."""

    def test_create_server(self):
        """Test creating a discovered server."""
        server = DiscoveredMcpServer(
            name="test-server",
            source="workspace",
            command="test-command",
            args=["--arg1"],
            description="Test server",
        )
        assert server.name == "test-server"
        assert server.source == "workspace"
        assert server.command == "test-command"


class TestMcpServerDiscoveryService:
    """Tests for McpServerDiscoveryService."""

    @pytest.fixture
    def workspace_dir(self, tmp_path):
        """Create a temporary workspace directory."""
        return tmp_path / "workspace"

    @pytest.fixture
    def service(self, workspace_dir):
        """Create a test discovery service."""
        workspace_dir.mkdir(parents=True, exist_ok=True)
        return McpServerDiscoveryService(workspace_dir=workspace_dir)

    def test_discover_workspace_servers_nested_format(self, service, workspace_dir):
        """Test discovering servers from nested config format."""
        config = {
            "servers": {
                "server-1": {
                    "command": "cmd1",
                    "args": ["--arg1"],
                    "description": "Server 1",
                },
                "server-2": {
                    "url": "http://localhost:3000",
                    "description": "Server 2",
                },
            }
        }

        config_path = workspace_dir / ".mcp.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        servers = service.discover_workspace_servers(workspace_dir)
        assert len(servers) == 2

        names = [s.name for s in servers]
        assert "server-1" in names
        assert "server-2" in names

    def test_discover_workspace_servers_list_format(self, workspace_dir):
        """Test discovering servers from list config format."""
        workspace_dir.mkdir(parents=True, exist_ok=True)

        config = {
            "servers": [
                {"name": "server-a", "command": "cmd-a"},
                {"name": "server-b", "command": "cmd-b"},
            ]
        }

        config_path = workspace_dir / "mcp-config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        service = McpServerDiscoveryService(workspace_dir=workspace_dir)
        servers = service.discover_workspace_servers(workspace_dir)
        assert len(servers) == 2

    def test_discover_workspace_servers_flat_format(self, workspace_dir):
        """Test discovering servers from flat config format."""
        workspace_dir.mkdir(parents=True, exist_ok=True)

        config = {
            "server-x": {"command": "cmd-x"},
            "server-y": {"command": "cmd-y"},
        }

        config_path = workspace_dir / "mcp.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        service = McpServerDiscoveryService(workspace_dir=workspace_dir)
        servers = service.discover_workspace_servers(workspace_dir)
        assert len(servers) == 2

    def test_discover_nonexistent_workspace(self, tmp_path):
        """Test discovering from nonexistent workspace."""
        nonexistent = tmp_path / "nonexistent"
        service = McpServerDiscoveryService(workspace_dir=nonexistent)
        servers = service.discover_workspace_servers(nonexistent)
        assert len(servers) == 0

    def test_discover_environment_servers(self, monkeypatch):
        """Test discovering servers from environment variables."""
        monkeypatch.setenv("MCP_SERVER_TEST1_COMMAND", "test-cmd-1")
        monkeypatch.setenv("MCP_SERVER_TEST1_ARGS", '["--arg1"]')
        monkeypatch.setenv("MCP_SERVER_TEST2_URL", "http://localhost:4000")

        service = McpServerDiscoveryService()
        servers = service.discover_environment_servers()

        assert len(servers) >= 2
        names = [s.name for s in servers]
        assert "test1" in names
        assert "test2" in names

        test1 = next(s for s in servers if s.name == "test1")
        assert test1.command == "test-cmd-1"
        assert test1.args == ["--arg1"]

        test2 = next(s for s in servers if s.name == "test2")
        assert test2.url == "http://localhost:4000"

    def test_discover_all(self, service, workspace_dir):
        """Test discovering from all sources."""
        config = {
            "servers": {
                "workspace-server": {"command": "ws-cmd"},
            }
        }

        config_path = workspace_dir / ".mcp.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        servers = service.discover_all()
        assert len(servers) >= 1
        assert any(s.name == "workspace-server" for s in servers)

    def test_cache_invalidation(self, service, workspace_dir):
        """Test cache invalidation."""
        # Initial discovery
        servers1 = service.discover_all()
        count1 = len(servers1)

        # Add a server
        config = {"servers": {"new-server": {"command": "new-cmd"}}}
        config_path = workspace_dir / ".mcp.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        # Cache should still return old count
        servers2 = service.discover_all(use_cache=True)
        assert len(servers2) == count1

        # Invalidate cache
        service.invalidate_cache()

        # Now should return new count
        servers3 = service.discover_all()
        assert len(servers3) == count1 + 1

    def test_list_server_names(self, service, workspace_dir):
        """Test listing server names."""
        config = {
            "servers": {
                "server-a": {"command": "cmd-a"},
                "server-b": {"command": "cmd-b"},
            }
        }

        config_path = workspace_dir / ".mcp.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        names = service.list_server_names()
        assert "server-a" in names
        assert "server-b" in names

    def test_get_server(self, service, workspace_dir):
        """Test getting a specific server."""
        config = {
            "servers": {
                "target-server": {
                    "command": "target-cmd",
                    "description": "Target server",
                },
            }
        }

        config_path = workspace_dir / ".mcp.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        server = service.get_server("target-server")
        assert server is not None
        assert server.name == "target-server"
        assert server.command == "target-cmd"

    def test_get_server_not_found(self, service, workspace_dir):
        """Test getting nonexistent server."""
        workspace_dir.mkdir(parents=True, exist_ok=True)
        server = service.get_server("nonexistent")
        assert server is None

    def test_parse_server_with_env(self, service, workspace_dir):
        """Test parsing server with environment variables."""
        config = {
            "servers": {
                "env-server": {
                    "command": "env-cmd",
                    "env": {"KEY1": "value1", "KEY2": "value2"},
                },
            }
        }

        config_path = workspace_dir / ".mcp.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        servers = service.discover_workspace_servers(workspace_dir)
        assert len(servers) == 1

        server = servers[0]
        assert server.env == {"KEY1": "value1", "KEY2": "value2"}

    def test_multiple_config_files(self, workspace_dir):
        """Test discovering from multiple config files."""
        workspace_dir.mkdir(parents=True, exist_ok=True)

        # Create .mcp.json
        config1 = {"servers": {"server-1": {"command": "cmd-1"}}}
        (workspace_dir / ".mcp.json").write_text(
            json.dumps(config1), encoding="utf-8"
        )

        # Create mcp-config.json
        config2 = {"servers": {"server-2": {"command": "cmd-2"}}}
        (workspace_dir / "mcp-config.json").write_text(
            json.dumps(config2), encoding="utf-8"
        )

        service = McpServerDiscoveryService(workspace_dir=workspace_dir)
        servers = service.discover_workspace_servers(workspace_dir)

        # Should find servers from both files
        assert len(servers) == 2
        names = [s.name for s in servers]
        assert "server-1" in names
        assert "server-2" in names
