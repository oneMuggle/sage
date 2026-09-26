"""
Unit tests for plugin lifecycle management.

Tests cover:
- Plugin installation and state transitions
- Enable/disable/uninstall/restore operations
- Database persistence
- Error handling

Author: Claude
Date: 2026-09-26
"""

import pytest

from backend.plugins.lifecycle import (
    PluginLifecycleError,
    PluginLifecycleManager,
    PluginNotFoundError,
    PluginRecord,
    PluginStateError,
    PluginStatus,
)
from backend.plugins.manifest import EXAMPLE_MANIFEST, PluginManifest


class TestPluginStatus:
    """Tests for PluginStatus enum."""

    def test_status_values(self):
        """Test status enum values."""
        assert PluginStatus.INSTALLED.value == "installed"
        assert PluginStatus.ENABLED.value == "enabled"
        assert PluginStatus.DISABLED.value == "disabled"
        assert PluginStatus.UNINSTALLED.value == "uninstalled"


class TestPluginRecord:
    """Tests for PluginRecord model."""

    def test_create_record(self):
        """Test creating a plugin record."""
        record = PluginRecord(
            name="test-plugin",
            version="1.0.0",
            status=PluginStatus.INSTALLED,
            install_path="/path/to/plugin",
            installed_at=1234567890.0,
        )
        assert record.name == "test-plugin"
        assert record.version == "1.0.0"
        assert record.status == PluginStatus.INSTALLED


