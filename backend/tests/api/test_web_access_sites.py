"""站点登录 API — /api/v1/web-access/sites* 契约测试。

覆盖：模板列表、已登录网站脱敏列表与模板展示名映射、删除、
后台登录任务（scheme / 网络策略门禁 / job 生命周期查询）、Origin 守卫。

凭据库与任务管理器全部 monkeypatch —— 契约测试不启动浏览器、不落真实库。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import backend.api.web_access_routes as routes

pytestmark = pytest.mark.unit


def _record(**overrides):
    record = {
        "domain": ".cnki.net",
        "kind": "cookie",
        "cookie_names": ["SID"],
        "saved_at": 1737000000000,
        "expires_in_seconds": 86400,
        "expired": False,
        "encrypted": True,
        "has_storage": True,
        "origin_count": 1,
        "source_profile": "login-default",
    }
    record.update(overrides)
    return record


class _FakeJobs:
    def __init__(self) -> None:
        self.jobs = {}

    def start(self, url: str) -> str:
        job = {"job_id": "j-1", "url": url, "status": "running", "result": None, "error": None}
        self.jobs["j-1"] = job
        return "j-1"

    def get(self, job_id: str):
        return self.jobs.get(job_id)


def _decision(allowed: bool, needs_approval: bool = False, reason: str = "ok"):
    return SimpleNamespace(allowed=allowed, needs_approval=needs_approval, reason=reason)


async def test_site_templates_lists_cnki(client):
    resp = await client.get("/api/v1/web-access/site-templates")
    assert resp.status_code == 200
    templates = resp.json()["templates"]
    ids = [t["id"] for t in templates]
    assert "cnki" in ids
    cnki = next(t for t in templates if t["id"] == "cnki")
    assert cnki["login_url"].startswith("https://")


async def test_sites_maps_template_and_masks_values(client, monkeypatch):
    monkeypatch.setattr(routes, "list_credentials", lambda: [_record()])
    resp = await client.get("/api/v1/web-access/sites")
    assert resp.status_code == 200
    site = resp.json()["sites"][0]
    assert site["domain"] == ".cnki.net"
    assert site["display_name"] == "知网 CNKI"
    assert site["login_url"].startswith("https://")
    assert site["status"] == "logged_in"
    assert site["has_local_storage"] is True
    dump = str(resp.json())
    assert "SID" not in dump  # cookie 名都不回显

    monkeypatch.setattr(routes, "list_credentials", lambda: [_record(expired=True)])
    resp2 = await client.get("/api/v1/web-access/sites")
    assert resp2.json()["sites"][0]["status"] == "expired"


async def test_delete_site_success_and_404(client, monkeypatch):
    deleted = []
    monkeypatch.setattr(
        routes, "delete_credential", lambda domain: deleted.append(domain) or True
    )
    resp = await client.delete("/api/v1/web-access/sites/.cnki.net")
    assert resp.status_code == 200
    assert deleted == [".cnki.net"]

    monkeypatch.setattr(routes, "delete_credential", lambda domain: False)
    resp2 = await client.delete("/api/v1/web-access/sites/.other.com")
    assert resp2.status_code == 404


async def test_start_login_rejects_non_http_scheme(client):
    resp = await client.post(
        "/api/v1/web-access/sites/login", json={"url": "file:///etc/passwd"}
    )
    assert resp.status_code == 422


async def test_start_login_rejects_userinfo(client, monkeypatch):
    from backend.tools import network_config

    monkeypatch.setattr(
        network_config,
        "load_network_policy",
        lambda: SimpleNamespace(check_host=lambda url: None),
    )
    resp = await client.post(
        "/api/v1/web-access/sites/login",
        json={"url": "https://user:pass@kns.cnki.net/"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "url_userinfo_not_allowed"


async def test_start_login_returns_409_when_another_login_active(client, monkeypatch):
    from backend.tools import network_config

    monkeypatch.setattr(
        network_config,
        "load_network_policy",
        lambda: SimpleNamespace(check_host=lambda url: None),
    )

    class _BusyJobs:
        def start(self, url):
            raise ValueError("login_in_progress")

    monkeypatch.setattr(routes, "site_login_jobs", _BusyJobs())
    monkeypatch.setattr(routes, "_login_permission_decision", lambda url: _decision(True))
    resp = await client.post(
        "/api/v1/web-access/sites/login",
        json={"url": "https://kns.cnki.net/", "approved": True},
    )
    assert resp.status_code == 409


async def test_create_cookie_rejects_too_many_entries(client):
    cookies = [
        {"name": f"c{i}", "value": "v", "domain": ".example.com", "path": "/"}
        for i in range(501)
    ]
    resp = await client.post(
        "/api/v1/web-access/credentials/cookie",
        json={"domain": ".example.com", "cookies": cookies},
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "too_many_cookies"


async def test_start_login_enforces_network_policy(client, monkeypatch):
    from backend.tools import network_config

    monkeypatch.setattr(
        network_config,
        "load_network_policy",
        lambda: SimpleNamespace(check_host=lambda url: "offline 模式禁止出网"),
    )
    resp = await client.post(
        "/api/v1/web-access/sites/login", json={"url": "https://kns.cnki.net/"}
    )
    assert resp.status_code == 403


async def test_start_login_returns_job_id_and_job_can_be_polled(client, monkeypatch):
    from backend.tools import network_config

    monkeypatch.setattr(
        network_config,
        "load_network_policy",
        lambda: SimpleNamespace(check_host=lambda url: None),
    )
    fake_jobs = _FakeJobs()
    monkeypatch.setattr(routes, "site_login_jobs", fake_jobs)
    monkeypatch.setattr(
        routes,
        "_login_permission_decision",
        lambda url: _decision(False, needs_approval=True, reason="requires approval"),
    )

    resp = await client.post(
        "/api/v1/web-access/sites/login",
        json={"url": "https://kns.cnki.net/", "approved": True},
    )
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "j-1"

    job = await client.get("/api/v1/web-access/sites/login/j-1")
    assert job.status_code == 200
    assert job.json()["status"] == "running"
    assert job.json()["url"] == "https://kns.cnki.net/"

    missing = await client.get("/api/v1/web-access/sites/login/unknown")
    assert missing.status_code == 404


async def test_start_login_requires_explicit_approval(client, monkeypatch):
    from backend.tools import network_config

    monkeypatch.setattr(
        network_config,
        "load_network_policy",
        lambda: SimpleNamespace(check_host=lambda url: None),
    )
    monkeypatch.setattr(
        routes,
        "_login_permission_decision",
        lambda url: _decision(False, needs_approval=True, reason="requires approval"),
    )
    monkeypatch.setattr(
        routes,
        "site_login_jobs",
        SimpleNamespace(start=lambda url: (_ for _ in ()).throw(AssertionError("must not start"))),
    )
    resp = await client.post(
        "/api/v1/web-access/sites/login", json={"url": "https://kns.cnki.net/"}
    )
    assert resp.status_code == 202
    assert resp.json()["approval_required"] is True


async def test_start_login_denied_in_read_only_mode(client, monkeypatch):
    from backend.tools import network_config

    monkeypatch.setattr(
        network_config,
        "load_network_policy",
        lambda: SimpleNamespace(check_host=lambda url: None),
    )
    monkeypatch.setattr(
        routes,
        "_login_permission_decision",
        lambda url: _decision(False, needs_approval=False, reason="discuss mode is read-only"),
    )
    resp = await client.post(
        "/api/v1/web-access/sites/login",
        json={"url": "https://kns.cnki.net/", "approved": True},
    )
    assert resp.status_code == 403
    assert "permission_denied" in resp.json()["error"]


async def test_start_login_auto_mode_starts_without_approval(client, monkeypatch):
    from backend.tools import network_config

    monkeypatch.setattr(
        network_config,
        "load_network_policy",
        lambda: SimpleNamespace(check_host=lambda url: None),
    )
    monkeypatch.setattr(routes, "_login_permission_decision", lambda url: _decision(True))
    monkeypatch.setattr(routes, "site_login_jobs", _FakeJobs())
    resp = await client.post(
        "/api/v1/web-access/sites/login", json={"url": "https://kns.cnki.net/"}
    )
    assert resp.status_code == 200


async def test_sites_origin_guard(client):
    resp = await client.get(
        "/api/v1/web-access/sites", headers={"Origin": "https://evil.example"}
    )
    assert resp.status_code == 403


def test_login_permission_decision_uses_enforcer(monkeypatch):
    calls = []

    class _Enforcer:
        def check(self, tool_name, args):
            calls.append((tool_name, args))
            return _decision(True)

    monkeypatch.setattr(
        "backend.tools.permissions.load_enforcer_from_settings",
        lambda *a, **kw: _Enforcer(),
    )
    decision = routes._login_permission_decision("https://kns.cnki.net/")
    assert decision.allowed is True
    assert calls == [("browser_login", {"url": "https://kns.cnki.net/"})]


def test_login_permission_denies_in_read_only_mode(monkeypatch):
    from backend.tools.permissions import PermissionEnforcer, PermissionMode

    monkeypatch.setattr(
        "backend.tools.permissions.load_enforcer_from_settings",
        lambda *a, **kw: PermissionEnforcer(mode=PermissionMode.READ_ONLY, rules=[]),
    )
    decision = routes._login_permission_decision("https://kns.cnki.net/")
    assert decision.allowed is False
    assert decision.needs_approval is False


def test_login_permission_asks_in_prompt_mode(monkeypatch):
    from backend.tools.permissions import PermissionEnforcer, PermissionMode

    monkeypatch.setattr(
        "backend.tools.permissions.load_enforcer_from_settings",
        lambda *a, **kw: PermissionEnforcer(mode=PermissionMode.PROMPT, rules=[]),
    )
    decision = routes._login_permission_decision("https://kns.cnki.net/")
    assert decision.allowed is False
    assert decision.needs_approval is True


async def test_verify_site_not_found(client, monkeypatch):
    monkeypatch.setattr(routes, "list_credentials", lambda: [])
    resp = await client.post("/api/v1/web-access/sites/verify", json={"domain": ".cnki.net"})
    assert resp.status_code == 404


async def test_verify_site_logged_in(client, monkeypatch):
    monkeypatch.setattr(routes, "list_credentials", lambda: [_record()])
    from backend.tools import web_render

    monkeypatch.setattr(
        web_render,
        "render_page",
        lambda *a, **kw: {"login_wall": False, "content": "欢迎回来 退出登录"},
    )
    resp = await client.post("/api/v1/web-access/sites/verify", json={"domain": ".cnki.net"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "logged_in"
    assert body["domain"] == ".cnki.net"
    assert body["url"].startswith("https://")
    assert isinstance(body["checked_at"], int)


async def test_verify_site_login_required(client, monkeypatch):
    monkeypatch.setattr(routes, "list_credentials", lambda: [_record()])
    from backend.tools import web_render

    monkeypatch.setattr(
        web_render,
        "render_page",
        lambda *a, **kw: {"login_wall": False, "content": "请登录后查看全文"},
    )
    resp = await client.post("/api/v1/web-access/sites/verify", json={"domain": ".cnki.net"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "login_required"


async def test_verify_site_render_error_is_unknown(client, monkeypatch):
    monkeypatch.setattr(routes, "list_credentials", lambda: [_record()])
    from backend.tools import web_render

    def _boom(*a, **kw):
        raise web_render.RenderError("browser missing")

    monkeypatch.setattr(web_render, "render_page", _boom)
    resp = await client.post("/api/v1/web-access/sites/verify", json={"domain": ".cnki.net"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unknown"
    assert "browser missing" in body["error"]


async def test_verify_site_rejects_header_credential(client, monkeypatch):
    monkeypatch.setattr(routes, "list_credentials", lambda: [_record(kind="header")])
    resp = await client.post("/api/v1/web-access/sites/verify", json={"domain": ".cnki.net"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "unsupported_credential_kind"
