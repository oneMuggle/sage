"""端到端 GET/PUT /settings 行为测试 (legacy_routes)。

覆盖 Task 2: 翻译层 + 白名单 + JSON 损坏 fallback。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from backend.api.hex_routes import get_chat_service
from backend.data.settings_repo import SettingsRepository
from backend.main import app


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


@pytest_asyncio.fixture(autouse=True)
async def _override_get_chat_service():
    """PUT /settings handler 依赖 ``get_chat_service``; 测试环境无 ChatService 实例,
    用 MagicMock 注入避免 NotImplementedError。同时隔离: 保存原 override, 退出时恢复,
    避免污染后续 test (与 test_settings_route_hex.py 同款 pattern).

    不加这个 fixture, hex mode 下 PUT handler 会 raise NotImplementedError("get_chat_service()
    must be overridden"), win7 py3.8 ci 即 fail 在此.
    """
    saved = app.dependency_overrides.get(get_chat_service)
    app.dependency_overrides[get_chat_service] = lambda: MagicMock()
    try:
        yield
    finally:
        if saved is not None:
            app.dependency_overrides[get_chat_service] = saved
        else:
            app.dependency_overrides.pop(get_chat_service, None)


@pytest.mark.asyncio()
async def test_get_translates_legacy_snake_to_camel(client):
    """DB 里手插一条 snake_case 行, GET 应翻译为 camelCase 返回。

    alpha.8 (2026-08-27): GET 走 redact_secrets() 后, endpoints[*].apiKey
    永远空串 + hasApiKey 元数据; 不再回显真实 key. 翻译到 camelCase 这一步
    仍生效 (``base_url`` → ``baseUrl``), 验证点从 apiKey 值改为 hasApiKey 标记.
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
    # alpha.8: apiKey 被脱敏为空串 + hasApiKey 元数据; 不再断言 apiKey 值.
    assert body["endpoints"][0]["apiKey"] == ""
    assert body["endpoints"][0]["hasApiKey"] is True
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
    """PUT 接受 schema 内字段 + 不在白名单的字段 → 400 + 详细信息.

    win7 Note: Pydantic v1 + FastAPI 在 ``extra="allow"`` schema 下有时会
    在 Pydantic 层 (handler 没跑) 直接 422 reject unknown field; main pytest
    走 handler raise 400. 两个 status code 都表明 PUT 被 reject, 所以测试容差
    接受 400 (handler raise) 或 422 (Pydantic 早期校验), 验证 body 包含 'foo' 错误信号.
    """
    resp = await client.put(
        "/api/v1/settings",
        json={
            "streaming": True,
            "foo": "bar",  # 不在 AppSettings 白名单
        },
    )
    assert resp.status_code in (400, 422), (
        f"expected PUT reject (400 or 422), got {resp.status_code}: {resp.text}"
    )
    assert "foo" in resp.text or "extra_forbidden" in resp.text or "extra fields not permitted" in resp.text, (
        f"Pydantic 422 body 或 handler 400 都应包含 'foo' 拒绝信号, got: {resp.text}"
    )


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


# === alpha.8 (2026-08-27): GET /settings 不回显明文 apiKey ===
#
# Background: settings_canonicalizer.redact_secrets 是主要防线; legacy GET 路由
# 必须在 ``return translated`` 前调用它, 否则真实 key 经 IPC 进入 renderer,
# 触发 [[sage-settings-redaction-key-preservation]] 的"GET hasApiKey=true 但
# apiKey 是空串"陷阱——前端 deepMerge remote-wins 会用空串覆盖本地真实 key。
#
# RED signal: 本测试会失败因为 alpha.7 canonicalizer 还没有 redact_secrets,
# GET 直接 echo 了 DB 中原始 key (DB 中有非空 key 时)。


@pytest.mark.asyncio()
async def test_get_settings_redacts_api_key_in_response(client):
    """legacy GET /settings 响应中 endpoints[*].apiKey 必须是空串, 不得回显真实 key。

    DB 存的是原始 key ("sk-real-key"), 响应必须经 redact_secrets() 把它抹掉并
    加上 hasApiKey=True, 让前端按 endpoint ID 找回本地 key 而不是覆盖之。
    """
    SettingsRepository().set_json(
        "app_settings",
        {
            "endpoints": [
                {
                    "id": "e1",
                    "name": "LM Studio",
                    "baseUrl": "http://127.0.0.1:1234/v1",
                    "apiKey": "sk-real-key-abc123",
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
    assert body["endpoints"][0]["id"] == "e1"
    # 真实 key 不得出现在响应中
    assert body["endpoints"][0]["apiKey"] == ""
    assert "sk-real-key-abc123" not in resp.text
    # hasApiKey 元数据必须为 True (原来 key 是非空)
    assert body["endpoints"][0]["hasApiKey"] is True


@pytest.mark.asyncio()
async def test_get_settings_redacts_empty_api_key_correctly(client):
    """DB 里 apiKey 本来就是空 → 响应里 apiKey="" 且 hasApiKey=False (幂等)。"""
    SettingsRepository().set_json(
        "app_settings",
        {
            "endpoints": [
                {
                    "id": "e1",
                    "apiKey": "",
                    "protocol": "openai-compatible",
                }
            ]
        },
        category="general",
    )
    resp = await client.get("/api/v1/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["endpoints"][0]["apiKey"] == ""
    assert body["endpoints"][0]["hasApiKey"] is False
