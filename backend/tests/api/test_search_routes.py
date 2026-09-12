# backend/tests/api/test_search_routes.py
"""P1-3.7 全局搜索路由测试（/api/v1/search/global）。

覆盖：参数校验 / 三类聚合 / types 过滤 / 会话命中 / 无匹配。
memory 与 knowledge 源在测试环境通常为空，且 helper 内部已 try/except 降级，
因此断言聚焦于结构而非具体条数（会话源可直接造数据验证）。
"""
import pytest

from backend.data.session_repo import SessionRepository


@pytest.mark.asyncio()
async def test_global_search_missing_q_returns_422(client):
    resp = await client.get("/api/v1/search/global")
    assert resp.status_code == 422


@pytest.mark.asyncio()
async def test_global_search_empty_q_returns_422(client):
    # q 的 min_length=1，空串应被 FastAPI 校验拒绝
    resp = await client.get("/api/v1/search/global", params={"q": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio()
async def test_global_search_returns_all_three_keys(client):
    resp = await client.get("/api/v1/search/global", params={"q": "never-match-xyz"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"sessions", "memories", "knowledge"}
    assert body["sessions"] == []
    assert isinstance(body["memories"], list)
    assert isinstance(body["knowledge"], list)


@pytest.mark.asyncio()
async def test_global_search_types_filter_limits_keys(client):
    resp = await client.get("/api/v1/search/global", params={"q": "abc", "types": "session"})
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"sessions"}


@pytest.mark.asyncio()
async def test_global_search_finds_session_by_title(client):
    repo = SessionRepository()
    repo.create(title="项目计划评审")
    repo.create(title="无关会话")

    resp = await client.get("/api/v1/search/global", params={"q": "项目计划"})
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["title"] == "项目计划评审"
    assert "message_count" in sessions[0]
    assert "updated_at" in sessions[0]


@pytest.mark.asyncio()
async def test_global_search_respects_limit(client):
    repo = SessionRepository()
    for i in range(5):
        repo.create(title=f"限制测试-{i}")

    resp = await client.get("/api/v1/search/global", params={"q": "限制测试", "limit": 2})
    assert resp.status_code == 200
    assert len(resp.json()["sessions"]) == 2
