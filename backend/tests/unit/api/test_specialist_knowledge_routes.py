"""M2-Task 2 — 专家知识绑定 CRUD 端点测试。

三个端点:

- ``GET /api/v1/specialists/{agent_id}/knowledge``
    → 返回该专家当前绑定的知识源列表（按 created_at 升序）。

- ``POST /api/v1/specialists/{agent_id}/knowledge``
    → 新增一条绑定；返回创建的绑定（含默认 id / created_at）。
    - 404 — 专家不存在
    - 422 — source_type 非法 / 必填字段缺失 / extra 字段

- ``DELETE /api/v1/specialists/{agent_id}/knowledge/{binding_id}``
    → 移除指定绑定。
    - 204 — 删除成功
    - 404 — 专家不存在 / binding_id 不归属该专家

测试不依赖真实嵌入或存储，只验证路由层的校验与持久化行为。
AgentRepository 走 conftest 提供的临时 DB。
"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from backend.data.agent_repo import AgentRepository
from backend.main import app

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    )


def _ensure_specialist(agent_id: str = "sp_test") -> None:
    """在临时 DB 植入一个 specialist 角色专家（其余字段最小化）。"""
    repo = AgentRepository()
    existing = repo.get(agent_id)
    if existing is not None:
        return
    repo.upsert(
        {
            "id": agent_id,
            "name": "测试专家",
            "role": "specialist",
            "system_prompt": "test",
            "tools": [],
            "memory_access": "own",
            "model_config": {},
            "max_iterations": 20,
            "enabled": 1,
            "description": "测试用专家",
            "skills": [],
            "knowledge_bindings": [],
            "memory_policy": {},
            "persona_ui": {},
            "permission_mode": "read_only",
            "version": 1,
            "source": "user",
        }
    )


class TestListKnowledge:
    async def test_returns_empty_list_for_new_specialist(self):
        _ensure_specialist("sp_empty")
        async with _client() as ac:
            resp = await ac.get("/api/v1/specialists/sp_empty/knowledge")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_returns_404_for_unknown_specialist(self):
        async with _client() as ac:
            resp = await ac.get("/api/v1/specialists/nonexistent/knowledge")
        assert resp.status_code == 404

    async def test_returns_existing_bindings_ordered_by_created_at(self):
        _ensure_specialist("sp_ordered")
        repo = AgentRepository()
        repo.update(
            "sp_ordered",
            {
                "knowledge_bindings": [
                    {
                        "id": "b1",
                        "agent_id": "sp_ordered",
                        "source_type": "wiki_project",
                        "source_id": "p1",
                        "name": "先",
                        "filters": {},
                        "created_at": 100,
                    },
                    {
                        "id": "b2",
                        "agent_id": "sp_ordered",
                        "source_type": "zotero_collection",
                        "source_id": "c1",
                        "name": "后",
                        "filters": {},
                        "created_at": 200,
                    },
                ]
            },
        )

        async with _client() as ac:
            resp = await ac.get("/api/v1/specialists/sp_ordered/knowledge")

        assert resp.status_code == 200
        body = resp.json()
        assert [b["id"] for b in body] == ["b1", "b2"]


class TestCreateKnowledge:
    async def test_creates_binding_with_generated_id(self):
        _ensure_specialist("sp_create")
        payload = {
            "agent_id": "sp_create",
            "source_type": "wiki_project",
            "source_id": "proj_1",
            "name": "项目 Wiki",
        }
        async with _client() as ac:
            resp = await ac.post(
                "/api/v1/specialists/sp_create/knowledge", json=payload
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["agent_id"] == "sp_create"
        assert body["source_type"] == "wiki_project"
        assert body["source_id"] == "proj_1"
        assert body["name"] == "项目 Wiki"
        assert isinstance(body["id"], str)
        assert len(body["id"]) >= 8
        assert isinstance(body["created_at"], int)
        assert body["created_at"] > 0
        assert body["filters"] == {}

        # 持久化：从 DB 直接读回
        profile = AgentRepository().get("sp_create")
        assert profile is not None
        bindings = profile.get("knowledge_bindings", [])
        assert len(bindings) == 1
        assert bindings[0]["id"] == body["id"]

    async def test_returns_404_for_unknown_specialist(self):
        payload = {
            "agent_id": "ghost",
            "source_type": "wiki_project",
            "source_id": "x",
            "name": "x",
        }
        async with _client() as ac:
            resp = await ac.post(
                "/api/v1/specialists/ghost/knowledge", json=payload
            )
        assert resp.status_code == 404

    async def test_rejects_unknown_source_type(self):
        _ensure_specialist("sp_bad_source")
        payload = {
            "agent_id": "sp_bad_source",
            "source_type": "unknown_source",
            "source_id": "x",
            "name": "x",
        }
        async with _client() as ac:
            resp = await ac.post(
                "/api/v1/specialists/sp_bad_source/knowledge", json=payload
            )
        assert resp.status_code == 422

    async def test_rejects_extra_fields(self):
        _ensure_specialist("sp_extra")
        payload = {
            "agent_id": "sp_extra",
            "source_type": "wiki_project",
            "source_id": "x",
            "name": "x",
            "malicious": "field",
        }
        async with _client() as ac:
            resp = await ac.post(
                "/api/v1/specialists/sp_extra/knowledge", json=payload
            )
        assert resp.status_code == 422

    async def test_rejects_empty_name(self):
        _ensure_specialist("sp_nonblank")
        payload = {
            "agent_id": "sp_nonblank",
            "source_type": "wiki_project",
            "source_id": "x",
            "name": "",
        }
        async with _client() as ac:
            resp = await ac.post(
                "/api/v1/specialists/sp_nonblank/knowledge", json=payload
            )
        assert resp.status_code == 422

    async def test_body_agent_id_must_match_path(self):
        """body 里 agent_id 与路径不一致 → 422（避免错位绑定）。"""
        _ensure_specialist("sp_mismatch")
        payload = {
            "agent_id": "other_agent",
            "source_type": "wiki_project",
            "source_id": "x",
            "name": "x",
        }
        async with _client() as ac:
            resp = await ac.post(
                "/api/v1/specialists/sp_mismatch/knowledge", json=payload
            )
        assert resp.status_code == 422


class TestDeleteKnowledge:
    async def test_deletes_binding(self):
        _ensure_specialist("sp_del")
        # 先创建
        payload = {
            "agent_id": "sp_del",
            "source_type": "specialist_private",
            "source_id": "sp_del",
            "name": "私有知识",
        }
        async with _client() as ac:
            created = await ac.post(
                "/api/v1/specialists/sp_del/knowledge", json=payload
            )
            assert created.status_code == 201
            binding_id = created.json()["id"]

            resp = await ac.delete(
                f"/api/v1/specialists/sp_del/knowledge/{binding_id}"
            )
        assert resp.status_code == 204

        # 列表应回归空
        async with _client() as ac:
            listing = await ac.get("/api/v1/specialists/sp_del/knowledge")
        assert listing.json() == []

    async def test_returns_404_for_unknown_binding_id(self):
        _ensure_specialist("sp_del_miss")
        async with _client() as ac:
            resp = await ac.delete(
                "/api/v1/specialists/sp_del_miss/knowledge/does-not-exist"
            )
        assert resp.status_code == 404

    async def test_returns_404_for_unknown_specialist(self):
        async with _client() as ac:
            resp = await ac.delete(
                "/api/v1/specialists/ghost/knowledge/whatever"
            )
        assert resp.status_code == 404

    async def test_binding_must_belong_to_specialist(self):
        """A 专家的绑定不能被 B 专家的路径删到。"""
        _ensure_specialist("sp_a")
        _ensure_specialist("sp_b")
        async with _client() as ac:
            created = await ac.post(
                "/api/v1/specialists/sp_a/knowledge",
                json={
                    "agent_id": "sp_a",
                    "source_type": "wiki_project",
                    "source_id": "p1",
                    "name": "A 的绑定",
                },
            )
            binding_id = created.json()["id"]

            resp = await ac.delete(
                f"/api/v1/specialists/sp_b/knowledge/{binding_id}"
            )
        assert resp.status_code == 404

        # A 的绑定仍在
        async with _client() as ac:
            listing = await ac.get("/api/v1/specialists/sp_a/knowledge")
        assert len(listing.json()) == 1
