import contextlib
import os
import tempfile

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.arena_routes import init_arena_service, router
from backend.config.arena_automation import ArenaAutomationConfig


@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    key = Fernet.generate_key()
    cfg = ArenaAutomationConfig(enabled=True)
    service = init_arena_service(db_path=path, encryption_key=key, config=cfg)
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    service.close()  # Windows：连接未关闭时 unlink 报 WinError 32
    with contextlib.suppress(PermissionError):
        os.unlink(path)


@pytest.fixture()
def disabled_client():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    key = Fernet.generate_key()
    cfg = ArenaAutomationConfig(enabled=False)
    service = init_arena_service(db_path=path, encryption_key=key, config=cfg)
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    service.close()  # Windows：连接未关闭时 unlink 报 WinError 32
    with contextlib.suppress(PermissionError):
        os.unlink(path)


def test_create_and_list_accounts(client):
    r = client.post(
        "/api/v1/arena/accounts",
        json={"email": "x@example.com", "password": "p"},
    )
    assert r.status_code == 201
    acc = r.json()
    assert acc["email"] == "x@example.com"
    # List
    r2 = client.get("/api/v1/arena/accounts")
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_get_account_returns_decrypted(client):
    r = client.post(
        "/api/v1/arena/accounts",
        json={"email": "y@example.com", "password": "secret"},
    )
    acc_id = r.json()["id"]
    r2 = client.get(f"/api/v1/arena/accounts/{acc_id}")
    assert r2.status_code == 200
    # password is stripped from API responses (VULN-01 fix)
    assert "password" not in r2.json()
    assert r2.json()["email"] == "y@example.com"


def test_soft_delete_account(client):
    r = client.post(
        "/api/v1/arena/accounts",
        json={"email": "z@example.com", "password": "p"},
    )
    acc_id = r.json()["id"]
    r2 = client.delete(f"/api/v1/arena/accounts/{acc_id}")
    assert r2.status_code == 204
    r3 = client.get(f"/api/v1/arena/accounts/{acc_id}")
    assert r3.json()["state"] == "destroyed"


def test_endpoints_return_403_when_disabled(disabled_client):
    r = disabled_client.post(
        "/api/v1/arena/accounts",
        json={"email": "x@example.com", "password": "p"},
    )
    assert r.status_code == 403
    r2 = disabled_client.get("/api/v1/arena/accounts")
    assert r2.status_code == 403


def test_enable_account_resets_state(client):
    r = client.post(
        "/api/v1/arena/accounts",
        json={"email": "e@example.com", "password": "p"},
    )
    acc_id = r.json()["id"]
    # Disable via isolate
    client.post(f"/api/v1/arena/accounts/{acc_id}/isolate")
    r2 = client.post(f"/api/v1/arena/accounts/{acc_id}/enable")
    assert r2.status_code == 200
    r3 = client.get(f"/api/v1/arena/accounts/{acc_id}")
    assert r3.json()["state"] == "available"


def test_get_service_raises_503_when_uninitialized():
    """Line 58: get_service() raises 503 if init_arena_service was never called."""
    import backend.api.arena_routes as routes_mod

    old_svc = routes_mod._service
    try:
        routes_mod._service = None
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as excinfo:
            routes_mod.get_service()
        assert excinfo.value.status_code == 503
    finally:
        routes_mod._service = old_svc


def test_max_accounts_returns_409():
    """Line 74: creating account beyond max_accounts limit returns 409."""
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    key = Fernet.generate_key()
    cfg = ArenaAutomationConfig(enabled=True, max_accounts=1)
    service = init_arena_service(db_path=path, encryption_key=key, config=cfg)
    app = FastAPI()
    app.include_router(router)
    tc = TestClient(app)
    try:
        r1 = tc.post(
            "/api/v1/arena/accounts",
            json={"email": "first@example.com", "password": "p"},
        )
        assert r1.status_code == 201
        r2 = tc.post(
            "/api/v1/arena/accounts",
            json={"email": "second@example.com", "password": "p"},
        )
        assert r2.status_code == 409
    finally:
        service.close()  # Windows：连接未关闭时 unlink 报 WinError 32
        with contextlib.suppress(PermissionError):
            os.unlink(path)


def test_duplicate_email_returns_409(client):
    """Lines 80-81: duplicate email raises HTTPException 409."""
    client.post(
        "/api/v1/arena/accounts",
        json={"email": "dup@example.com", "password": "p"},
    )
    r = client.post(
        "/api/v1/arena/accounts",
        json={"email": "dup@example.com", "password": "p2"},
    )
    assert r.status_code == 409


