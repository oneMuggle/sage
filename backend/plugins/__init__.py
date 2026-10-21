"""
Sage Plugin System.

This package provides the plugin infrastructure for Sage,
inspired by ZCode's plugin architecture.

Main components:
- manifest: Plugin manifest schema (plugin.json)
- lifecycle: Plugin lifecycle management (install/enable/disable/uninstall)
- registry: Plugin capability registry
- host: Out-of-process plugin runtime (R83)
- scaffold: Plugin templates, static validation, and dev smoke (R86)
- index_catalog: Static plugin index build/validate/search (R86)

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
from backend.plugins.index_catalog import (
    PluginCompatibility,
    PluginIndex,
    PluginIndexBuildResult,
    PluginIndexEntry,
    PluginIndexIssue,
    PluginIndexValidation,
    PluginSignature,
    PluginSource,
    PluginSourceKind,
    Win7Support,
    build_plugin_index,
    discover_plugin_roots,
    load_plugin_index,
    search_plugin_index,
    validate_plugin_index,
    write_plugin_index,
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
from backend.plugins.scaffold import (
    TEMPLATE_NAMES,
    PluginDevResult,
    PluginPackageValidation,
    PluginValidationIssue,
    list_templates,
    run_plugin_dev,
    scaffold_plugin,
    validate_plugin_package,
)
from backend.plugins.scaffold_templates import (
    PluginEcosystemError,
    ScaffoldOptions,
    ScaffoldResult,
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
    # Ecosystem: scaffold / validation / dev smoke (R86)
    "TEMPLATE_NAMES",
    "PluginEcosystemError",
    "ScaffoldOptions",
    "ScaffoldResult",
    "list_templates",
    "scaffold_plugin",
    "PluginValidationIssue",
    "PluginPackageValidation",
    "validate_plugin_package",
    "PluginDevResult",
    "run_plugin_dev",
    # Ecosystem: static index (R86)
    "PluginCompatibility",
    "PluginSignature",
    "PluginSource",
    "PluginSourceKind",
    "Win7Support",
    "PluginIndexEntry",
    "PluginIndex",
    "PluginIndexIssue",
    "PluginIndexValidation",
    "PluginIndexBuildResult",
    "discover_plugin_roots",
    "build_plugin_index",
    "write_plugin_index",
    "load_plugin_index",
    "validate_plugin_index",
    "search_plugin_index",
]

__version__ = "1.0.0"
