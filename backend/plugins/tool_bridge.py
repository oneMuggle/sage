"""Bridge running out-of-process plugin tools into the LLM ToolRegistry (R90).

Only :class:`~backend.plugins.host.PluginHostManager` sessions publish tools
here. Installing or enabling a lifecycle record is not enough, and this
module never starts a plugin process: a user must explicitly start the R83
runtime first. Tools are namespaced, schema-gated, dynamically fanned out to
live registries, and removed when the host unregisters the plugin.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import threading
import weakref
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from backend.domain.risk import RiskClass
from backend.domain.tool_names import PLUGIN_TOOL_PREFIX
from backend.plugins.manifest import CapabilityType, PluginCapability
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

# PLUGIN_TOOL_PREFIX 的单一来源在 backend.domain.tool_names；此处导入后
# 仍以模块级名字再导出（__all__ 保留），既有导入面不变。
MAX_TOOL_NAME_LENGTH = 128
MAX_DESCRIPTION_CHARS = 1024
MAX_SCHEMA_BYTES = 16 * 1024
MAX_TOOLS_PER_PLUGIN = 100

_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_EXTERNAL_PERMISSION_TOKENS = {
    "external",
    "http",
    "https",
    "internet",
    "network",
    "online",
    "remote",
    "url",
    "web",
}

InvokeFn = Callable[[str, str, Dict[str, Any]], Any]


def plugin_tool_name(plugin_name: str, capability_name: str) -> str:
    """Return the LLM-visible namespaced name for a plugin tool."""

    return f"{PLUGIN_TOOL_PREFIX}{plugin_name}__{capability_name}"


def _is_valid_tool_name(name: Any) -> bool:
    return (
        isinstance(name, str)
        and 0 < len(name) <= MAX_TOOL_NAME_LENGTH
        and _TOOL_NAME_RE.match(name) is not None
    )


def risk_for_permissions(permissions: Optional[Sequence[Any]]) -> RiskClass:
    """Map declared plugin permissions to a conservative tool risk.

    Calling a plugin handler executes third-party code, and manifest
    permissions are declarations rather than an OS sandbox. The floor is
    therefore ``EXEC``; only an explicit outbound/network signal can raise
    (never lower) it to ``EXTERNAL``.
    """

    tokens = set()
    for permission in permissions or []:
        tokens.update(re.split(r"[^a-z0-9]+", str(permission).lower()))
    tokens.discard("")
    if tokens & _EXTERNAL_PERMISSION_TOKENS:
        return RiskClass.EXTERNAL
    return RiskClass.EXEC


def normalize_input_schema(raw: Any) -> Optional[Dict[str, Any]]:  # noqa: PLR0911 — schema 守卫逐项早退
    """Normalize a manifest argument schema, or return ``None`` if unusable.

    The bridge accepts only schemas that unambiguously describe a JSON
    object argument payload. It deliberately does not invent a schema for
    handlers whose manifest omitted one.
    """

    if not isinstance(raw, dict):
        return None
    try:
        encoded = json.dumps(
            raw,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return None
    if len(encoded.encode("utf-8")) > MAX_SCHEMA_BYTES:
        return None

    # Round-tripping gives us a JSON-only deep copy whose keys/value shapes
    # cannot mutate the manifest object held by the host.
    schema = json.loads(encoded)
    if not isinstance(schema, dict):
        return None

    schema_type = schema.get("type")
    if schema_type is None:
        object_keywords = {
            "properties",
            "required",
            "additionalProperties",
            "patternProperties",
            "propertyNames",
        }
        if not object_keywords.intersection(schema):
            return None
        schema["type"] = "object"
    elif schema_type != "object":
        return None

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return None
    schema["properties"] = properties

    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list):
            return None
        normalized_required: List[str] = []
        for item in required:
            if isinstance(item, str) and item not in normalized_required:
                normalized_required.append(item)
        schema["required"] = normalized_required

    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, (bool, dict)):  # noqa: UP038 — py38 tuple form
        return None
    return schema


def resolve_input_schema(capability: PluginCapability) -> Optional[Dict[str, Any]]:
    """Resolve ``input_schema`` with the R86 ``config_schema`` fallback."""

    raw = getattr(capability, "input_schema", None)
    if raw is None:
        raw = getattr(capability, "config_schema", None)
    return normalize_input_schema(raw)


def _format_description(plugin_name: str, capability: PluginCapability) -> str:
    description = str(getattr(capability, "description", "") or "").strip()
    if not description:
        description = f"Run plugin tool {capability.name}."
    text = f"[Plugin:{plugin_name}] {description}"
    if len(text) <= MAX_DESCRIPTION_CHARS:
        return text
    return text[: MAX_DESCRIPTION_CHARS - 3].rstrip() + "..."


def _render_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(result)


class PluginTool(BaseTool):
    """A ToolRegistry adapter for one running out-of-process plugin tool."""

    requires_tool_context = False
    concurrency_safe = False
    is_blocking = True

    def __init__(
        self,
        *,
        plugin_name: str,
        capability: PluginCapability,
        parameters: Dict[str, Any],
        invoke: InvokeFn,
    ) -> None:
        self._plugin_name = plugin_name
        self._capability_name = capability.name
        self._tool_name = plugin_tool_name(plugin_name, capability.name)
        self._description = _format_description(plugin_name, capability)
        self._parameters = copy.deepcopy(parameters)
        self._invoke = invoke
        self.risk = risk_for_permissions(getattr(capability, "permissions", []))
        super().__init__()

    @property
    def plugin_name(self) -> str:
        return self._plugin_name

    @property
    def capability_name(self) -> str:
        return self._capability_name

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._tool_name,
            description=self._description,
            parameters=copy.deepcopy(self._parameters),
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            result = self._invoke(
                self._plugin_name,
                self._capability_name,
                dict(kwargs),
            )
        except Exception as exc:  # noqa: BLE001 - tool errors must not crash Agent
            code = str(getattr(exc, "code", "") or "").strip()
            detail = f"{type(exc).__name__}: {exc}"
            if code:
                detail = f"{code}: {detail}"
            logger.error(
                "Plugin tool %s failed: %s",
                self._tool_name,
                detail,
            )
            return ToolResult(
                success=False,
                error=(
                    f"插件 {self._plugin_name} 的工具 "
                    f"{self._capability_name} 调用失败: {detail}"
                ),
            )
        return ToolResult(
            success=True,
            content=_render_result(result),
            output=result,
        )


@dataclass
class _PublishedTool:
    tool_name: str
    plugin_name: str
    capability_name: str
    host: Any
    tool: PluginTool
    fingerprint: str


def _fingerprint(tool: PluginTool) -> str:
    schema = tool.schema
    payload = {
        "name": schema.name,
        "description": schema.description,
        "parameters": schema.parameters,
        "risk": tool.risk.value,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class PluginToolBridge:
    """Fan running plugin tools out to live ToolRegistry instances."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._registries: List[weakref.ReferenceType] = []
        self._host_refs: List[Callable[[], Any]] = []
        self._published: Dict[str, _PublishedTool] = {}

    # ---- host and registry tracking ------------------------------------

    def attach_host(self, host: Any, *, sync: bool = True) -> None:
        """Attach a PluginHostManager-like object and optionally refresh it."""

        if host is None:
            return
        self._remember_host(host)
        setter = getattr(host, "set_tool_bridge", None)
        if callable(setter):
            setter(self)
        if sync:
            self.refresh_host(host)

    def detach_host(self, host: Any) -> int:
        """Stop publishing one host's tools and forget the host."""

        removed = self.unpublish_host(host)
        with self._lock:
            self._host_refs = [
                ref for ref in self._host_refs if ref() is not None and ref() is not host
            ]
        setter = getattr(host, "set_tool_bridge", None)
        if callable(setter):
            try:
                setter(None)
            except Exception:  # noqa: BLE001 - detach is best-effort cleanup
                logger.warning("Failed to detach plugin tool bridge from host", exc_info=True)
        return removed

    def _remember_host(self, host: Any) -> None:
        with self._lock:
            live: List[Callable[[], Any]] = []
            found = False
            for ref in self._host_refs:
                current = ref()
                if current is None:
                    continue
                live.append(ref)
                if current is host:
                    found = True
            if not found:
                try:
                    live.append(weakref.ref(host))
                except TypeError:
                    live.append(lambda host=host: host)
            self._host_refs = live

    def _live_hosts(self) -> List[Any]:
        with self._lock:
            hosts = [ref() for ref in self._host_refs]
            self._host_refs = [
                ref for ref in self._host_refs if ref() is not None
            ]
        return [host for host in hosts if host is not None]

    def track_registry(self, registry: Any) -> None:
        """Remember a ToolRegistry (weak ref) for dynamic fan-out."""

        with self._lock:
            self._registries = [
                ref for ref in self._registries if ref() is not None
            ]
            if not any(ref() is registry for ref in self._registries):
                self._registries.append(weakref.ref(registry))

    def _live_registries(self) -> List[Any]:
        with self._lock:
            live = [ref() for ref in self._registries]
            self._registries = [
                ref for ref in self._registries if ref() is not None
            ]
        return [registry for registry in live if registry is not None]

    # ---- publication ----------------------------------------------------

    def register_into(self, registry: Any) -> int:
        """Track *registry*, refresh attached hosts, and register live tools."""

        self.track_registry(registry)
        for host in self._live_hosts():
            self.refresh_host(host)
        with self._lock:
            records = list(self._published.values())
        count = 0
        for record in records:
            if self._register_record_into(registry, record):
                count += 1
        return count

    def refresh_host(self, host: Any) -> int:
        """Reconcile published tools with one host's running sessions."""

        self._remember_host(host)
        getter = getattr(host, "running_tool_capabilities", None)
        if not callable(getter):
            return 0
        try:
            entries = list(getter())
        except Exception:  # noqa: BLE001 - bridge refresh must not break Agent setup
            logger.warning("Failed to refresh plugin tools from host", exc_info=True)
            return 0

        grouped: Dict[str, List[PluginCapability]] = {}
        for entry in entries:
            try:
                plugin_name, capability = entry
            except (TypeError, ValueError):
                continue
            grouped.setdefault(str(plugin_name), []).append(capability)

        with self._lock:
            known_plugins = {
                record.plugin_name
                for record in self._published.values()
                if record.host is host
            }
        for plugin_name in known_plugins - set(grouped):
            self.unpublish_plugin(host, plugin_name)

        total = 0
        for plugin_name, capabilities in grouped.items():
            total += self.publish_plugin(host, plugin_name, capabilities)
        return total

    def publish_plugin(
        self,
        host: Any,
        plugin_name: str,
        capabilities: Sequence[PluginCapability],
    ) -> int:
        """Publish/replace one running plugin's LLM-visible tools."""

        self._remember_host(host)
        desired = self._build_records(host, plugin_name, capabilities)
        return self._replace_plugin_records(host, plugin_name, desired)

    def unpublish_plugin(self, host: Any, plugin_name: str) -> int:
        """Remove one plugin's tools from every live registry."""

        with self._lock:
            records = [
                record
                for record in self._published.values()
                if record.host is host and record.plugin_name == plugin_name
            ]
            for record in records:
                self._published.pop(record.tool_name, None)
        self._unregister_records(records)
        return len(records)

    def unpublish_host(self, host: Any) -> int:
        """Remove every tool published by one host."""

        with self._lock:
            records = [
                record
                for record in self._published.values()
                if record.host is host
            ]
            for record in records:
                self._published.pop(record.tool_name, None)
        self._unregister_records(records)
        return len(records)

    def clear(self) -> None:
        """Remove all published tools and forget hosts/registries."""

        with self._lock:
            records = list(self._published.values())
            self._published.clear()
            registries = self._live_registries()
            self._registries = []
            self._host_refs = []
        self._unregister_records(records, registries=registries)

    def published_tool_names(self) -> Tuple[str, ...]:
        with self._lock:
            return tuple(self._published.keys())

    # ---- internals ------------------------------------------------------

    def _build_records(
        self,
        host: Any,
        plugin_name: str,
        capabilities: Sequence[PluginCapability],
    ) -> List[_PublishedTool]:
        invoke = getattr(host, "invoke", None)
        if not callable(invoke):
            logger.warning(
                "Plugin host for %s has no invoke(); skipping LLM tools",
                plugin_name,
            )
            return []

        records: List[_PublishedTool] = []
        seen_names = set()
        for capability in capabilities:
            if getattr(capability, "type", None) != CapabilityType.TOOL:
                continue
            if not getattr(capability, "entry_point", None):
                continue
            tool_name = plugin_tool_name(plugin_name, capability.name)
            if tool_name in seen_names:
                continue
            seen_names.add(tool_name)
            if not _is_valid_tool_name(tool_name):
                logger.warning(
                    "Skipping plugin tool with invalid LLM name %r",
                    tool_name,
                )
                continue
            parameters = resolve_input_schema(capability)
            if parameters is None:
                logger.info(
                    "Plugin tool %s/%s has no usable input_schema; "
                    "keeping it API-only",
                    plugin_name,
                    capability.name,
                )
                continue
            tool = PluginTool(
                plugin_name=plugin_name,
                capability=capability,
                parameters=parameters,
                invoke=invoke,
            )
            records.append(
                _PublishedTool(
                    tool_name=tool_name,
                    plugin_name=plugin_name,
                    capability_name=capability.name,
                    host=host,
                    tool=tool,
                    fingerprint=_fingerprint(tool),
                )
            )
            if len(records) >= MAX_TOOLS_PER_PLUGIN:
                logger.warning(
                    "Plugin %s advertised more than %d LLM tools; truncating",
                    plugin_name,
                    MAX_TOOLS_PER_PLUGIN,
                )
                break
        return records

    def _replace_plugin_records(
        self,
        host: Any,
        plugin_name: str,
        desired: Sequence[_PublishedTool],
    ) -> int:
        with self._lock:
            old_records = [
                record
                for record in self._published.values()
                if record.host is host and record.plugin_name == plugin_name
            ]
            old_by_name = {record.tool_name: record for record in old_records}
            desired_by_name = {record.tool_name: record for record in desired}
            if old_by_name.keys() == desired_by_name.keys() and all(
                old_by_name[name].fingerprint == record.fingerprint
                for name, record in desired_by_name.items()
            ):
                return len(old_records)

            for record in old_records:
                self._published.pop(record.tool_name, None)

            accepted: List[_PublishedTool] = []
            for record in desired:
                existing = self._published.get(record.tool_name)
                if existing is not None:
                    logger.warning(
                        "Plugin tool %s already published by %s; first wins",
                        record.tool_name,
                        existing.plugin_name,
                    )
                    continue
                self._published[record.tool_name] = record
                accepted.append(record)

        self._unregister_records(old_records)
        for registry in self._live_registries():
            for record in accepted:
                self._register_record_into(registry, record)
        return len(accepted)

    def _register_record_into(self, registry: Any, record: _PublishedTool) -> bool:
        with self._lock:
            # A concurrent unpublish may have removed this snapshot after
            # register_into()/publish captured it. Holding the bridge lock
            # through the registry mutation makes publish vs. unpublish
            # linearizable: either this registration lands first and the
            # later unpublish removes it, or it is rejected as stale.
            if self._published.get(record.tool_name) is not record:
                return False
            getter = getattr(registry, "get", None)
            existing = getter(record.tool_name) if callable(getter) else None
            if existing is record.tool:
                return False
            exists = getattr(registry, "exists", None)
            if existing is not None or (callable(exists) and exists(record.tool_name)):
                logger.warning(
                    "Plugin tool %s already registered; first wins, skipping",
                    record.tool_name,
                )
                return False
            registry.register(record.tool)
            return True

    def _unregister_records(
        self,
        records: Sequence[_PublishedTool],
        *,
        registries: Optional[Sequence[Any]] = None,
    ) -> None:
        if not records:
            return
        targets = list(registries) if registries is not None else self._live_registries()
        with self._lock:
            for registry in targets:
                getter = getattr(registry, "get", None)
                unregister = getattr(registry, "unregister", None)
                if not callable(unregister):
                    continue
                for record in records:
                    existing = getter(record.tool_name) if callable(getter) else None
                    # Only remove objects this bridge actually installed. A
                    # same-named built-in/first registrant must survive.
                    if existing is record.tool:
                        unregister(record.tool_name)


