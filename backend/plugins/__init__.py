"""
Sage Plugin System.

This package provides the plugin infrastructure for Sage,
inspired by ZCode's plugin architecture.

Main components:
- manifest: Plugin manifest schema (plugin.json)
- lifecycle: Plugin lifecycle management (install/enable/disable/uninstall)
- registry: Plugin capability registry

Author: Claude
Date: 2026-09-26
"""

from backend.plugins.lifecycle import (
    PluginLifecycleError,
    PluginLifecycleManager,
    PluginNotFoundError,
    PluginRecord,
    PluginStateError,
    PluginStatus,
    get_lifecycle_manager,
)
from backend.plugins.manifest import (
    CapabilityType,
    PluginCapability,
    PluginDependency,
    PluginManifest,
    PluginMetadata,
    PluginType,
    validate_plugin_manifest,
)

__all__ = [
    # Manifest
    "PluginManifest",
    "PluginCapability",
    "PluginDependency",
    "PluginMetadata",
    "PluginType",
    "CapabilityType",
    "validate_plugin_manifest",
    # Lifecycle
    "PluginLifecycleManager",
    "PluginRecord",
    "PluginStatus",
    "PluginLifecycleError",
    "PluginNotFoundError",
    "PluginStateError",
    "get_lifecycle_manager",
]

__version__ = "1.0.0"
