"""M1 工具安全加固 — /api/v1/permissions REST 契约测试。

覆盖:
- GET /pending 返回挂起请求的 JSON 契约
- POST /{id}/answer 成功 / 未知 id / gate 未初始化
- remember=true → permission_rules 持久化 (allow 与 deny)
- 请求体非法 → 422 (pydantic extra=forbid)
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

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


def _pending_request(
    tool_name: str = "bash", plugin_name: Optional[str] = None
) -> ApprovalRequest:
    return ApprovalRequest.create(
        tool_name=tool_name,
        args={"command": "ls"},
        risk="suspicious",
        message="prompt 模式需要确认",
        plugin_name=plugin_name,
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
    assert item["tool_name"] == "bash"
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


async def test_post_answer_carries_deny_reason_to_gate(gate, client):
    """对标 ZCode freeText：body.reason 经路由透传到 ApprovalAnswer.reason。"""
    # Arrange
    req = _pending_request()
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)
    feedback = "路径不对，应该写到 docs/ 目录"

    # Act
    resp = await client.post(
        f"/api/v1/permissions/{req.request_id}/answer",
        json={"approved": False, "remember": False, "reason": feedback},
    )
    answer = await holder

    # Assert
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert answer.approved is False
    assert answer.reason == feedback


async def test_post_answer_rejects_oversized_reason(gate, client):
    """reason 超 500 字符 → 422（pydantic max_length）。"""
    # Arrange
    req = _pending_request()
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    # Act
    resp = await client.post(
        f"/api/v1/permissions/{req.request_id}/answer",
        json={"approved": False, "reason": "x" * 501},
    )

    # Assert
    assert resp.status_code == 422
    holder.cancel()


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
    req = _pending_request("bash")
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
    assert PermissionRule("bash", "deny") in rules


async def test_remember_appends_to_existing_rules(gate, client):
    """已有规则不被覆盖, 新规则追加到末尾。"""
    # Arrange
    repo = SettingsRepository()
    repo.set_json(SETTINGS_KEY_RULES, [{"tool_pattern": "read_file", "decision": "allow"}])
    req = _pending_request("bash")
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
        PermissionRule("bash", "allow"),
    ]


async def test_remember_deduplicates_identical_rule(gate, client):
    """R99: 完全相同的 (tool_pattern, decision) 已存在 → 不重复落一条。"""
    # Arrange
    repo = SettingsRepository()
    repo.set_json(SETTINGS_KEY_RULES, [{"tool_pattern": "bash", "decision": "allow"}])
    req = _pending_request("bash")
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
    assert parse_rules(repo.get_json(SETTINGS_KEY_RULES)) == [
        PermissionRule("bash", "allow")
    ]


async def test_remember_different_decision_not_deduplicated(gate, client):
    """R99: 同 pattern 不同 decision 不是重复，照常追加（冲突由求值优先级裁决）。"""
    # Arrange
    repo = SettingsRepository()
    repo.set_json(SETTINGS_KEY_RULES, [{"tool_pattern": "bash", "decision": "deny"}])
    req = _pending_request("bash")
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
    assert parse_rules(repo.get_json(SETTINGS_KEY_RULES)) == [
        PermissionRule("bash", "deny"),
        PermissionRule("bash", "allow"),
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


# ---------------------------------------------------------------------------
# FIX-3: remember 通配符规则注入防护
# ---------------------------------------------------------------------------


async def test_remember_with_wildcard_tool_name_is_not_persisted(gate, client):
    """remember + tool_name="*" → 应答成功但规则不落库（防永久 allow-all）。"""
    # Arrange
    req = _pending_request("*")
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    # Act
    resp = await client.post(
        f"/api/v1/permissions/{req.request_id}/answer",
        json={"approved": True, "remember": True},
    )
    answer = await holder

    # Assert — 本次批准生效, 但 settings 未被写入
    assert resp.json() == {"ok": True}
    assert answer.approved is True
    assert SettingsRepository().get(SETTINGS_KEY_RULES) is None


@pytest.mark.parametrize("bad_name", ["*", "term?", "[t]erminal", "wr]ite"])
async def test_remember_rejects_fnmatch_metacharacters(gate, client, bad_name):
    """fnmatch 元字符 (* ? [ ]) 一律静默降级为不记住。"""
    # Arrange
    req = _pending_request(bad_name)
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
    assert parse_rules(SettingsRepository().get_json(SETTINGS_KEY_RULES) or []) == []


async def test_remember_with_exact_tool_name_still_persisted(gate, client):
    """回归保护: 精确工具名（无元字符）remember 照常持久化。"""
    # Arrange
    req = _pending_request("bash")
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
    assert PermissionRule("bash", "allow") in rules


# ---------------------------------------------------------------------------
# R95 按插件记住审批决定
# ---------------------------------------------------------------------------


async def test_remember_plugin_scope_persists_restricted_allow_rule(
    gate, client
):
    """权威 plugin_name + plugin 范围 → 单插件受限 allow 规则。"""
    req = _pending_request("plugin__demo__hello", plugin_name="demo")
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    pending = await client.get("/api/v1/permissions/pending")
    assert pending.json()[0]["plugin_name"] == "demo"

    resp = await client.post(
        f"/api/v1/permissions/{req.request_id}/answer",
        json={
            "approved": True,
            "remember": True,
            "remember_scope": "plugin",
        },
    )
    answer = await holder

    assert resp.json() == {"ok": True}
    assert answer.approved is True
    rules = parse_rules(SettingsRepository().get_json(SETTINGS_KEY_RULES))
    assert rules == [PermissionRule("plugin__demo__*", "allow")]


async def test_remember_plugin_scope_deduplicates_derived_rule(gate, client):
    """R99: 整插件派生规则已存在时再次记住 → 仍只有一条。"""
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES,
        [{"tool_pattern": "plugin__demo__*", "decision": "allow"}],
    )
    req = _pending_request("plugin__demo__hello", plugin_name="demo")
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    resp = await client.post(
        f"/api/v1/permissions/{req.request_id}/answer",
        json={
            "approved": True,
            "remember": True,
            "remember_scope": "plugin",
        },
    )
    await holder

    assert resp.json() == {"ok": True}
    rules = parse_rules(repo.get_json(SETTINGS_KEY_RULES))
    assert rules == [PermissionRule("plugin__demo__*", "allow")]


async def test_remember_plugin_scope_persists_restricted_deny_rule(
    gate, client
):
    """整插件拒绝与批准共用范围语义，落 deny。"""
    req = _pending_request("plugin__demo__hello", plugin_name="demo")
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    resp = await client.post(
        f"/api/v1/permissions/{req.request_id}/answer",
        json={
            "approved": False,
            "remember": True,
            "remember_scope": "plugin",
        },
    )
    answer = await holder

    assert resp.json() == {"ok": True}
    assert answer.approved is False
    rules = parse_rules(SettingsRepository().get_json(SETTINGS_KEY_RULES))
    assert rules == [PermissionRule("plugin__demo__*", "deny")]


async def test_remember_tool_scope_keeps_exact_plugin_tool_rule(gate, client):
    """显式 tool 范围仍只记当前完整插件工具名。"""
    req = _pending_request("plugin__demo__hello", plugin_name="demo")
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    resp = await client.post(
        f"/api/v1/permissions/{req.request_id}/answer",
        json={
            "approved": True,
            "remember": True,
            "remember_scope": "tool",
        },
    )
    await holder

    assert resp.json() == {"ok": True}
    rules = parse_rules(SettingsRepository().get_json(SETTINGS_KEY_RULES))
    assert rules == [PermissionRule("plugin__demo__hello", "allow")]


@pytest.mark.parametrize(
    ("tool_name", "plugin_name"),
    [
        ("plugin__demo__hello", None),
        ("plugin__demo__hello", "other"),
        ("plugin__demo__hello", "de mo"),
        ("bash", "demo"),
    ],
)
async def test_remember_plugin_scope_without_authoritative_match_not_persisted(
    gate, client, tool_name, plugin_name
):
    """插件名缺失/不匹配时本次应答生效，但不猜测、不落任何规则。"""
    req = _pending_request(tool_name, plugin_name=plugin_name)
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    resp = await client.post(
        f"/api/v1/permissions/{req.request_id}/answer",
        json={
            "approved": True,
            "remember": True,
            "remember_scope": "plugin",
        },
    )
    answer = await holder

    assert resp.json() == {"ok": True}
    assert answer.approved is True
    assert parse_rules(SettingsRepository().get_json(SETTINGS_KEY_RULES) or []) == []


async def test_invalid_remember_scope_returns_422(gate, client):
    """范围是封闭枚举，未知值不能被静默当作精确或整插件。"""
    req = _pending_request("plugin__demo__hello", plugin_name="demo")
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    resp = await client.post(
        f"/api/v1/permissions/{req.request_id}/answer",
        json={
            "approved": True,
            "remember": True,
            "remember_scope": "all-plugins",
        },
    )

    assert resp.status_code == 422
    gate.answer(req.request_id, approved=False)
    await holder


# ---------------------------------------------------------------------------
# FIX-4: 审批路由 Origin 守卫
# ---------------------------------------------------------------------------


async def test_answer_with_evil_origin_returns_403(gate, client):
    """带第三方网页 Origin 的 POST answer → 403 forbidden_origin。"""
    # Arrange / Act
    resp = await client.post(
        "/api/v1/permissions/whatever/answer",
        json={"approved": True},
        headers={"Origin": "https://evil.com"},
    )

    # Assert
    assert resp.status_code == 403
    assert resp.json() == {"ok": False, "error": "forbidden_origin"}


async def test_answer_with_allowed_dev_origin_passes(gate, client):
    """Electron 开发 Origin (http://localhost:1420) → 200 正常应答。"""
    # Arrange
    req = _pending_request()
    holder = asyncio.create_task(gate.request(req, timeout=5.0))
    await asyncio.sleep(0.01)

    # Act
    resp = await client.post(
        f"/api/v1/permissions/{req.request_id}/answer",
        json={"approved": True},
        headers={"Origin": "http://localhost:1420"},
    )
    answer = await holder

    # Assert
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert answer.approved is True


async def test_answer_without_origin_header_passes(gate, client):
    """无 Origin 头（同源 / curl / python）→ 放行, 走正常错误语义。"""
    # Arrange / Act
    resp = await client.post(
        "/api/v1/permissions/whatever/answer", json={"approved": True}
    )

    # Assert — 放行到业务层, 未知 id 返回 ok=false 而不是 403
    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "error": "unknown_or_expired"}


