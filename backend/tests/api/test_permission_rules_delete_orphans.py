"""R104：整组删除无归属（missing）孤儿规则的契约测试。

删除集合由服务端用 R101 同一分类口径选出（missing 类），
请求无任何选择子；索引不可用 503 不写，全局插件通配与
有归属/内置规则永不命中；无孤儿时幂等 ok 且不写存储。
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


async def test_delete_orphans_removes_only_missing_rules(client):
    """只删无记录的插件形规则；在册/已卸载归属、全局通配、内置工具全保留。"""
    await _install_plugin(client, "demoplug")
    await _install_plugin(client, "goneplug")
    resp = await client.delete("/api/v1/plugins/goneplug")
    assert resp.status_code == 200
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES,
        [
            {"tool_pattern": "plugin__ghost__*", "decision": "deny"},
            {"tool_pattern": "plugin__ghost__run", "decision": "allow"},
            {"tool_pattern": "plugin__demoplug__*", "decision": "allow"},
            {"tool_pattern": "plugin__goneplug__*", "decision": "deny"},
            {"tool_pattern": "plugin__*", "decision": "ask"},
            {"tool_pattern": "bash", "decision": "allow"},
        ],
    )

    resp = await client.post("/api/v1/permissions/rules/delete-orphans")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["removed"] == 2
    kept_patterns = [
        "plugin__demoplug__*",
        "plugin__goneplug__*",
        "plugin__*",
        "bash",
    ]
    assert [r["tool_pattern"] for r in body["rules"]] == kept_patterns
    assert body["rules"][1]["plugin_status"] == "uninstalled"
    assert [r["tool_pattern"] for r in repo.get_json(SETTINGS_KEY_RULES)] == (
        kept_patterns
    )


async def test_delete_orphans_respects_longest_owner(client, monkeypatch):
    """a / a__b 共存：落在 a__b 命名空间的规则有归属，不得按 missing 误删。"""
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
            {"tool_pattern": "plugin__ghost__run", "decision": "deny"},
        ],
    )

    resp = await client.post("/api/v1/permissions/rules/delete-orphans")

    assert resp.status_code == 200
    assert resp.json()["removed"] == 1
    assert repo.get_json(SETTINGS_KEY_RULES) == [
        {"tool_pattern": "plugin__a__b__run", "decision": "allow"}
    ]


async def test_delete_orphans_with_empty_index_keeps_global_wildcard(
    client, monkeypatch
):
    """插件册为空（索引可读但无记录）：插件形规则全清，全局通配仍保留。"""
    monkeypatch.setattr(permission_routes, "_plugin_status_index", lambda: {})
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES,
        [
            {"tool_pattern": "plugin__ghost__*", "decision": "deny"},
            {"tool_pattern": "plugin__*", "decision": "ask"},
            {"tool_pattern": "bash", "decision": "deny"},
        ],
    )

    resp = await client.post("/api/v1/permissions/rules/delete-orphans")

    assert resp.status_code == 200
    assert resp.json()["removed"] == 1
    assert repo.get_json(SETTINGS_KEY_RULES) == [
        {"tool_pattern": "plugin__*", "decision": "ask"},
        {"tool_pattern": "bash", "decision": "deny"},
    ]


async def test_delete_orphans_idempotent_when_none(client):
    """无 missing 规则 → removed=0 返回 ok，存储不变。"""
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES, [{"tool_pattern": "bash", "decision": "deny"}]
    )

    resp = await client.post("/api/v1/permissions/rules/delete-orphans")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["removed"] == 0
    assert repo.get_json(SETTINGS_KEY_RULES) == [
        {"tool_pattern": "bash", "decision": "deny"}
    ]


async def test_delete_orphans_index_unavailable_503(client, monkeypatch):
    """插件索引不可读 → 503 拒绝写（不能区分无归属与读不到）。"""

    def _boom(self, status=None):
        raise RuntimeError("plugins db unavailable")

    monkeypatch.setattr(PluginLifecycleManager, "list_plugins", _boom)
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES,
        [{"tool_pattern": "plugin__ghost__*", "decision": "deny"}],
    )

    resp = await client.post("/api/v1/permissions/rules/delete-orphans")

    assert resp.status_code == 503
    assert resp.json() == {"ok": False, "error": "plugin index unavailable"}
    assert parse_rules(repo.get_json(SETTINGS_KEY_RULES)) == [
        PermissionRule("plugin__ghost__*", "deny")
    ]


async def test_delete_orphans_evil_origin_403(client):
    """第三方网页 Origin → 403，存储不变。"""
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES,
        [{"tool_pattern": "plugin__ghost__*", "decision": "deny"}],
    )

    resp = await client.post(
        "/api/v1/permissions/rules/delete-orphans",
        headers={"Origin": "https://evil.com"},
    )

    assert resp.status_code == 403
    assert resp.json() == {"ok": False, "error": "forbidden_origin"}
    assert parse_rules(repo.get_json(SETTINGS_KEY_RULES)) == [
        PermissionRule("plugin__ghost__*", "deny")
    ]
