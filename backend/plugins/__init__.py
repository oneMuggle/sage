"""
Sage Plugin System.

This package provides the plugin infrastructure for Sage,
inspired by ZCode's plugin architecture.

Main components:
- manifest: Plugin manifest schema (plugin.json)
- lifecycle: Plugin lifecycle management (install/enable/disable/uninstall)
- registry: Plugin capability registry
- host: Out-of-process plugin runtime (R83)

Author: Claude
Date: 2026-09-26
"""

from backend.plugins.host import (
    PluginHostError,
    PluginHostLimits,
    PluginHostManager,
    PluginRuntimeStatus,
    get_plugin_host_manager,
    shutdown_plugin_hosts,
)
from backend.plugins.lifecycle import (
    PluginEvent,
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
from backend.plugins.registry import (
    CapabilityConflictError,
    CapabilityNotFoundError,
    CapabilityRegistry,
    RegisteredCapability,
    get_capability_registry,
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
    "PluginEvent",
    "PluginStatus",
    "PluginLifecycleError",
    "PluginNotFoundError",
    "PluginStateError",
    "get_lifecycle_manager",
    # Registry / out-of-process host (R83)
    "CapabilityRegistry",
    "RegisteredCapability",
    "CapabilityConflictError",
    "CapabilityNotFoundError",
    "get_capability_registry",
    "PluginHostManager",
    "PluginHostLimits",
    "PluginHostError",
    "PluginRuntimeStatus",
    "get_plugin_host_manager",
    "shutdown_plugin_hosts",
]

__version__ = "1.0.0"
