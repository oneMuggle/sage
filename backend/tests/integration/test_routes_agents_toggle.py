"""
toggle_agent 路由集成测试 — 覆盖 PATCH /api/v1/agents/{id}/toggle 端点 (PR-5)。

对应 Tauri command ``toggle_agent``:

- PATCH 启用/禁用 → 200 + 更新后完整 profile (enabled 字段已切)
- PATCH 不存在 id → 404 + 结构化 detail (与 PR-3 / PR-4 复用同一 type)
- PATCH 缺 enabled 字段 → 422 (FastAPI 自动)
- PATCH 同值 (幂等) → 200 + 不抛错, updated_at 仍刷新 (set_enabled 总是写 SQL)
- updated_at 字段在更新后被刷新
- 不影响其它 agent

设计取舍
--------
- 单独 /toggle 而非复用 PATCH /agents/{id} {enabled: bool} — 见
  ``docs/plans/2026-06-12_finish-designed-features.md`` §3.1
- 路由层无 Pydantic role / max_iterations 校验 (toggle 不动这些字段)
- 复用 ``AgentRepository.set_enabled()`` — 后者本就为本 PR 而生
"""

import asyncio

import pytest

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_toggle_agent_disable_persists(client):
    """PATCH /toggle 关闭一个默认启用的 agent → enabled=false, 后续 GET 反映新值."""
    resp = await client.patch(f"{PREFIX}/agents/coder/toggle", json={"enabled": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "coder"
    assert body["enabled"] is False

    follow = await client.get(f"{PREFIX}/agents/coder")
    assert follow.json()["enabled"] is False


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_toggle_agent_enable_after_disable(client):
    """先关再开 → 状态恢复, GET 反映 true."""
    off = await client.patch(f"{PREFIX}/agents/coder/toggle", json={"enabled": False})
    assert off.status_code == 200
    assert off.json()["enabled"] is False

    on = await client.patch(f"{PREFIX}/agents/coder/toggle", json={"enabled": True})
    assert on.status_code == 200
    assert on.json()["enabled"] is True

    assert (await client.get(f"{PREFIX}/agents/coder")).json()["enabled"] is True


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_toggle_agent_not_found_returns_404(client):
    """不存在的 agent_id → 404 + 结构化 detail (与 update_agent 风格一致)."""
    resp = await client.patch(
        f"{PREFIX}/agents/nonexistent-agent-id/toggle",
        json={"enabled": False},
    )
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["type"] == "agent_not_found"


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_toggle_agent_missing_enabled_field_returns_422(client):
    """缺 enabled 字段 → 422 (Pydantic 必填)."""
    resp = await client.patch(f"{PREFIX}/agents/coder/toggle", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_toggle_agent_wrong_type_returns_422(client):
    """enabled 必须是 bool, 字符串/数字应 422 (StrictBool 拒绝 lax 强转)."""
    # "yes" — Pydantic lax 模式会强转 True, StrictBool 应拒绝
    resp = await client.patch(f"{PREFIX}/agents/coder/toggle", json={"enabled": "yes"})
    assert resp.status_code == 422

    # 1 / 0 — int 也是常见的 bool 强转源, StrictBool 应拒绝
    resp_int = await client.patch(f"{PREFIX}/agents/coder/toggle", json={"enabled": 1})
    assert resp_int.status_code == 422

    # null — 既不是 missing 也不是 bool, 应 422 (与"缺字段"区分)
    resp_null = await client.patch(f"{PREFIX}/agents/coder/toggle", json={"enabled": None})
    assert resp_null.status_code == 422


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_toggle_agent_idempotent_same_value(client):
    """连发两次同值 toggle → 第二次也 200 (幂等), enabled 不变."""
    first = await client.patch(f"{PREFIX}/agents/coder/toggle", json={"enabled": False})
    assert first.status_code == 200
    assert first.json()["enabled"] is False

    second = await client.patch(f"{PREFIX}/agents/coder/toggle", json={"enabled": False})
    assert second.status_code == 200
    assert second.json()["enabled"] is False


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_toggle_agent_bumps_updated_at(client):
    """toggle 状态变化 → updated_at 必变."""

    before = (await client.get(f"{PREFIX}/agents/coder")).json()
    await asyncio.sleep(0.01)

    resp = await client.patch(f"{PREFIX}/agents/coder/toggle", json={"enabled": False})
    assert resp.status_code == 200
    after = resp.json()
    assert after["updated_at"] > before["updated_at"]


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_toggle_agent_does_not_affect_other_agents(client):
    """toggle 一个 agent 不应影响其它 agent."""
    before_primary = (await client.get(f"{PREFIX}/agents/primary")).json()
    before_researcher = (await client.get(f"{PREFIX}/agents/researcher")).json()

    resp = await client.patch(f"{PREFIX}/agents/coder/toggle", json={"enabled": False})
    assert resp.status_code == 200

    after_primary = (await client.get(f"{PREFIX}/agents/primary")).json()
    after_researcher = (await client.get(f"{PREFIX}/agents/researcher")).json()
    assert after_primary == before_primary
    assert after_researcher == before_researcher


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_toggle_agent_returns_full_profile(client):
    """toggle 返回的 body 应包含 list_agents 输出的所有字段, 便于前端 setState 一次过."""
    resp = await client.patch(f"{PREFIX}/agents/coder/toggle", json={"enabled": False})
    assert resp.status_code == 200
    body = resp.json()

    required_fields = {
        "id",
        "name",
        "role",
        "system_prompt",
        "tools",
        "memory_access",
        "model_config",
        "max_iterations",
        "enabled",
        "description",
        "updated_at",
    }
    assert required_fields.issubset(body.keys())


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_toggle_agent_preserves_other_fields(client):
    """toggle 只动 enabled + updated_at — 其它字段全部保留原值."""
    before = (await client.get(f"{PREFIX}/agents/coder")).json()

    resp = await client.patch(f"{PREFIX}/agents/coder/toggle", json={"enabled": False})
    assert resp.status_code == 200
    after = resp.json()

    for field in (
        "id",
        "name",
        "role",
        "system_prompt",
        "tools",
        "memory_access",
        "model_config",
        "max_iterations",
        "description",
    ):
        assert after[field] == before[field], f"field {field} should not change"
