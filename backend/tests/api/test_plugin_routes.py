# ruff: noqa: UP006, UP007, UP035
"""R82：``/api/v1/plugins`` 生命周期 REST 契约测试。"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict

import pytest

from backend.plugins.host import PluginHostLimits, PluginHostManager
from backend.plugins.manifest import EXAMPLE_MANIFEST
from backend.plugins.registry import CapabilityRegistry
from backend.plugins.tool_bridge import PluginToolBridge

pytestmark = pytest.mark.unit


def _manifest(name: str = "route-plugin", *, with_permissions: bool = True) -> Dict[str, Any]:
    data = copy.deepcopy(EXAMPLE_MANIFEST)
    data["name"] = name
    if with_permissions:
        data["capabilities"][0]["permissions"] = ["file:read"]
        data["capabilities"][1]["permissions"] = ["network:write", "file:read"]
    else:
        data["capabilities"][0]["permissions"] = []
        data["capabilities"][1]["permissions"] = []
    return data


def _body(
    name: str = "route-plugin",
    *,
    confirm: bool = False,
    with_permissions: bool = True,
) -> Dict[str, Any]:
    return {
        "manifest": _manifest(name, with_permissions=with_permissions),
        "install_path": f"/plugins/{name}",
        "confirm_permissions": confirm,
    }


async def _install(client, name: str = "route-plugin"):
    response = await client.post("/api/v1/plugins", json=_body(name, confirm=True))
    assert response.status_code == 201
    return response


@pytest.mark.asyncio()
async def test_install_requires_backend_permission_confirmation(client):
    response = await client.post("/api/v1/plugins", json=_body())

    assert response.status_code == 409
    payload = response.json()
    assert payload["error"] == "permissions_confirmation_required"
    assert payload["permissions"] == ["file:read", "network:write"]
    assert [group["capability"] for group in payload["by_capability"]] == [
        "example-tool",
        "example-skill",
    ]

    detail = await client.get("/api/v1/plugins/route-plugin")
    assert detail.status_code == 404


@pytest.mark.asyncio()
async def test_install_without_permissions_does_not_require_confirmation(client):
    response = await client.post(
        "/api/v1/plugins",
        json=_body("quiet-plugin", with_permissions=False),
    )

    assert response.status_code == 201
    assert response.json()["plugin"]["permissions"] == []


@pytest.mark.asyncio()
async def test_plugin_lifecycle_full_chain(client):
    response = await _install(client)
    plugin = response.json()["plugin"]
    assert plugin["name"] == "route-plugin"
    assert plugin["status"] == "installed"
    assert plugin["display_name"] == "Example Plugin"
    assert plugin["permissions"] == ["file:read", "network:write"]
    assert plugin["manifest"]["capabilities"][0]["name"] == "example-tool"
    assert plugin["runtime"]["state"] == "pending"
    assert plugin["runtime"]["running"] is False

    listed = await client.get("/api/v1/plugins", params={"status": "installed"})
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()["plugins"]] == ["route-plugin"]

    permissions = await client.get("/api/v1/plugins/route-plugin/permissions")
    assert permissions.status_code == 200
    assert permissions.json()["permissions"] == ["file:read", "network:write"]

    enabled = await client.post("/api/v1/plugins/route-plugin/enable")
    assert enabled.status_code == 200
    assert enabled.json()["plugin"]["status"] == "enabled"

    configured = await client.patch(
        "/api/v1/plugins/route-plugin/config",
        json={"config": {"api_key": "secret", "enabled": True}},
    )
    assert configured.status_code == 200
    assert configured.json()["plugin"]["config"] == {
        "api_key": "secret",
        "enabled": True,
    }

    disabled = await client.post("/api/v1/plugins/route-plugin/disable")
    assert disabled.status_code == 200
    assert disabled.json()["plugin"]["status"] == "disabled"

    uninstalled = await client.delete("/api/v1/plugins/route-plugin")
    assert uninstalled.status_code == 200
    assert uninstalled.json()["plugin"]["status"] == "uninstalled"

    restored = await client.post("/api/v1/plugins/route-plugin/restore")
    assert restored.status_code == 200
    assert restored.json()["plugin"]["status"] == "installed"

    logs = await client.get("/api/v1/plugins/route-plugin/logs")
    assert logs.status_code == 200
    assert [event["event"] for event in reversed(logs.json()["logs"])] == [
        "installed",
        "enabled",
        "config_updated",
        "disabled",
        "uninstalled",
        "restored",
    ]


@pytest.mark.asyncio()
async def test_global_logs_route_is_not_shadowed_by_detail(client):
    await _install(client)
    await client.post("/api/v1/plugins/route-plugin/enable")

    response = await client.get("/api/v1/plugins/logs", params={"limit": 1})

    assert response.status_code == 200
    assert len(response.json()["logs"]) == 1
    assert response.json()["logs"][0]["plugin_name"] == "route-plugin"
    assert response.json()["logs"][0]["event"] == "enabled"


@pytest.mark.asyncio()
async def test_duplicate_install_returns_conflict(client):
    await _install(client)

    response = await client.post(
        "/api/v1/plugins",
        json=_body(confirm=True),
    )

    assert response.status_code == 409
    assert response.json()["error"] == "plugin_already_exists"


@pytest.mark.asyncio()
async def test_invalid_manifest_returns_422(client):
    body = _body(confirm=True)
    del body["manifest"]["metadata"]

    response = await client.post("/api/v1/plugins", json=body)

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_manifest"


@pytest.mark.asyncio()
async def test_unknown_plugin_returns_404(client):
    for method, path in [
        ("get", "/api/v1/plugins/missing-plugin"),
        ("post", "/api/v1/plugins/missing-plugin/enable"),
        ("get", "/api/v1/plugins/missing-plugin/logs"),
        ("get", "/api/v1/plugins/missing-plugin/runtime"),
        ("post", "/api/v1/plugins/missing-plugin/runtime/start"),
    ]:
        response = await getattr(client, method)(path)
        assert response.status_code == 404
        assert response.json()["error"] == "plugin_not_found"


@pytest.mark.asyncio()
async def test_disable_before_enable_returns_state_conflict(client):
    await _install(client)

    response = await client.post("/api/v1/plugins/route-plugin/disable")

    assert response.status_code == 409
    assert response.json()["error"] == "invalid_plugin_state"


@pytest.mark.asyncio()
async def test_invalid_status_filter_returns_422(client):
    response = await client.get("/api/v1/plugins", params={"status": "sleeping"})

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_status"


@pytest.mark.asyncio()
async def test_plugin_routes_reject_untrusted_origin(client):
    response = await client.get(
        "/api/v1/plugins",
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden_origin"


@pytest.mark.asyncio()
async def test_plugin_runtime_full_chain(client, tmp_path: Path, monkeypatch):
    root = tmp_path / "runtime-plugin"
    root.mkdir()
    (root / "handlers.py").write_text(
        """
