"""
Unit tests for plugin manifest schema.

Tests cover:
- Manifest creation and validation
- Serialization/deserialization
- Field validators
- Error handling

Author: Claude
Date: 2026-09-26
"""

import json
import tempfile
from pathlib import Path

import pytest

from backend.plugins.manifest import (
    EXAMPLE_MANIFEST,
    CapabilityType,
    PluginCapability,
    PluginDependency,
    PluginManifest,
    PluginMetadata,
    PluginType,
    validate_plugin_manifest,
)


class TestPluginCapability:
    """Tests for PluginCapability model."""

    def test_create_valid_capability(self):
        """Test creating a valid capability."""
        cap = PluginCapability(
            type=CapabilityType.TOOL,
            name="my-tool",
            description="A test tool",
            entry_point="tools.my_tool",
        )
        assert cap.type == CapabilityType.TOOL
        assert cap.name == "my-tool"
        assert cap.description == "A test tool"
        assert cap.entry_point == "tools.my_tool"

    def test_capability_name_validation(self):
        """Test capability name validation."""
        # Valid names
        valid_names = ["my-tool", "my_tool", "tool123", "ToolName"]
        for name in valid_names:
            cap = PluginCapability(type=CapabilityType.TOOL, name=name)
            assert cap.name == name

        # Invalid names
        invalid_names = ["my tool", "my.tool", "tool@home", "tool!"]
        for name in invalid_names:
            with pytest.raises(ValueError, match="只能包含字母、数字"):
                PluginCapability(type=CapabilityType.TOOL, name=name)

    def test_capability_with_permissions(self):
        """Test capability with permissions."""
        cap = PluginCapability(
            type=CapabilityType.TOOL,
            name="file-reader",
            permissions=["file:read", "file:list"],
        )
        assert len(cap.permissions) == 2
        assert "file:read" in cap.permissions


class TestPluginDependency:
    """Tests for PluginDependency model."""

    def test_create_valid_dependency(self):
        """Test creating a valid dependency."""
        dep = PluginDependency(name="other-plugin", version="^1.0.0")
        assert dep.name == "other-plugin"
        assert dep.version == "^1.0.0"
        assert dep.optional is False

    def test_dependency_version_formats(self):
        """Test various version constraint formats."""
        valid_versions = ["1.0.0", "^1.0.0", "~1.0.0", "*", ">=1.0.0"]
        for version in valid_versions:
            dep = PluginDependency(name="plugin", version=version)
            assert dep.version == version

    def test_optional_dependency(self):
        """Test optional dependency."""
        dep = PluginDependency(name="plugin", version="1.0.0", optional=True)
        assert dep.optional is True


class TestPluginMetadata:
    """Tests for PluginMetadata model."""

    def test_create_valid_metadata(self):
        """Test creating valid metadata."""
        meta = PluginMetadata(
            display_name="My Plugin",
            description="A test plugin",
            author="Test Author",
        )
        assert meta.display_name == "My Plugin"
        assert meta.description == "A test plugin"
        assert meta.author == "Test Author"
        assert meta.license == "MIT"  # Default

    def test_metadata_with_categories(self):
        """Test metadata with categories and tags."""
        meta = PluginMetadata(
            display_name="Plugin",
            categories=["productivity", "tools"],
            tags=["test", "demo"],
        )
        assert len(meta.categories) == 2
        assert len(meta.tags) == 2


