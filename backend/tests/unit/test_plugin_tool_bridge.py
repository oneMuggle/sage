# ruff: noqa: UP006, UP007, UP035
"""R90 plugin ToolRegistry bridge tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from backend.domain.risk import RiskClass
from backend.plugins.host import PluginHostLimits, PluginHostManager
from backend.plugins.lifecycle import PluginRecord, PluginStatus
from backend.plugins.manifest import CapabilityType, PluginCapability
from backend.plugins.registry import CapabilityRegistry
from backend.plugins.tool_bridge import (
    PluginTool,
    PluginToolBridge,
    normalize_input_schema,
    plugin_tool_name,
    register_plugin_tools,
    resolve_input_schema,
    risk_for_permissions,
)
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.registry import ToolRegistry


def _schema(*, required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "default": "World"},
        },
        "required": required or [],
        "additionalProperties": False,
    }


def _cap(
    name: str = "hello",
    *,
    input_schema: Optional[Dict[str, Any]] = None,
    config_schema: Optional[Dict[str, Any]] = None,
    permissions: Optional[List[str]] = None,
    description: str = "Say hello",
) -> PluginCapability:
    return PluginCapability(
        type=CapabilityType.TOOL,
        name=name,
        description=description,
        version="1.0.0",
        entry_point="handlers:run",
        permissions=permissions or [],
        input_schema=_schema() if input_schema is None else input_schema,
        config_schema=config_schema,
    )


class _FakeHostError(RuntimeError):
    code = "FAKE_PLUGIN_DOWN"


class _FakeHost:
    """PluginHostManager-shaped fake; records that bridge never starts it."""

    def __init__(
        self,
        running: Optional[List[Tuple[str, PluginCapability]]] = None,
        result: Any = None,
    ) -> None:
        self.running = list(running or [])
        self.result = result
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []
        self.start_calls = 0
        self.bridge: Optional[Any] = None

    def set_tool_bridge(self, bridge: Any) -> None:
        self.bridge = bridge

    def running_tool_capabilities(self) -> List[Tuple[str, PluginCapability]]:
        return list(self.running)

    def invoke(
        self,
        plugin_name: str,
        capability_name: str,
        arguments: Dict[str, Any],
    ) -> Any:
        self.calls.append((plugin_name, capability_name, dict(arguments)))
        if isinstance(self.result, Exception):
            raise self.result
        if self.result is not None:
            return self.result
        return {"echo": dict(arguments)}

    def start(self, record: Any) -> None:  # pragma: no cover - guard only
        self.start_calls += 1
        raise AssertionError("bridge must never start a plugin")


class _ExistingTool(BaseTool):
    def __init__(self, name: str) -> None:
        self._name = name
        super().__init__()

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description="pre-existing tool",
            parameters={"type": "object", "properties": {}},
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, content="existing")


def test_register_plugin_tools_syncs_running_tool_and_executes() -> None:
    capability = _cap()
    host = _FakeHost(running=[("demo-plugin", capability)])
    bridge = PluginToolBridge()
    registry = ToolRegistry()

    count = register_plugin_tools(registry, host=host, bridge=bridge)

    tool_name = plugin_tool_name("demo-plugin", "hello")
    assert count == 1
    assert host.start_calls == 0
    assert registry.list_names() == [tool_name]
    assert registry.risk_of(tool_name) is RiskClass.EXEC
    assert registry.classify(tool_name) is RiskClass.EXEC

    schemas = registry.get_schemas_for_llm()
    assert schemas == [
        {
            "name": tool_name,
            "description": "[Plugin:demo-plugin] Say hello",
            "parameters": _schema(),
        }
    ]

    tool = registry.get(tool_name)
    assert isinstance(tool, PluginTool)
    assert tool.plugin_name == "demo-plugin"
    assert tool.capability_name == "hello"
    assert tool.concurrency_safe is False
    assert tool.is_blocking is True
    assert tool.requires_tool_context is False

    result = tool.execute(name="Ada")
    assert result.success is True
    assert result.output == {"echo": {"name": "Ada"}}
    assert json.loads(result.content) == {"echo": {"name": "Ada"}}
    assert host.calls == [("demo-plugin", "hello", {"name": "Ada"})]


def test_input_schema_wins_and_config_schema_is_legacy_fallback() -> None:
    primary = _schema(required=["name"])
    fallback = {
        "properties": {"legacy": {"type": "string"}},
        "additionalProperties": True,
    }
    both = _cap(input_schema=primary, config_schema=fallback)
    legacy_only = _cap(input_schema=None, config_schema=fallback)
    # _cap uses a default when input_schema is None, so clear it explicitly
    # to model a manifest generated before R90.
    legacy_only.input_schema = None

    assert resolve_input_schema(both) == primary
    assert resolve_input_schema(legacy_only) == {
        "type": "object",
        "properties": {"legacy": {"type": "string"}},
        "additionalProperties": True,
    }


@pytest.mark.parametrize(
    "schema",
    [
        None,
        [],
        {"type": "array", "items": {"type": "string"}},
        {"type": "object", "properties": []},
        {"type": "object", "properties": {"x": {"default": object()}}},
        {
            "type": "object",
            "properties": {"x": {"type": "string", "description": "x" * 17000}},
        },
    ],
)
def test_invalid_or_missing_schema_stays_api_only(schema: Any) -> None:
    assert normalize_input_schema(schema) is None

    capability = _cap()
    capability.input_schema = schema
    capability.config_schema = None
    host = _FakeHost()
    bridge = PluginToolBridge()
    registry = ToolRegistry()
    bridge.attach_host(host, sync=False)
    bridge.register_into(registry)

    assert bridge.publish_plugin(host, "demo", [capability]) == 0
    assert registry.list_names() == []


@pytest.mark.parametrize(
    ("permissions", "expected"),
    [
        ([], RiskClass.EXEC),
        (["file:read"], RiskClass.EXEC),
        (["file:write"], RiskClass.EXEC),
        (["network:read"], RiskClass.EXTERNAL),
        (["https:write"], RiskClass.EXTERNAL),
        (["external_api:send"], RiskClass.EXTERNAL),
    ],
)
def test_risk_floor_is_exec_and_network_raises_external(
    permissions: List[str],
    expected: RiskClass,
) -> None:
    assert risk_for_permissions(permissions) is expected


def test_bridge_fans_out_replaces_and_unpublishes_live_registries() -> None:
    host = _FakeHost()
    bridge = PluginToolBridge()
    first = ToolRegistry()
    second = ToolRegistry()
    bridge.attach_host(host, sync=False)
    bridge.register_into(first)
    bridge.register_into(second)
    tool_name = plugin_tool_name("demo", "hello")

    assert bridge.publish_plugin(host, "demo", [_cap()]) == 1
    old_tool = first.get(tool_name)
    assert old_tool is not None
    assert second.get(tool_name) is old_tool

    changed = _cap(description="Say hello, updated")
    assert bridge.publish_plugin(host, "demo", [changed]) == 1
    new_tool = first.get(tool_name)
    assert new_tool is not None
    assert new_tool is not old_tool
    assert second.get(tool_name) is new_tool
    assert first.get_schemas_for_llm()[0]["description"].endswith("updated")

    assert bridge.unpublish_plugin(host, "demo") == 1
    assert first.list_names() == []
    assert second.list_names() == []


def test_stale_record_cannot_register_after_unpublish() -> None:
    host = _FakeHost()
    bridge = PluginToolBridge()
    assert bridge.publish_plugin(host, "demo", [_cap()]) == 1
    stale_record = next(iter(bridge._published.values()))

    assert bridge.unpublish_plugin(host, "demo") == 1

    registry = ToolRegistry()
    assert bridge._register_record_into(registry, stale_record) is False
    assert registry.list_names() == []


def test_refresh_removes_tools_when_host_no_longer_reports_running() -> None:
    host = _FakeHost(running=[("demo", _cap())])
    bridge = PluginToolBridge()
    registry = ToolRegistry()
    register_plugin_tools(registry, host=host, bridge=bridge)
    assert registry.list_names() == [plugin_tool_name("demo", "hello")]

    host.running = []

    assert bridge.refresh_host(host) == 0
    assert registry.list_names() == []


def test_existing_registry_tool_wins_and_survives_plugin_unpublish() -> None:
    tool_name = plugin_tool_name("demo", "hello")
    existing = _ExistingTool(tool_name)
    registry = ToolRegistry()
    registry.register(existing)
    host = _FakeHost()
    bridge = PluginToolBridge()
    bridge.attach_host(host, sync=False)
    bridge.register_into(registry)

    assert bridge.publish_plugin(host, "demo", [_cap()]) == 1
    assert registry.get(tool_name) is existing

    assert bridge.unpublish_plugin(host, "demo") == 1
    assert registry.get(tool_name) is existing


def test_namespaced_collision_across_plugin_segments_first_wins() -> None:
    host = _FakeHost()
    bridge = PluginToolBridge()
    registry = ToolRegistry()
    bridge.attach_host(host, sync=False)
    bridge.register_into(registry)

    assert bridge.publish_plugin(host, "a__b", [_cap("c")]) == 1
    assert bridge.publish_plugin(host, "a", [_cap("b__c")]) == 0

    tool = registry.get("plugin__a__b__c")
    assert isinstance(tool, PluginTool)
    assert tool.plugin_name == "a__b"
    assert tool.capability_name == "c"


def test_profile_whitelist_requires_exact_plugin_tool_name() -> None:
    host = _FakeHost(running=[("demo", _cap())])
    bridge = PluginToolBridge()
    registry = ToolRegistry()
    register_plugin_tools(registry, host=host, bridge=bridge)
    tool_name = plugin_tool_name("demo", "hello")

    assert registry.get_schemas_for_llm(allowed_tools=[tool_name])
    assert registry.get_schemas_for_llm(allowed_tools=[]) == []
    assert registry.get_schemas_for_llm(allowed_tools=["plugin__demo__*"]) == []


def test_overlong_namespaced_name_is_skipped() -> None:
    host = _FakeHost()
    bridge = PluginToolBridge()
    registry = ToolRegistry()
    bridge.attach_host(host, sync=False)
    bridge.register_into(registry)

    assert bridge.publish_plugin(host, "p" * 100, [_cap("c" * 30)]) == 0
    assert registry.list_names() == []


def test_plugin_tool_returns_structured_host_error() -> None:
    host = _FakeHost(result=_FakeHostError("worker down"))
    tool = PluginTool(
        plugin_name="demo",
        capability=_cap(),
        parameters=_schema(),
        invoke=host.invoke,
    )

    result = tool.execute(name="Ada")

    assert result.success is False
    assert result.error is not None
    assert "FAKE_PLUGIN_DOWN" in result.error
    assert "worker down" in result.error


def _real_plugin_record(tmp_path: Path) -> PluginRecord:
    root = tmp_path / "bridge-plugin"
    root.mkdir(parents=True)
    (root / "handlers.py").write_text(
        """
