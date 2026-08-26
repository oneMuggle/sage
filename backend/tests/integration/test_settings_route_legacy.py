"""端到端 GET/PUT /settings 行为测试 (legacy_routes)。

覆盖 Task 2: 翻译层 + 白名单 + JSON 损坏 fallback。
"""

from __future__ import annotations

import json

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
    """DB 里手插一条 snake_case 行, GET 应翻译为 camelCase 返回。

    2026-08-26: 翻译 + 边界净化 + 脱敏契约 —— apiKey 字段翻译成 camelCase
    后, GET 响应里必须用 hasApiKey=True 标记, apiKey 置空 (OWASP A02:2021).
    """
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
    # 2026-08-26: redaction 契约 —— 明文 apiKey 不出现在 GET 响应里.
    assert body["endpoints"][0]["apiKey"] == ""
    assert body["endpoints"][0]["hasApiKey"] is True
    assert "base_url" not in body["endpoints"][0]
    assert "k" not in resp.text


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
async def test_put_survives_legacy_residue_and_cleans_db(client):
    """existing 里残留前端已删字段 (compactMode/proxyMode 等) → PUT 不再 400,
    且首次成功保存后 DB 自动净化（残留字段被剥离, 合法字段保留）。"""
    SettingsRepository().set_json(
        "app_settings",
        {
            "streaming": True,
            "compactMode": False,
            "proxyMode": "auto",
            "proxyUrl": "http://x",
            "tlsVersion": "1.2",
            "version": "4.0.0",
        },
        category="general",
    )
    resp = await client.put(
        "/api/v1/settings",
        json={"streaming": True, "temperature": 0.7},
    )
    assert resp.status_code == 200
    stored = SettingsRepository().get_json("app_settings")
    assert stored is not None
    assert stored["streaming"] is True
    assert stored["temperature"] == 0.7
    assert "compactMode" not in stored
    assert "proxyMode" not in stored
    assert "proxyUrl" not in stored
    assert "tlsVersion" not in stored


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


# ============================================================================
# Task 1 (2026-08-23) — settings migration + timezone (IANA) 校验
# ============================================================================
#
# 覆盖：
# 1. timezone camelCase 合法值 → 200 + 持久化
# 2. timezone 非法 IANA 字符串 → 422 (Pydantic)
# 3. EndpointConfig 新字段 protocol / modelId / localModelPath 通过白名单校验 + 存到 DB
# 4. GET /settings 把新字段原样回传 (canonicalizer 不破坏 camelCase)


