"""GET/PUT /preferences/auto_memory — Task 2 Gap B whitelist extension.

The auto_memory key is added to SettingsRepository.KEYS so the IPC bridge
(memory_get_auto / memory_set_auto from T1) can read & write it via the
generic /preferences/{key} endpoints.
"""

from __future__ import annotations

import os

import pytest
from httpx import AsyncClient

from backend.data.settings_repo import SettingsRepository
from backend.main import app

_API_MODE = os.environ.get("API_MODE", "legacy").lower()
_HEX_ONLY = pytest.mark.skipif(
    _API_MODE != "hex",
    reason=f"本文件测 hex 端点 /preferences；当前 API_MODE={_API_MODE!r}（需 hex）",
)


def test_auto_memory_key_is_whitelisted():
    """Whitelist must include 'auto_memory' so IPC commands can pass through."""
    assert "auto_memory" in SettingsRepository.KEYS


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_get_auto_memory_returns_null_when_missing():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/preferences/auto_memory")
    assert resp.status_code == 200
    assert resp.json()["value"] is None


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_put_auto_memory_then_get_round_trips():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        put_resp = await ac.put(
            "/api/v1/preferences/auto_memory", json={"value": "false"}
        )
        assert put_resp.status_code == 200

        get_resp = await ac.get("/api/v1/preferences/auto_memory")
    assert get_resp.status_code == 200
    assert get_resp.json()["value"] == "false"


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_put_auto_memory_string_true_round_trips():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        await ac.put("/api/v1/preferences/auto_memory", json={"value": "true"})
        resp = await ac.get("/api/v1/preferences/auto_memory")
    assert resp.json()["value"] == "true"