class TestPluginLifecycleManager:
    """Tests for PluginLifecycleManager."""

    @pytest.fixture()
    def manager(self, tmp_path):
        """Create a test lifecycle manager."""
        db_path = tmp_path / "test_plugins.db"
        return PluginLifecycleManager(db_path=db_path)

    @pytest.fixture()
    def manifest(self):
        """Create a test manifest."""
        return PluginManifest.model_validate(EXAMPLE_MANIFEST)

    def test_install_plugin(self, manager, manifest):
        """Test installing a plugin."""
        record = manager.install(manifest, "/path/to/plugin")
        assert record.name == manifest.name
        assert record.version == manifest.version
        assert record.status == PluginStatus.INSTALLED
        assert record.install_path == "/path/to/plugin"

    def test_install_duplicate_raises(self, manager, manifest):
        """Test installing duplicate plugin raises error."""
        manager.install(manifest, "/path/to/plugin")
        with pytest.raises(PluginLifecycleError, match="插件已安装"):
            manager.install(manifest, "/path/to/plugin")

    def test_enable_plugin(self, manager, manifest):
        """Test enabling a plugin."""
        manager.install(manifest, "/path/to/plugin")
        record = manager.enable(manifest.name)
        assert record.status == PluginStatus.ENABLED
        assert record.enabled_at is not None

    def test_enable_already_enabled(self, manager, manifest):
        """Test enabling already enabled plugin is idempotent."""
        manager.install(manifest, "/path/to/plugin")
        manager.enable(manifest.name)
        record = manager.enable(manifest.name)  # Should not raise
        assert record.status == PluginStatus.ENABLED

    def test_disable_plugin(self, manager, manifest):
        """Test disabling a plugin."""
        manager.install(manifest, "/path/to/plugin")
        manager.enable(manifest.name)
        record = manager.disable(manifest.name)
        assert record.status == PluginStatus.DISABLED
        assert record.disabled_at is not None

    def test_disable_not_enabled_raises(self, manager, manifest):
        """Test disabling non-enabled plugin raises error."""
        manager.install(manifest, "/path/to/plugin")
        with pytest.raises(PluginStateError, match="插件未启用"):
            manager.disable(manifest.name)

    def test_uninstall_plugin(self, manager, manifest):
        """Test uninstalling a plugin."""
        manager.install(manifest, "/path/to/plugin")
        manager.uninstall(manifest.name)
        record = manager.get_plugin(manifest.name)
        assert record.status == PluginStatus.UNINSTALLED
        assert record.uninstalled_at is not None

    def test_uninstall_already_uninstalled(self, manager, manifest):
        """Test uninstalling already uninstalled plugin is idempotent."""
        manager.install(manifest, "/path/to/plugin")
        manager.uninstall(manifest.name)
        manager.uninstall(manifest.name)  # Should not raise
        record = manager.get_plugin(manifest.name)
        assert record.status == PluginStatus.UNINSTALLED

    def test_restore_plugin(self, manager, manifest):
        """Test restoring an uninstalled plugin."""
        manager.install(manifest, "/path/to/plugin")
        manager.uninstall(manifest.name)
        record = manager.restore(manifest.name)
        assert record.status == PluginStatus.INSTALLED
        assert record.uninstalled_at is None

    def test_restore_not_uninstalled_raises(self, manager, manifest):
        """Test restoring non-uninstalled plugin raises error."""
        manager.install(manifest, "/path/to/plugin")
        with pytest.raises(PluginStateError, match="插件未卸载"):
            manager.restore(manifest.name)

    def test_get_plugin(self, manager, manifest):
        """Test getting a plugin by name."""
        manager.install(manifest, "/path/to/plugin")
        record = manager.get_plugin(manifest.name)
        assert record.name == manifest.name

    def test_get_plugin_not_found_raises(self, manager):
        """Test getting non-existent plugin raises error."""
        with pytest.raises(PluginNotFoundError, match="插件未找到"):
            manager.get_plugin("nonexistent-plugin")

    def test_list_plugins_all(self, manager, manifest):
        """Test listing all plugins."""
        manager.install(manifest, "/path/to/plugin")
        plugins = manager.list_plugins()
        assert len(plugins) == 1

    def test_list_plugins_filtered(self, manager, manifest):
        """Test listing plugins with status filter."""
        manager.install(manifest, "/path/to/plugin")
        manager.enable(manifest.name)

        enabled = manager.list_plugins(status=PluginStatus.ENABLED)
        assert len(enabled) == 1

        installed = manager.list_plugins(status=PluginStatus.INSTALLED)
        assert len(installed) == 0

    def test_update_config(self, manager, manifest):
        """Test updating plugin configuration."""
        manager.install(manifest, "/path/to/plugin")
        config = {"api_key": "test123", "enabled": True}
        record = manager.update_config(manifest.name, config)
        assert record.config == config

    def test_persistence_across_instances(self, tmp_path, manifest):
        """Test that plugin data persists across manager instances."""
        db_path = tmp_path / "test_plugins.db"

        # First instance: install
        manager1 = PluginLifecycleManager(db_path=db_path)
        manager1.install(manifest, "/path/to/plugin")
        manager1.close()

        # Second instance: retrieve
        manager2 = PluginLifecycleManager(db_path=db_path)
        record = manager2.get_plugin(manifest.name)
        assert record.name == manifest.name
        manager2.close()

    def test_state_transitions(self, manager, manifest):
        """Test full state transition cycle."""
        # Install
        record = manager.install(manifest, "/path/to/plugin")
        assert record.status == PluginStatus.INSTALLED

        # Enable
        record = manager.enable(manifest.name)
        assert record.status == PluginStatus.ENABLED

        # Disable
        record = manager.disable(manifest.name)
        assert record.status == PluginStatus.DISABLED

        # Enable again
        record = manager.enable(manifest.name)
        assert record.status == PluginStatus.ENABLED

        # Uninstall
        manager.uninstall(manifest.name)
        record = manager.get_plugin(manifest.name)
        assert record.status == PluginStatus.UNINSTALLED

        # Restore
        record = manager.restore(manifest.name)
        assert record.status == PluginStatus.INSTALLED


class TestPluginLifecycleErrors:
    """Tests for lifecycle error handling."""

    def test_enable_uninstalled_raises(self, tmp_path):
        """Test enabling uninstalled plugin raises error."""
        db_path = tmp_path / "test.db"
        manager = PluginLifecycleManager(db_path=db_path)
        manifest = PluginManifest.model_validate(EXAMPLE_MANIFEST)

        manager.install(manifest, "/path")
        manager.uninstall(manifest.name)

        with pytest.raises(PluginStateError, match="插件已卸载"):
            manager.enable(manifest.name)

    def test_disable_uninstalled_raises(self, tmp_path):
        """Test disabling uninstalled plugin raises error."""
        db_path = tmp_path / "test.db"
        manager = PluginLifecycleManager(db_path=db_path)
        manifest = PluginManifest.model_validate(EXAMPLE_MANIFEST)

        manager.install(manifest, "/path")
        manager.uninstall(manifest.name)

        with pytest.raises(PluginStateError, match="插件未启用"):
            manager.disable(manifest.name)