import os

CONFIG = {}


def configure(config):
    CONFIG.clear()
    CONFIG.update(config)


def greet(arguments):
    return {
        "message": "%s, %s!"
        % (CONFIG.get("greeting", "Hello"), arguments.get("name", "World"))
    }


def crash():
    os._exit(9)
""".lstrip(),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1.0",
        "name": "bridge-plugin",
        "version": "1.0.0",
        "type": "personal",
        "metadata": {
            "display_name": "Bridge Plugin",
            "description": "R90 bridge integration plugin",
            "author": "Sage Tests",
        },
        "capabilities": [
            {
                "type": "tool",
                "name": "greet",
                "description": "Greet someone",
                "version": "1.0.0",
                "entry_point": "handlers:greet",
                "permissions": [],
                "input_schema": _schema(),
            },
            {
                "type": "tool",
                "name": "crash",
                "description": "Crash the worker",
                "version": "1.0.0",
                "entry_point": "handlers:crash",
                "permissions": [],
                "input_schema": {"type": "object", "properties": {}},
            },
        ],
        "dependencies": [],
        "min_sage_version": "0.4.0",
    }
    return PluginRecord(
        name="bridge-plugin",
        version="1.0.0",
        status=PluginStatus.ENABLED,
        install_path=str(root),
        installed_at=0.0,
        config={"greeting": "Hello"},
        manifest=manifest,
    )


def test_real_host_start_crash_restart_and_stop_sync_tool_registry(
    tmp_path: Path,
) -> None:
    bridge = PluginToolBridge()
    capability_registry = CapabilityRegistry()
    host = PluginHostManager(
        PluginHostLimits(
            startup_timeout_seconds=5,
            request_timeout_seconds=2,
            shutdown_timeout_seconds=1,
        ),
        registry=capability_registry,
        tool_bridge=bridge,
    )
    registry = ToolRegistry()
    record = _real_plugin_record(tmp_path)
    greet_name = plugin_tool_name(record.name, "greet")
    crash_name = plugin_tool_name(record.name, "crash")

    try:
        bridge.attach_host(host)
        bridge.register_into(registry)
        assert registry.list_names() == []

        host.start(record)
        assert registry.list_names() == [greet_name, crash_name]

        greet = registry.get(greet_name)
        assert isinstance(greet, PluginTool)
        result = greet.execute(name="Ada")
        assert result.success is True
        assert result.output == {"message": "Hello, Ada!"}

        crash = registry.get(crash_name)
        assert isinstance(crash, PluginTool)
        failed = crash.execute()
        assert failed.success is False
        assert registry.list_names() == []
        assert (
            capability_registry.get_handler(CapabilityType.TOOL, "greet")
            is None
        )

        host.restart(record)
        assert registry.list_names() == [greet_name, crash_name]

        host.stop(record.name)
        assert registry.list_names() == []
    finally:
        host.shutdown_all()
        bridge.clear()
