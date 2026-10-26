"""R106：会话级规则查看与撤销的契约测试。

会话规则只存进程内存（R105）；按会话读/逐条撤销/清空
恒不写持久 settings，删除未命中 400、跨站 Origin 403，
且不影响其它会话与持久规则。
"""

from __future__ import annotations

from typing import Iterator

import pytest

from backend.data.settings_repo import SettingsRepository
from backend.tools.permissions import (
    SETTINGS_KEY_RULES,
    PermissionRule,
    clear_session_rules,
    parse_rules,
    remember_session_rule,
    session_rules_for,
)

pytestmark = pytest.mark.unit  # 走 ASGITransport 直连 app, 属快测

SID = "sess-r106"
OTHER = "sess-r106-other"
LIST_URL = f"/api/v1/permissions/session/{SID}/remembered-rules"
DELETE_URL = f"{LIST_URL}/delete"
CLEAR_URL = f"{LIST_URL}/clear"


@pytest.fixture(autouse=True)
def _clean_session_rules() -> Iterator[None]:
    clear_session_rules()
    yield
    clear_session_rules()


def _seed(session_id: str = SID) -> None:
    remember_session_rule(session_id, PermissionRule("bash", "allow"))
    remember_session_rule(session_id, PermissionRule("plugin__ghost__*", "deny"))


def _persistent_rules():
    return parse_rules(SettingsRepository().get_json(SETTINGS_KEY_RULES))


async def test_list_session_rules_with_annotation(client):
    """列表形态与持久列表同形，插件形无归属规则标注 missing。"""
    _seed()

    resp = await client.get(LIST_URL)

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "session_id": SID,
        "rules": [
            {
                "tool_pattern": "bash",
                "decision": "allow",
                "plugin_name": None,
                "plugin_status": None,
            },
            {
                "tool_pattern": "plugin__ghost__*",
                "decision": "deny",
                "plugin_name": None,
                "plugin_status": "missing",
            },
        ],
    }


async def test_list_unknown_session_is_empty(client):
    resp = await client.get(f"/api/v1/permissions/session/{OTHER}/remembered-rules")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "session_id": OTHER, "rules": []}


async def test_delete_session_rule_returns_remaining_and_skips_settings(client):
    SettingsRepository().set_json(
        SETTINGS_KEY_RULES, [{"tool_pattern": "bash", "decision": "deny"}]
    )
    _seed()
    _seed(OTHER)

    resp = await client.post(
        DELETE_URL, json={"tool_pattern": "bash", "decision": "allow"}
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["session_id"] == SID
    assert [r["tool_pattern"] for r in data["rules"]] == ["plugin__ghost__*"]
    assert session_rules_for(SID) == (PermissionRule("plugin__ghost__*", "deny"),)
    assert len(session_rules_for(OTHER)) == 2
    # 会话撤销永不触碰持久规则（含内容不同的同名持久规则）
    assert _persistent_rules() == [PermissionRule("bash", "deny")]


async def test_delete_session_rule_not_found_400(client):
    _seed()

    resp = await client.post(
        DELETE_URL, json={"tool_pattern": "bash", "decision": "deny"}
    )

    assert resp.status_code == 400
    assert resp.json() == {"ok": False, "error": "rule not found"}
    assert len(session_rules_for(SID)) == 2


async def test_delete_session_rule_invalid_decision_400(client):
    _seed()

    resp = await client.post(
        DELETE_URL, json={"tool_pattern": "bash", "decision": "maybe"}
    )

    assert resp.status_code == 400
    assert resp.json() == {"ok": False, "error": "rule not found"}
    assert len(session_rules_for(SID)) == 2


async def test_delete_session_rule_evil_origin_403(client):
    _seed()

    resp = await client.post(
        DELETE_URL,
        json={"tool_pattern": "bash", "decision": "allow"},
        headers={"Origin": "https://evil.com"},
    )

    assert resp.status_code == 403
    assert resp.json() == {"ok": False, "error": "forbidden_origin"}
    assert len(session_rules_for(SID)) == 2


async def test_clear_session_rules_only_own_session(client):
    SettingsRepository().set_json(
        SETTINGS_KEY_RULES, [{"tool_pattern": "bash", "decision": "deny"}]
    )
    _seed()
    _seed(OTHER)

    resp = await client.post(CLEAR_URL)

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "session_id": SID, "rules": []}
    assert session_rules_for(SID) == ()
    assert len(session_rules_for(OTHER)) == 2
    assert _persistent_rules() == [PermissionRule("bash", "deny")]


async def test_clear_session_rules_idempotent(client):
    resp = await client.post(CLEAR_URL)

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "session_id": SID, "rules": []}


async def test_clear_session_rules_evil_origin_403(client):
    _seed()

    resp = await client.post(CLEAR_URL, headers={"Origin": "https://evil.com"})

    assert resp.status_code == 403
    assert resp.json() == {"ok": False, "error": "forbidden_origin"}
    assert len(session_rules_for(SID)) == 2