def test_list_accounts_with_state_filter(client):
    """Lines 91-95: valid state filter returns filtered list."""
    client.post(
        "/api/v1/arena/accounts",
        json={"email": "s1@example.com", "password": "p"},
    )
    r = client.get("/api/v1/arena/accounts?state=available")
    assert r.status_code == 200
    # Invalid state returns 400
    r2 = client.get("/api/v1/arena/accounts?state=garbage")
    assert r2.status_code == 400


def test_get_nonexistent_account_returns_404(client):
    """Line 107: get_account returns 404 when id doesn't exist."""
    r = client.get("/api/v1/arena/accounts/nonexistent-id")
    assert r.status_code == 404


def test_delete_nonexistent_account_returns_404(client):
    """Line 118: soft_delete returns 404 when id doesn't exist."""
    r = client.delete("/api/v1/arena/accounts/nonexistent-id")
    assert r.status_code == 404


def test_isolate_nonexistent_account_returns_404(client):
    """Line 130: isolate returns 404 when id doesn't exist."""
    r = client.post("/api/v1/arena/accounts/nonexistent-id/isolate")
    assert r.status_code == 404


def test_enable_nonexistent_account_returns_404(client):
    """Line 145: enable returns 404 when id doesn't exist."""
    r = client.post("/api/v1/arena/accounts/nonexistent-id/enable")
    assert r.status_code == 404