def add(a, b):
    return {"sum": a + b}
""",
        encoding="utf-8",
    )
    body = _body("runtime-plugin", with_permissions=False)
    body["install_path"] = str(root)
    body["manifest"]["capabilities"][0]["entry_point"] = "handlers:add"

    host = PluginHostManager(
        PluginHostLimits(
            startup_timeout_seconds=5,
            request_timeout_seconds=2,
            shutdown_timeout_seconds=1,
        ),
        registry=CapabilityRegistry(),
    )
    monkeypatch.setattr(
        "backend.api.plugin_routes.get_plugin_host_manager",
        lambda: host,
    )

    try:
        installed = await client.post("/api/v1/plugins", json=body)
        assert installed.status_code == 201
        assert installed.json()["plugin"]["runtime"]["state"] == "pending"

        premature_start = await client.post(
            "/api/v1/plugins/runtime-plugin/runtime/start"
        )
        assert premature_start.status_code == 409
        assert premature_start.json()["code"] == "PLUGIN_NOT_ENABLED"

        enabled = await client.post("/api/v1/plugins/runtime-plugin/enable")
        assert enabled.status_code == 200
        assert enabled.json()["plugin"]["runtime"]["state"] == "pending"

        premature_invoke = await client.post(
            "/api/v1/plugins/runtime-plugin/runtime/invoke",
            json={"capability": "example-tool", "arguments": {"a": 1, "b": 2}},
        )
        assert premature_invoke.status_code == 409
        assert premature_invoke.json()["code"] == "PLUGIN_NOT_RUNNING"

        started = await client.post(
            "/api/v1/plugins/runtime-plugin/runtime/start"
        )
        assert started.status_code == 200
        runtime = started.json()["runtime"]
        assert runtime["state"] == "active"
        assert runtime["running"] is True
        assert runtime["pid"] is not None
        assert runtime["capabilities"] == ["example-tool"]
        assert started.json()["plugin"]["runtime"]["state"] == "active"

        invoked = await client.post(
            "/api/v1/plugins/runtime-plugin/runtime/invoke",
            json={"capability": "example-tool", "arguments": {"a": 2, "b": 5}},
        )
        assert invoked.status_code == 200
        assert invoked.json()["result"] == {"sum": 7}

        restarted = await client.post(
            "/api/v1/plugins/runtime-plugin/runtime/restart"
        )
        assert restarted.status_code == 200
        assert restarted.json()["runtime"]["restart_count"] == 1
        assert restarted.json()["runtime"]["state"] == "active"

        configured = await client.patch(
            "/api/v1/plugins/runtime-plugin/config",
            json={"config": {"fresh": True}},
        )
        assert configured.status_code == 200
        assert configured.json()["plugin"]["runtime"]["state"] == "disposed"

        restarted_after_config = await client.post(
            "/api/v1/plugins/runtime-plugin/runtime/start"
        )
        assert restarted_after_config.status_code == 200
        assert restarted_after_config.json()["runtime"]["state"] == "active"

        disabled = await client.post("/api/v1/plugins/runtime-plugin/disable")
        assert disabled.status_code == 200
        assert disabled.json()["plugin"]["status"] == "disabled"
        assert disabled.json()["plugin"]["runtime"]["state"] == "disposed"

        runtime_status = await client.get(
            "/api/v1/plugins/runtime-plugin/runtime"
        )
        assert runtime_status.status_code == 200
        assert runtime_status.json()["runtime"]["running"] is False

        logs = await client.get("/api/v1/plugins/runtime-plugin/logs")
        events = [event["event"] for event in reversed(logs.json()["logs"])]
        assert "runtime_started" in events
        assert "runtime_invoked" in events
        assert "runtime_restarted" in events
        assert events.count("runtime_stopped") == 2  # config update, disable
        assert "runtime_failed" in events  # premature start attempt
    finally:
        host.shutdown_all()


@pytest.mark.asyncio()
async def test_published_runtime_tools_follow_explicit_start_and_stop(
    client,
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "runtime-tools-plugin"
    root.mkdir()
    (root / "handlers.py").write_text(
        """