async def test_get_pending_with_evil_origin_returns_403(gate, client):
    """GET /pending 同样受 Origin 守卫保护。"""
    # Arrange / Act
    resp = await client.get(
        "/api/v1/permissions/pending", headers={"Origin": "https://evil.com"}
    )

    # Assert
    assert resp.status_code == 403
    assert resp.json() == {"ok": False, "error": "forbidden_origin"}


async def test_get_pending_with_file_origin_passes(gate, client):
    """打包 Electron 的 file:// Origin → 200。"""
    # Arrange / Act
    resp = await client.get(
        "/api/v1/permissions/pending", headers={"Origin": "file://"}
    )

    # Assert
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# R97 已保存规则的查看与逐条删除
# ---------------------------------------------------------------------------


async def test_list_rules_empty_when_unset(client):
    """未保存任何规则 → 空列表（不是 404/500）。"""
    resp = await client.get("/api/v1/permissions/rules")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "rules": []}


async def test_list_rules_returns_effective_rules_and_skips_invalid(client):
    """列表口径与 parse_rules 一致：非法条目不展示、有效条目保序。"""
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES,
        [
            {"tool_pattern": "read_file", "decision": "allow"},
            {"tool_pattern": 123, "decision": "allow"},
            "junk",
            {"tool_pattern": "bash", "decision": "bogus"},
            {"tool_pattern": "plugin__demo__*", "decision": "deny"},
        ],
    )

    resp = await client.get("/api/v1/permissions/rules")

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "rules": [
            {"tool_pattern": "read_file", "decision": "allow", "plugin_name": None, "plugin_status": None},
            {"tool_pattern": "plugin__demo__*", "decision": "deny", "plugin_name": None, "plugin_status": "missing"},
        ],
    }


