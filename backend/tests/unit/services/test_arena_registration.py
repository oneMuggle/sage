"""Tests for the registration job orchestration + API (plan §5.8/§5.10).

The protocol layer is fully faked (``register_fn`` seam); these tests cover
the job machinery: clamping, stop, bookkeeping, events, export, and the
route gating/lifecycle.
"""

import contextlib
import os
import tempfile
import time as _time

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import arena_routes
from backend.api.arena_routes import init_arena_service, router, shutdown_arena_service
from backend.config.arena_automation import ArenaAutomationConfig
from backend.services import arena_registration as ar
from backend.services.arena_accounts import ArenaAccountService
from backend.services.arena_protocol import RegisterResult


class FlakyRegister:
    """async register_one stand-in: ok / fail / slow, in configurable order."""

    def __init__(self, outcomes=("ok", "ok", "ok"), delay=0.0):
        self.outcomes = list(outcomes)
        self.delay = delay
        self.calls = 0

    async def __call__(self, mail_provider, session_factory=None, log=None,
                       cancel=None, mail_timeout=90, domain=None):
        self.calls += 1
        if self.delay:
            for _ in range(int(self.delay / 0.05)):
                if cancel and cancel():
                    return RegisterResult(ok=False, error="cancelled")
                _time.sleep(0.05)
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"
        if outcome == "ok":
            return RegisterResult(
                email=f"user{self.calls:02d}@dbwot.com",
                password="Passw0rd!xy",
                user_id=f"uid-{self.calls}",
                credits="15000",
                ok=True,
            )
        return RegisterResult(ok=False, error="ArenaProtocolError: boom")


