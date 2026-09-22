"""P4 draw engine：门闸/协议客户端/抽卡轮次/job 编排。

关键契约：
- read_run_token 帧修复：坏帧/无效 JWT 继续等，不结束轮次；
- token 消费语义：draw_once 用 consume=True 取票（V3 一次性）；
- 429 阶梯 + CF 挑战识别 + switch 语义原样继承参考实现；
- 未命中 miss_action（默认 archive，归档失败退删除）；
- 熔断：全局 reCAPTCHA 拒绝超阈值 → 冷却。
"""

import base64
import json
import threading
import time as _time
from typing import Any, Dict, List, Optional

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import arena_routes
from backend.api.arena_routes import init_arena_service, router, shutdown_arena_service
from backend.config.arena_automation import ArenaAutomationConfig
from backend.services import arena_draw_engine as de
from backend.services.arena_draw_engine import (
    GATE_LADDER,
    DrawClient,
    DrawError,
    Gate,
    RateLimited,
    draw_once,
    gate_key,
)


# ── helpers ────────────────────────────────────────────────────────────


def _b64(obj: Dict[str, Any]) -> str:
    raw = json.dumps(obj).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _run_token(run_id: str = "run_abc123", *, iss: str = "https://id.trigger.dev",
               aud: Optional[str] = "https://api.trigger.dev", pub: Any = True,
               exp: Optional[float] = None, scopes: Optional[List[str]] = None) -> str:
    claims: Dict[str, Any] = {
        "iss": iss,
        "pub": pub,
        "exp": exp if exp is not None else _time.time() + 600,
    }
    if aud is not None:
        claims["aud"] = aud
    if scopes is not None:
        claims["scopes"] = scopes
    else:
        claims["run"] = run_id
    return f"header.{_b64(claims)}.signature"


class FakeResponse:
    def __init__(self, status_code: int, text: str = "", payload: Any = None):
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else ({} if status_code == 200 else {"detail": "x"})

    def json(self):
        return self._payload


class FakeStream:
    def __init__(self, status_code: int, frames: List[str]):
        self.status_code = status_code
        self._frames = frames

    def iter_content(self, chunk_size: int = 4096):
        for frame in self._frames:
            yield frame.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    """Session stub: canned responses per (method, url-substring)."""

    def __init__(self, responses: Optional[List[Any]] = None, stream: Optional[FakeStream] = None):
        self.responses = list(responses or [])
        self.stream = stream
        self.calls: List[Dict[str, Any]] = []

    def request(self, method: str, url: str, **kw):
        self.calls.append({"method": method, "url": url, **kw})
        return self.responses.pop(0) if self.responses else FakeResponse(200, payload={"id": "sid-default"})

    def get(self, url: str, **kw):
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw):
        return self.request("POST", url, **kw)

    def close(self):
        pass

    def stream_get(self, url: str, **kw):
        self.calls.append({"method": "GET-stream", "url": url, **kw})
        return self.stream or FakeStream(200, [])


def _sse(payload: Dict[str, Any]) -> str:
    return "event: message\ndata: " + json.dumps(payload) + "\n\n"


def _frame_with_token(token: str, headers_form: str = "dict") -> str:
    headers = (
        {"public-access-token": token} if headers_form == "dict" else [["public-access-token", token]]
    )
    return _sse({"records": [{"headers": headers}]})


class FakeCache:
    """TokenWindowCache stub for draw_once.

    consume=True 消费后立刻“补铸”一枚新票（真实形态：窗口看到 needed
    就重新出票），除非 token=None（模拟窗口不可用）。
    """

    def __init__(self, token: Optional[str] = "T" * 600, remint: bool = True):
        self.token = token
        self.remint = remint
        self.rejected: List[str] = []
        self.get_calls: List[Dict[str, Any]] = []

    def get(self, max_age_sec=None, wait_sec=0.0, consume=False):
        self.get_calls.append({"max_age_sec": max_age_sec, "wait_sec": wait_sec, "consume": consume})
        if not self.token:
            return None
        snap = {"token": self.token, "exit_ip": "1.1.1.1", "ua": "ua", "age_sec": 0.1}
        if consume and self.remint:
            self.token = "U" * 600  # 窗口补铸
        elif consume:
            self.token = None
        return snap

    def mark_rejected(self, reason: str = "") -> None:
        self.rejected.append(reason)

    def request_proxy_change(self, proxy_url: str = "") -> None:
        self.proxy_changes = getattr(self, "proxy_changes", [])
        self.proxy_changes.append(proxy_url)


