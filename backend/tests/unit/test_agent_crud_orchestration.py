"""writer 种子 + POST /agents 创建端点（US-4 角色可扩展）。

- create_default_agents 含 writer，tools 用 registry 正确名（read_file/write_file）
- ensure_default_agents 增量补插（已存在 DB 也能拿到 writer）
- POST /agents 创建成功 → 200 + 完整 profile
- POST /agents 重复 id → 409
- POST /agents 非法 role → 422
"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from backend.data.agent_repo import AgentRepository
from backend.main import app


@pytest.mark.asyncio()
async def test_writer_is_in_default_agents_with_correct_tool_names():
    from backend.agents.profiles import create_default_agents

    writers = [a for a in create_default_agents() if a.id == "writer"]
    assert writers, "create_default_agents 必须含 writer 种子"
    writer = writers[0]
    assert "read_file" in writer.tools  # registry 实际注册名（非过时 file_read）
    assert "write_file" in writer.tools
    assert "memory_search" in writer.tools


@pytest.mark.asyncio()
async def test_ensure_default_agents_inserts_writer_into_existing_db():
    """已存在 DB（非空表）也要有 writer —— seed_defaults_if_empty 只覆盖空表。

    幂等断言：无论 conftest 是否已把含 writer 的默认集 seed 进表，本测试都成立。
    """
    from backend.agents.profiles import ensure_default_agents

    # 第一次：确保所有默认角色在位（含 writer）
    ensure_default_agents()
    assert AgentRepository().get("writer") is not None
    # 第二次应为 no-op（全部已存在）—— 不依赖 conftest 是否已 seed writer
    assert ensure_default_agents() == 0


@pytest.mark.asyncio()
async def test_create_agent_endpoint_creates_custom_role():
    payload = {
        "id": "quant_analyst",
        "name": "量化分析师",
        "role": "researcher",
        "system_prompt": "你是一名量化交易分析师",
        "tools": ["web_search", "memory_search"],
        "description": "分析量化交易数据",
    }
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post("/api/v1/agents", json=payload)
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["id"] == "quant_analyst"
    assert created["tools"] == ["web_search", "memory_search"]
    # 落库可读
    assert AgentRepository().get("quant_analyst")["name"] == "量化分析师"


@pytest.mark.asyncio()
async def test_create_agent_endpoint_rejects_duplicate_id():
    payload = {
        "id": "researcher",  # 已存在默认角色
        "name": "重复",
        "role": "researcher",
        "system_prompt": "x",
    }
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post("/api/v1/agents", json=payload)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["type"] == "agent_already_exists"


@pytest.mark.asyncio()
async def test_create_agent_endpoint_validates_role():
    payload = {
        "id": "bad_role",
        "name": "坏角色",
        "role": "not_a_real_role",
        "system_prompt": "x",
    }
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post("/api/v1/agents", json=payload)
    assert resp.status_code == 422, resp.text