@pytest.fixture()
def svc(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    service = ArenaAccountService(db_path=path, encryption_key=Fernet.generate_key())
    yield service
    service.close()
    with contextlib.suppress(PermissionError):
        os.unlink(path)


@pytest.fixture()
def store():
    job_store = ar.JobStore()
    ar._reset_store_for_tests()
    yield job_store
    ar._reset_store_for_tests()


def _config(max_accounts=5, concurrency=2):
    config = ArenaAutomationConfig(enabled=True, max_accounts=max_accounts)
    config.registration.enabled = True
    config.registration.concurrency = concurrency
    config.registration.mail_timeout_sec = 5
    config.proxy.enabled = True
    return config


def _wait_done(job_store, job_id, timeout=15.0):
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        job = job_store.get(job_id)
        if job is not None and job.status in ("done", "failed", "stopped"):
            return job
        _time.sleep(0.05)
    raise AssertionError("job did not finish in time")


def test_job_registers_accounts_and_writes_pool(svc, store):
    config = _config()
    fake = FlakyRegister(outcomes=("ok", "fail", "ok"))
    job_id = ar.start_job(
        count=3, concurrency=2, accounts_service=svc, config=config,
        register_fn=fake, job_store=store,
    )
    job = _wait_done(store, job_id)
    assert job.status == "done"
    assert job.ok == 2 and job.failed == 1 and job.total == 3

    accounts = svc.list_accounts()
    assert len(accounts) == 2
    by_email = {a["email"]: a for a in accounts}
    assert by_email["user01@dbwot.com"]["credits"] == 15000
    assert by_email["user01@dbwot.com"]["user_id"] == "uid-1"
    assert by_email["user01@dbwot.com"]["source"] == "registered"

    kinds = [e.kind for e in store.events_after(job_id)]
    assert "register_result" in kinds
    assert "progress" in kinds and "done" in kinds
    # events never carry the password
    for event in store.events_after(job_id):
        assert "Passw0rd!xy" not in str(event.data) and "Passw0rd!xy" not in event.message


def test_job_results_carry_plaintext_for_explicit_endpoints(svc, store):
    config = _config()
    fake = FlakyRegister(outcomes=("ok",))
    job_id = ar.start_job(
        count=1, concurrency=1, accounts_service=svc, config=config,
        register_fn=fake, job_store=store,
    )
    _wait_done(store, job_id)
    job = store.get(job_id)
    assert job.results[0]["password"] == "Passw0rd!xy"
    assert job.results[0]["account_id"]


def test_job_stop_midway(svc, store):
    config = _config()
    fake = FlakyRegister(outcomes=["ok"] * 10, delay=0.4)
    job_id = ar.start_job(
        count=5, concurrency=1, accounts_service=svc, config=config,
        register_fn=fake, job_store=store,
    )
    # wait for the first account to land, then stop
    deadline = _time.monotonic() + 10
    while _time.monotonic() < deadline:
        if store.get(job_id).results:
            break
        _time.sleep(0.05)
    store.request_stop(job_id)
    job = _wait_done(store, job_id)
    assert job.status == "stopped"
    assert job.ok < 5


def test_job_clamps_to_max_accounts(svc, store):
    config = _config(max_accounts=3)
    fake = FlakyRegister(outcomes=["ok"] * 5)
    job_id = ar.start_job(
        count=5, concurrency=2, accounts_service=svc, config=config,
        register_fn=fake, job_store=store,
    )
    job = _wait_done(store, job_id)
    assert job.total == 3
    assert job.params["clamped_by_max_accounts"] is True
    assert svc.count_accounts() == 3


def test_job_refuses_when_pool_full(svc, store):
    config = _config(max_accounts=2)
    for i in range(2):
        svc.create_account(email=f"fill{i}@x.example", password="p")
    with pytest.raises(ValueError, match="max_accounts"):
        ar.start_job(
            count=1, concurrency=1, accounts_service=svc, config=config,
            register_fn=FlakyRegister(), job_store=store,
        )


def test_export_accounts_format(svc, store, tmp_path):
    config = _config()
    fake = FlakyRegister(outcomes=("ok", "ok"))
    job_id = ar.start_job(
        count=2, concurrency=1, accounts_service=svc, config=config,
        register_fn=fake, job_store=store,
    )
    _wait_done(store, job_id)
    path = ar.export_accounts(job_id, tmp_path, job_store=store)
    text = path.read_text(encoding="utf-8")
    lines = text.strip().split("\n")
    assert len(lines) == 2
    assert lines[0].startswith("user01@dbwot.com----Passw0rd!xy----15000")
    assert path.parent == tmp_path
    assert path.name.startswith("accounts_")


def test_export_rejects_unknown_or_empty(store, tmp_path):
    with pytest.raises(ValueError, match="unknown job"):
        ar.export_accounts("nope", tmp_path, job_store=store)
    job = store.create("registration", total=1)
    with pytest.raises(ValueError, match="no successful registrations"):
        ar.export_accounts(job.id, tmp_path, job_store=store)


# ── P2：代理模式 ───────────────────────────────────────────────────────

class StubProxyProvider:
    """Deterministic provider: hands out fixed URLs, records exclusions."""

    def __init__(self, urls):
        self.urls = list(urls)
        self.calls = 0
        self.seen_exclusions = []

    def acquire(self, exclude_sids=None):
        self.calls += 1
        self.seen_exclusions.append(set(exclude_sids or ()))
        url = self.urls[min(self.calls - 1, len(self.urls) - 1)]
        sid = ar.proxy_sid(url)
        if sid and sid in (exclude_sids or ()):
            raise ar.ArenaProxyError("exhausted")
        return url


def test_job_proxy_mode_binds_exit_and_keeps_mail_direct(svc, store):
    config = _config()
    fake = FlakyRegister(outcomes=("ok",))
    stub = StubProxyProvider(["http://cust-sid-Ab12Cd:pw@1.2.3.4:8080"])
    job_id = ar.start_job(
        count=1, concurrency=1, accounts_service=svc, config=config,
        register_fn=fake, job_store=store,
        proxy_provider=stub,
        exit_ip_probe=lambda url: "203.0.113.9",
    )
    job = _wait_done(store, job_id)
    assert job.status == "done" and job.ok == 1

    account = svc.list_accounts()[0]
    assert account["proxy_url"] == "http://cust-sid-Ab12Cd:pw@1.2.3.4:8080"
    assert account["proxy_sid"] == "Ab12Cd"
    assert account["exit_ip"] == "203.0.113.9"

    events = store.events_after(job_id)
    messages = " | ".join(e.message for e in events)
    assert "邮箱流量恒直连" in messages
    assert "arena 走代理" in messages or "arena 出口" in messages
    # credentials never appear in logs
    assert ":pw@" not in messages


def test_job_proxy_mode_excludes_bound_sids(svc, store):
    config = _config()
    svc.create_account(email="existing@x.example", password="p")
    # simulate an account already bound to sid Taken1
    existing = svc.list_accounts()[0]
    svc.update_binding(existing["id"], "http://u-sid-Taken1:pw@9.9.9.9:9", proxy_sid="Taken1")

    stub = StubProxyProvider(["http://u-sid-Free1:pw@1.1.1.1:1", "http://u-sid-Taken1:pw@2.2.2.2:2"])
    job_id = ar.start_job(
        count=1, concurrency=1, accounts_service=svc, config=config,
        register_fn=FlakyRegister(outcomes=("ok",)), job_store=store,
        proxy_provider=stub, exit_ip_probe=lambda url: "203.0.113.9",
    )
    _wait_done(store, job_id)
    assert stub.seen_exclusions and "Taken1" in stub.seen_exclusions[0]
    new_accounts = [a for a in svc.list_accounts() if a["email"] != "existing@x.example"]
    assert new_accounts[0]["proxy_sid"] == "Free1"


def test_job_proxy_mode_no_proxy_available(svc, store):
    from backend.services.arena_proxies import ArenaProxyError

    class Empty:
        def acquire(self, exclude_sids=None):
            raise ArenaProxyError("no proxy left")

    config = _config()
    job_id = ar.start_job(
        count=1, concurrency=1, accounts_service=svc, config=config,
        register_fn=FlakyRegister(outcomes=("ok",)), job_store=store,
        proxy_provider=Empty(),
    )
    job = _wait_done(store, job_id)
    assert job.status == "done" and job.ok == 0 and job.failed == 1
    assert svc.count_accounts() == 0
    messages = " | ".join(e.message for e in store.events_after(job_id))
    assert "无可用代理" in messages


# ── API 层 ─────────────────────────────────────────────────────────────

@pytest.fixture()
def client(svc, store, tmp_path):
    ar._reset_store_for_tests()
    config = _config()
    config.data_dir = str(tmp_path)
    throwaway = init_arena_service(
        db_path=str(tmp_path / "unused.sqlite"),
        encryption_key=Fernet.generate_key(),
        config=config,
    )
    # the route-level job store is the module singleton; swap the throwaway
    # service for the fixture's real pool service
    arena_routes._service = svc
    throwaway.close()
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    shutdown_arena_service()
    ar._reset_store_for_tests()


def test_api_registration_disabled_403(client):
    arena_routes._config.enabled = True
    arena_routes._config.registration.enabled = False
    try:
        response = client.post("/api/v1/arena/registration/jobs", json={"count": 2})
        assert response.status_code == 403
        assert "registration is disabled" in response.json()["detail"]
    finally:
        arena_routes._config.registration.enabled = True


def test_api_job_lifecycle_and_events(client, store, monkeypatch):
    fake = FlakyRegister(outcomes=("ok", "ok"))
    real_start = ar.start_job

    def start_with_store(**kwargs):
        kwargs["job_store"] = ar.get_job_store()
        kwargs["register_fn"] = fake
        kwargs["accounts_service"] = arena_routes._service
        kwargs["config"] = arena_routes._config
        return real_start(**kwargs)

    monkeypatch.setattr(ar, "start_job", start_with_store)

    response = client.post("/api/v1/arena/registration/jobs", json={"count": 2, "concurrency": 1})
    assert response.status_code == 202
    job_id = response.json()["id"]

    deadline = _time.monotonic() + 15
    while _time.monotonic() < deadline:
        if client.get(f"/api/v1/arena/registration/jobs/{job_id}").json()["status"] in (
            "done", "failed", "stopped"
        ):
            break
        _time.sleep(0.05)

    snapshot = client.get(f"/api/v1/arena/registration/jobs/{job_id}").json()
    assert snapshot["status"] == "done"
    assert snapshot["ok"] == 2

    results = client.get(f"/api/v1/arena/registration/jobs/{job_id}/results").json()
    assert len(results) == 2
    assert results[0]["password"] == "Passw0rd!xy"

    # NDJSON stream: full replay, then after_seq resume
    stream = client.get(f"/api/v1/arena/jobs/{job_id}/events")
    assert stream.status_code == 200
    lines = [ln for ln in stream.text.split("\n") if ln]
    import json as _json

    events = [_json.loads(ln) for ln in lines]
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)
    assert any(e["kind"] == "register_result" for e in events)

    resumed = client.get(f"/api/v1/arena/jobs/{job_id}/events?after_seq={seqs[0]}")
    resumed_events = [_json.loads(ln) for ln in resumed.text.split("\n") if ln]
    assert [e["seq"] for e in resumed_events] == seqs[1:]

    # export
    export = client.get(f"/api/v1/arena/registration/jobs/{job_id}/export")
    assert export.status_code == 200
    assert "accounts_" in export.headers.get("content-disposition", "")
    assert "user01@dbwot.com----Passw0rd!xy----15000" in export.text


