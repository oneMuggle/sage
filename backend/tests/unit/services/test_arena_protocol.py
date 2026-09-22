"""Unit tests for backend/services/arena_protocol.py.

Everything runs against httpx.MockTransport — no network, per plan §9
("任何单测不得真连网").
"""

import asyncio
import base64
import json
import time

import httpx
import pytest

from backend.services.arena_protocol import (
    ArenaCaptchaRejected,
    ArenaDrawClient,
    ArenaProtocolError,
    ArenaRateLimited,
    ArenaRegisterClient,
    RegisterResult,
    gen_password,
    is_cf_challenge,
    register_one,
    run_id_from_token,
    validate_password,
)
from backend.services.temporary_mail.base import Mailbox, TemporaryMailProvider


# ── helpers ────────────────────────────────────────────────────────────

def _b64url(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def _jwt(claims) -> str:
    return f"eyJhbGciOiJIUzI1NiJ9.{_b64url(claims)}.{_b64url({'sig': 1})}"


def _run_token(run_id="run_abc123", scopes=False):
    claims = {
        "iss": "https://id.trigger.dev",
        "aud": "https://api.trigger.dev",
        "exp": time.time() + 600,
        "pub": True,
    }
    if scopes:
        claims["scopes"] = [f"read:runs:{run_id}"]
    else:
        claims["run"] = run_id
    return _jwt(claims)


class FakeMail(TemporaryMailProvider):
    name = "fake"

    def __init__(self, link=None):
        self.link = link
        self.mailbox = None

    async def create_mailbox(self) -> Mailbox:
        # Mailbox 自 #1211 起要求 password/provider_token 必填（协议层透传存池）
        self.mailbox = Mailbox(
            email="ab12cd34ef@dbwot.com",
            password="fake-password",
            provider_token="fake-token",
            provider="fake",
        )
        return self.mailbox

    async def wait_for_code(self, mailbox, subject_pattern=None, timeout_sec=10, poll_interval_sec=1):
        return None

    async def wait_for_link(self, mailbox, link_pattern=None, timeout_sec=90, poll_interval_sec=4, subject_pattern=None):
        return self.link

    async def destroy_mailbox(self, mailbox):
        return None

    async def _fetch_messages(self, mailbox, since_timestamp=None):
        return []


# ── 密码规则 ───────────────────────────────────────────────────────────

def test_validate_password_rules():
    assert validate_password("Abcdef1!") is True
    assert validate_password("Aa1!") is False        # < 8
    assert validate_password("abcdefg1!") is False   # no upper
    assert validate_password("ABCDEFG1!") is False   # no lower
    assert validate_password("Abcdefgh!") is False   # no digit
    assert validate_password("Abcdefg1") is False    # no special
    assert validate_password("") is False


def test_gen_password_always_valid():
    for _ in range(200):
        assert validate_password(gen_password()) is True
    assert len(gen_password(14)) == 14
    assert len(gen_password(20)) == 20


# ── CF 识别 ────────────────────────────────────────────────────────────

def test_is_cf_challenge():
    assert is_cf_challenge("Just a moment...") is True
    assert is_cf_challenge("<html>Attention Required! | Cloudflare</html>") is True
    assert is_cf_challenge('{"ok": false}') is False
    assert is_cf_challenge("<html>hello cloudflare</html>") is True
    assert is_cf_challenge("") is False


# ── 注册客户端 6 步 ────────────────────────────────────────────────────

def _register_handler(state):
    """Scripted arena backend for the registration flow."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        method = request.method
        state["requests"].append((method, url))
        if url.endswith("/nextjs-api/sign-up"):
            return httpx.Response(200, json={"access_token": "at-1"})
        if url.endswith("/nextjs-api/sign-up/magic-link"):
            state["magic_link_body"] = json.loads(request.read().decode())
            return httpx.Response(200, json={})
        if "/nextjs-api/callback" in url:
            return httpx.Response(
                302, headers={"Location": "https://arena.ai/set-password?token=TOK123"}
            )
        if url.endswith("/nextjs-api/auth/set-password"):
            state["set_password_bodies"].append(json.loads(request.read().decode()))
            return httpx.Response(200, json={})
        if url.endswith("/nextjs-api/sign-in/email"):
            state["sign_in_count"] += 1
            if state["sign_in_first_fails"] and state["sign_in_count"] == 1:
                return httpx.Response(401, json={})
            return httpx.Response(200, json={})
        if url.endswith("/api/me"):
            return httpx.Response(200, json={"user": {"id": "user-42"}})
        if url.endswith("/api/billing/balance"):
            state["balance_calls"] += 1
            if state["balance_calls"] < 2:
                return httpx.Response(429, text="slow down")
            return httpx.Response(200, json={"creditsRemaining": 15000})
        return httpx.Response(404, text="unexpected " + url)

    return handler


def _register_client(state):
    session = httpx.MockTransport(_register_handler(state))
    from backend.services.arena_http import make_session

    return ArenaRegisterClient(
        email="ab12cd34ef@dbwot.com",
        session=make_session(transport=session),
    )


def test_register_client_six_steps():
    state = {
        "requests": [], "magic_link_body": None, "set_password_bodies": [],
        "sign_in_count": 0, "sign_in_first_fails": False, "balance_calls": 0,
    }
    client = _register_client(state)
    client.create_user()
    client.send_magic_link("ab12cd34ef@dbwot.com")
    token = client.confirm_link("https://arena.ai/nextjs-api/callback?flow=xyz")
    client.set_password(token, "Abcdef1!")
    assert client.sign_in() is True
    assert client.get_me() == {"id": "user-42"}

    assert token == "TOK123"
    assert state["magic_link_body"] == {
        "email": "ab12cd34ef@dbwot.com",
        "fullName": "Arena User",
        "shouldLinkHistory": False,
        "marketingConsent": False,
        "registeredCountryCode": "US",
    }
    assert state["set_password_bodies"][0] == {"password": "Abcdef1!", "token": "TOK123"}


def test_register_client_get_balance_retries():
    state = {
        "requests": [], "magic_link_body": None, "set_password_bodies": [],
        "sign_in_count": 0, "sign_in_first_fails": False, "balance_calls": 0,
    }
    client = _register_client(state)
    sleeps = []
    balance = client.get_balance(retries=4, delay=3.0, sleep=sleeps.append)
    assert balance == {"creditsRemaining": 15000}
    assert state["balance_calls"] == 2
    assert sleeps == [3.0]


def test_register_client_error_status_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    from backend.services.arena_http import make_session

    client = ArenaRegisterClient(session=make_session(transport=httpx.MockTransport(handler)))
    with pytest.raises(ArenaProtocolError, match="sign-up HTTP 500"):
        client.create_user()


# ── register_one 编排 ──────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def test_register_one_happy_path():
    state = {
        "requests": [], "magic_link_body": None, "set_password_bodies": [],
        "sign_in_count": 0, "sign_in_first_fails": False, "balance_calls": 0,
    }
    logs = []

    def session_factory():
        from backend.services.arena_http import make_session

        return make_session(transport=httpx.MockTransport(_register_handler(state)))

    result = _run(
        register_one(
            FakeMail(link="https://arena.ai/nextjs-api/callback?flow=abc"),
            session_factory=session_factory,
            log=logs.append,
            mail_timeout=5,
        )
    )
    assert result.ok is True
    assert result.email == "ab12cd34ef@dbwot.com"
    assert result.user_id == "user-42"
    assert result.credits == "15000"
    assert validate_password(result.password) is True
    assert result.to_dict()["password"] == "***"  # events never carry plaintext
    assert any("注册成功" in m for m in logs)


def test_register_one_retries_password_when_first_signin_fails():
    state = {
        "requests": [], "magic_link_body": None, "set_password_bodies": [],
        "sign_in_count": 0, "sign_in_first_fails": True, "balance_calls": 0,
    }

    def session_factory():
        from backend.services.arena_http import make_session

        return make_session(transport=httpx.MockTransport(_register_handler(state)))

    result = _run(
        register_one(
            FakeMail(link="https://arena.ai/nextjs-api/callback?flow=abc"),
            session_factory=session_factory,
            mail_timeout=5,
        )
    )
    assert result.ok is True
    assert state["sign_in_count"] == 2
    assert len(state["set_password_bodies"]) == 2  # set-password retried once


def test_register_one_mail_timeout_is_error_not_crash():
    # session_factory is mandatory in tests — without it register_one would
    # build a REAL arena session (plan §9: 单测不得真连网).
    state = {
        "requests": [], "magic_link_body": None, "set_password_bodies": [],
        "sign_in_count": 0, "sign_in_first_fails": False, "balance_calls": 0,
    }

    def session_factory():
        from backend.services.arena_http import make_session

        return make_session(transport=httpx.MockTransport(_register_handler(state)))

    result = _run(
        register_one(
            FakeMail(link=None),  # provider yields no link → mail timeout
            session_factory=session_factory,
            mail_timeout=1,
        )
    )
    assert result.ok is False
    assert "等待验证邮件超时" in result.error


# ── 抽卡协议客户端 ─────────────────────────────────────────────────────

def _draw_handler(state):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        method = request.method
        state["requests"].append((method, url))
        if url.endswith("/nextjs-api/sign-in/email"):
            return httpx.Response(200, json={})
        if url.endswith("/nextjs-api/stream/create-chat"):
            body = json.loads(request.read().decode())
            state["create_chat_bodies"].append(body)
            mode = state.get("create_chat_mode", "ok")
            if mode == "429":
                return httpx.Response(429, text=state.get("create_chat_body", "rate limited"))
            if mode == "429-cf":
                return httpx.Response(429, text="Just a moment...")
            if mode == "captcha":
                return httpx.Response(400, json={"message": "recaptcha validation failed"})
            if mode == "no-id":
                return httpx.Response(200, json={})
            return httpx.Response(200, json={"id": "sid-1"})
        if url.endswith("/api/chat/trigger-token"):
            return httpx.Response(200, json={"token": "session-jwt"})
        if "/ai-proxy/realtime/v1/sessions/sid-1/out" in url:
            noise = 'data: {"records": [{"headers": [["x", "y"]]}]}\n\n'
            bad = "data: " + _jwt({"iss": "https://wrong", "exp": 1}) + "\n\n"
            good = (
                "data: "
                + json.dumps(
                    {"records": [{"headers": [["public-access-token", _run_token("run_abc123")]]}]}
                )
                + "\n\n"
            )
            return httpx.Response(
                200, content=(noise + bad + good).encode(), headers={"Content-Type": "text/event-stream"}
            )
        if "/api/history/agentic/sid-1" in url:
            state["rename_body"] = json.loads(request.read().decode())
            return httpx.Response(200, json={})
        if url.endswith("/api/chat/sid-1/archive") or url.endswith("/api/chat/sid-1/unarchive"):
            return httpx.Response(200, json={})
        if url.endswith("/api/chat/sid-1"):
            return httpx.Response(200, json={})
        if "/api/v1/runs/run_abc123/events" in url:
            return httpx.Response(200, json=state["run_events"])
        if "/api/v1/runs/run_abc123/spans/" in url:
            span_id = url.rsplit("/", 1)[-1]
            return httpx.Response(200, json=state["spans"].get(span_id, {}))
        return httpx.Response(404, text="unexpected " + url)

    return handler


def _draw_client(state):
    from backend.services.arena_http import make_session

    return ArenaDrawClient(
        email="a@dbwot.com",
        password="Abcdef1!",
        session=make_session(transport=httpx.MockTransport(_draw_handler(state))),
    )


def test_draw_client_login_reuse_and_create_chat():
    state = {"requests": [], "create_chat_bodies": []}
    client = _draw_client(state)
    assert client.login() is True
    assert client.login() is True  # second call reuses session, no request
    sign_ins = [r for r in state["requests"] if r[1].endswith("/nextjs-api/sign-in/email")]
    assert len(sign_ins) == 1

    sid = client.create_chat("v3-token-xyz")
    assert sid == "sid-1"
    body = state["create_chat_bodies"][0]
    assert body["recaptchaV3Token"] == "v3-token-xyz"
    assert body["message"]["parts"][0]["text"] == "1+1="
    assert body["timezone"] == "Asia/Shanghai"


def test_draw_client_429_variants():
    state = {"requests": [], "create_chat_bodies": [], "create_chat_mode": "429"}
    client = _draw_client(state)
    with pytest.raises(ArenaRateLimited) as excinfo:
        client.create_chat("t")
    assert excinfo.value.cf is False

    state["create_chat_mode"] = "429-cf"
    with pytest.raises(ArenaRateLimited, match="Cloudflare"):
        client.create_chat("t")
    # cf flag asserted via second raise
    state["create_chat_mode"] = "429-cf"
    try:
        client.create_chat("t")
    except ArenaRateLimited as exc:
        assert exc.cf is True


def test_draw_client_captcha_rejection():
    state = {"requests": [], "create_chat_bodies": [], "create_chat_mode": "captcha"}
    client = _draw_client(state)
    with pytest.raises(ArenaCaptchaRejected, match="recaptcha"):
        client.create_chat("t")


def test_draw_client_create_chat_missing_id():
    state = {"requests": [], "create_chat_bodies": [], "create_chat_mode": "no-id"}
    client = _draw_client(state)
    with pytest.raises(ArenaProtocolError, match="未返回会话 ID"):
        client.create_chat("t")


def test_draw_client_read_run_token_skips_bad_frames():
    state = {"requests": [], "create_chat_bodies": []}
    client = _draw_client(state)
    token = client.read_run_token("sid-1", "session-jwt", wait=5.0)
    assert token.startswith("eyJhbGciOiJIUzI1NiJ9")
    assert run_id_from_token(token) == "run_abc123"


def test_run_id_from_token_scopes_format():
    token = _run_token("run_legacy99", scopes=True)
    assert run_id_from_token(token) == "run_legacy99"


def test_run_id_from_token_rejects_garbage():
    with pytest.raises(ArenaProtocolError):
        run_id_from_token("not-a-jwt")
    with pytest.raises(ArenaProtocolError, match="read:runs"):
        run_id_from_token(_jwt({"iss": "https://id.trigger.dev"}))


def test_draw_client_disposition_endpoints():
    state = {"requests": [], "create_chat_bodies": []}
    client = _draw_client(state)
    assert client.rename_chat("sid-1", "gpt-6-astra-low·r4096") is True
    assert state["rename_body"] == {"title": "gpt-6-astra-low·r4096"}
    assert client.archive_chat("sid-1") is True
    assert client.archive_chat("sid-1", archive=False) is True
    assert client.delete_chat("sid-1") is True


def test_draw_client_fetch_run_events_waits_for_internal():
    state = {
        "requests": [],
        "create_chat_bodies": [],
        "run_events": {
            "events": [
                {
                    "runId": "run_abc123",
                    "message": "ai.streamText.doStream",
                    "spanId": "s1",
                    "style": {
                        "icon": "ai-provider-openai",
                        "accessory": {"items": [{"icon": "tabler-cube", "text": "GPT-6 Astra"}]},
                    },
                }
            ]
        },
        "spans": {},
    }
    client = _draw_client(state)
    sleeps = []

    # want_internal=False: model label is enough → returned immediately
    events = client.fetch_run_events("rt", "run_abc123", want_internal=False, retries=3, sleep=sleeps.append)
    assert events == state["run_events"]
    assert sleeps == []

    # want_internal=True: no modelName anywhere → retries exhausted, best returned
    events = client.fetch_run_events("rt", "run_abc123", want_internal=True, retries=2, sleep=sleeps.append)
    assert events == state["run_events"]
    assert len(sleeps) == 1


def test_draw_client_read_usage_authoritative_and_weak():
    state = {
        "requests": [],
        "create_chat_bodies": [],
        "run_events": {
            "events": [
                {"message": "ai.streamText.doStream", "spanId": "span-stream"},
                {"message": "token.usage.recorded", "spanId": "span-usage"},
            ]
        },
        "spans": {
            "span-usage": {"properties": {"reasoningTokens": 4096, "modelName": "gpt-6-astra-low"}},
            "span-stream": {
                "properties": {
                    "ai": {"usage": {"reasoningTokens": 1, "inputTokens": 11}},
                    "gen_ai": {"request": {"model": "weak-model"}},
                }
            },
        },
    }
    client = _draw_client(state)
    sleeps = []
    usage = client.read_usage("rt", "run_abc123", state["run_events"], sleep=sleeps.append)
    assert usage["reasoningTokens"] == 4096   # usage span wins over stream's 1
    assert usage["inputTokens"] == 11         # stream fills the gap
    assert usage["requestModel"] == "weak-model"
    assert usage["modelName"] == "gpt-6-astra-low"
    assert usage["stopped"] == ""
    assert sleeps == [0.25]  # between the two span reads


def test_draw_client_read_usage_stops_on_429():
    state = {
        "requests": [],
        "create_chat_bodies": [],
        "run_events": {"events": [{"message": "token.usage.recorded", "spanId": "limited"}]},
        "spans": {},
        "span_429": True,
    }

    handler = _draw_handler(state)

    def limited_handler(request: httpx.Request) -> httpx.Response:
        if "/spans/" in str(request.url):
            return httpx.Response(429, text="limited")
        return handler(request)

    from backend.services.arena_http import make_session

    client = ArenaDrawClient(
        email="a@dbwot.com", password="x",
        session=make_session(transport=httpx.MockTransport(limited_handler)),
    )
    usage = client.read_usage("rt", "run_abc123", state["run_events"], sleep=lambda _s: None)
    assert usage["stopped"] == "span详情限流"


def test_register_result_dataclass_defaults():
    result = RegisterResult()
    assert result.to_dict() == {
        "email": "", "password": "", "user_id": "", "credits": "",
        "ok": False, "error": "",
    }
