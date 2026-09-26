"""
Plugin capability registry.

This module provides the CapabilityRegistry for managing plugin capabilities:
tools, skills, hooks, MCP servers, and commands.

Capabilities can be dynamically registered and unregistered at runtime.

Author: Claude
Date: 2026-09-26
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from backend.plugins.manifest import CapabilityType, PluginCapability

logger = logging.getLogger(__name__)


class RegisteredCapability(BaseModel):
    """A capability registered at runtime."""

    plugin_name: str = Field(..., description="提供此能力的插件名称")
    capability: PluginCapability = Field(..., description="能力定义")
    handler: Optional[Any] = Field(default=None, description="能力处理器（函数/对象）")
    enabled: bool = Field(default=True, description="是否启用")

    class Config:
        """Pydantic v1 compatibility."""

        arbitrary_types_allowed = True


class CapabilityConflictError(Exception):
    """Raised when capability name conflicts."""

    pass


class CapabilityNotFoundError(Exception):
    """Raised when capability is not found."""

    pass


class CapabilityRegistry:
    """
    Registry for plugin capabilities.

    Manages dynamic registration and unregistration of plugin capabilities
    (tools, skills, hooks, MCP servers, commands).

    Usage:
        registry = CapabilityRegistry()
        registry.register("my-plugin", capability, handler=my_handler)
        handler = registry.get("tool", "my-tool")
        registry.unregister("my-plugin", "my-tool")
    """

    def __init__(self) -> None:
        """Initialize capability registry."""
        # Key: (capability_type, capability_name) -> RegisteredCapability
        self._capabilities: Dict[tuple[str, str], RegisteredCapability] = {}

        # Plugin index: plugin_name -> set of (type, name)
        self._plugin_index: Dict[str, set[tuple[str, str]]] = {}

    def register(
        self,
        plugin_name: str,
        capability: PluginCapability,
        handler: Optional[Any] = None,
    ) -> RegisteredCapability:
        """
        Register a capability.

        Args:
            plugin_name: Name of the plugin providing the capability
            capability: Capability definition
            handler: Optional handler function/object

        Returns:
            RegisteredCapability

        Raises:
            CapabilityConflictError: If capability already registered
        """
        key = (capability.type.value, capability.name)

        if key in self._capabilities:
            existing = self._capabilities[key]
            raise CapabilityConflictError(
                f"能力已注册: {capability.type.value}/{capability.name} "
                f"(由插件 {existing.plugin_name} 提供)"
            )

        registered = RegisteredCapability(
            plugin_name=plugin_name,
            capability=capability,
            handler=handler,
            enabled=True,
        )

        self._capabilities[key] = registered

        # Update plugin index
        if plugin_name not in self._plugin_index:
            self._plugin_index[plugin_name] = set()
        self._plugin_index[plugin_name].add(key)

        logger.info(
            f"能力已注册: {plugin_name} -> {capability.type.value}/{capability.name}"
        )

        return registered

    def unregister(self, plugin_name: str, capability_name: str) -> None:
        """
        Unregister a capability.

        Args:
            plugin_name: Plugin name
            capability_name: Capability name

        Raises:
            CapabilityNotFoundError: If capability not found
        """
        # Find the capability by name (search all types)
        key = None
        for cap_type in CapabilityType:
            test_key = (cap_type.value, capability_name)
            if test_key in self._capabilities:
                registered = self._capabilities[test_key]
                if registered.plugin_name == plugin_name:
                    key = test_key
                    break

        if key is None:
            raise CapabilityNotFoundError(
                f"能力未找到: {plugin_name}/{capability_name}"
            )

        del self._capabilities[key]

        # Update plugin index
        if plugin_name in self._plugin_index:
            self._plugin_index[plugin_name].discard(key)
            if not self._plugin_index[plugin_name]:
                del self._plugin_index[plugin_name]

        logger.info(f"能力已注销: {plugin_name} -> {capability_name}")

    def unregister_all(self, plugin_name: str) -> int:
        """
        Unregister all capabilities from a plugin.

        Args:
            plugin_name: Plugin name

        Returns:
            Number of unregistered capabilities
        """
        if plugin_name not in self._plugin_index:
            return 0

        keys = list(self._plugin_index[plugin_name])
        count = 0

        for key in keys:
            if key in self._capabilities:
                del self._capabilities[key]
                count += 1

        del self._plugin_index[plugin_name]

        logger.info(f"已注销插件 {plugin_name} 的 {count} 个能力")

        return count

    def get(
        self, capability_type: Union[CapabilityType, str], capability_name: str
    ) -> Optional[RegisteredCapability]:
        """
        Get a registered capability.

        Args:
            capability_type: Capability type (enum or string)
            capability_name: Capability name

        Returns:
            RegisteredCapability or None if not found
        """
        if isinstance(capability_type, CapabilityType):
            type_str = capability_type.value
        else:
            type_str = capability_type

        key = (type_str, capability_name)
        registered = self._capabilities.get(key)

        if registered is None or not registered.enabled:
            return None

        return registered

    def get_handler(
        self, capability_type: Union[CapabilityType, str], capability_name: str
    ) -> Optional[Any]:
        """
        Get the handler for a capability.

        Args:
            capability_type: Capability type
            capability_name: Capability name

        Returns:
            Handler or None if not found
        """
        registered = self.get(capability_type, capability_name)
        return registered.handler if registered else None

    def enable(self, plugin_name: str, capability_name: str) -> None:
        """
        Enable a capability.

        Args:
            plugin_name: Plugin name
            capability_name: Capability name

        Raises:
            CapabilityNotFoundError: If capability not found
        """
        registered = self._find_capability(plugin_name, capability_name)
        registered.enabled = True
        logger.info(f"能力已启用: {plugin_name}/{capability_name}")

    def disable(self, plugin_name: str, capability_name: str) -> None:
        """
        Disable a capability.

        Args:
            plugin_name: Plugin name
            capability_name: Capability name

        Raises:
            CapabilityNotFoundError: If capability not found
        """
        registered = self._find_capability(plugin_name, capability_name)
        registered.enabled = False
        logger.info(f"能力已禁用: {plugin_name}/{capability_name}")

    def list_capabilities(
        self,
        plugin_name: Optional[str] = None,
        capability_type: Optional[CapabilityType | str] = None,
    ) -> List[RegisteredCapability]:
        """
        List registered capabilities.

        Args:
            plugin_name: Optional filter by plugin
            capability_type: Optional filter by type

        Returns:
            List of RegisteredCapability
        """
        results = []

        for registered in self._capabilities.values():
            # Filter by plugin
            if plugin_name is not None and registered.plugin_name != plugin_name:
                continue

            # Filter by type
            if capability_type is not None:
                if isinstance(capability_type, CapabilityType):
                    type_str = capability_type.value
                else:
                    type_str = capability_type

                if registered.capability.type.value != type_str:
                    continue

            results.append(registered)

        return results

    def list_plugins(self) -> List[str]:
        """
        List all plugins with registered capabilities.

        Returns:
            List of plugin names
        """
        return list(self._plugin_index.keys())

    def has_capability(
        self, capability_type: Union[CapabilityType, str], capability_name: str
    ) -> bool:
        """
        Check if a capability is registered.

        Args:
            capability_type: Capability type
            capability_name: Capability name

        Returns:
            True if registered and enabled
        """
        return self.get(capability_type, capability_name) is not None

    def _find_capability(
        self, plugin_name: str, capability_name: str
    ) -> RegisteredCapability:
        """Find a capability by plugin and name."""
        for registered in self._capabilities.values():
            if (
                registered.plugin_name == plugin_name
                and registered.capability.name == capability_name
            ):
                return registered

        raise CapabilityNotFoundError(
            f"能力未找到: {plugin_name}/{capability_name}"
        )

    def clear(self) -> None:
        """Clear all registered capabilities."""
        count = len(self._capabilities)
        self._capabilities.clear()
        self._plugin_index.clear()
        logger.info(f"已清空注册表（{count} 个能力）")


# Global instance
_registry: Optional[CapabilityRegistry] = None


def get_capability_registry() -> CapabilityRegistry:
    """Get global capability registry instance."""
    global _registry
    if _registry is None:
        _registry = CapabilityRegistry()
    return _registry