class TestPluginManifest:
    """Tests for PluginManifest model."""

    def test_create_valid_manifest(self):
        """Test creating a valid manifest from example."""
        manifest = PluginManifest.model_validate(EXAMPLE_MANIFEST)
        assert manifest.name == "example-plugin"
        assert manifest.version == "1.0.0"
        assert manifest.type == PluginType.PERSONAL
        assert len(manifest.capabilities) == 2

    def test_manifest_name_validation(self):
        """Test plugin name validation."""
        # Valid names
        valid_names = ["my-plugin", "my_plugin", "plugin123", "PluginName"]
        for name in valid_names:
            manifest_data = {**EXAMPLE_MANIFEST, "name": name}
            manifest = PluginManifest.model_validate(manifest_data)
            assert manifest.name == name.lower()  # Should be lowercased

        # Invalid names
        invalid_names = ["-my-plugin", "my-plugin-", "my plugin", "my.plugin"]
        for name in invalid_names:
            manifest_data = {**EXAMPLE_MANIFEST, "name": name}
            with pytest.raises(ValueError):
                PluginManifest.model_validate(manifest_data)

    def test_manifest_capabilities_unique(self):
        """Test that capability names must be unique."""
        manifest_data = {
            **EXAMPLE_MANIFEST,
            "capabilities": [
                {"type": "tool", "name": "duplicate"},
                {"type": "skill", "name": "duplicate"},  # Same name!
            ],
        }
        with pytest.raises(ValueError, match="能力名称必须唯一"):
            PluginManifest.model_validate(manifest_data)

    def test_manifest_no_self_dependency(self):
        """Test that plugin cannot depend on itself."""
        manifest_data = {
            **EXAMPLE_MANIFEST,
            "name": "my-plugin",
            "dependencies": [{"name": "my-plugin", "version": "1.0.0"}],
        }
        with pytest.raises(ValueError, match="插件不能依赖自身"):
            PluginManifest.model_validate(manifest_data)

    def test_manifest_serialization_json(self):
        """Test JSON serialization/deserialization."""
        manifest = PluginManifest.model_validate(EXAMPLE_MANIFEST)

        # Serialize to JSON
        json_str = manifest.to_json()
        assert isinstance(json_str, str)
        assert len(json_str) > 0

        # Deserialize from JSON
        manifest2 = PluginManifest.from_json(json_str)
        assert manifest == manifest2

    def test_manifest_serialization_dict(self):
        """Test dictionary serialization."""
        manifest = PluginManifest.model_validate(EXAMPLE_MANIFEST)
        data = manifest.to_dict()

        assert isinstance(data, dict)
        assert data["name"] == "example-plugin"
        assert data["version"] == "1.0.0"
        assert "metadata" in data
        assert "capabilities" in data

    def test_manifest_file_operations(self):
        """Test file save/load operations."""
        manifest = PluginManifest.model_validate(EXAMPLE_MANIFEST)

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "plugin.json"

            # Save to file
            manifest.save(manifest_path)
            assert manifest_path.exists()

            # Load from file
            manifest2 = PluginManifest.from_file(manifest_path)
            assert manifest == manifest2

            # Verify JSON format
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert data["name"] == "example-plugin"

    def test_manifest_from_file_not_found(self):
        """Test loading from non-existent file."""
        with pytest.raises(FileNotFoundError, match="插件清单文件不存在"):
            PluginManifest.from_file("/nonexistent/plugin.json")

    def test_manifest_from_file_not_file(self):
        """Test loading from directory path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="路径不是文件"):
                PluginManifest.from_file(tmpdir)


class TestValidatePluginManifest:
    """Tests for validate_plugin_manifest function."""

    def test_validate_valid_manifest(self):
        """Test validating a valid manifest file."""
        manifest = PluginManifest.model_validate(EXAMPLE_MANIFEST)

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "plugin.json"
            manifest.save(manifest_path)

            is_valid, errors = validate_plugin_manifest(manifest_path)
            assert is_valid is True
            assert len(errors) == 0

    def test_validate_nonexistent_file(self):
        """Test validating non-existent file."""
        is_valid, errors = validate_plugin_manifest("/nonexistent/plugin.json")
        assert is_valid is False
        assert len(errors) == 1
        assert "文件不存在" in errors[0]

    def test_validate_invalid_json(self):
        """Test validating invalid JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "plugin.json"
            manifest_path.write_text("invalid json{", encoding="utf-8")

            is_valid, errors = validate_plugin_manifest(manifest_path)
            assert is_valid is False
            assert len(errors) == 1
            assert "JSON 解析错误" in errors[0]

    def test_validate_invalid_schema(self):
        """Test validating manifest with invalid schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "plugin.json"
            # Missing required fields
            invalid_data = {"name": "test"}
            manifest_path.write_text(json.dumps(invalid_data), encoding="utf-8")

            is_valid, errors = validate_plugin_manifest(manifest_path)
            assert is_valid is False
            assert len(errors) == 1


class TestPluginType:
    """Tests for PluginType enum."""

    def test_plugin_types(self):
        """Test plugin type values."""
        assert PluginType.BUILTIN.value == "builtin"
        assert PluginType.CDN.value == "cdn"
        assert PluginType.PERSONAL.value == "personal"


class TestCapabilityType:
    """Tests for CapabilityType enum."""

    def test_capability_types(self):
        """Test capability type values."""
        assert CapabilityType.TOOL.value == "tool"
        assert CapabilityType.SKILL.value == "skill"
        assert CapabilityType.HOOK.value == "hook"
        assert CapabilityType.MCP_SERVER.value == "mcp_server"
        assert CapabilityType.COMMAND.value == "command"