# ── Gate ───────────────────────────────────────────────────────────────


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_gate_ladder_escalates_and_resets():
    clock = FakeClock()
    gate = Gate(base_gap=0.0, clock=clock)
    key = "acct-a"
    gate.note_rate_limited(key)
    assert gate.gate_status(key)["level"] == 1
    assert gate.gate_status(key)["left"] == pytest.approx(GATE_LADDER[0], abs=0.01)
    clock.advance(20)
    gate.note_rate_limited(key)
    gate.note_rate_limited(key)
    st = gate.gate_status(key)
    assert st["level"] == 3
    assert st["gap"] == pytest.approx(min(60.0, 5.0 * 3), abs=0.01)
    gate.gate_reset(key)
    st = gate.gate_status(key)
    assert st["level"] == 0 and st["left"] == 0.0 and st["gap"] == 0.0


def test_gate_decay_after_quiet_period():
    clock = FakeClock()
    gate = Gate(clock=clock)
    key = "acct-b"
    gate.note_rate_limited(key)
    gate.note_rate_limited(key)
    assert gate.gate_status(key)["level"] == 2
    clock.advance(241)
    gate.gate_wait(key)  # 无退避窗口时触发降级
    assert gate.gate_status(key)["level"] == 1


def test_gate_cf_challenge_detection():
    assert Gate.is_cf_challenge("<html>Just a moment...</html>")
    assert Gate.is_cf_challenge("cf-chl-bypass")
    assert Gate.is_cf_challenge("Attention Required! | Cloudflare")
    assert Gate.is_cf_challenge("<!doctype html><title>cloudflare</title>")
    assert not Gate.is_cf_challenge("cloudflare mentioned in plain text")
    assert not Gate.is_cf_challenge("")
    assert not Gate.is_cf_challenge("429 Too Many Requests")


def test_gate_reject_double_counting():
    gate = Gate()
    gate.note_recaptcha_reject("a")
    gate.note_recaptcha_reject("a")
    gate.note_recaptcha_reject()
    assert gate.rej_count("a") == 2
    assert gate.rej_count() == 3
    gate.reset_rejects()
    assert gate.rej_count() == 0 and gate.rej_count("a") == 0


# ── DrawClient ─────────────────────────────────────────────────────────


def _client(session: FakeSession, gate: Optional[Gate] = None) -> DrawClient:
    return DrawClient(
        "user@x.com", "pw", session=session, gate=gate or Gate(), log=lambda *a, **k: None
    )


def test_create_chat_ok_and_throttle_call():
    session = FakeSession(responses=[FakeResponse(200, payload={"id": "sid-1"})])
    gate = Gate(base_gap=0.0)
    c = _client(session, gate)
    sid = c.create_chat({"recaptchaV3Token": "T" * 600})
    assert sid == "sid-1"
    assert session.calls[0]["json"]["recaptchaV3Token"] == "T" * 600


def test_create_chat_429_plain_and_switch():
    gate = Gate()
    c = _client(FakeSession(responses=[FakeResponse(429, text="Too Many Requests")]), gate)
    with pytest.raises(RateLimited) as ei:
        c.create_chat({})
    assert ei.value.cf is False and ei.value.switch is False

    gate2 = Gate()
    gate2.set_switch_level(1)
    c2 = _client(FakeSession(responses=[FakeResponse(429, text="Too Many Requests")]), gate2)
    with pytest.raises(RateLimited) as ei2:
        c2.create_chat({})
    assert ei2.value.switch is True  # level 已到 1 档


def test_create_chat_429_cf_forces_switch():
    gate = Gate()
    gate.set_switch_level(3)
    c = _client(
        FakeSession(responses=[FakeResponse(429, text="<html>Just a moment...")]), gate
    )
    with pytest.raises(RateLimited) as ei:
        c.create_chat({})
    assert ei.value.cf is True and ei.value.switch is True