_BRIDGE: Optional[PluginToolBridge] = None
_BRIDGE_LOCK = threading.RLock()


def get_plugin_tool_bridge() -> PluginToolBridge:
    """Return the process-wide plugin tool bridge."""

    global _BRIDGE
    with _BRIDGE_LOCK:
        if _BRIDGE is None:
            _BRIDGE = PluginToolBridge()
        return _BRIDGE


def reset_plugin_tool_bridge() -> None:
    """Clear the process-wide bridge (primarily for tests/shutdown)."""

    global _BRIDGE
    with _BRIDGE_LOCK:
        bridge = _BRIDGE
        _BRIDGE = None
    if bridge is not None:
        bridge.clear()


def register_plugin_tools(
    registry: Any,
    *,
    host: Any = None,
    bridge: Optional[PluginToolBridge] = None,
) -> int:
    """Sync already-running plugin tools into *registry*.

    This never starts a plugin. It only attaches to the existing host
    singleton (or an injected host) and mirrors its running sessions.
    """

    active_bridge = bridge or get_plugin_tool_bridge()
    try:
        active_host = host
        if active_host is None:
            from backend.plugins.host import get_plugin_host_manager

            active_host = get_plugin_host_manager()
        active_bridge.attach_host(active_host)
        return active_bridge.register_into(registry)
    except Exception:  # noqa: BLE001 - dynamic tools must not break built-ins
        logger.error("Plugin tool registration failed", exc_info=True)
        return 0


__all__ = [
    "MAX_DESCRIPTION_CHARS",
    "MAX_SCHEMA_BYTES",
    "MAX_TOOL_NAME_LENGTH",
    "MAX_TOOLS_PER_PLUGIN",
    "PLUGIN_TOOL_PREFIX",
    "PluginTool",
    "PluginToolBridge",
    "get_plugin_tool_bridge",
    "normalize_input_schema",
    "plugin_tool_name",
    "register_plugin_tools",
    "reset_plugin_tool_bridge",
    "resolve_input_schema",
    "risk_for_permissions",
]
