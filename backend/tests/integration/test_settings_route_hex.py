"""hex_routes SettingsRequest 白名单校验。"""

from __future__ import annotations

import os

import pytest

from backend.api.hex_routes import get_chat_service
from backend.data.settings_repo import SettingsRepository
from backend.main import app

_API_MODE = os.environ.get("API_MODE", "legacy").lower()
_HEX_ONLY = pytest.mark.skipif(
    _API_MODE != "hex",
    reason=f"hex_routes requires API_MODE='hex'; got {_API_MODE!r}",
)


@pytest.fixture(autouse=True)
def _clean():
    repo = SettingsRepository()
    conn = repo.db.get_connection()
    conn.execute("DELETE FROM preferences WHERE key='app_settings'")
    conn.commit()
    saved = app.dependency_overrides.get(get_chat_service)
    app.dependency_overrides[get_chat_service] = lambda: object()
    yield
    conn.execute("DELETE FROM preferences WHERE key='app_settings'")
    conn.commit()
    if saved is None:
        app.dependency_overrides.pop(get_chat_service, None)
    else:
        app.dependency_overrides[get_chat_service] = saved


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_hex_put_rejects_unknown_field(client):
    """hex_routes 通过 Pydantic extra=forbid 拒收白名单外字段。"""
    resp = await client.put(
        "/api/v1/settings",
        json={"streaming": True, "foo": "bar"},
    )
    assert resp.status_code == 422
    assert "foo" in resp.text