def test_create_chat_recaptcha_reject_counted():
    gate = Gate()
    c = _client(
        FakeSession(responses=[FakeResponse(403, text="recaptcha check failed")]), gate
    )
    with pytest.raises(DrawError):
        c.create_chat({})
    assert gate.rej_count(gate_key("user@x.com", "")) == 1


def test_read_run_token_frame_fix_skips_invalid_then_accepts():
    good = _run_token("run_target")
    bad_jwt = "header.not-a-json.signature"
    expired = _run_token("run_x", exp=_time.time() - 10)
    wrong_iss = _run_token("run_x", iss="https://evil.example")
    no_run = _run_token("run_x")  # 有效但 run claim 形式正确 —— 换成无 run 的 scopes 变体
    no_run = f"header.{_b64({'iss': 'https://id.trigger.dev', 'pub': True, 'exp': _time.time() + 600, 'scopes': []})}.sig"
    frames = [
        "event: ping\ndata: {}\n\n",                 # 无 records
        _frame_with_token(bad_jwt),                    # JWT 解不开 → 继续等
        _frame_with_token(expired),                    # 过期 → 继续等
        _frame_with_token(wrong_iss),                  # 签发者不对 → 继续等
        _frame_with_token(no_run),                     # 无 run 权限 → 继续等
        _frame_with_token(good, headers_form="list"),  # list-pair 头 + 合法 → 命中
    ]
    c = _client(FakeSession(stream=FakeStream(200, frames)))
    got = c.read_run_token("sid", "sess-token", wait=5.0)
    assert got == good


def test_read_run_token_timeout_raises():
    c = _client(FakeSession(stream=FakeStream(200, [_frame_with_token("garbage-token")])))
    with pytest.raises(DrawError):
        c.read_run_token("sid", "sess-token", wait=0.3)


def test_run_id_from_token_both_claim_forms():
    assert de.run_id_from_token(_run_token("run_abc")) == "run_abc"
    scoped = f"h.{_b64({'iss': 'https://id.trigger.dev', 'pub': True, 'exp': _time.time() + 600, 'scopes': ['read:runs:run_legacy']})}.s"
    assert de.run_id_from_token(scoped) == "run_legacy"
    with pytest.raises(DrawError):
        de.run_id_from_token(_run_token("run_x", scopes=["read:other"]))


def test_fetch_run_events_retries_and_404_stops(monkeypatch):
    sleeps: List[float] = []
    monkeypatch.setattr(de.time, "sleep", lambda s: sleeps.append(s))
    session = FakeSession(responses=[
        FakeResponse(500),
        FakeResponse(200, payload={"events": [{"runId": "run_1", "message": "ai.streamText.doStream",
            "style": {"icon": "ai-provider-openai", "accessory": {"items": [
                {"icon": "tabler-cube", "text": "gpt-6-astra-low"}]}}}]}),
    ])
    events = de.fetch_run_events("rt", "run_1", session=session, retries=2, delay=3.0)
    assert events["events"][0]["runId"] == "run_1"
    assert sleeps == [3.0]

    session404 = FakeSession(responses=[FakeResponse(404)])
    with pytest.raises(DrawError):
        de.fetch_run_events("rt", "run_missing", session=session404, retries=3, delay=0.0)


# ── draw_once ──────────────────────────────────────────────────────────


class StubClient:
    """Full DrawClient stand-in; behaviour scripted per test."""

    def __init__(self):
        self.logged = True
        self.s = None  # session 占位（draw_once 经 getattr 取）
        self.calls: List[str] = []
        self.create_error: Optional[Exception] = None
        self.archive_ok = True

    def login(self, force: bool = False) -> bool:
        self.calls.append("login")
        return True

    def create_chat(self, tokens, text="1+1=", cancel=None):
        self.calls.append("create_chat")
        if self.create_error is not None:
            raise self.create_error
        self.last_token = tokens.get("recaptchaV3Token", "")
        return "sid-42"

    def session_token(self, sid: str) -> str:
        return "sess-jwt"

    def read_run_token(self, sid: str, token: str, wait: float = 90.0, cancel=None) -> str:
        return _run_token("run_42")

    def rename_chat(self, sid: str, title: str) -> bool:
        self.calls.append(f"rename:{title}")
        return True

    def archive_chat(self, sid: str, archive: bool = True) -> bool:
        self.calls.append("archive")
        return self.archive_ok

    def delete_chat(self, sid: str) -> bool:
        self.calls.append("delete")
        return True

    def close(self):
        pass