async def test_delete_rule_removes_one_and_returns_updated_list(client):
    """R99: 按内容只删一条（重复规则逐条删），写回并返回最新列表。"""
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES,
        [
            {"tool_pattern": "bash", "decision": "allow"},
            {"tool_pattern": "bash", "decision": "allow"},
            {"tool_pattern": "write_file", "decision": "ask"},
        ],
    )

    resp = await client.post(
        "/api/v1/permissions/rules/delete",
        json={"tool_pattern": "bash", "decision": "allow"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "rules": [
            {"tool_pattern": "bash", "decision": "allow", "plugin_name": None, "plugin_status": None},
            {"tool_pattern": "write_file", "decision": "ask", "plugin_name": None, "plugin_status": None},
        ],
    }
    assert parse_rules(repo.get_json(SETTINGS_KEY_RULES)) == [
        PermissionRule("bash", "allow"),
        PermissionRule("write_file", "ask"),
    ]


async def test_delete_rule_targets_content_not_list_position(client):
    """R99: 删除以内容为准，列表位置变化不会删错规则（含 ask 规则可删）。"""
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES,
        [
            {"tool_pattern": "bash", "decision": "deny"},
            {"tool_pattern": "read_file", "decision": "allow"},
            {"tool_pattern": "write_file", "decision": "ask"},
        ],
    )

    resp = await client.post(
        "/api/v1/permissions/rules/delete",
        json={"tool_pattern": "write_file", "decision": "ask"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "rules": [
            {"tool_pattern": "bash", "decision": "deny", "plugin_name": None, "plugin_status": None},
            {"tool_pattern": "read_file", "decision": "allow", "plugin_name": None, "plugin_status": None},
        ],
    }
    assert parse_rules(repo.get_json(SETTINGS_KEY_RULES)) == [
        PermissionRule("bash", "deny"),
        PermissionRule("read_file", "allow"),
    ]


async def test_delete_rule_not_found_returns_400_and_keeps_storage(client):
    """无完全一致的规则（pattern 或 decision 不符）→ 400，存储不被改写。"""
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES, [{"tool_pattern": "bash", "decision": "deny"}]
    )

    for body in (
        {"tool_pattern": "bash", "decision": "allow"},
        {"tool_pattern": "read_file", "decision": "deny"},
        {"tool_pattern": "*", "decision": "deny"},
    ):
        resp = await client.post(
            "/api/v1/permissions/rules/delete", json=body
        )
        assert resp.status_code == 400
        assert resp.json() == {"ok": False, "error": "rule not found"}

    assert parse_rules(repo.get_json(SETTINGS_KEY_RULES)) == [
        PermissionRule("bash", "deny")
    ]