def add(a, b):
    return {"sum": a + b}
""",
        encoding="utf-8",
    )
    body = _body("runtime-tools-plugin", confirm=True)
    body["install_path"] = str(root)
    capability = body["manifest"]["capabilities"][0]
    capability["entry_point"] = "handlers:add"
    capability["input_schema"] = {
        "type": "object",
        "properties": {
            "a": {"type": "number"},
            "b": {"type": "number"},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    }

    bridge = PluginToolBridge()
    host = PluginHostManager(
        PluginHostLimits(
            startup_timeout_seconds=5,
            request_timeout_seconds=2,
            shutdown_timeout_seconds=1,
        ),
        registry=CapabilityRegistry(),
        tool_bridge=bridge,
    )
    monkeypatch.setattr(
        "backend.api.plugin_routes.get_plugin_host_manager",
        lambda: host,
    )
    monkeypatch.setattr(
        "backend.api.plugin_routes.get_plugin_tool_bridge",
        lambda: bridge,
    )

    try:
        installed = await client.post("/api/v1/plugins", json=body)
        assert installed.status_code == 201
        enabled = await client.post(
            "/api/v1/plugins/runtime-tools-plugin/enable"
        )
        assert enabled.status_code == 200

        before_start = await client.get("/api/v1/plugins/runtime/tools")
        assert before_start.status_code == 200
        assert before_start.json() == {"tools": [], "count": 0}
        runtime = await client.get(
            "/api/v1/plugins/runtime-tools-plugin/runtime"
        )
        assert runtime.json()["runtime"]["running"] is False

        blocked = await client.get(
            "/api/v1/plugins/runtime/tools",
            headers={"Origin": "https://evil.example"},
        )
        assert blocked.status_code == 403
        assert blocked.json()["error"] == "forbidden_origin"

        started = await client.post(
            "/api/v1/plugins/runtime-tools-plugin/runtime/start"
        )
        assert started.status_code == 200
        assert started.json()["runtime"]["running"] is True

        listed = await client.get("/api/v1/plugins/runtime/tools")
        assert listed.status_code == 200
        assert listed.json() == {
            "tools": [
                {
                    "plugin_name": "runtime-tools-plugin",
                    "capability_name": "example-tool",
                    "tool_name": (
                        "plugin__runtime-tools-plugin__example-tool"
                    ),
                    "description": (
                        "[Plugin:runtime-tools-plugin] "
                        "An example tool provided by this plugin"
                    ),
                    "risk": "exec",
                    "permissions": ["file:read"],
                }
            ],
            "count": 1,
        }

        stopped = await client.post(
            "/api/v1/plugins/runtime-tools-plugin/runtime/stop"
        )
        assert stopped.status_code == 200
        after_stop = await client.get("/api/v1/plugins/runtime/tools")
        assert after_stop.status_code == 200
        assert after_stop.json() == {"tools": [], "count": 0}
        assert host.tool_bridge is bridge
    finally:
        host.shutdown_all()
