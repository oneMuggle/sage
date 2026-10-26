"""R102：按插件删除其全部已保存规则的契约测试。

选择子只能是生命周期在册的权威插件名；删除集合由服务
端以 R101 同款结构化归属选出（含长名字消歧），客户端
无 pattern 表达能力。名字不在册 400、索引不可用 503，
两者都不写存储；无规则时幂等 ok。
"""

from __future__ import annotations

import copy
from typing import Any, Dict

import pytest

from backend.api import permission_routes
from backend.data.settings_repo import SettingsRepository
from backend.plugins.lifecycle import PluginLifecycleManager
from backend.plugins.manifest import EXAMPLE_MANIFEST
from backend.tools.permissions import SETTINGS_KEY_RULES, PermissionRule, parse_rules

pytestmark = pytest.mark.unit  # 走 ASGITransport 直连 app, 属快测


def _install_body(name: str) -> Dict[str, Any]:
    data = copy.deepcopy(EXAMPLE_MANIFEST)
    data["name"] = name
    data["capabilities"][0]["permissions"] = []
    data["capabilities"][1]["permissions"] = []
    return {
        "manifest": data,
        "install_path": f"/plugins/{name}",
        "confirm_permissions": False,
    }


async def _install_plugin(client, name: str) -> None:
    resp = await client.post("/api/v1/plugins", json=_install_body(name))
    assert resp.status_code == 201


async def test_delete_by_plugin_removes_only_its_rules(client):
    """只删目标插件的通配 + 精确规则；别家与内置工具不动。"""
    await _install_plugin(client, "demoplug")
    await _install_plugin(client, "otherplug")
    resp = await client.delete("/api/v1/plugins/demoplug")
    assert resp.status_code == 200
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES,
        [
            {"tool_pattern": "plugin__demoplug__*", "decision": "deny"},
            {"tool_pattern": "plugin__demoplug__run", "decision": "allow"},
            {"tool_pattern": "plugin__otherplug__*", "decision": "allow"},
            {"tool_pattern": "bash", "decision": "allow"},
        ],
    )

    resp = await client.post(
        "/api/v1/permissions/rules/delete-by-plugin",
        json={"plugin_name": "demoplug"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["removed"] == 2
    assert [r["tool_pattern"] for r in body["rules"]] == [
        "plugin__otherplug__*",
        "bash",
    ]
    assert body["rules"][0]["plugin_name"] == "otherplug"
    assert repo.get_json(SETTINGS_KEY_RULES) == [
        {"tool_pattern": "plugin__otherplug__*", "decision": "allow"},
        {"tool_pattern": "bash", "decision": "allow"},
    ]


async def test_delete_by_plugin_unknown_plugin_400_and_no_write(client):
    """不在生命周期册子里的名字（含 missing 孤儿名）→ 400，存储不变。"""
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES,
        [{"tool_pattern": "plugin__ghost__*", "decision": "deny"}],
    )

    resp = await client.post(
        "/api/v1/permissions/rules/delete-by-plugin",
        json={"plugin_name": "ghost"},
    )

    assert resp.status_code == 400
    assert resp.json() == {"ok": False, "error": "plugin not found"}
    assert parse_rules(repo.get_json(SETTINGS_KEY_RULES)) == [
        PermissionRule("plugin__ghost__*", "deny")
    ]


async def test_delete_by_plugin_idempotent_when_no_rules_owned(client):
    """在册但无规则 → removed=0 返回 ok，存储一个字节不改。"""
    await _install_plugin(client, "quietplug")
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES, [{"tool_pattern": "bash", "decision": "deny"}]
    )

    resp = await client.post(
        "/api/v1/permissions/rules/delete-by-plugin",
        json={"plugin_name": "quietplug"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["removed"] == 0
    assert [r["tool_pattern"] for r in body["rules"]] == ["bash"]
    assert repo.get_json(SETTINGS_KEY_RULES) == [
        {"tool_pattern": "bash", "decision": "deny"}
    ]


async def test_delete_by_plugin_index_unavailable_503(client, monkeypatch):
    """插件索引不可读 → 503 拒绝写，存储不变。"""

    def _boom(self, status=None):
        raise RuntimeError("plugins db unavailable")

    monkeypatch.setattr(PluginLifecycleManager, "list_plugins", _boom)
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES,
        [{"tool_pattern": "plugin__ghost__*", "decision": "deny"}],
    )

    resp = await client.post(
        "/api/v1/permissions/rules/delete-by-plugin",
        json={"plugin_name": "ghost"},
    )

    assert resp.status_code == 503
    assert resp.json() == {"ok": False, "error": "plugin index unavailable"}
    assert parse_rules(repo.get_json(SETTINGS_KEY_RULES)) == [
        PermissionRule("plugin__ghost__*", "deny")
    ]


async def test_delete_by_plugin_prefers_longest_owner(client, monkeypatch):
    """a / a__b 共存：删 a 不碰 a__b 的规则（结构化归属与标注同源）。"""
    monkeypatch.setattr(
        permission_routes,
        "_plugin_status_index",
        lambda: {"a": "enabled", "a__b": "uninstalled"},
    )
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES,
        [
            {"tool_pattern": "plugin__a__b__run", "decision": "allow"},
            {"tool_pattern": "plugin__a__run", "decision": "deny"},
            {"tool_pattern": "plugin__a__*", "decision": "ask"},
        ],
    )

    resp = await client.post(
        "/api/v1/permissions/rules/delete-by-plugin",
        json={"plugin_name": "a"},
    )

    assert resp.status_code == 200
    assert resp.json()["removed"] == 2
    assert repo.get_json(SETTINGS_KEY_RULES) == [
        {"tool_pattern": "plugin__a__b__run", "decision": "allow"}
    ]


async def test_delete_by_plugin_evil_origin_403(client):
    """第三方网页 Origin → 403，存储不变。"""
    await _install_plugin(client, "demoplug")
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES,
        [{"tool_pattern": "plugin__demoplug__*", "decision": "allow"}],
    )

    resp = await client.post(
        "/api/v1/permissions/rules/delete-by-plugin",
        json={"plugin_name": "demoplug"},
        headers={"Origin": "https://evil.com"},
    )

    assert resp.status_code == 403
    assert resp.json() == {"ok": False, "error": "forbidden_origin"}
    assert parse_rules(repo.get_json(SETTINGS_KEY_RULES)) == [
        PermissionRule("plugin__demoplug__*", "allow")
    ]


async def test_delete_by_plugin_rejects_extra_fields(client):
    """请求体只准 plugin_name（extra=forbid → 422）。"""
    resp = await client.post(
        "/api/v1/permissions/rules/delete-by-plugin",
        json={"plugin_name": "demo", "tool_pattern": "plugin__demo__*"},
    )

    assert resp.status_code == 422
