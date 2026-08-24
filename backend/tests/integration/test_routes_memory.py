"""
记忆 API 集成测试 — 覆盖 /memory/search, /memory/save, /memory/delete, /memory/list。
"""

import pytest

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


@pytest.mark.asyncio()
async def test_memory_search_empty(client):
    """空数据库上 /memory/search 返回空列表。"""
    resp = await client.get(f"{PREFIX}/memory/search", params={"query": "nothing"})
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio()
async def test_memory_search_returns_saved_content(client):
    """保存后 /memory/search 能查到。"""
    save_resp = await client.post(
        f"{PREFIX}/memory/save",
        json={
            "content": "用户喜欢吃火锅",
            "memory_type": "episodic",
            "importance": 6,
            "tags": ["preference"],
        },
    )
    assert save_resp.status_code == 200
    memory_id = save_resp.json()["id"]
    assert memory_id

    resp = await client.get(
        f"{PREFIX}/memory/search",
        params={"query": "火锅", "type": "episodic"},
    )
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) >= 1
    assert any("火锅" in r.get("content", "") for r in results)


@pytest.mark.asyncio()
async def test_memory_save_default_type(client):
    """默认 memory_type=episodic 时保存成功。"""
    resp = await client.post(
        f"{PREFIX}/memory/save",
        json={"content": "默认类型测试"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["id"]


@pytest.mark.asyncio()
async def test_memory_save_semantic(client):
    """memory_type=semantic 时保存成功。"""
    resp = await client.post(
        f"{PREFIX}/memory/save",
        json={
            "content": "用户的职业是软件工程师",
            "memory_type": "semantic",
            "importance": 8,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["id"]


@pytest.mark.asyncio()
async def test_memory_delete_episodic(client):
    """删除已保存的 episodic 记忆返回 ok。"""
    save_resp = await client.post(
        f"{PREFIX}/memory/save",
        json={"content": "待删除记忆", "memory_type": "episodic"},
    )
    memory_id = save_resp.json()["id"]

    resp = await client.post(
        f"{PREFIX}/memory/delete",
        json={"id": memory_id},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio()
async def test_memory_delete_not_found_returns_404(client):
    """删除不存在的记忆返回 404。"""
    resp = await client.post(
        f"{PREFIX}/memory/delete",
        json={"id": "nonexistent-memory-id"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "记忆不存在"


@pytest.mark.asyncio()
async def test_memory_list_empty(client):
    """空库上 /memory/list 返回 envelope(无 items)。"""
    resp = await client.get(f"{PREFIX}/memory/list")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["layer"] == "all"


@pytest.mark.asyncio()
async def test_memory_list_returns_saved(client):
    """保存后 /memory/list 能查到, envelope 含 layer/source_breakdown。"""
    await client.post(
        f"{PREFIX}/memory/save",
        json={"content": "列表查询测试", "memory_type": "episodic"},
    )

    resp = await client.get(f"{PREFIX}/memory/list", params={"type": "episodic"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["layer"] == "episodic"
    items = body["items"]
    assert len(items) >= 1
    assert any(r.get("content") == "列表查询测试" for r in items)
    # 每条记录都带 source/layer 字段
    assert all(r.get("source") == "episodic" for r in items)
    assert all(r.get("layer") == "episodic" for r in items)


@pytest.mark.asyncio()
async def test_memory_list_default_type_is_episodic(client):
    """不指定 type 时默认查询所有层(layer=='all')。"""
    await client.post(
        f"{PREFIX}/memory/save",
        json={"content": "默认类型列表", "memory_type": "episodic"},
    )

    resp = await client.get(f"{PREFIX}/memory/list")
    assert resp.status_code == 200
    body = resp.json()
    assert body["layer"] == "all"
    items = body["items"]
    assert any(r.get("content") == "默认类型列表" for r in items)


@pytest.mark.asyncio()
async def test_memory_list_type_semantic(client):
    """type=semantic 时查询语义记忆。"""
    await client.post(
        f"{PREFIX}/memory/save",
        json={"content": "语义记忆测试", "memory_type": "semantic"},
    )

    resp = await client.get(f"{PREFIX}/memory/list", params={"type": "semantic"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["layer"] == "semantic"
    items = body["items"]
    assert any(r.get("content") == "语义记忆测试" for r in items)
    assert all(r.get("source") == "semantic" for r in items)


@pytest.mark.asyncio()
async def test_memory_list_pagination_envelope(client):
    """``page`` / ``page_size`` clamp + envelope 字段。"""
    await client.post(
        f"{PREFIX}/memory/save",
        json={"content": "P 测试1", "memory_type": "episodic"},
    )
    await client.post(
        f"{PREFIX}/memory/save",
        json={"content": "P 测试2", "memory_type": "episodic"},
    )

    resp = await client.get(
        f"{PREFIX}/memory/list",
        params={"type": "episodic", "page": 1, "page_size": 1},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert len(body["items"]) == 1
    assert body["total"] >= 2
    # source_breakdown 在 envelope 里
    assert "source_breakdown" in body


@pytest.mark.asyncio()
async def test_memory_list_clamps_invalid_page_size(client):
    """``page_size > 100`` 必须 clamp 到 100。"""
    resp = await client.get(
        f"{PREFIX}/memory/list",
        params={"type": "episodic", "page_size": 9999},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["page_size"] == 100


@pytest.mark.asyncio()
async def test_memory_list_clamps_invalid_page(client):
    """``page > 10`` 必须 clamp 到 10,避免无界取数。"""
    resp = await client.get(
        f"{PREFIX}/memory/list",
        params={"type": "episodic", "page": 9999},
    )
    assert resp.status_code == 200
    assert resp.json()["page"] == 10
