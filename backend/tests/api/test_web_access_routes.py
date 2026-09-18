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


# ---------- Round 14：header 型凭据新增入口 ----------


async def test_create_header_credential_ok(client, monkeypatch):
    import backend.api.web_access_routes as routes

    captured = {}
    monkeypatch.setattr(
        routes,
        "save_header_credential",
        lambda domain, headers: captured.update(domain=domain, headers=headers),
    )
    resp = await client.post(
        "/api/v1/web-access/credentials/header",
        json={"domain": ".example.com", "header_name": "Authorization", "value": "Bearer t"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert captured == {
        "domain": ".example.com",
        "headers": {"Authorization": "Bearer t"},
    }


async def test_create_header_credential_invalid_returns_422(client, monkeypatch):
    import backend.api.web_access_routes as routes

    def _reject(domain, headers):
        raise ValueError("save_header_credential: 非法或不允许的头名 cookie")

    monkeypatch.setattr(routes, "save_header_credential", _reject)
    resp = await client.post(
        "/api/v1/web-access/credentials/header",
        json={"domain": ".example.com", "header_name": "cookie", "value": "x"},
    )
    assert resp.status_code == 422
    assert resp.json()["ok"] is False


async def test_create_header_credential_origin_guard(client):
    resp = await client.post(
        "/api/v1/web-access/credentials/header",
        json={"domain": ".example.com", "header_name": "Authorization", "value": "t"},
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403


async def test_create_header_credential_malformed_body_hides_values(client):
    """Pydantic 请求体校验失败（缺 domain）不得回显提交的凭据值。

    FastAPI 默认 422 会在 ``detail[].input`` 原样回显 body，header 的
    ``value`` 与 cookie 值同属敏感凭据，故与 cookie 路由统一走脱敏响应。
    """
    secret = "header-secret-422"
    resp = await client.post(
        "/api/v1/web-access/credentials/header",
        json={"header_name": "Authorization", "value": secret},
    )
    assert resp.status_code == 422
    assert resp.json() == {"ok": False, "error": "invalid_header_credential"}
    assert secret not in resp.text


# ---------- Round 19：cookie 型凭据导入入口 ----------


async def test_create_cookie_credential_ok(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        routes,
        "save_credential",
        lambda domain, cookies: captured.update(domain=domain, cookies=cookies),
    )
    response = await client.post(
        "/api/v1/web-access/credentials/cookie",
        json={
            "domain": ".example.com",
            "cookies": [{"name": "SID", "value": "opaque", "path": "/"}],
        },
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert captured == {
        "domain": ".example.com",
        "cookies": [{"name": "SID", "value": "opaque", "path": "/"}],
    }


async def test_create_cookie_credential_rejects_invalid_cookie(client, monkeypatch):
    cookie_value = "cookie-secret-123"

    def reject(domain, cookies):
        raise ValueError(f"cookie validation failed for {cookie_value}")

    monkeypatch.setattr(routes, "save_credential", reject)
    response = await client.post(
        "/api/v1/web-access/credentials/cookie",
        json={
            "domain": ".example.com",
            "cookies": [{"name": "SID", "value": cookie_value}],
        },
    )
    assert response.status_code == 422
    assert response.json() == {
        "ok": False,
        "error": "invalid_cookie_credential",
    }
    assert cookie_value not in response.text


async def test_create_cookie_credential_malformed_body_hides_values(client):
    """Pydantic 请求体校验失败（cookies 类型错误）不得回显提交的 cookie 值。

    FastAPI 默认 422 把 ``detail[].input`` 原样回显，明文 cookie 会随响应
    外泄；本批次凭据路由必须统一回固定非敏感错误。
    """
    secret = "cookie-secret-422"
    response = await client.post(
        "/api/v1/web-access/credentials/cookie",
        json={"domain": ".example.com", "cookies": secret},
    )
    assert response.status_code == 422
    assert response.json() == {"ok": False, "error": "invalid_cookie_credential"}
    assert secret not in response.text


async def test_create_cookie_credential_missing_domain_hides_values(client):
    """缺 domain 的 422 不得回显 cookies 列表里的明文值。"""
    secret = "cookie-secret-missing-domain"
    response = await client.post(
        "/api/v1/web-access/credentials/cookie",
        json={"cookies": [{"name": "SID", "value": secret}]},
    )
    assert response.status_code == 422
    assert response.json() == {"ok": False, "error": "invalid_cookie_credential"}
    assert secret not in response.text


async def test_create_cookie_credential_origin_guard(client):
    response = await client.post(
        "/api/v1/web-access/credentials/cookie",
        json={"domain": ".example.com", "cookies": [{"name": "SID", "value": "opaque"}]},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


# ---------- Round 15：per-host 出网指标端点 ----------


async def test_get_metrics_empty(client, monkeypatch):
    import backend.api.web_access_routes as routes

    monkeypatch.setattr(routes, "_metrics_snapshot", lambda: {})
    resp = await client.get("/api/v1/web-access/metrics")
    assert resp.status_code == 200
    assert resp.json() == {"metrics": {}}


async def test_get_metrics_reports_hosts(client, monkeypatch):
    import backend.api.web_access_routes as routes

    monkeypatch.setattr(
        routes,
        "_metrics_snapshot",
        lambda: {"example.com": {"ok": 3, "fail": 1, "escalated": 1, "avg_elapsed_ms": 120}},
    )
    resp = await client.get("/api/v1/web-access/metrics")
    assert resp.status_code == 200
    assert resp.json()["metrics"]["example.com"]["ok"] == 3


async def test_reset_metrics(client, monkeypatch):
    called = []
    monkeypatch.setattr(
        "backend.tools.web_metrics.reset", lambda: called.append(1)
    )
    resp = await client.put("/api/v1/web-access/metrics/reset")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert called == [1]


async def test_metrics_origin_guard(client):
    resp = await client.get(
        "/api/v1/web-access/metrics", headers={"Origin": "https://evil.example"}
    )
    assert resp.status_code == 403


# ---------- Round 20：诊断导出集成 web-metrics ----------


def test_exporter_includes_web_metrics(monkeypatch):
    """X2 闭环：诊断包 zip 含 web-metrics.json（快照非空时）。"""
    import io
    import json
    import zipfile

    from backend.services.llm_trace import exporter

    monkeypatch.setattr(
        "backend.tools.web_metrics.snapshot",
        lambda: {"example.com": {"ok": 2, "fail": 0, "escalated": 1, "avg_elapsed_ms": 50}},
    )
    data = exporter.export_to_zip_bytes(
        records=[],
        include_prompts=False,
        include_hostname=False,
        app_version="test",
        config_snapshot="",
    )
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert "web-metrics.json" in zf.namelist()
    metrics = json.loads(zf.read("web-metrics.json"))
    assert metrics["example.com"]["ok"] == 2


def test_exporter_skips_web_metrics_when_empty(monkeypatch):
    import io
    import zipfile

    from backend.services.llm_trace import exporter

    monkeypatch.setattr(
        "backend.tools.web_metrics.snapshot", lambda: {}
    )
    data = exporter.export_to_zip_bytes(
        records=[],
        include_prompts=False,
        include_hostname=False,
        app_version="test",
        config_snapshot="",
    )
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert "web-metrics.json" not in zf.namelist()
