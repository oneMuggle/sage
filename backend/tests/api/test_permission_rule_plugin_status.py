"""R101：已保存规则列表的插件归属标注契约测试。

归属是响应视图上的只读派生：以生命周期权威名单 + 结构化
命名空间 helper 判定（不按工具名切分猜名），永不落盘；
生命周期不可读时整体降级为 null，不把「读不到」误报成
「插件无记录」。独立成文件而非续写 test_permission_routes
是因为后者已被 architecture-baseline 冻结在 831 行。
"""

from __future__ import annotations

import copy
from typing import Any, Dict

import pytest

from backend.api import permission_routes
from backend.data.settings_repo import SettingsRepository
from backend.plugins.lifecycle import PluginLifecycleManager
from backend.plugins.manifest import EXAMPLE_MANIFEST
from backend.tools.permissions import SETTINGS_KEY_RULES

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


async def test_list_rules_annotates_plugin_ownership(client):
    """通配/精确插件规则按生命周期名单归属；形状孤儿只报 missing。"""
    await _install_plugin(client, "demoplug")
    resp = await client.delete("/api/v1/plugins/demoplug")
    assert resp.status_code == 200
    SettingsRepository().set_json(
        SETTINGS_KEY_RULES,
        [
            {"tool_pattern": "plugin__demoplug__*", "decision": "deny"},
            {"tool_pattern": "plugin__demoplug__run", "decision": "allow"},
            {"tool_pattern": "bash", "decision": "allow"},
            {"tool_pattern": "plugin__ghost__*", "decision": "ask"},
            {"tool_pattern": "plugin__*", "decision": "deny"},
        ],
    )

    resp = await client.get("/api/v1/permissions/rules")

    assert resp.status_code == 200
    assert resp.json()["rules"] == [
        {
            "tool_pattern": "plugin__demoplug__*",
            "decision": "deny",
            "plugin_name": "demoplug",
            "plugin_status": "uninstalled",
        },
        {
            "tool_pattern": "plugin__demoplug__run",
            "decision": "allow",
            "plugin_name": "demoplug",
            "plugin_status": "uninstalled",
        },
        {
            "tool_pattern": "bash",
            "decision": "allow",
            "plugin_name": None,
            "plugin_status": None,
        },
        {
            "tool_pattern": "plugin__ghost__*",
            "decision": "ask",
            "plugin_name": None,
            "plugin_status": "missing",
        },
        {
            "tool_pattern": "plugin__*",
            "decision": "deny",
            "plugin_name": None,
            "plugin_status": "all",
        },
    ]


async def test_list_rules_annotates_enabled_plugin(client):
    """仍在册的插件按当前状态标注（enable 后为 enabled）。"""
    await _install_plugin(client, "liveplug")
    resp = await client.post("/api/v1/plugins/liveplug/enable")
    assert resp.status_code == 200
    SettingsRepository().set_json(
        SETTINGS_KEY_RULES,
        [{"tool_pattern": "plugin__liveplug__*", "decision": "allow"}],
    )

    resp = await client.get("/api/v1/permissions/rules")

    assert resp.json()["rules"] == [
        {
            "tool_pattern": "plugin__liveplug__*",
            "decision": "allow",
            "plugin_name": "liveplug",
            "plugin_status": "enabled",
        }
    ]


async def test_delete_response_annotated_but_storage_stays_pure(client):
    """标注只出现在响应视图：删除写回的存储只有 pattern/decision。"""
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES,
        [
            {"tool_pattern": "bash", "decision": "allow"},
            {"tool_pattern": "plugin__ghost__*", "decision": "deny"},
        ],
    )

    resp = await client.post(
        "/api/v1/permissions/rules/delete",
        json={"tool_pattern": "bash", "decision": "allow"},
    )

    assert resp.status_code == 200
    assert resp.json()["rules"] == [
        {
            "tool_pattern": "plugin__ghost__*",
            "decision": "deny",
            "plugin_name": None,
            "plugin_status": "missing",
        }
    ]
    assert repo.get_json(SETTINGS_KEY_RULES) == [
        {"tool_pattern": "plugin__ghost__*", "decision": "deny"}
    ]


async def test_annotation_degrades_to_null_when_lifecycle_unavailable(
    client, monkeypatch
):
    """生命周期不可读 → 列表照常返回，标注全 null（不误报 missing）。"""

    def _boom(self, status=None):
        raise RuntimeError("plugins db unavailable")

    monkeypatch.setattr(PluginLifecycleManager, "list_plugins", _boom)
    SettingsRepository().set_json(
        SETTINGS_KEY_RULES,
        [{"tool_pattern": "plugin__ghost__*", "decision": "deny"}],
    )

    resp = await client.get("/api/v1/permissions/rules")

    assert resp.status_code == 200
    assert resp.json()["rules"] == [
        {
            "tool_pattern": "plugin__ghost__*",
            "decision": "deny",
            "plugin_name": None,
            "plugin_status": None,
        }
    ]


def test_annotate_prefers_longest_plugin_name(monkeypatch):
    """a 与 a__b 共存：plugin__a__b__run 归更具体的 a__b。"""
    monkeypatch.setattr(
        permission_routes,
        "_plugin_status_index",
        lambda: {"a": "enabled", "a__b": "installed"},
    )

    annotated = permission_routes._annotate_rules_with_plugin_status(
        [
            {"tool_pattern": "plugin__a__b__run", "decision": "allow"},
            {"tool_pattern": "plugin__a__run", "decision": "deny"},
        ]
    )

    assert annotated[0]["plugin_name"] == "a__b"
    assert annotated[0]["plugin_status"] == "installed"
    assert annotated[1]["plugin_name"] == "a"
    assert annotated[1]["plugin_status"] == "enabled"
