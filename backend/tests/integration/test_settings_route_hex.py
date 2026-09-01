"""hex_routes SettingsRequest 白名单校验。"""

from __future__ import annotations

import json
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
async def test_hex_put_invalid_settings_uses_safe_structured_error_and_log(client, caplog):
    """Hex settings validation does not echo protocol/path values."""
    import logging

    caplog.set_level(logging.WARNING)
    protocol = "sk-hex-secret-protocol-value"
    local_path = r"C:\Users\synthetic\private-model.gguf"

    invalid_protocol = await client.put(
        "/api/v1/settings", json={"endpoints": [{"protocol": protocol}]}
    )
    invalid_path = await client.put(
        "/api/v1/settings",
        json={"endpoints": [{"protocol": "ollama", "localModelPath": local_path}]},
    )

    for response in (invalid_protocol, invalid_path):
        assert response.status_code == 422
        assert response.status_code != 500
        assert response.json()["detail"]["type"] == "invalid_settings_payload"
        assert response.json()["detail"]["message"] == "设置内容无效，请检查字段格式"
        assert protocol not in response.text
        assert local_path not in response.text
    logs = " ".join(record.getMessage() for record in caplog.records)
    assert protocol not in logs
    assert local_path not in logs
    assert "error_type=invalid_settings_payload" in logs

@pytest.mark.asyncio()
@_HEX_ONLY
async def test_hex_put_settings_prevalidation_error_is_fixed_and_non_echoing(client):
    """Pydantic failures on hex /settings never expose submitted values."""
    secret = "synthetic-secret-hex"
    path = "/absolute/synthetic/hex-model.gguf"
    cases = [
        {"endpoints": [{"protocol": 123, "apiKey": secret, "localModelPath": path}]},
        {"endpoints": [{"protocol": "ollama", "localModelPath": [path]}]},
        {"unexpected": secret},
    ]
    for payload in cases:
        response = await client.put("/api/v1/settings", json=payload)
        assert response.status_code == 422
        assert response.json() == {
            "detail": {
                "type": "invalid_settings_payload",
                "message": "设置内容无效，请检查字段格式",
            }
        }
        assert secret not in response.text
        assert path not in response.text


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_hex_other_validation_routes_keep_fastapi_default_handler(client):
    """The scoped handler must not rewrite validation errors elsewhere."""
    response = await client.patch("/api/v1/agents/primary/toggle", json={"enabled": "secret"})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "enabled"
    assert response.json()["detail"][0]["type"]


@pytest.mark.asyncio()
@_HEX_ONLY
@pytest.mark.parametrize(
    "dirty_settings",
    [
        {"endpoints": 1},
        {
            "endpoints": [
                {
                    "apiKey": "synthetic-secret",
                    "localModelPath": "/private/synthetic/path",
                    "discoveredModels": 1,
                }
            ]
        },
        {"modelSelections": 1},
        {"wiki": 1},
        {"orch": 1},
    ],
)
async def test_hex_put_rejects_scalar_persisted_settings_containers_without_500(
    client, dirty_settings
):
    """脏持久化容器应返回明确 4xx, 且错误响应不回显 secret/path."""
    SettingsRepository().set_json("app_settings", dirty_settings, category="general")

    resp = await client.put("/api/v1/settings", json={"streaming": True})

    assert 400 <= resp.status_code < 500
    assert resp.status_code != 500
    assert "synthetic-secret" not in resp.text
    assert "/private/synthetic/path" not in resp.text


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_hex_put_with_unknown_field_rejected(client):
    """hex_routes 通过 Pydantic extra=forbid 拒收白名单外字段。"""
    resp = await client.put(
        "/api/v1/settings",
        json={"streaming": True, "foo": "bar"},
    )
    assert resp.status_code == 422
    assert "foo" not in resp.text


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


@pytest.mark.asyncio()
@_HEX_ONLY
@pytest.mark.parametrize(
    "scalar_value",
    [
        json.dumps("api-token-secret"),
        "42",
        "null",
        "[]",
    ],
)
async def test_hex_get_preference_scalar_app_settings_returns_safe_object(scalar_value):
    """历史 app_settings 标量不得在 hex preference GET 中原样回显."""
    conn = SettingsRepository().db.get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO preferences(key,value,value_type,category,created_at,updated_at) "
        "VALUES('app_settings', ?, 'string', 'general', 1, 1)",
        (scalar_value,),
    )
    conn.commit()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/v1/preferences/app_settings")

    assert resp.status_code == 200
    assert resp.json()["value"] == "{}"
    assert "api-token-secret" not in resp.text


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_hex_put_preference_app_settings_redacts_variants_and_preserves_storage(client):
    payload = {
        "endpoints": [{"id": "ep", "apiKey": "synthetic-api-key"}],
        "dbPassword": "synthetic-db-password",
        "secretKey": "synthetic-secret-key",
        "privateKey": "synthetic-private-key",
        "authorization": "synthetic-authorization",
        "authToken": "synthetic-auth-token",
        "clientSecret": "synthetic-client-secret",
        "tokenization": "ordinary-setting",
        "passwordPolicy": "ordinary-policy",
    }
    resp = await client.put(
        "/api/v1/preferences/app_settings", json={"value": json.dumps(payload)}
    )
    assert resp.status_code == 200
    assert "synthetic-" not in resp.text
    returned = json.loads(resp.json()["value"])
    assert returned["endpoints"][0]["apiKey"] == ""
    assert returned["endpoints"][0]["hasApiKey"] is True
    assert returned["dbPassword"] == ""
    assert returned["secretKey"] == ""
    assert returned["privateKey"] == ""
    assert returned["authorization"] == ""
    assert returned["authToken"] == ""
    assert returned["clientSecret"] == ""
    assert returned["tokenization"] == "ordinary-setting"
    assert returned["passwordPolicy"] == "ordinary-policy"
    assert SettingsRepository().get_json("app_settings") == payload


@pytest.mark.asyncio()
@_HEX_ONLY
@pytest.mark.parametrize("invalid_value", ["not-json", "[]", "null", '"scalar"', "42"])
async def test_hex_put_preference_app_settings_rejects_invalid_json_without_overwrite(
    client, invalid_value
):
    baseline = {"streaming": True}
    SettingsRepository().set_json("app_settings", baseline, category="general")
    resp = await client.put(
        "/api/v1/preferences/app_settings", json={"value": invalid_value}
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "app_settings must be a JSON object"
    assert SettingsRepository().get_json("app_settings") == baseline