def test_api_unknown_job_404(client):
    assert client.get("/api/v1/arena/registration/jobs/nope").status_code == 404
    assert client.post("/api/v1/arena/registration/jobs/nope/stop").status_code == 404
    assert client.get("/api/v1/arena/jobs/nope/events").status_code == 404
    assert client.get("/api/v1/arena/registration/jobs/nope/export").status_code == 404


def test_api_stop_unknown_and_real(client, store, monkeypatch):
    fake = FlakyRegister(outcomes=["ok"] * 10, delay=0.3)
    real_start = ar.start_job

    def start_with_store(**kwargs):
        kwargs.update(
            job_store=ar.get_job_store(), register_fn=fake,
            accounts_service=arena_routes._service, config=arena_routes._config,
        )
        return real_start(**kwargs)

    monkeypatch.setattr(ar, "start_job", start_with_store)
    job_id = client.post(
        "/api/v1/arena/registration/jobs", json={"count": 4, "concurrency": 1}
    ).json()["id"]
    response = client.post(f"/api/v1/arena/registration/jobs/{job_id}/stop")
    assert response.status_code == 200
    assert response.json()["status"] == "stopping"


# ── P2：/proxies/* API ────────────────────────────────────────────────

def test_api_proxy_endpoints_disabled_403(client):
    arena_routes._config.enabled = True
    arena_routes._config.proxy.enabled = False
    try:
        assert client.post(
            "/api/v1/arena/proxies/parse", json={"pool_text": "a:1"}
        ).status_code == 403
        assert client.post(
            "/api/v1/arena/proxies/test", json={"proxy_url": ""}
        ).status_code == 403
        assert client.post("/api/v1/arena/proxies/fetch", json={}).status_code == 403
        assert client.post(
            "/api/v1/arena/registration/jobs", json={"count": 1, "proxy_mode": "pool"}
        ).status_code == 403
    finally:
        arena_routes._config.proxy.enabled = True


