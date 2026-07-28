"""M1 工具安全加固 — /api/v1/permissions REST 契约测试。

覆盖:
- GET /pending 返回挂起请求的 JSON 契约
- POST /{id}/answer 成功 / 未知 id / gate 未初始化
- remember=true → permission_rules 持久化 (allow 与 deny)
- 请求体非法 → 422 (pydantic extra=forbid)
"""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from backend.data.settings_repo import SettingsRepository
from backend.services.permission_gate import (
    ApprovalRequest,
    init_permission_gate,
    reset_permission_gate,
)
from backend.tools.permissions import SETTINGS_KEY_RULES, PermissionRule, parse_rules

pytestmark = pytest.mark.unit  # 走 ASGITransport 直连 app, 属快测


@pytest.fixture()
def gate():
    """每个测试初始化独立 gate, 结束重置。"""
    reset_permission_gate()
    g = init_permission_gate()
    yield g
    reset_permission_gate()


def _pending_request(tool_name: str = "terminal") -> ApprovalRequest:
    return ApprovalRequest.create(
        tool_name=tool_name,
        args={"command": "ls"},
        risk="suspicious",
        message="prompt 模式需要确认",
    )


async def test_get_pending_returns_empty_list_when_gate_uninitialized(client):
    """gate 未初始化 → GET /pending 返回空列表而非 500。"""
    # Arrange
    reset_permission_gate()

    # Act
    resp = await client.get("/api/v1/permissions/pending")

    # Assert
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_pending_returns_registered_requests(gate, client):
    """挂起请求出现在 /pending, 字段形态符合前端契约。"""
    # Arrange
    req = _pending_request()
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)  # 等注册完成

    # Act
    resp = await client.get("/api/v1/permissions/pending")

    # Assert
    assert resp.status_code == 200
    items: List[dict] = resp.json()
    assert len(items) == 1
    item = items[0]
    assert item["request_id"] == req.request_id
    assert item["tool_name"] == "terminal"
    assert item["risk"] == "suspicious"
    assert item["message"] == "prompt 模式需要确认"
    assert "ls" in item["args_summary"]
    assert isinstance(item["created_at"], float)

    # 清理 —— 应答掉挂起请求
    gate.answer(req.request_id, approved=False)
    await holder


async def test_post_answer_approves_and_resolves_gate_future(gate, client):
    """POST answer approved=true → ok, gate 的 request() 解析为 approved。"""
    # Arrange
    req = _pending_request()
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    # Act
    resp = await client.post(
        f"/api/v1/permissions/{req.request_id}/answer",
        json={"approved": True, "remember": False},
    )
    answer = await holder

    # Assert
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert answer.approved is True
    assert answer.answered_by == "gui"


async def test_post_answer_unknown_id_returns_ok_false(gate, client):
    """未知 request_id → {"ok": false, "error": "unknown_or_expired"}。"""
    # Arrange / Act
    resp = await client.post(
        "/api/v1/permissions/no-such-id/answer",
        json={"approved": True, "remember": False},
    )

    # Assert
    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "error": "unknown_or_expired"}


async def test_post_answer_when_gate_uninitialized_returns_ok_false(client):
    """gate 未初始化 → {"ok": false, "error": "permission_gate_not_initialized"}。"""
    # Arrange
    reset_permission_gate()

    # Act
    resp = await client.post(
        "/api/v1/permissions/whatever/answer", json={"approved": True}
    )

    # Assert
    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "error": "permission_gate_not_initialized"}


async def test_post_answer_rejects_extra_body_fields(gate, client):
    """extra=forbid: 未知字段 → 422。"""
    # Arrange / Act
    resp = await client.post(
        "/api/v1/permissions/x/answer",
        json={"approved": True, "remember": False, "hacker_field": 1},
    )

    # Assert
    assert resp.status_code == 422


async def test_remember_true_persists_allow_rule_to_settings(gate, client):
    """remember + approved → permission_rules 追加 allow 规则 (精确工具名)。"""
    # Arrange
    req = _pending_request("write_file")
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    # Act
    resp = await client.post(
        f"/api/v1/permissions/{req.request_id}/answer",
        json={"approved": True, "remember": True},
    )
    await holder

    # Assert
    assert resp.json() == {"ok": True}
    rules = parse_rules(SettingsRepository().get_json(SETTINGS_KEY_RULES))
    assert PermissionRule("write_file", "allow") in rules


async def test_remember_denial_persists_deny_rule(gate, client):
    """remember + rejected → deny 规则, 下次 enforcer 直接拒。"""
    # Arrange
    req = _pending_request("terminal")
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    # Act
    resp = await client.post(
        f"/api/v1/permissions/{req.request_id}/answer",
        json={"approved": False, "remember": True},
    )
    await holder

    # Assert
    assert resp.json() == {"ok": True}
    rules = parse_rules(SettingsRepository().get_json(SETTINGS_KEY_RULES))
    assert PermissionRule("terminal", "deny") in rules


async def test_remember_appends_to_existing_rules(gate, client):
    """已有规则不被覆盖, 新规则追加到末尾。"""
    # Arrange
    repo = SettingsRepository()
    repo.set_json(SETTINGS_KEY_RULES, [{"tool_pattern": "read_file", "decision": "allow"}])
    req = _pending_request("terminal")
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    # Act
    await client.post(
        f"/api/v1/permissions/{req.request_id}/answer",
        json={"approved": True, "remember": True},
    )
    await holder

    # Assert
    rules = parse_rules(repo.get_json(SETTINGS_KEY_RULES))
    assert rules == [
        PermissionRule("read_file", "allow"),
        PermissionRule("terminal", "allow"),
    ]


async def test_no_remember_does_not_touch_settings(gate, client):
    """remember=false (默认) → settings 不变。"""
    # Arrange
    req = _pending_request()
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    # Act
    await client.post(
        f"/api/v1/permissions/{req.request_id}/answer",
        json={"approved": True},
    )
    await holder

    # Assert
    assert SettingsRepository().get(SETTINGS_KEY_RULES) is None