def _patch_round(monkeypatch, model="GPT-6 Astra", internal="gpt-6-astra-low", usage=None):
    events = {
        "events": [
            {
                "runId": "run_42",
                "message": "ai.streamText.doStream",
                "style": {
                    "icon": "ai-provider-openai",
                    "accessory": {"items": [{"icon": "tabler-cube", "text": model}]},
                },
            }
        ]
    }

    def fake_events(run_token, run_id, session=None, retries=8, delay=3.0, want_internal=False, log=None):
        return events

    def fake_usage(run_token, run_id, ev, session=None, max_spans=8, log=None):
        return usage or {}

    monkeypatch.setattr(de, "fetch_run_events", fake_events)
    monkeypatch.setattr(de, "read_usage", fake_usage)


ACCOUNT = {"id": "acc-1", "email": "user@x.com", "proxy_url": ""}


def test_draw_once_hit_renames_and_keeps(monkeypatch):
    _patch_round(monkeypatch, usage={"reasoningTokens": 123, "inputTokens": 10, "outputTokens": 5, "modelName": "gpt-6-astra-low", "settingHints": ["reasoning"]})
    cache = FakeCache()
    client = StubClient()
    res = draw_once(ACCOUNT, "pw", cache, Gate(), keep_pattern="astra", client=client)
    assert res["ok"] and res["kept"]
    assert res["model"] == "GPT-6 Astra" and res["internal"] == "gpt-6-astra-low"
    assert res["reasoning"] == 123 and res["tier"] == "low"
    assert any(c.startswith("rename:gpt-6-astra-low·r123") for c in client.calls)
    # 消费语义：取票必须 consume=True
    assert cache.get_calls[0]["consume"] is True


def test_draw_once_miss_archive_with_delete_fallback(monkeypatch):
    _patch_round(monkeypatch, model="Claude Fable", internal="claude-fable-5.1")
    client = StubClient()
    client.archive_ok = False
    res = draw_once(ACCOUNT, "pw", FakeCache(), Gate(), keep_pattern="astra", miss_action="archive", client=client)
    assert res["ok"] and not res["kept"]
    assert "archive" in client.calls and "delete" in client.calls


def test_draw_once_miss_delete_and_keep(monkeypatch):
    _patch_round(monkeypatch, model="Claude Fable", internal="claude-fable-5.1")
    client = StubClient()
    res = draw_once(ACCOUNT, "pw", FakeCache(), Gate(), keep_pattern="astra", miss_action="delete", client=client)
    assert res["ok"] and not res["kept"] and "delete" in client.calls

    client2 = StubClient()
    res2 = draw_once(ACCOUNT, "pw", FakeCache(), Gate(), keep_pattern="astra", miss_action="keep", client=client2)
    assert res2["ok"] and not res2["kept"]
    assert not any(c.startswith(("archive", "delete", "rename")) for c in client2.calls)


def test_draw_once_empty_pattern_keeps_everything(monkeypatch):
    _patch_round(monkeypatch, model="Whatever Model")
    client = StubClient()
    res = draw_once(ACCOUNT, "pw", FakeCache(), Gate(), keep_pattern="", client=client)
    assert res["kept"] is True


def test_draw_once_require_reasoning_discards(monkeypatch):
    _patch_round(monkeypatch, model="GPT-6 Astra", usage={"reasoningTokens": 0})
    client = StubClient()
    res = draw_once(
        ACCOUNT, "pw", FakeCache(), Gate(), keep_pattern="astra",
        require_reasoning=True, client=client,
    )
    assert res["ok"] and not res["kept"]
    assert not any(c.startswith("rename") for c in client.calls)


