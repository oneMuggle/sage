"""R105「仅本次会话记住」的应答契约测试。

remember + remember_duration=session → 只写进程内会话
规则存储（按请求创建时服务端捕获的会话归属），settings
永不落盘；无会话归属时降级为不记住、绝不转永久；默认
时长（不带字段）仍是既有持久化行为。
"""

from __future__ import annotations

import asyncio
from typing import Optional

import pytest

from backend.data.settings_repo import SettingsRepository
from backend.services.permission_gate import (
    ApprovalRequest,
    init_permission_gate,
    reset_permission_gate,
)
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.permissions import (
    SETTINGS_KEY_RULES,
    PermissionRule,
    clear_session_rules,
    parse_rules,
    session_rules_for,
)

pytestmark = pytest.mark.unit  # 走 ASGITransport 直连 app, 属快测


@pytest.fixture()
def gate():
    reset_permission_gate()
    g = init_permission_gate()
    yield g
    reset_permission_gate()


@pytest.fixture(autouse=True)
def _clean_session_rules():
    clear_session_rules()
    yield
    clear_session_rules()


def _pending_request(
    tool_name: str = "bash",
    plugin_name: Optional[str] = None,
    session_id: Optional[str] = "sess-r105",
) -> ApprovalRequest:
    """在指定会话上下文下创建待审批请求（模拟 agent 循环建请求）。"""
    if session_id is None:
        return ApprovalRequest.create(
            tool_name=tool_name,
            args={"command": "ls"},
            risk="suspicious",
            message="prompt 模式需要确认",
            plugin_name=plugin_name,
        )
    token = set_tool_context(
        ToolExecutionContext(
            session_id=session_id,
            stream_id="test-stream",
            binding_generation=0,
            office_doc_scope=frozenset(),
        )
    )
    try:
        return ApprovalRequest.create(
            tool_name=tool_name,
            args={"command": "ls"},
            risk="suspicious",
            message="prompt 模式需要确认",
            plugin_name=plugin_name,
        )
    finally:
        reset_tool_context(token)


async def _answer(client, gate, req, **body):
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)
    resp = await client.post(
        f"/api/v1/permissions/{req.request_id}/answer", json=body
    )
    answer = await holder
    return resp, answer


async def test_session_remember_writes_only_session_store(gate, client):
    """session 时长：settings 不变，会话存储命中该会话。"""
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES, [{"tool_pattern": "read_file", "decision": "deny"}]
    )
    req = _pending_request()
    assert req.session_id == "sess-r105"  # 创建时从上下文捕获
    assert "session_id" not in req.to_dict()  # 不下发前端

    resp, answer = await _answer(
        client,
        gate,
        req,
        approved=True,
        remember=True,
        remember_duration="session",
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert answer.approved is True
    assert parse_rules(repo.get_json(SETTINGS_KEY_RULES)) == [
        PermissionRule("read_file", "deny")
    ]
    assert session_rules_for("sess-r105") == (PermissionRule("bash", "allow"),)


async def test_session_remember_denial_stores_deny_rule(gate, client):
    req = _pending_request()
    resp, _ = await _answer(
        client,
        gate,
        req,
        approved=False,
        remember=True,
        remember_duration="session",
    )
    assert resp.json() == {"ok": True}
    assert session_rules_for("sess-r105") == (PermissionRule("bash", "deny"),)
    assert parse_rules(SettingsRepository().get_json(SETTINGS_KEY_RULES)) == []


async def test_session_remember_without_session_context_stores_nothing(
    gate, client
):
    """请求无会话归属 + session 时长 → 哪都不写（绝不转永久）。"""
    req = _pending_request(session_id=None)
    assert req.session_id is None

    resp, answer = await _answer(
        client,
        gate,
        req,
        approved=True,
        remember=True,
        remember_duration="session",
    )

    assert resp.json() == {"ok": True}
    assert answer.approved is True
    assert parse_rules(SettingsRepository().get_json(SETTINGS_KEY_RULES)) == []
    assert session_rules_for("sess-r105") == ()


async def test_session_remember_plugin_scope(gate, client):
    req = _pending_request(tool_name="plugin__demo__hello", plugin_name="demo")
    resp, _ = await _answer(
        client,
        gate,
        req,
        approved=True,
        remember=True,
        remember_scope="plugin",
        remember_duration="session",
    )
    assert resp.json() == {"ok": True}
    assert session_rules_for("sess-r105") == (
        PermissionRule("plugin__demo__*", "allow"),
    )
    assert parse_rules(SettingsRepository().get_json(SETTINGS_KEY_RULES)) == []


async def test_session_remember_fnmatch_guard_still_applies(gate, client):
    req = _pending_request(tool_name="*")
    resp, answer = await _answer(
        client,
        gate,
        req,
        approved=True,
        remember=True,
        remember_duration="session",
    )
    assert resp.json() == {"ok": True}
    assert answer.approved is True
    assert session_rules_for("sess-r105") == ()


async def test_default_duration_still_persists_to_settings(gate, client):
    """不带 remember_duration（老客户端）→ 既有持久化行为不变。"""
    req = _pending_request()
    resp, _ = await _answer(
        client, gate, req, approved=True, remember=True
    )
    assert resp.json() == {"ok": True}
    assert parse_rules(SettingsRepository().get_json(SETTINGS_KEY_RULES)) == [
        PermissionRule("bash", "allow")
    ]
    assert session_rules_for("sess-r105") == ()