def test_api_proxy_parse_masks_credentials(client):
    response = client.post(
        "/api/v1/arena/proxies/parse",
        json={"pool_text": "gw.example.com:8080:user:pw\ngarbage-line"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"] == ["http://user:***@gw.example.com:8080"]
    assert len(body["errors"]) == 1


def test_api_proxy_test_direct_and_proxied(client, monkeypatch):
    from backend.services import arena_proxies

    monkeypatch.setattr(arena_proxies, "direct_exit_ip", lambda timeout=12.0, transport=None: "198.51.100.9")
    monkeypatch.setattr(
        arena_proxies, "proxy_exit_ip",
        lambda url, timeout=12.0, transport=None: "203.0.113.7",
    )
    monkeypatch.setattr(arena_proxies, "proxy_alive", lambda url, timeout=8.0, transport=None: True)

    direct = client.post("/api/v1/arena/proxies/test", json={"proxy_url": ""})
    assert direct.json() == {"proxy_url": "", "exit_ip": "198.51.100.9", "alive": True}

    proxied = client.post(
        "/api/v1/arena/proxies/test", json={"proxy_url": "http://u:p@1.2.3.4:8080"}
    )
    assert proxied.json() == {
        "proxy_url": "http://u:***@1.2.3.4:8080",
        "exit_ip": "203.0.113.7",
        "alive": True,
    }


def test_api_proxy_fetch(client, monkeypatch):
    from backend.services import arena_proxies

    arena_routes._config.proxy.api_url = "https://proxy.example/api"
    arena_routes._config.proxy.api_token = "secret-token"
    monkeypatch.setattr(
        arena_proxies, "proxy_exit_ip", lambda url, timeout=12.0, transport=None: "203.0.113.8"
    )

    class FakeApi:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def fetch(self):
            return "http://9.9.9.9:3128"

    monkeypatch.setattr(arena_proxies, "ProxyApi", FakeApi)
    response = client.post(
        "/api/v1/arena/proxies/fetch", json={"country": "us", "protocol": "http"}
    )
    assert response.status_code == 200
    assert response.json() == {"proxy_url": "http://9.9.9.9:3128", "exit_ip": "203.0.113.8"}


def test_api_proxy_fetch_unconfigured(client):
    arena_routes._config.proxy.api_url = ""
    arena_routes._config.proxy.api_token = ""
    response = client.post("/api/v1/arena/proxies/fetch", json={})
    assert response.status_code == 400


def test_api_registration_proxy_mode_pool_requires_provider(client, monkeypatch):
    # proxy enabled but no pool/API configured → 400
    arena_routes._config.proxy.pool_text = ""
    arena_routes._config.proxy.api_url = ""
    arena_routes._config.proxy.api_token = ""
    response = client.post(
        "/api/v1/arena/registration/jobs", json={"count": 1, "proxy_mode": "pool"}
    )
    assert response.status_code == 400
    assert "not configured" in response.json()["detail"]

    # invalid mode → 400
    assert client.post(
        "/api/v1/arena/registration/jobs", json={"count": 1, "proxy_mode": "socks"}
    ).status_code == 400