def test_draw_once_token_window_unavailable(monkeypatch):
    _patch_round(monkeypatch)
    res = draw_once(ACCOUNT, "pw", FakeCache(token=None, remint=False), Gate(), client=StubClient())
    assert not res["ok"]
    assert "token 窗口不可用" in res["error"]


def test_draw_once_recaptcha_reject_marks_cache(monkeypatch):
    _patch_round(monkeypatch)
    monkeypatch.setattr(de, "_sleep_cancellable", lambda s, cancel=None, step=0.4: None)
    cache = FakeCache()
    client = StubClient()
    client.create_error = DrawError("create-chat HTTP 403: recaptcha denied")
    res = draw_once(ACCOUNT, "pw", cache, Gate(), client=client)
    assert not res["ok"]
    assert "recaptcha" in res["error"]
    # 两次尝试各记一次（参考语义：重试的拒绝也计数，喂熔断）
    assert cache.rejected == ["create-chat recaptcha", "create-chat recaptcha"]


def test_draw_once_switch_propagates(monkeypatch):
    _patch_round(monkeypatch)
    client = StubClient()
    client.create_error = RateLimited("429 到档", cf=True, switch=True)
    res = draw_once(ACCOUNT, "pw", FakeCache(), Gate(), client=client)
    assert res["switch"] is True and not res["ok"]


def test_token_cache_consume_semantics():
    from backend.services.arena_token_cache import TokenWindowCache

    cache = TokenWindowCache(max_age_sec=60.0)
    cache.push("T" * 600)
    first = cache.get(wait_sec=0.1, consume=True)
    assert first is not None and first["token"] == "T" * 600
    assert cache.get(wait_sec=0.1) is None            # 已消费：槽位清空
    assert cache.health()["ready"] is False
    cache.push("U" * 600)
    warm = cache.get(wait_sec=0.1)                     # 不消费可重复读
    assert warm["token"] == "U" * 600
    assert cache.get(wait_sec=0.1)["token"] == "U" * 600


# ── job 编排 ───────────────────────────────────────────────────────────


class FakeAccounts:
    def __init__(self, n: int = 2):
        self.rows = [
            {"id": f"acc-{i}", "email": f"user{i}@x.com", "state": "available", "proxy_url": ""}
            for i in range(n)
        ]
        self.draws: List[Dict[str, Any]] = []
        self.released: List[str] = []
        self.failures: List[str] = []

    def get_account(self, account_id: str, include_secret: bool = False):
        return next((r for r in self.rows if r["id"] == account_id), None)

    def list_accounts(self, state=None):
        return list(self.rows)

    def get_secret(self, account_id: str) -> str:
        return "pw"

    def release_account(self, account_id: str) -> None:
        self.released.append(account_id)

    def record_failure(self, account_id: str, reason: str) -> None:
        self.failures.append(f"{account_id}:{reason}")

    def record_draw(self, account_id: str, payload: Dict[str, Any]) -> str:
        self.draws.append({"account_id": account_id, **payload})
        return f"d{len(self.draws)}"

    def update_binding(self, account_id: str, proxy_url: str, proxy_sid=None, exit_ip=None):
        for r in self.rows:
            if r["id"] == account_id:
                r["proxy_url"] = proxy_url


def _draw_config(**over):
    cfg = ArenaAutomationConfig(enabled=True)
    cfg.draw.enabled = True
    cfg.draw.reject_threshold = 999  # 默认不触发熔断
    for k, v in over.items():
        setattr(cfg.draw, k, v)
    return cfg


def _wait_job(store, job_id, timeout=10.0):
    end = _time.monotonic() + timeout
    while _time.monotonic() < end:
        job = store.get(job_id)
        if job is not None and job.status in ("done", "failed", "stopped"):
            return job
        _time.sleep(0.05)
    raise AssertionError("draw job did not finish")