async def test_delete_rule_rejects_extra_body_fields(client):
    """删除端点不接受额外字段（extra=forbid → 422）。"""
    resp = await client.post(
        "/api/v1/permissions/rules/delete",
        json={"tool_pattern": "bash", "decision": "allow", "hacker_field": 1},
    )

    assert resp.status_code == 422


async def test_delete_rule_rejects_legacy_index_body(client):
    """R99: 旧的下标请求体不再被接受（422）。"""
    resp = await client.post(
        "/api/v1/permissions/rules/delete",
        json={"index": 0},
    )

    assert resp.status_code == 422


async def test_delete_rule_with_evil_origin_returns_403(client):
    """第三方网页 Origin 删除规则 → 403，存储不变。"""
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES, [{"tool_pattern": "bash", "decision": "allow"}]
    )

    resp = await client.post(
        "/api/v1/permissions/rules/delete",
        json={"tool_pattern": "bash", "decision": "allow"},
        headers={"Origin": "https://evil.com"},
    )

    assert resp.status_code == 403
    assert resp.json() == {"ok": False, "error": "forbidden_origin"}
    assert parse_rules(repo.get_json(SETTINGS_KEY_RULES)) == [
        PermissionRule("bash", "allow")
    ]


# ---------------------------------------------------------------------------
# R100 已保存规则一键清空
# ---------------------------------------------------------------------------


async def test_clear_rules_empties_storage_and_returns_empty_list(client):
    """R100: 清空写入空列表并返回空 rules；无效存量条目随之一并消失。"""
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES,
        [
            {"tool_pattern": "bash", "decision": "deny"},
            {"tool_pattern": 123, "decision": "allow"},
            {"tool_pattern": "plugin__demo__*", "decision": "allow"},
        ],
    )

    resp = await client.post("/api/v1/permissions/rules/clear")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "rules": []}
    assert repo.get_json(SETTINGS_KEY_RULES) == []
    listed = await client.get("/api/v1/permissions/rules")
    assert listed.json() == {"ok": True, "rules": []}


async def test_clear_rules_is_idempotent_when_empty(client):
    """R100: 本无规则时清空仍返回 ok，不报错。"""
    resp = await client.post("/api/v1/permissions/rules/clear")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "rules": []}
    assert SettingsRepository().get_json(SETTINGS_KEY_RULES) == []


async def test_clear_rules_with_evil_origin_returns_403(client):
    """第三方网页 Origin 清空规则 → 403，存储不变。"""
    repo = SettingsRepository()
    repo.set_json(
        SETTINGS_KEY_RULES, [{"tool_pattern": "bash", "decision": "allow"}]
    )

    resp = await client.post(
        "/api/v1/permissions/rules/clear",
        headers={"Origin": "https://evil.com"},
    )

    assert resp.status_code == 403
    assert resp.json() == {"ok": False, "error": "forbidden_origin"}
    assert parse_rules(repo.get_json(SETTINGS_KEY_RULES)) == [
        PermissionRule("bash", "allow")
    ]
