"""R77 — web-access 凭据/配置/指标路由单元测试。

直接调用路由函数（异步），origin 守卫统一打桩放行（r166 惯例）；
SettingsRepository / credential_vault / web_metrics / tls_transport 全
monkeypatch。覆盖：凭据清单透传、删除命中与 404、config 读写合并语义
与写失败 500、header/cookie 凭据新增（域名归一 + 422）、指标快照合并
与重置、Origin 守卫拦截路径、载荷 extra=forbid。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.api import web_access_routes as war

pytestmark = pytest.mark.unit


class _FakeRequest:
    """origin 守卫打桩后不读该对象。"""


@pytest.fixture(autouse=True)
def _allow_origin(monkeypatch):
    monkeypatch.setattr(war, "forbidden_origin_response", lambda request: None)


@pytest.mark.asyncio()
async def test_origin_guard_short_circuits_list(monkeypatch):
    sentinel = SimpleNamespace(status_code=403)
    monkeypatch.setattr(war, "forbidden_origin_response", lambda request: sentinel)
    out = await war.list_web_credentials(_FakeRequest())
    assert out is sentinel


# ---------------------------------------------------------------------------
# 凭据清单 / 删除
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_list_credentials_passthrough(monkeypatch):
    monkeypatch.setattr(
        war, "list_credentials", lambda: [{"domain": "example.com", "kind": "cookie"}]
    )
    out = await war.list_web_credentials(_FakeRequest())
    assert out == {
        "credentials": [{"domain": "example.com", "kind": "cookie"}]
    }


@pytest.mark.asyncio()
async def test_delete_credential_hit(monkeypatch):
    monkeypatch.setattr(war, "delete_credential", lambda domain: True)
    out = await war.delete_web_credential(_FakeRequest(), "example.com")
    assert out == {"ok": True}


@pytest.mark.asyncio()
async def test_delete_credential_miss_404(monkeypatch):
    monkeypatch.setattr(war, "delete_credential", lambda domain: False)
    resp = await war.delete_web_credential(_FakeRequest(), "ghost.com")
    assert resp.status_code == 404
    assert json.loads(resp.body) == {"ok": False, "error": "not_found"}


# ---------------------------------------------------------------------------
# config 读写
# ---------------------------------------------------------------------------


@pytest.fixture()
def settings_store(monkeypatch):
    state = {"web_access_config": ""}

    class _Repo:
        def get(self, key):
            return state.get(key)

        def set(self, key, value):
            state[key] = value

    monkeypatch.setattr(war, "SettingsRepository", _Repo)
    return state


@pytest.mark.asyncio()
async def test_get_config_defaults_false(settings_store):
    out = await war.get_web_access_config(_FakeRequest())
    assert out == {"render_persistent": False, "auto_refresh_credentials": False}


@pytest.mark.asyncio()
async def test_get_config_reads_stored_values(settings_store):
    settings_store["web_access_config"] = json.dumps(
        {"render_persistent": True, "auto_refresh_credentials": True, "extra": 1}
    )
    out = await war.get_web_access_config(_FakeRequest())
    assert out == {"render_persistent": True, "auto_refresh_credentials": True}


@pytest.mark.asyncio()
async def test_put_config_merges_with_existing(settings_store):
    settings_store["web_access_config"] = json.dumps({"render_persistent": True})
    body = war.WebAccessConfigBody(auto_refresh_credentials=True)
    out = await war.put_web_access_config(_FakeRequest(), body)
    assert out == {"ok": True, "render_persistent": True,
                   "auto_refresh_credentials": True}
    saved = json.loads(settings_store["web_access_config"])
    assert saved == {"render_persistent": True, "auto_refresh_credentials": True}


@pytest.mark.asyncio()
async def test_put_config_write_failure_500(settings_store, monkeypatch):
    class _BrokenRepo:
        def get(self, key):
            return ""

        def set(self, key, value):
            raise RuntimeError("settings db locked")

    monkeypatch.setattr(war, "SettingsRepository", _BrokenRepo)
    body = war.WebAccessConfigBody(render_persistent=True)
    resp = await war.put_web_access_config(_FakeRequest(), body)
    assert resp.status_code == 500
    assert "settings db locked" in json.loads(resp.body)["error"]


def test_config_body_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        war.WebAccessConfigBody(render_persistent=True, extra_key=1)


# ---------------------------------------------------------------------------
# header / cookie 凭据新增
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_create_header_credential_normalizes_domain(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        war,
        "save_header_credential",
        lambda domain, headers: captured.update(
            domain=domain, headers=headers
        ) or True,
    )
    body = war.HeaderCredentialBody(
        domain="  Example.COM ", header_name="X-Token", value="v"
    )
    out = await war.create_header_credential(_FakeRequest(), body)
    assert out == {"ok": True}
    assert captured["domain"] == "example.com"
    assert captured["headers"] == {"X-Token": "v"}


@pytest.mark.asyncio()
async def test_create_header_credential_value_error_422(monkeypatch):
    def reject(domain, headers):
        raise ValueError("invalid token syntax")

    monkeypatch.setattr(war, "save_header_credential", reject)
    body = war.HeaderCredentialBody(domain="d.com", header_name="X", value="bad")
    resp = await war.create_header_credential(_FakeRequest(), body)
    assert resp.status_code == 422
    assert "invalid token syntax" in json.loads(resp.body)["error"]


@pytest.mark.asyncio()
async def test_create_cookie_credential_success(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        war,
        "save_credential",
        lambda domain, cookies: captured.update(
            domain=domain, cookies=cookies
        ) or True,
    )
    body = war.CookieCredentialBody(
        domain="Example.com", cookies=[{"name": "sid", "value": "1"}]
    )
    out = await war.create_cookie_credential(_FakeRequest(), body)
    assert out == {"ok": True}
    assert captured["domain"] == "example.com"


@pytest.mark.asyncio()
async def test_create_cookie_credential_invalid_422(monkeypatch):
    def reject(domain, cookies):
        raise ValueError("bad cookie")

    monkeypatch.setattr(war, "save_credential", reject)
    body = war.CookieCredentialBody(domain="d.com", cookies=[])
    resp = await war.create_cookie_credential(_FakeRequest(), body)
    assert resp.status_code == 422
    assert json.loads(resp.body)["error"] == "invalid_cookie_credential"


def test_credential_bodies_reject_extra_fields():
    with pytest.raises(ValidationError):
        war.HeaderCredentialBody(domain="d", header_name="X", value="v", extra=1)
    with pytest.raises(ValidationError):
        war.CookieCredentialBody(domain="d", cookies=[], extra=1)


# ---------------------------------------------------------------------------
# metrics 快照与重置
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_metrics_snapshot_merges_tls_stats(monkeypatch):
    monkeypatch.setattr(
        "backend.tools.web_metrics.snapshot",
        lambda: {"per_host": {"a.com": 3}},
    )
    monkeypatch.setattr(
        "backend.tools.tls_transport.stats", lambda: {"ab3_calls": 1}
    )
    out = await war.get_web_metrics(_FakeRequest())
    assert out["metrics"]["per_host"] == {"a.com": 3}
    assert out["metrics"]["tls_fingerprint"] == {"ab3_calls": 1}


@pytest.mark.asyncio()
async def test_reset_metrics(monkeypatch):
    reset_calls = []
    monkeypatch.setattr(
        "backend.tools.web_metrics.reset", lambda: reset_calls.append(1)
    )
    out = await war.reset_web_metrics(_FakeRequest())
    assert out == {"ok": True}
    assert reset_calls == [1]
