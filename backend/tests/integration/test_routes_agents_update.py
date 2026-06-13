"""
update_agent 路由集成测试 — 覆盖 PATCH /api/v1/agents/{id} 端点。

对应 Tauri command `update_agent`（PR-4）:
- PATCH 单字段 / 多字段 → 200 + 更新后完整 profile
- PATCH 不存在 id → 404 + 结构化 detail
- PATCH 空 body → 200 (no-op, updated_at 不动)
- PATCH 校验: role 必须是白名单成员 (coordinator/researcher/coder/memory_manager)
- PATCH 校验: max_iterations 在 1..50
- PATCH 不传字段: 保留原值 (partial update)
- updated_at 字段在更新后被刷新
"""

import asyncio

import pytest

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"

# 与 backend/agents/profiles.py:create_default_agents 角色定义保持一致
VALID_ROLES = {"coordinator", "researcher", "coder", "memory_manager"}


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_update_agent_name_persists(client):
    """PATCH 改 name → 200 + 后续 GET 看到新 name."""
    resp = await client.patch(f"{PREFIX}/agents/coder", json={"name": "代码工匠"})
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["id"] == "coder"
    assert updated["name"] == "代码工匠"

    follow = await client.get(f"{PREFIX}/agents/coder")
    assert follow.json()["name"] == "代码工匠"


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_update_agent_role_validates_against_whitelist(client):
    """PATCH role 必须在白名单 — 其它值返回 422."""
    ok = await client.patch(f"{PREFIX}/agents/coder", json={"role": "researcher"})
    assert ok.status_code == 200
    assert ok.json()["role"] == "researcher"

    bad = await client.patch(f"{PREFIX}/agents/coder", json={"role": "hacker"})
    assert bad.status_code == 422


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_update_agent_max_iterations_in_range(client):
    """PATCH max_iterations 必须在 1..50."""
    ok = await client.patch(f"{PREFIX}/agents/coder", json={"max_iterations": 25})
    assert ok.status_code == 200
    assert ok.json()["max_iterations"] == 25

    too_low = await client.patch(f"{PREFIX}/agents/coder", json={"max_iterations": 0})
    assert too_low.status_code == 422

    too_high = await client.patch(f"{PREFIX}/agents/coder", json={"max_iterations": 51})
    assert too_high.status_code == 422


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_update_agent_partial_preserves_unset_fields(client):
    """PATCH 不传字段保留原值 (partial update 而非全量替换)."""
    before = (await client.get(f"{PREFIX}/agents/primary")).json()
    original_role = before["role"]
    original_system_prompt = before["system_prompt"]

    resp = await client.patch(f"{PREFIX}/agents/primary", json={"name": "新版主助手"})
    assert resp.status_code == 200
    after = resp.json()
    assert after["name"] == "新版主助手"
    assert after["role"] == original_role
    assert after["system_prompt"] == original_system_prompt


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_update_agent_multiple_fields_at_once(client):
    """PATCH 可同时改多个字段."""
    resp = await client.patch(
        f"{PREFIX}/agents/researcher",
        json={"name": "研究僧", "max_iterations": 12, "description": "新描述"},
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["name"] == "研究僧"
    assert updated["max_iterations"] == 12
    assert updated["description"] == "新描述"


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_update_agent_not_found_returns_404(client):
    """不存在的 agent_id → 404 + 结构化 detail."""
    resp = await client.patch(
        f"{PREFIX}/agents/nonexistent-agent-id",
        json={"name": "X"},
    )
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["type"] == "agent_not_found"


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_update_agent_empty_body_is_noop(client):
    """PATCH 空 body → 200 + 不动 updated_at (无字段变化)."""
    before = (await client.get(f"{PREFIX}/agents/coder")).json()
    resp = await client.patch(f"{PREFIX}/agents/coder", json={})
    assert resp.status_code == 200
    after = resp.json()
    assert after["name"] == before["name"]
    assert after["role"] == before["role"]
    assert after["updated_at"] == before["updated_at"]


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_update_agent_bumps_updated_at(client):
    """PATCH 改任意字段 → updated_at 必变."""

    before = (await client.get(f"{PREFIX}/agents/coder")).json()
    await asyncio.sleep(0.01)
    resp = await client.patch(f"{PREFIX}/agents/coder", json={"name": "Coder2"})
    assert resp.status_code == 200
    after = resp.json()
    assert after["updated_at"] > before["updated_at"]


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_update_agent_tools_list_persists(client):
    """PATCH 改 tools 列表 → 200 + 列表正确序列化."""
    new_tools = ["tool_a", "tool_b", "tool_c"]
    resp = await client.patch(f"{PREFIX}/agents/coder", json={"tools": new_tools})
    assert resp.status_code == 200
    assert resp.json()["tools"] == new_tools


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_update_agent_does_not_affect_other_agents(client):
    """PATCH 一个 agent 不应影响其他 agent."""
    before_primary = (await client.get(f"{PREFIX}/agents/primary")).json()
    before_researcher = (await client.get(f"{PREFIX}/agents/researcher")).json()

    resp = await client.patch(f"{PREFIX}/agents/coder", json={"name": "X"})
    assert resp.status_code == 200

    after_primary = (await client.get(f"{PREFIX}/agents/primary")).json()
    after_researcher = (await client.get(f"{PREFIX}/agents/researcher")).json()
    assert after_primary == before_primary
    assert after_researcher == before_researcher