def test_draw_job_round_trip(monkeypatch):
    accounts = FakeAccounts(n=2)
    store = de.JobStore()
    cfg = _draw_config()
    calls: List[Dict[str, Any]] = []

    def fake_draw_once(account, password, **kw):
        calls.append({"account": account["id"], "gate": kw.get("gate") is not None, "cache": kw.get("token_cache") is not None})
        return {
            "email": account["email"], "model": "GPT-6 Astra", "internal": "gpt-6-astra-low",
            "provider": "openai", "session_id": "s", "run_id": "r", "kept": True,
            "ok": True, "error": "", "reasoning": 5, "tokens_in": 1, "tokens_out": 2,
            "tier": "low", "setting_hints": "", "switch": False,
        }

    monkeypatch.setattr(de, "draw_once", fake_draw_once)
    job_id = de.start_draw_job(
        {"all_accounts": True, "rounds_per_account": 2}, accounts, cfg,
        job_store=store, token_cache=FakeCache(),
    )
    job = _wait_job(store, job_id)
    assert job.status == "done" and job.ok == 4 and job.failed == 0
    assert len(accounts.draws) == 4
    assert sorted(accounts.released) == ["acc-0", "acc-0", "acc-1", "acc-1"]
    assert all(c["gate"] and c["cache"] for c in calls)
    events = store.events_after(job_id)
    assert any(e.kind == "done" for e in events)


def test_draw_job_stop_midway(monkeypatch):
    accounts = FakeAccounts(n=1)
    store = de.JobStore()

    def fake_draw_once(account, password, **kw):
        _time.sleep(0.3)  # 5 轮 ≈ 1.5s，留出 stop 窗口
        return {"ok": True, "model": "M", "kept": False, "switch": False, "email": account["email"]}

    monkeypatch.setattr(de, "draw_once", fake_draw_once)
    job_id = de.start_draw_job(
        {"all_accounts": True, "rounds_per_account": 5}, accounts, _draw_config(),
        job_store=store, token_cache=FakeCache(),
    )
    _time.sleep(0.35)
    assert store.request_stop(job_id) is True
    job = _wait_job(store, job_id, timeout=15)
    assert job.status == "stopped"
    assert job.ok + job.failed < 5  # 没跑完就停了


def test_draw_job_reject_breaker_cools_down(monkeypatch):
    accounts = FakeAccounts(n=1)
    store = de.JobStore()
    cfg = _draw_config(reject_threshold=2, cooldown_sec=0.05)
    cooldowns: List[float] = []

    def fake_draw_once(account, password, **kw):
        gate = kw["gate"]
        gate.note_recaptcha_reject(account["email"].split("@")[0])
        gate.note_recaptcha_reject(account["email"].split("@")[0])
        return {"ok": True, "model": "M", "kept": False, "switch": False, "email": account["email"]}

    def fake_sleep(seconds, cancel=None, step=0.4):
        if seconds and seconds > 0.01:
            cooldowns.append(seconds)
        return None

    monkeypatch.setattr(de, "_sleep_cancellable", fake_sleep)
    monkeypatch.setattr(de, "draw_once", fake_draw_once)
    job_id = de.start_draw_job(
        {"all_accounts": True, "rounds_per_account": 2}, accounts, cfg,
        job_store=store, token_cache=FakeCache(),
    )
    job = _wait_job(store, job_id)
    assert job.ok == 2
    assert cooldowns == [0.05]          # 第 2 轮触发一次熔断冷却
    events = store.events_after(job_id)
    assert any("冷却" in e.message for e in events)


def test_start_draw_job_validates_params():
    accounts = FakeAccounts(n=1)
    store = de.JobStore()
    with pytest.raises(ValueError):
        de.start_draw_job({"rounds_per_account": 1}, accounts, _draw_config(), job_store=store)
    with pytest.raises(ValueError):
        de.start_draw_job(
            {"all_accounts": True, "miss_action": "nuke"}, accounts, _draw_config(), job_store=store
        )
    with pytest.raises(ValueError):
        de.start_draw_job(
            {"account_ids": ["ghost"], "rounds_per_account": 1}, accounts, _draw_config(), job_store=store
        )


# ── 路由合同 ───────────────────────────────────────────────────────────


