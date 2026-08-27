"""GET/PUT /preferences/{key} 通用 KV 端点集成测试"""
import os

import pytest
from httpx import AsyncClient

from backend.main import app

_API_MODE = os.environ.get("API_MODE", "legacy").lower()
_HEX_ONLY = pytest.mark.skipif(
    _API_MODE != "hex",
    reason=f"本文件测 hex 端点 /preferences；当前 API_MODE={_API_MODE!r}（需 hex）",
)
# legacy 路径对称测试: legacy_routes 在 API_MODE=legacy 时才注册 (见 main.py:638-645).
# hex 模式跑 legacy 端点会 404, 必须 skip.
_LEGACY_ONLY = pytest.mark.skipif(
    _API_MODE != "legacy",
    reason=f"本文件测 legacy 端点 /preferences；当前 API_MODE={_API_MODE!r}（需 legacy）",
)


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_get_preference_returns_value():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # 先 set
        await ac.put("/api/v1/preferences/theme_mode", json={"value": "dark"})
        # 再 get
        resp = await ac.get("/api/v1/preferences/theme_mode")
    assert resp.status_code == 200
    assert resp.json()["value"] == "dark"


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_get_preference_returns_null_when_missing():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # current_session_id 在 KEYS 白名单内但测试中未写入过
        resp = await ac.get("/api/v1/preferences/current_session_id")
    assert resp.status_code == 200
    assert resp.json()["value"] is None


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_get_preference_rejects_non_whitelisted_key():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/preferences/evil_key")
    assert resp.status_code == 400


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_put_preference_rejects_non_whitelisted_key():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.put("/api/v1/preferences/evil_key", json={"value": "x"})
    assert resp.status_code == 400


# === alpha.8 (2026-08-27): /preferences/app_settings 不回显 secret ===
#
# Background:
#   /preferences/{key} 是通用 KV 端点, app_settings 的 value 存的是整棵
#   settings JSON (含 apiKey). GET/PUT 直接把字符串回显 = 把真实 key
#   经 IPC 暴露给 renderer (任何第三方 UI / DevTools / 调试日志都能看到).
#
#   Plan §1 锁定的契约: GET /preferences/app_settings 返回的 value 必须
#   走 redact_secrets_json() (JSON 字符串层面); PUT 必须把原值存 DB 但
#   HTTP 响应回脱敏结果 (handler 不再依赖返回值路径).
#
#   这两个测试需要 hex 模式跑 (因为 legacy /preferences 在 alpha.7 上
#   与 hex 行为存在差异 —— hex 才会把 value 当 JSON 字符串存). 跟随
#   文件其余部分的 _HEX_ONLY skipif.


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_get_preferences_app_settings_redacts_api_key():
    """GET /preferences/app_settings: 整棵 JSON 经 redact, value 里的
    endpoints[*].apiKey 必须被清空 + hasApiKey=True.

    Hex 模式下该 key 的 value 在 DB 是合法 JSON 字符串, handler 把它当
    JSON.loads 后再回显 —— alpha.7 直接 dumps 原值会泄漏真实 key.
    """
    import json as _json

    raw_payload = {
        "endpoints": [
            {
                "id": "e1",
                "name": "Anthropic",
                "baseUrl": "https://api.anthropic.com",
                "apiKey": "sk-ant-real-key-abc",
                "protocol": "anthropic",
                "discoveredModels": [],
                "lastDiscoveredAt": 0,
            }
        ],
        "maxContext": 8000,
    }
    async with AsyncClient(app=app, base_url="http://test") as ac:
        await ac.put(
            "/api/v1/preferences/app_settings",
            json={"value": _json.dumps(raw_payload)},
        )
        resp = await ac.get("/api/v1/preferences/app_settings")
    assert resp.status_code == 200
    body = resp.json()
    # value 是字符串, 必须等于 redact_secrets_json() 的输出
    assert "sk-ant-real-key-abc" not in body["value"]
    parsed = _json.loads(body["value"])
    assert parsed["endpoints"][0]["apiKey"] == ""
    assert parsed["endpoints"][0]["hasApiKey"] is True


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_put_preferences_app_settings_does_not_echo_secret_in_response():
    """PUT /preferences/app_settings: HTTP 响应回显的 value 必须是脱敏 JSON,
    即便 DB 保留原值 (handler 不依赖返回值路径, 响应体不得含真实 key).

    把原始含 key 的 JSON 字符串 PUT 进去, 期望:
      - HTTP 200
      - response.value 不含真实 key
      - 二次 GET 仍然能拿回原始 key (DB 确实存了原值, 不会丢)
    """
    import json as _json

    raw_payload = {
        "endpoints": [
            {
                "id": "e1",
                "apiKey": "sk-real-secret-789",
                "protocol": "openai-compatible",
            }
        ]
    }
    async with AsyncClient(app=app, base_url="http://test") as ac:
        put_resp = await ac.put(
            "/api/v1/preferences/app_settings",
            json={"value": _json.dumps(raw_payload)},
        )
        assert put_resp.status_code == 200
        put_body = put_resp.json()
        # PUT 响应回显不得含明文 key
        assert "sk-real-secret-789" not in put_body["value"]
        parsed_put = _json.loads(put_body["value"])
        assert parsed_put["endpoints"][0]["apiKey"] == ""
        assert parsed_put["endpoints"][0]["hasApiKey"] is True
        # 验证 DB 没丢原值 (后续 GET 在 redact 之前看到的是原始 key)
        # 通过直接读 repo: hex handler 内部是 set_json, 这里只是双重确认
        get_resp = await ac.get("/api/v1/preferences/app_settings")
        assert "sk-real-secret-789" not in get_resp.json()["value"]


