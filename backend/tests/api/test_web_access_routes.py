"""Round 12 凭据管理 UI — /api/v1/web-access REST 契约测试。

覆盖:
- GET /credentials 空档案 / 有档案（脱敏字段形态，不回显值）
- DELETE /credentials/{domain} 成功 / 404
- GET /config 缺省补 False
- PUT /config 合法更新 / 未知键 422（pydantic extra=forbid）
- Origin 守卫：非白名单 Origin → 403

SettingsRepository / vault 读写全部 monkeypatch —— 契约测试不落真实库。
"""

from __future__ import annotations

import pytest

import backend.api.web_access_routes as routes

pytestmark = pytest.mark.unit  # ASGITransport 直连 app, 属快测


def _fake_record() -> dict:
    return {
        "domain": ".example.com",
        "kind": "cookie",
        "cookie_names": ["SID"],
        "saved_at": 1737000000000,
        "expires_in_seconds": 86400,
        "expired": False,
        "encrypted": True,
        "source_profile": "default",
    }


async def test_list_credentials_empty(client, monkeypatch):
    monkeypatch.setattr(routes, "list_credentials", lambda: [])
    resp = await client.get("/api/v1/web-access/credentials")
    assert resp.status_code == 200
    assert resp.json() == {"credentials": []}


async def test_list_credentials_masks_values(client, monkeypatch):
    monkeypatch.setattr(routes, "list_credentials", lambda: [_fake_record()])
    resp = await client.get("/api/v1/web-access/credentials")
    assert resp.status_code == 200
    items = resp.json()["credentials"]
    assert len(items) == 1
    item = items[0]
    assert item["domain"] == ".example.com"
    assert item["kind"] == "cookie"
    assert item["cookie_names"] == ["SID"]
    assert item["source_profile"] == "default"
    assert item["encrypted"] is True
    assert item["expires_in_seconds"] == 86400


async def test_delete_credential_success_and_404(client, monkeypatch):
    deleted = []
    monkeypatch.setattr(
        routes, "delete_credential", lambda domain: deleted.append(domain) or True
    )
    resp = await client.delete("/api/v1/web-access/credentials/.example.com")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert deleted == [".example.com"]

    monkeypatch.setattr(routes, "delete_credential", lambda domain: False)
    resp2 = await client.delete("/api/v1/web-access/credentials/.other.com")
    assert resp2.status_code == 404


async def test_get_config_defaults_false(client, monkeypatch):
    monkeypatch.setattr(routes, "_load_config_dict", lambda: {})
    resp = await client.get("/api/v1/web-access/config")
    assert resp.status_code == 200
    assert resp.json() == {
        "render_persistent": False,
        "auto_refresh_credentials": False,
    }


async def test_put_config_roundtrip(client, monkeypatch):
    stored = {}

    class _FakeRepo:
        def get(self, key):
            return None

        def set(self, key, value, value_type="string", category="general"):
            stored[key] = value

    monkeypatch.setattr(routes, "SettingsRepository", _FakeRepo)
    resp = await client.put(
        "/api/v1/web-access/config", json={"auto_refresh_credentials": True}
    )
    assert resp.status_code == 200
    assert resp.json()["auto_refresh_credentials"] is True
    assert "auto_refresh_credentials" in stored[routes.SETTINGS_KEY_WEB_ACCESS_CONFIG]

    # GET 走真实 _load_config_dict 路径需重新 monkeypatch 读取
    monkeypatch.setattr(
        routes,
        "_load_config_dict",
        lambda: {"auto_refresh_credentials": True},
    )
    resp2 = await client.get("/api/v1/web-access/config")
    assert resp2.json() == {
        "render_persistent": False,
        "auto_refresh_credentials": True,
    }


async def test_put_config_rejects_unknown_keys(client):
    resp = await client.put(
        "/api/v1/web-access/config",
        json={"render_persistent": True, "evil_key": True},
    )
    assert resp.status_code == 422


async def test_origin_guard_blocks_foreign_origin(client):
    resp = await client.get(
        "/api/v1/web-access/credentials",
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403