@pytest.mark.asyncio()
async def test_settings_migrates_legacy_snake_case_and_rejects_invalid_timezone(client):
    """Task 1: PUT /settings 接受合法 IANA timezone 并持久化; 非法 timezone → 422."""
    valid = await client.put(
        "/api/v1/settings",
        json={"timezone": "Asia/Shanghai"},
    )
    assert valid.status_code == 200
    persisted = SettingsRepository().get_json("app_settings")
    assert persisted is not None
    assert persisted.get("timezone") == "Asia/Shanghai"

    invalid = await client.put(
        "/api/v1/settings",
        json={"timezone": "Not/AZone"},
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio()
async def test_settings_accepts_protocol_model_id_local_model_path(client):
    """Task 1: EndpointConfig 新字段 protocol / modelId / localModelPath 应通过
    canonicalizer 白名单校验 + 存到 DB."""
    resp = await client.put(
        "/api/v1/settings",
        json={
            "endpoints": [
                {
                    "id": "lmstudio-1",
                    "name": "LM Studio",
                    "baseUrl": "http://127.0.0.1:1234/v1",
                    "apiKey": "",
                    "protocol": "openai-compatible",
                    "modelId": "qwen2.5-7b-instruct",
                    "localModelPath": "/Users/me/Models/qwen.gguf",
                    "discoveredModels": [],
                    "lastDiscoveredAt": 0,
                }
            ]
        },
    )
    assert resp.status_code == 200
    persisted = SettingsRepository().get_json("app_settings")
    assert persisted is not None
    ep = persisted["endpoints"][0]
    assert ep["protocol"] == "openai-compatible"
    assert ep["modelId"] == "qwen2.5-7b-instruct"
    assert ep["localModelPath"] == "/Users/me/Models/qwen.gguf"


@pytest.mark.asyncio()
async def test_settings_unknown_endpoint_field_still_rejected(client):
    """回归门禁: 新增白名单字段后, 老的「未知字段 → 400」行为不变."""
    resp = await client.put(
        "/api/v1/settings",
        json={
            "endpoints": [
                {
                    "id": "e1",
                    "baseUrl": "http://x",
                    "apiKey": "",
                    "category": "primary",  # 不在白名单
                }
            ]
        },
    )
    assert resp.status_code == 400
    assert "category" in resp.text


@pytest.mark.asyncio()
async def test_get_round_trips_new_fields_through_canonicalizer(client):
    """Task 1: GET /settings 把 DB 中的 timezone / protocol / modelId / localModelPath
    原样回传 (DB 已存 camelCase, canonicalizer 不需动作)."""
    SettingsRepository().set_json(
        "app_settings",
        {
            "streaming": True,
            "timezone": "Asia/Shanghai",
            "endpoints": [
                {
                    "id": "lmstudio-1",
                    "name": "LM Studio",
                    "baseUrl": "http://127.0.0.1:1234/v1",
                    "apiKey": "",
                    "protocol": "openai-compatible",
                    "modelId": "qwen2.5-7b-instruct",
                    "localModelPath": "/tmp/qwen.gguf",
                    "discoveredModels": [],
                    "lastDiscoveredAt": 0,
                }
            ],
            "version": "4.0.0",
        },
        category="general",
    )
    resp = await client.get("/api/v1/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["timezone"] == "Asia/Shanghai"
    ep = body["endpoints"][0]
    assert ep["protocol"] == "openai-compatible"
    assert ep["modelId"] == "qwen2.5-7b-instruct"
    assert ep["localModelPath"] == "/tmp/qwen.gguf"


# ============================================================================
# 2026-08-26: settings 响应脱敏 + legacy payload 字段净化
# ============================================================================
#
# 背景:
# - 真实 Electron 验证中发现 GET /api/v1/settings 会明文回传端点 apiKey,
#   导致 settingsClient.getSettings() 把真实凭据写入 React state / localStorage
#   / 日志. 需要把 apiKey 替换为非敏感的 hasApiKey 标记, 真实 key 仅在 PUT
#   接收并持久化, 不再出现在 GET 响应里.
# - 已知历史前端会发送 snake_case 残留 (memory_server_sync / local_model_path
#   等), 这些不是白名单字段. canonicalizer 应该把合法 legacy residue 在 GET
#   返回前清理, 同时保证响应仍然合法.
#
# 注意: 该测试集是 RED — 当前实现仍返回明文 apiKey, 测试会失败, 确认错误信息
# 再走 GREEN.

_REDACTED_APIKEY = "sk-test-SECRET-do-not-leak-1f2e3d4c5b6a"


@pytest.mark.asyncio()
async def test_get_settings_redacts_endpoint_api_key(client):
    """GET /settings 返回的 endpoint 必须把 apiKey 替换为非敏感标记, DB 原 key 不外泄."""
    SettingsRepository().set_json(
        "app_settings",
        {
            "endpoints": [
                {
                    "id": "ep-real",
                    "name": "Real",
                    "baseUrl": "https://api.example.com/v1",
                    "apiKey": _REDACTED_APIKEY,
                    "protocol": "openai-compatible",
                    "discoveredModels": [],
                    "lastDiscoveredAt": 0,
                }
            ]
        },
        category="general",
    )
    resp = await client.get("/api/v1/settings")
    assert resp.status_code == 200
    body = resp.json()
    ep = body["endpoints"][0]
    assert ep.get("apiKey") in (None, ""), (
        "apiKey leaked in GET /settings response: "
        f"got {ep.get('apiKey')!r}, expected None or empty"
    )
    assert _REDACTED_APIKEY not in resp.text
    assert ep.get("hasApiKey") is True
    assert ep["baseUrl"] == "https://api.example.com/v1"


@pytest.mark.asyncio()
async def test_get_settings_reports_has_api_key_false_when_missing(client):
    """GET /settings 当 endpoint 没有 apiKey 时, hasApiKey 应为 False."""
    SettingsRepository().set_json(
        "app_settings",
        {
            "endpoints": [
                {
                    "id": "ep-empty",
                    "name": "LM Studio",
                    "baseUrl": "http://127.0.0.1:1234/v1",
                    "apiKey": "",
                    "protocol": "openai-compatible",
                    "discoveredModels": [],
                    "lastDiscoveredAt": 0,
                }
            ]
        },
        category="general",
    )
    resp = await client.get("/api/v1/settings")
    assert resp.status_code == 200
    body = resp.json()
    ep = body["endpoints"][0]
    assert ep.get("apiKey") in (None, "")
    assert ep.get("hasApiKey") is False


@pytest.mark.asyncio()
async def test_get_settings_cleans_legacy_snake_case_residue(client):
    """GET /settings 收到 legacy DB 行残留 snake_case 字段时, 应清洗后回传."""
    SettingsRepository().set_json(
        "app_settings",
        {
            "streaming": True,
            "memory_server_sync": True,
            "endpoints": [
                {
                    "id": "ep1",
                    "baseUrl": "http://x",
                    "apiKey": "k",
                    "local_model_path": "/old/path",
                }
            ],
        },
        category="general",
    )
    resp = await client.get("/api/v1/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert "memory_server_sync" not in body
    ep = body["endpoints"][0]
    assert "local_model_path" not in ep


@pytest.mark.asyncio()
async def test_get_preference_redacts_app_settings_payload(client):
    """GET /preferences/app_settings 应返回脱敏 payload, 不含明文 apiKey."""
    SettingsRepository().set_json(
        "app_settings",
        {
            "endpoints": [
                {
                    "id": "ep-real",
                    "name": "Real",
                    "baseUrl": "https://api.example.com/v1",
                    "apiKey": _REDACTED_APIKEY,
                    "protocol": "openai-compatible",
                    "discoveredModels": [],
                    "lastDiscoveredAt": 0,
                }
            ]
        },
        category="general",
    )
    resp = await client.get("/api/v1/preferences/app_settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["value"] is not None
    assert _REDACTED_APIKEY not in body["value"]
    parsed = json.loads(body["value"])
    ep = parsed["endpoints"][0]
    assert ep.get("apiKey") in (None, "")
    assert ep.get("hasApiKey") is True


@pytest.mark.asyncio()
async def test_put_app_settings_does_not_echo_plaintext_api_key(client):
    """PUT /settings 响应 (LegacySettingsResponse) 不应包含明文 apiKey."""
    resp = await client.put(
        "/api/v1/settings",
        json={
            "endpoints": [
                {
                    "id": "ep-x",
                    "name": "Real",
                    "baseUrl": "https://api.example.com/v1",
                    "apiKey": _REDACTED_APIKEY,
                    "protocol": "openai-compatible",
                    "discoveredModels": [],
                    "lastDiscoveredAt": 0,
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert _REDACTED_APIKEY not in resp.text
    body = resp.json()
    assert "endpoints" not in body
