"""Gap E (Task 5) — traceability endpoint + MemoryPort query tests.

Covers the three new MemoryPort methods (``find_by_turn`` /
``find_by_category`` / ``find_by_category_and_session``) backed by the
real ``MemoryAdapter`` (conftest provides a fresh temp SQLite DB per test)
plus the three new HTTP endpoints in ``legacy_routes``.

Note: importance values are chosen so ``MemoryAdapter.store`` classifies
the memory as **episodic** (``_classify_memory_type``: >=8 → semantic,
<5 and short → working, else episodic). We query the episodic table, so
tests use importance in {5, 6, 7}.
"""

import pytest

from backend.adapters.out.memory.adapter import MemoryAdapter
from backend.memory import get_memory_manager


def _adapter() -> MemoryAdapter:
    """Fresh adapter bound to the per-test MemoryManager (temp DB)."""
    return MemoryAdapter(get_memory_manager())


# ==================== MemoryPort query methods ====================


@pytest.mark.asyncio()
async def test_find_by_turn_returns_empty_when_no_match():
    adapter = _adapter()
    result = await adapter.find_by_turn("nonexistent-turn")
    assert result == []


@pytest.mark.asyncio()
async def test_find_by_turn_returns_memories_for_turn():
    adapter = _adapter()
    await adapter.store(
        "用户偏好 KISS 风格",
        importance=7,
        memory_category="user_pref",
        source_turn_id="turn-abc",
        session_id="s1",
    )
    await adapter.store(
        "另一 turn 的记忆",
        importance=6,
        memory_category="project_fact",
        source_turn_id="turn-xyz",
        session_id="s1",
    )

    results = await adapter.find_by_turn("turn-abc")
    assert len(results) == 1
    assert results[0]["source_turn_id"] == "turn-abc"
    assert "KISS" in results[0]["content"]


@pytest.mark.asyncio()
async def test_find_by_category_filters_correctly():
    adapter = _adapter()
    await adapter.store(
        "用户喜欢猫", importance=7, memory_category="user_pref", source_turn_id="t1",
        session_id="s1",
    )
    await adapter.store(
        "项目使用 React", importance=6, memory_category="project_fact", source_turn_id="t2",
        session_id="s1",
    )

    prefs = await adapter.find_by_category("user_pref")
    assert len(prefs) == 1
    assert "猫" in prefs[0]["content"]
    assert prefs[0]["memory_category"] == "user_pref"


@pytest.mark.asyncio()
async def test_find_by_category_respects_limit():
    adapter = _adapter()
    for i in range(3):
        await adapter.store(
            f"事实 {i}",
            importance=6,
            memory_category="project_fact",
            source_turn_id=f"t{i}",
            session_id="s1",
        )

    results = await adapter.find_by_category("project_fact", limit=2)
    assert len(results) == 2


@pytest.mark.asyncio()
async def test_find_by_category_and_session_filters_by_session():
    adapter = _adapter()
    await adapter.store(
        "会话A的任务总结",
        importance=6,
        memory_category="task_summary",
        session_id="sA",
        source_turn_id="t1",
    )
    await adapter.store(
        "会话B的任务总结",
        importance=6,
        memory_category="task_summary",
        session_id="sB",
        source_turn_id="t2",
    )

    results = await adapter.find_by_category_and_session("task_summary", "sA")
    assert len(results) == 1
    assert "会话A" in results[0]["content"]
    assert results[0]["session_id"] == "sA"


@pytest.mark.asyncio()
async def test_find_by_category_excludes_invalid_memories():
    adapter = _adapter()
    mid = await adapter.store(
        "待软删记忆", importance=6, memory_category="project_fact", source_turn_id="t1",
        session_id="s1",
    )
    get_memory_manager().episodic.delete(mid)

    results = await adapter.find_by_category("project_fact")
    assert results == []


# ==================== HTTP endpoints ====================


@pytest.mark.asyncio()
async def test_profile_endpoint_empty(client):
    resp = await client.get("/api/v1/memory/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"preferences": [], "decisions": [], "facts": [], "total_count": 0}


@pytest.mark.asyncio()
async def test_profile_endpoint_groups_by_category(client):
    adapter = _adapter()
    await adapter.store(
        "用户偏好极简界面", importance=7, memory_category="user_pref", source_turn_id="t1",
        session_id="s1",
    )
    await adapter.store(
        "决定使用 React 重构", importance=6, memory_category="decision", source_turn_id="t2",
        session_id="s1",
    )
    await adapter.store(
        "项目使用 TypeScript", importance=7, memory_category="project_fact", source_turn_id="t3",
        session_id="s1",
    )

    resp = await client.get("/api/v1/memory/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["preferences"]) == 1
    assert len(body["decisions"]) == 1
    assert len(body["facts"]) == 1
    assert body["total_count"] == 3


@pytest.mark.asyncio()
async def test_by_turn_endpoint_returns_memories(client):
    adapter = _adapter()
    await adapter.store(
        "关于 KISS 的记忆",
        importance=7,
        memory_category="decision",
        source_turn_id="turn-abc",
        session_id="s1",
    )

    resp = await client.get("/api/v1/memory/by-turn/turn-abc")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["memories"]) == 1
    assert body["memories"][0]["source_turn_id"] == "turn-abc"
    assert "KISS" in body["memories"][0]["content"]


@pytest.mark.asyncio()
async def test_by_turn_endpoint_returns_empty_for_unknown_turn(client):
    resp = await client.get("/api/v1/memory/by-turn/no-such-turn")
    assert resp.status_code == 200
    assert resp.json() == {"memories": []}


@pytest.mark.asyncio()
async def test_summary_endpoint_filters_by_session(client):
    adapter = _adapter()
    await adapter.store(
        "sA 的任务总结",
        importance=6,
        memory_category="task_summary",
        session_id="sA",
        source_turn_id="t1",
    )
    await adapter.store(
        "sB 的任务总结",
        importance=6,
        memory_category="task_summary",
        session_id="sB",
        source_turn_id="t2",
    )

    resp = await client.get("/api/v1/memory/summary/sA")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "sA"
    assert len(body["summaries"]) == 1
    assert "sA" in body["summaries"][0]["content"]


@pytest.mark.asyncio()
async def test_delete_accepts_memory_id_alias(client):
    """Gap E — the renderer bridge (T1) calls delete with ``{ memory_id }``
    while the legacy request model only accepted ``{ id }``. Accept both."""
    adapter = _adapter()
    mid = await adapter.store(
        "待删除记忆", importance=6, memory_category="project_fact", session_id="s1"
    )

    resp = await client.post("/api/v1/memory/delete", json={"memory_id": mid})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio()
async def test_delete_requires_an_id(client):
    resp = await client.post("/api/v1/memory/delete", json={})
    assert resp.status_code == 422
