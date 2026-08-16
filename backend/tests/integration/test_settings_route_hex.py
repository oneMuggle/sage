"""hex_routes SettingsRequest 白名单校验。"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

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
    # 用 MagicMock() 替代 lambda: object() — 后者没 .events.emit，
    # 若 handler 路径走到 emit 调用即会 AttributeError。
    # MagicMock() 自动接受任意属性访问 / 调用，永不抛 AttributeError。
    app.dependency_overrides[get_chat_service] = lambda: MagicMock()
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


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_hex_put_survives_legacy_residue_and_cleans_db(client):
    """existing 里残留前端已删字段 (compactMode/proxyMode 等) → hex PUT 不再
    400, 首次成功保存后 DB 自动净化 (残留剥离, 合法字段保留)。"""
    SettingsRepository().set_json(
        "app_settings",
        {
            "streaming": True,
            "compactMode": False,
            "proxyMode": "auto",
            "version": "4.0.0",
        },
        category="general",
    )
    resp = await client.put(
        "/api/v1/settings",
        json={"streaming": True, "maxContext": 8192},
    )
    assert resp.status_code == 200
    stored = SettingsRepository().get_json("app_settings")
    assert stored is not None
    assert stored["streaming"] is True
    assert stored["maxContext"] == 8192
    assert "compactMode" not in stored
    assert "proxyMode" not in stored
