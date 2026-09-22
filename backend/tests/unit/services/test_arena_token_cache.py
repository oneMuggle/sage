"""P3 token window：cache 语义 + /token-window/* 路由合同。

覆盖 plan §5.9/§5.10 的验收前置：
- push 形状门控（400）与子开关门控（403）；
- state 永不 403（窗口要能拿到 enabled=false 才能优雅停）；
- get 的条件变量等待（draw 线程阻塞 → push 唤醒）与 needed 标记；
- max_age 过期拒绝；request_proxy_change 的 relay 映射（凭据不达 Chromium）。
"""

import threading
import time as _time

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import arena_routes
from backend.api.arena_routes import init_arena_service, router, shutdown_arena_service
from backend.config.arena_automation import ArenaAutomationConfig
from backend.services import arena_token_cache as atc
from backend.services.arena_token_cache import get_token_window_cache


def _token(n: int = 600) -> str:
    return "t" * n


def _config(max_age_sec: float = 110.0, poll_interval_sec: float = 2.0):
    config = ArenaAutomationConfig(enabled=True)
    config.token_window.enabled = True
    config.token_window.max_age_sec = max_age_sec
    config.token_window.poll_interval_sec = poll_interval_sec
    return config


@pytest.fixture()
def client(tmp_path):
    atc.reset_token_window_cache_for_tests()
    throwaway = init_arena_service(
        db_path=str(tmp_path / "unused.sqlite"),
        encryption_key=Fernet.generate_key(),
        config=_config(),
    )
    throwaway.close()
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    shutdown_arena_service()
    atc.reset_token_window_cache_for_tests()


# ── cache 单元语义 ────────────────────────────────────────────────────


def test_push_ok_and_refresh_age(client):
    cache = get_token_window_cache(arena_routes._config)
    first = cache.push(_token(), exit_ip="1.2.3.4", ua="ua-x")
    assert first == {"ok": True, "age_sec": 0}
    _time.sleep(0.02)
    second = cache.push(_token())
    assert second["ok"] is True
    assert second["age_sec"] >= 0.0
    health = cache.health()
    assert health["ready"] is True
    assert health["count"] == 2
    assert health["exit_ip"] == "1.2.3.4"
    assert health["ua"] == "ua-x"


def test_push_shape_gate(client):
    cache = get_token_window_cache(arena_routes._config)
    for bad in ("", "x" * 49, "x" * 20001):
        with pytest.raises(atc.ArenaTokenWindowError):
            cache.push(bad)
    # 边界值恰好可用
    assert cache.push("x" * 50)["ok"] is True
    assert cache.push("x" * 20000)["ok"] is True


def test_get_waits_and_wakes_on_push(client):
    cache = get_token_window_cache(arena_routes._config)

    def push_later():
        _time.sleep(0.2)
        cache.push(_token(), exit_ip="9.9.9.9")

    threading.Thread(target=push_later, daemon=True).start()
    got = cache.get(wait_sec=3.0)
    assert got is not None
    assert got["token"] == _token()
    assert got["exit_ip"] == "9.9.9.9"
    # push 之后 needed 必须被清掉
    assert cache.state(enabled=True)["needed"] is False


def test_get_timeout_raises_needed(client):
    cache = get_token_window_cache(arena_routes._config)
    got = cache.get(wait_sec=0.3)
    assert got is None
    # 等待期间 needed 被置位 → 窗口应立即补铸
    assert cache.state(enabled=True)["needed"] is True


def test_get_rejects_stale_token(client):
    # max_age 极小：push 后立刻过期
    atc.reset_token_window_cache_for_tests()
    cache = atc.TokenWindowCache(max_age_sec=0.05)
    cache.push(_token())
    _time.sleep(0.1)
    assert cache.get(wait_sec=0.1) is None
    assert cache.health()["ready"] is False


def test_mark_rejected_counts(client):
    cache = get_token_window_cache(arena_routes._config)
    cache.mark_rejected("recaptcha denied")
    cache.mark_rejected()
    state = cache.state(enabled=True)
    assert state["reject_count"] == 2
    assert cache.health()["error"] == "recaptcha denied"


