"""端到端 GET/PUT /settings 行为测试 (legacy_routes)。

覆盖 Task 2: 翻译层 + 白名单 + JSON 损坏 fallback。
"""

from __future__ import annotations

import pytest

from backend.data.settings_repo import SettingsRepository


@pytest.fixture(autouse=True)
def _clean_settings():
    """每测试前/后清空 app_settings 行。

    setup_test_db 已经每个测试用独立临时 SQLite, 这里兜底防 ad-hoc 调试干扰。
    """
    repo = SettingsRepository()
    conn = repo.db.get_connection()
    conn.execute("DELETE FROM preferences WHERE key='app_settings'")
    conn.commit()
    yield
    conn = repo.db.get_connection()
    conn.execute("DELETE FROM preferences WHERE key='app_settings'")
    conn.commit()


@pytest.mark.asyncio()
async def test_get_translates_legacy_snake_to_camel(client):
    """DB 里手插一条 snake_case 行, GET 应翻译为 camelCase 返回。"""
    SettingsRepository().set_json(
        "app_settings",
        {
            "endpoints": [
                {
                    "id": "e1",
                    "base_url": "u",
                    "api_key": "k",
                    "discovered_models": [],
                    "last_discovered_at": 0,
                }
            ]
        },
        category="general",
    )
    resp = await client.get("/api/v1/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["endpoints"][0]["baseUrl"] == "u"
    assert body["endpoints"][0]["apiKey"] == "k"
    assert "base_url" not in body["endpoints"][0]


@pytest.mark.asyncio()
async def test_get_returns_null_when_corrupted_json(client):
    """DB 行 JSON 损坏 → GET 返回 null (不抛 500)。"""
    conn = SettingsRepository().db.get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO preferences(key,value,value_type,category,created_at,updated_at) "
        "VALUES('app_settings', 'not-valid-json{', 'string', 'general', 1, 1)"
    )
    conn.commit()
    resp = await client.get("/api/v1/settings")
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.asyncio()
async def test_put_with_unknown_field_rejected(client):
    """PUT 接受 schema 内字段 + 不在白名单的字段 → 400 + 详细信息。"""
    resp = await client.put(
        "/api/v1/settings",
        json={
            "streaming": True,
            "foo": "bar",  # 不在 AppSettings 白名单
        },
    )
    assert resp.status_code == 400
    assert "unknown top-level field 'foo'" in resp.text


@pytest.mark.asyncio()
async def test_put_with_legacy_compat_fields_does_not_400(client):
    """B1 回归: legacy PUT 含 api_base_url / api_key / model 三个 legacy compat 字段
    不再返回 400. 这 3 字段剥离后不进 DB, 但进审计 changed_fields.
    """
    resp = await client.put(
        "/api/v1/settings",
        json={
            "api_base_url": "https://legacy.example.com/v1",
            "api_key": "test-legacy-key",
            "model": "legacy-model",
            "streaming": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # PUT response body 是 LegacySettingsResponse{status, changed_fields},
    # 不返回完整 settings. 验证 changed_fields + 直接读 DB 验持久化.
    assert body == {
        "status": "ok",
        "changed_fields": [
            "streaming",
            "api_base_url",
            "api_key",
            "model",
        ],
    } or set(body["changed_fields"]) == {"streaming", "api_base_url", "api_key", "model"}
    # DB 仍存纯 camelCase AppSettings 形状 — legacy 3 字段不进 DB
    persisted = SettingsRepository().get_json("app_settings")
    assert persisted is not None
    assert "api_base_url" not in persisted
    assert "api_key" not in persisted
    assert "model" not in persisted
    assert persisted.get("streaming") is True


@pytest.mark.asyncio()
async def test_get_returns_null_when_top_level_is_list(client):
    """B2 回归: DB 行是合法 JSON list (脏数据) → GET 返回 null, 不抛 500.
    与 hex GET 行为对齐 (parity).
    """
    conn = SettingsRepository().db.get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO preferences(key,value,value_type,category,created_at,updated_at) "
        "VALUES('app_settings', '[1, 2, 3]', 'string', 'general', 1, 1)"
    )
    conn.commit()
    resp = await client.get("/api/v1/settings")
    assert resp.status_code == 200
    assert resp.json() is None
