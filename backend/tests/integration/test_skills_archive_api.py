"""Integration tests for POST /api/v1/skills/{name}/archive（软归档端点）。"""

import pytest


@pytest.mark.asyncio()
async def test_archive_and_unarchive_builtin(client, reset_skill_adapter):
    # 归档 builtin（允许，非破坏可逆）
    r = await client.post("/api/v1/skills/search/archive", json={"archived": True})
    assert r.status_code == 200
    assert r.json()["lifecycle"] == "archived"

    # GET /skills 透出 lifecycle
    listing = await client.get("/api/v1/skills")
    by_name = {s["name"]: s for s in listing.json()}
    assert by_name["search"]["lifecycle"] == "archived"

    # 取消归档 → lifecycle 回到非 archived（search 从未 bump → stale）
    r2 = await client.post("/api/v1/skills/search/archive", json={"archived": False})
    assert r2.status_code == 200
    assert r2.json()["lifecycle"] != "archived"


@pytest.mark.asyncio()
async def test_archive_unknown_skill_404(client, reset_skill_adapter):
    r = await client.post("/api/v1/skills/no-such/archive", json={"archived": True})
    assert r.status_code == 404
    assert r.json()["detail"]["type"] == "skill_not_found"


@pytest.mark.asyncio()
async def test_archive_invalid_body_422(client, reset_skill_adapter):
    r = await client.post("/api/v1/skills/search/archive", json={"archived": "yes"})
    assert r.status_code == 422  # StrictBool 拒绝非布尔