def test_request_proxy_change_maps_relay(client, monkeypatch):
    mapped_backing = {"calls": []}

    def fake_local_proxy(upstream):
        mapped_backing["calls"].append(upstream)
        return "http://127.0.0.1:39999"

    monkeypatch.setattr(
        "backend.services.arena_proxy_relay.local_proxy", fake_local_proxy
    )
    cache = get_token_window_cache(arena_routes._config)
    cache.request_proxy_change("http://user:pass@1.2.3.4:8080")
    state = cache.state(enabled=True)
    assert state["want_proxy"] is True
    # 窗口只见本地 relay 地址，上游凭据绝不出现
    assert state["proxy_url"] == "http://127.0.0.1:39999"
    assert mapped_backing["calls"] == ["http://user:pass@1.2.3.4:8080"]
    # 空 URL = 回直连
    cache.request_proxy_change("")
    state = cache.state(enabled=True)
    assert state["want_proxy"] is False
    assert state["proxy_url"] == ""


def test_singleton_built_from_config_and_reset(client):
    atc.reset_token_window_cache_for_tests()
    a = get_token_window_cache(_config(poll_interval_sec=3.5))
    b = get_token_window_cache()
    assert a is b
    assert a.state(enabled=True)["poll_interval_sec"] == 3.5
    atc.reset_token_window_cache_for_tests()
    c = get_token_window_cache(_config(poll_interval_sec=1.5))
    assert c is not a
    assert c.state(enabled=True)["poll_interval_sec"] == 1.5


# ── 路由合同 ──────────────────────────────────────────────────────────


def test_api_push_round_trip(client):
    resp = client.post(
        "/api/v1/arena/token-window/push",
        json={"token": _token(), "exit_ip": "5.6.7.8", "ua": "Mozilla/5.0"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    health = client.get("/api/v1/arena/token-window/health").json()
    assert health["ready"] is True
    assert health["exit_ip"] == "5.6.7.8"
    assert health["ua"] == "Mozilla/5.0"


def test_api_push_bad_shape_400(client):
    resp = client.post("/api/v1/arena/token-window/push", json={"token": "short"})
    assert resp.status_code == 400


def test_api_push_gated_403(client):
    arena_routes._config.token_window.enabled = False
    try:
        resp = client.post("/api/v1/arena/token-window/push", json={"token": _token()})
        assert resp.status_code == 403
    finally:
        arena_routes._config.token_window.enabled = True
    # 主开关关掉同样 403
    arena_routes._config.enabled = False
    try:
        resp = client.post("/api/v1/arena/token-window/push", json={"token": _token()})
        assert resp.status_code == 403
        # 但 state/health 不 403——窗口靠它优雅停
        state = client.get("/api/v1/arena/token-window/state")
        assert state.status_code == 200
        assert state.json()["enabled"] is False
        health = client.get("/api/v1/arena/token-window/health")
        assert health.status_code == 200
        assert health.json()["ready"] is False
    finally:
        arena_routes._config.enabled = True


def test_api_state_reports_needed_and_poll_interval(client):
    cache = get_token_window_cache(arena_routes._config)
    cache.mark_needed()
    state = client.get("/api/v1/arena/token-window/state").json()
    assert state == {
        "enabled": True,
        "needed": True,
        "reject_count": 0,
        "want_proxy": False,
        "proxy_url": "",
        "poll_interval_sec": 2.0,
    }
    # push 清 needed
    client.post("/api/v1/arena/token-window/push", json={"token": _token()})
    assert client.get("/api/v1/arena/token-window/state").json()["needed"] is False


def test_api_state_uninitialized_defaults():
    # 未 init（_config=None）也不 403、不 500
    arena_routes._config = None
    try:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as bare:
            state = bare.get("/api/v1/arena/token-window/state")
            assert state.status_code == 200
            assert state.json()["enabled"] is False
            health = bare.get("/api/v1/arena/token-window/health")
            assert health.status_code == 200
            assert health.json()["ready"] is False
    finally:
        arena_routes._config = None