@pytest.fixture()
def client(tmp_path):
    de._reset_store_for_tests()
    cfg = _draw_config()
    service = init_arena_service(
        db_path=str(tmp_path / "unused.sqlite"),
        encryption_key=Fernet.generate_key(),
        config=cfg,
    )
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    shutdown_arena_service()  # 内部会 close 同一单例
    import contextlib

    with contextlib.suppress(Exception):
        service.close()
    de._reset_store_for_tests()


def _seed_accounts(client):  # 借助 accounts 路由造一个真实账号
    resp = client.post(
        "/api/v1/arena/accounts",
        json={"email": "smoke@x.com", "password": "Passw0rd!xx"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_api_draw_disabled_403(tmp_path):
    cfg = ArenaAutomationConfig(enabled=True)
    cfg.draw.enabled = False
    throwaway = init_arena_service(
        db_path=str(tmp_path / "x.sqlite"), encryption_key=Fernet.generate_key(), config=cfg
    )
    throwaway.close()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        r = c.post("/api/v1/arena/draw/jobs", json={"all_accounts": True})
        assert r.status_code == 403
    shutdown_arena_service()


def test_api_draw_job_round_trip(client, monkeypatch):
    account_id = _seed_accounts(client)

    def fake_draw_once(account, password, **kw):
        return {
            "email": account["email"], "model": "GPT-6 Astra", "internal": "gpt-6-astra-low",
            "provider": "openai", "session_id": "s", "run_id": "r", "kept": True,
            "ok": True, "error": "", "reasoning": "", "tokens_in": "", "tokens_out": "",
            "tier": "", "setting_hints": "", "switch": False,
        }

    monkeypatch.setattr(de, "draw_once", fake_draw_once)
    r = client.post(
        "/api/v1/arena/draw/jobs",
        json={"account_ids": [account_id], "rounds_per_account": 1, "keep_pattern": ""},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]

    end = _time.monotonic() + 10
    while _time.monotonic() < end:
        snap = client.get(f"/api/v1/arena/draw/jobs/{job_id}").json()
        if snap["status"] in ("done", "failed", "stopped"):
            break
        _time.sleep(0.05)
    assert snap["status"] == "done" and snap["ok"] == 1

    draws = client.get(f"/api/v1/arena/accounts/{account_id}/draws").json()
    assert len(draws) == 1 and draws[0]["model"] == "GPT-6 Astra"

    all_draws = client.get("/api/v1/arena/draws").json()
    assert len(all_draws) == 1

    events = client.get(f"/api/v1/arena/draw/jobs/{job_id}/events").text
    assert "GPT-6 Astra" in events

    assert client.get("/api/v1/arena/draw/jobs/nope").status_code == 404
    assert client.get("/api/v1/arena/accounts/ghost/draws").status_code == 404


def test_api_draw_job_bad_request(client):
    r = client.post("/api/v1/arena/draw/jobs", json={"rounds_per_account": 1})
    assert r.status_code == 400
    r = client.post(
        "/api/v1/arena/draw/jobs",
        json={"all_accounts": True, "miss_action": "nuke"},
    )
    assert r.status_code == 400

def test_client_forwards_measured_ua():
    """实测 UA 转发：出票窗口的 navigator.userAgent 必须随请求呈现。"""
    c = DrawClient(email="a@b.c", password="x", ua="UA-MEASURED/1.0")
    assert c._h()["User-Agent"] == "UA-MEASURED/1.0"
    c2 = DrawClient(email="a@b.c", password="x")
    assert "User-Agent" not in c2._h()


def test_draw_once_injects_snapshot_ua(monkeypatch):
    """draw_once：token 快照带回的实测 UA 注入 client（与出票窗口同 UA）。"""
    _patch_round(monkeypatch, usage={"reasoningTokens": 1, "inputTokens": 1, "outputTokens": 1, "modelName": "gpt-6-astra-low"})
    client = StubClient()
    assert getattr(client, "ua", "") == ""  # 注入前无 UA
    res = draw_once(ACCOUNT, "pw", FakeCache(), Gate(), keep_pattern="astra", client=client)
    assert res["ok"]
    # FakeCache 快照带 ua="ua"（exit_ip 同）→ draw_once 须转发给 client
    assert getattr(client, "ua", "") == "ua"
