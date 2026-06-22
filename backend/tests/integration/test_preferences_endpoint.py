"""GET/PUT /preferences/{key} 通用 KV 端点集成测试"""
import pytest
from httpx import AsyncClient

from backend.main import app


@pytest.mark.asyncio
async def test_get_preference_returns_value():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # 先 set
        await ac.put("/api/v1/preferences/theme_mode", json={"value": "dark"})
        # 再 get
        resp = await ac.get("/api/v1/preferences/theme_mode")
    assert resp.status_code == 200
    assert resp.json()["value"] == "dark"


@pytest.mark.asyncio
async def test_get_preference_returns_null_when_missing():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # current_session_id 在 KEYS 白名单内但测试中未写入过
        resp = await ac.get("/api/v1/preferences/current_session_id")
    assert resp.status_code == 200
    assert resp.json()["value"] is None


@pytest.mark.asyncio
async def test_get_preference_rejects_non_whitelisted_key():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/preferences/evil_key")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_put_preference_rejects_non_whitelisted_key():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.put("/api/v1/preferences/evil_key", json={"value": "x"})
    assert resp.status_code == 400