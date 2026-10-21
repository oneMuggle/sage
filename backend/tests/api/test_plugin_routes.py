# ruff: noqa: UP006, UP007, UP035
"""R82：``/api/v1/plugins`` 生命周期 REST 契约测试。"""

from __future__ import annotations

import copy
from typing import Any, Dict

import pytest

from backend.plugins.manifest import EXAMPLE_MANIFEST

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