def test_get_stats_endpoint(client):
    """Lines 155-159: stats endpoint returns state and failure count."""
    r1 = client.post(
        "/api/v1/arena/accounts",
        json={"email": "stats@example.com", "password": "p"},
    )
    acc_id = r1.json()["id"]
    r = client.get(f"/api/v1/arena/accounts/{acc_id}/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == acc_id
    assert body["state"] == "available"
    assert "failure_count" in body
    # nonexistent account returns 404
    r2 = client.get("/api/v1/arena/accounts/nonexistent-id/stats")
    assert r2.status_code == 404


def test_api_responses_never_leak_password(client):
    """VULN-01 regression: password must be stripped from every endpoint."""
    r1 = client.post(
        "/api/v1/arena/accounts",
        json={"email": "leak@example.com", "password": "sekret"},
    )
    assert "password" not in r1.json()
    acc_id = r1.json()["id"]
    # list
    r2 = client.get("/api/v1/arena/accounts")
    assert all("password" not in a for a in r2.json())
    # get
    r3 = client.get(f"/api/v1/arena/accounts/{acc_id}")
    assert "password" not in r3.json()
    # isolate
    r4 = client.post(f"/api/v1/arena/accounts/{acc_id}/isolate")
    assert "password" not in r4.json()
    # enable
    r5 = client.post(f"/api/v1/arena/accounts/{acc_id}/enable")
    assert "password" not in r5.json()


# ---------------------------------------------------------------------------
# 注册辅助端点（单账号 · 人工验证码）
# ---------------------------------------------------------------------------

class FakeRegistrationService:
    """记录调用并按脚本抛错的假注册服务。

    注意状态载荷叫 ``payload`` —— 不能叫 ``status``，否则实例属性会遮蔽
    ``status()`` 方法导致路由调用 ``reg.status()`` 时 TypeError。
    """

    def __init__(self):
        self.started = 0
        self.cancelled = 0
        self.password_calls: list = []
        self.opened = False
        self.payload = {
            "registration_id": "reg1",
            "email": "tmp@fake.example",
            "state": "awaiting_signup",
            "captcha_present": True,
            "verification_link": "",
            "email_filled": True,
            "error": "",
            "created_at": "2026-09-19T00:00:00",
            "expires_in_sec": 1800,
            "manual_hint": "hint",
        }

    def start(self):
        self.started += 1
        return self.payload

    def status(self):
        if self.started == 0:
            from backend.services.arena_registration import RegistrationNotFoundError

            raise RegistrationNotFoundError("没有进行中的注册")
        return self.payload

    def open_verification(self):
        if not self.opened:
            from backend.services.arena_registration import RegistrationError

            raise RegistrationError("打开验证链接失败: boom")
        return self.payload

    def set_password(self, password, manual=False):
        self.password_calls.append((password, manual))
        if password == "weak":
            raise ValueError("密码不满足要求：至少 8 位")
        if password == "boom":
            from backend.services.arena_registration import RegistrationError

            raise RegistrationError("入池失败")
        return {"id": "acc-new", "email": self.payload["email"]}

    def cancel(self):
        self.cancelled += 1
        if self.cancelled > 1:
            from backend.services.arena_registration import RegistrationNotFoundError

            raise RegistrationNotFoundError("没有可取消的注册")
        return {"registration_id": "reg1", "state": "cancelled"}


@pytest.fixture()
def reg_client(client):
    from backend.api import arena_routes
    from backend.config.arena_automation import ArenaAutomationConfig

    fake = FakeRegistrationService()
    arena_routes.init_registration_service(
        ArenaAutomationConfig(enabled=True), service=fake
    )
    yield fake
    arena_routes._registration = None


def test_register_start_returns_201(client, reg_client):
    r = client.post("/api/v1/arena/register/start")
    assert r.status_code == 201
    assert r.json()["state"] == "awaiting_signup"
    assert r.json()["captcha_present"] is True


def test_register_start_conflict_maps_409(client, reg_client):
    from backend.services.arena_registration import RegistrationConflictError

    def conflict():
        raise RegistrationConflictError("已有进行中的注册")

    reg_client.start = conflict
    r = client.post("/api/v1/arena/register/start")
    assert r.status_code == 409


def test_register_status_404_when_none(client, reg_client):
    reg_client.started = 0
    r = client.get("/api/v1/arena/register/current")
    assert r.status_code == 404


def test_register_open_verify_error_maps_502(client, reg_client):
    r = client.post("/api/v1/arena/register/current/open-verify")
    assert r.status_code == 502


def test_register_password_weak_maps_400(client, reg_client):
    r = client.post(
        "/api/v1/arena/register/current/password", json={"password": "weak"}
    )
    assert r.status_code == 400
    assert "密码" in r.json()["detail"]


def test_register_password_ok_and_manual_flag(client, reg_client):
    r = client.post(
        "/api/v1/arena/register/current/password",
        json={"password": "Str0ng!Pass", "manual": True},
    )
    assert r.status_code == 200
    assert reg_client.password_calls == [("Str0ng!Pass", True)]


def test_register_cancel(client, reg_client):
    r = client.post("/api/v1/arena/register/current/cancel")
    assert r.status_code == 200
    assert r.json()["state"] == "cancelled"
    # 第二次取消 → 404
    r2 = client.post("/api/v1/arena/register/current/cancel")
    assert r2.status_code == 404


def test_register_endpoints_403_when_disabled(disabled_client):
    from backend.api import arena_routes
    from backend.config.arena_automation import ArenaAutomationConfig

    arena_routes.init_registration_service(
        ArenaAutomationConfig(enabled=False), service=FakeRegistrationService()
    )
    try:
        r = disabled_client.post("/api/v1/arena/register/start")
        assert r.status_code == 403
        r2 = disabled_client.get("/api/v1/arena/observations")
        assert r2.status_code == 403
    finally:
        arena_routes._registration = None


# ---------------------------------------------------------------------------
# 观测端点
# ---------------------------------------------------------------------------

class FakePump:
    instances: list = []

    def __init__(self, *_a, **_k):
        type(self).instances.append(self)

    def start(self):
        pass

    def stop(self):
        pass


class FakeBrowserManager:
    def __init__(self, session):
        self._session = session

    def require(self, browser_id=None):
        from backend.tools.browser_cdp import BrowserCDPError

        if browser_id not in (None, self._session.browser_id):
            raise BrowserCDPError(f"未知 browser_id: {browser_id}")
        return self._session


def _attach_with_fakes(monkeypatch):
    from types import SimpleNamespace

    from backend.tools import browser_cdp

    session = SimpleNamespace(browser_id="b-test", port=0, ws_path="/devtools/x")
    monkeypatch.setattr(browser_cdp, "get_browser_manager", lambda: FakeBrowserManager(session))
    FakePump.instances.clear()
    monkeypatch.setattr(browser_cdp, "CdpEventPump", FakePump)
    return session


def test_observations_attach_list_detach(client, monkeypatch):
    _attach_with_fakes(monkeypatch)
    r = client.post("/api/v1/arena/observations/attach", json={"browser_id": None})
    assert r.status_code == 200
    assert r.json() == {"attached": True, "browser_id": "b-test"}
    # 列表：attached + 空判定
    r2 = client.get("/api/v1/arena/observations")
    assert r2.status_code == 200
    body = r2.json()
    assert body["attached"] is True
    assert body["verdicts"] == []
    # 未知 browser_id → 400
    r3 = client.post("/api/v1/arena/observations/attach", json={"browser_id": "nope"})
    assert r3.status_code == 400
    # 卸载
    r4 = client.post("/api/v1/arena/observations/detach")
    assert r4.status_code == 200
    assert r4.json() == {"attached": False}
    r5 = client.get("/api/v1/arena/observations")
    assert r5.json()["attached"] is False


def test_observations_503_when_not_initialized(client):
    from backend.api import arena_routes

    saved = arena_routes._observation
    arena_routes._observation = None
    try:
        r = client.get("/api/v1/arena/observations")
        assert r.status_code == 200
        assert r.json() == {"attached": False, "verdicts": []}
    finally:
        arena_routes._observation = saved