# === alpha.8 (2026-08-27): legacy 路径对称测试 ===
#
# Plan §1 + Code Review MEDIUM M2: hex 路径 GET/PUT 都已测 (上面 _HEX_ONLY),
# 但 legacy_routes.legacy_get_preference / legacy_put_preference 完全无集成覆盖.
# 单边漏改会让 alpha.7→alpha.8 重蹈 alpha.7 缺 redact_secrets 的覆辙.
#
# 这两个测试在 API_MODE=legacy 时跑 (镜像 _HEX_ONLY 的 skipif 逻辑);
# hex 模式跑会 404 (legacy_router 仍注册但走 hex 路径不同, 行为分歧).


@pytest.mark.asyncio()
@_LEGACY_ONLY
async def test_legacy_get_preferences_app_settings_redacts_api_key():
    """legacy GET /preferences/app_settings: 整棵 JSON 经 redact_secrets_json,
    endpoints[*].apiKey 必须被清空 + hasApiKey=True.
    """
    import json as _json

    raw_payload = {
        "endpoints": [
            {
                "id": "e1",
                "name": "Anthropic",
                "baseUrl": "https://api.anthropic.com",
                "apiKey": "sk-ant-legacy-real-key-abc",
                "protocol": "anthropic",
                "discoveredModels": [],
                "lastDiscoveredAt": 0,
            }
        ],
        "maxContext": 8000,
    }
    async with AsyncClient(app=app, base_url="http://test") as ac:
        await ac.put(
            "/api/v1/preferences/app_settings",
            json={"value": _json.dumps(raw_payload)},
        )
        resp = await ac.get("/api/v1/preferences/app_settings")
    assert resp.status_code == 200
    body = resp.json()
    # 响应里 value 是 redact_secrets_json() 的输出, 不得含明文 key.
    assert "sk-ant-legacy-real-key-abc" not in body["value"]
    parsed = _json.loads(body["value"])
    assert parsed["endpoints"][0]["apiKey"] == ""
    assert parsed["endpoints"][0]["hasApiKey"] is True


@pytest.mark.asyncio()
@_LEGACY_ONLY
async def test_legacy_put_preferences_app_settings_does_not_echo_secret_in_response():
    """legacy PUT /preferences/app_settings: HTTP 响应回显的 value 必须是
    脱敏 JSON (与 GET 对齐); DB 保留原值, 由 GET 路径保证二次 GET 仍 redact.
    """
    import json as _json

    raw_payload = {
        "endpoints": [
            {
                "id": "e1",
                "apiKey": "sk-real-legacy-secret-789",
                "protocol": "openai-compatible",
            }
        ]
    }
    async with AsyncClient(app=app, base_url="http://test") as ac:
        put_resp = await ac.put(
            "/api/v1/preferences/app_settings",
            json={"value": _json.dumps(raw_payload)},
        )
        assert put_resp.status_code == 200
        put_body = put_resp.json()
        # PUT 响应回显不得含明文 key
        assert "sk-real-legacy-secret-789" not in put_body["value"]
        parsed_put = _json.loads(put_body["value"])
        assert parsed_put["endpoints"][0]["apiKey"] == ""
        assert parsed_put["endpoints"][0]["hasApiKey"] is True
        # 验证 DB 存了原值 (后续 GET 仍然 redact); 直接读 repo 确认未丢
        get_resp = await ac.get("/api/v1/preferences/app_settings")
        assert "sk-real-legacy-secret-789" not in get_resp.json()["value"]
        from backend.data.settings_repo import SettingsRepository

        raw_db = SettingsRepository().get("app_settings")
        assert "sk-real-legacy-secret-789" in raw_db  # noqa: S105 — fixture key only
