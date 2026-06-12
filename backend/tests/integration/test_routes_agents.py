"""
list_agents 路由集成测试 — 覆盖 GET /api/v1/agents 端点。

对应 Tauri command `list_agents`（PR-3）:
- 启动 lifespan 时若 agents 表空, 种子化 4 个默认 agent (primary / researcher /
  coder / memory_manager), 见 backend/agents/profiles.py:create_default_agents()
- GET /agents → 200 + 4 个 agent profile
- 字段完整保留: name / role / system_prompt / tools / memory_access /
  model_config / max_iterations / enabled / description
- 已 disabled 的 agent 仍在列表中 (仅 enabled=false), 不被过滤
"""

import pytest

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"

EXPECTED_DEFAULT_IDS = {"primary", "researcher", "coder", "memory_manager"}


@pytest.mark.asyncio()
async def test_list_agents_returns_four_defaults_after_lifespan(client):
    """lifespan 启动后 GET /agents 必返回 4 个默认 agent."""
    resp = await client.get(f"{PREFIX}/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert isinstance(agents, list)

    ids = {a["id"] for a in agents}
    assert ids == EXPECTED_DEFAULT_IDS, f"期望默认 4 个 agent, 实际 {ids}"


@pytest.mark.asyncio()
async def test_list_agents_profile_preserves_all_fields(client):
    """Agent profile 字段完整保留: name/role/system_prompt/tools/memory_access/
    model_config/max_iterations/enabled/description."""
    resp = await client.get(f"{PREFIX}/agents")
    assert resp.status_code == 200
    agents = resp.json()

    by_id = {a["id"]: a for a in agents}
    primary = by_id["primary"]
    assert primary["name"] == "Sage 主助手"
    assert primary["role"] == "coordinator"
    assert primary["system_prompt"]  # 非空
    assert isinstance(primary["tools"], list)
    assert "calculator" in primary["tools"]
    assert isinstance(primary["memory_access"], list)
    assert "working" in primary["memory_access"]
    assert primary["model_config"]["model"] == "gpt-4"
    assert primary["max_iterations"] == 10
    assert primary["enabled"] is True
    assert primary["description"]  # 非空


@pytest.mark.asyncio()
async def test_list_agents_includes_disabled_agents(client):
    """disabled 的 agent 仍在列表里 — GET /agents 不做 enabled 过滤."""
    from backend.data.agent_repo import AgentRepository

    AgentRepository().set_enabled("coder", False)

    resp = await client.get(f"{PREFIX}/agents")
    assert resp.status_code == 200
    agents = resp.json()
    by_id = {a["id"]: a for a in agents}

    assert set(by_id.keys()) == EXPECTED_DEFAULT_IDS
    assert by_id["coder"]["enabled"] is False
    assert by_id["primary"]["enabled"] is True


@pytest.mark.asyncio()
async def test_list_agents_idempotent_across_lifespan(client):
    """同一 DB 多次跑 seed 不会重复插入 — 不破坏 (PRIMARY KEY, id)."""
    from backend.data.agent_repo import AgentRepository

    first = await client.get(f"{PREFIX}/agents")
    assert first.status_code == 200
    assert len(first.json()) == 4

    AgentRepository().seed_defaults_if_empty()

    second = await client.get(f"{PREFIX}/agents")
    assert second.status_code == 200
    assert len(second.json()) == 4


@pytest.mark.asyncio()
async def test_get_agent_by_id_returns_404(client):
    """不存在的 agent_id → 404 + 结构化 detail (给前端用)."""
    resp = await client.get(f"{PREFIX}/agents/nonexistent-agent-id")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["type"] == "agent_not_found"


@pytest.mark.asyncio()
async def test_get_agent_by_id_returns_profile(client):
    """存在的 agent_id → 200 + 该 agent 完整 profile."""
    resp = await client.get(f"{PREFIX}/agents/coder")
    assert resp.status_code == 200
    coder = resp.json()
    assert coder["id"] == "coder"
    assert coder["role"] == "coder"
    assert "file_write" in coder["tools"]
    assert coder["max_iterations"] == 15
