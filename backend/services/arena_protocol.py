"""arena.ai protocol clients (plan §5.5, ported from reference/ArenCard).

Two thin clients over ``arena_http`` sessions plus the single-account
registration orchestration:

* ``ArenaRegisterClient`` — the 6-step password registration flow
  (reference arena_core.py:340-495). No reCAPTCHA token needed: the sign-up
  endpoint does not validate it (measured in the reference).
* ``ArenaDrawClient`` — conversation-level model draw protocol steps 1,3,4,8
  (reference arena_draw.py). Rate-limit/captcha semantics are surfaced as
  typed exceptions; the *waiting policy* (gates, ladders, IP switching) lives
  in the P4 engine, not here.
* ``register_one`` — mailbox → account, with the reference's tolerance for
  the flaky set-password step (retry once with the same token).

Disciplines inherited verbatim (plan §2.6): per-account session, no custom
UA, mail traffic never proxied (the provider instance owns that), sign-in
state reused within a client, ``public-access-token`` never logged.

SSE/JWT parsing reuses ``backend/services/run_trace_resolver.py`` (plan
appendix C #1) instead of reimplementing.
"""

from __future__ import annotations

import logging
import random
import re
import string
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional

from backend.services.arena_http import (
    arena_headers,
    make_session,
    request_with_retry,
)
from backend.services.arena_trace_ext import (
    SPAN_KINDS,
    extract_usage,
    parse_models,
    setting_hints,
)
from backend.services.run_trace_resolver import (
    decode_jwt_payload,
    extract_public_access_token,
    extract_run_id_from_claims,
    parse_sse_frame,
    validate_jwt_claims,
)

logger = logging.getLogger(__name__)

# ── 协议常量（plan 附录 A，带来源） ─────────────────────────────────────

ARENA = "https://arena.ai"
TRIGGER_API = "https://api.trigger.dev"

#: 验证邮件里的 magic-link（reference arena_core.py:300-322）
VERIFY_LINK_RE = r"https://arena\.ai/nextjs-api/callback\S+"

#: reCAPTCHA Enterprise V3（reference token_server.py:28-44）
RECAPTCHA_ACTION = "agentic_chat_submit"

#: 建会话的第一条消息与默认时区（reference arena_draw.py DRAW_TEXT）
DRAW_TEXT = "1+1="
DRAW_TIMEZONE = "Asia/Shanghai"

#: 限速门闸经验值（P4 引擎消费；常量单点放这里，plan 附录 A）
GATE_LADDER = (15.0, 30.0, 60.0, 90.0)
GATE_DECAY_AFTER = 240.0
CF_HOLD = 180.0
CREATE_CHAT_BACKOFFS = (0, 15, 30, 60)

#: Cloudflare 挑战响应体特征（reference arena_draw.py:109）
CF_MARKERS = ("just a moment", "cf-chl", "attention required")

#: SSE 订阅头（reference arena_draw.py read_run_token）
SSE_HEADERS = {
    "x-trigger-source": "sdk",
    "x-trigger-realtime-streams-version": "v2",
}


# ── 异常 ──────────────────────────────────────────────────────────────

class ArenaProtocolError(RuntimeError):
    """Protocol-level failure (bad status, missing field, timeout)."""


class ArenaRateLimited(ArenaProtocolError):
    """HTTP 429. ``cf`` marks a Cloudflare challenge (waiting is useless —
    the exit IP is burned); the P4 engine decides whether to switch IP."""

    def __init__(self, message: str, cf: bool = False):
        super().__init__(message)
        self.cf = cf


class ArenaCaptchaRejected(ArenaProtocolError):
    """Server rejected the reCAPTCHA token (body mentions recaptcha)."""


def is_cf_challenge(text: str) -> bool:
    """Detect a Cloudflare interstitial in a 429/403 body (plan §2.3).

    ``just a moment`` / ``cf-chl`` / ``attention required``, or the word
    ``cloudflare`` inside an HTML body.
    """
    body = (text or "")[:800].lower()
    if not body:
        return False
    if any(marker in body for marker in CF_MARKERS):
        return True
    return "cloudflare" in body and "<html" in body


# ── 密码规则（reference arena_core.py:420-441） ────────────────────────

PWD_UPPER = string.ascii_uppercase
PWD_LOWER = string.ascii_lowercase
PWD_DIGITS = string.digits
PWD_SYMBOLS = "!@#$%^&*"


def validate_password(p: str) -> bool:
    """arena rule: ≥8 chars with upper + lower + digit + special."""
    if not p or len(p) < 8:
        return False
    return bool(
        re.search(r"[A-Z]", p)
        and re.search(r"[a-z]", p)
        and re.search(r"[0-9]", p)
        and re.search(r"[^A-Za-z0-9]", p)
    )


def gen_password(length: int = 14) -> str:
    """Generate a rule-compliant password (4 classes guaranteed, shuffled)."""
    pool = PWD_UPPER + PWD_LOWER + PWD_DIGITS + PWD_SYMBOLS
    rng = random.SystemRandom()
    for _ in range(50):
        pwd = [
            rng.choice(PWD_UPPER),
            rng.choice(PWD_LOWER),
            rng.choice(PWD_DIGITS),
            rng.choice(PWD_SYMBOLS),
        ]
        pwd += [rng.choice(pool) for _ in range(max(4, length - 4))]
        rng.shuffle(pwd)
        out = "".join(pwd)
        if validate_password(out):
            return out
    return "Arena!" + "".join(
        rng.choice(PWD_LOWER + PWD_DIGITS) for _ in range(8)
    )


# ── 注册客户端（6 步，reference arena_core.py:340-411） ────────────────

class ArenaRegisterClient:
    """One instance per account (cookie isolation, discipline 6)."""

    def __init__(
        self,
        email: str = "",
        password: str = "",
        session=None,
        timeout: float = 25.0,
        log: Optional[Callable[[str], None]] = None,
    ):
        self.email = email
        self.password = password
        self.timeout = timeout
        self.log = log or (lambda msg: None)
        self.session = session or make_session(timeout=timeout)

    def _headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        return arena_headers(ARENA, referer=referer)

    def _check(self, response, what: str) -> None:
        if response.status_code != 200:
            raise ArenaProtocolError(
                f"{what} HTTP {response.status_code}: "
                f"{getattr(response, 'text', '')[:150]}"
            )

    def create_user(self) -> str:
        """Step 2: sign-up. recaptchaToken is NOT validated server-side."""
        response = request_with_retry(
            self.session, "post", f"{ARENA}/nextjs-api/sign-up",
            json={"recaptchaToken": "", "provisionalUserId": str(uuid.uuid4())},
            headers=self._headers(),
        )
        self._check(response, "sign-up")
        try:
            return response.json().get("access_token", "")
        except ValueError:
            return ""

    def send_magic_link(self, email: str, full_name: str = "Arena User") -> None:
        """Step 3: ask arena to email a verification link."""
        response = request_with_retry(
            self.session, "post", f"{ARENA}/nextjs-api/sign-up/magic-link",
            json={
                "email": email,
                "fullName": full_name or "Arena User",
                "shouldLinkHistory": False,
                "marketingConsent": False,
                "registeredCountryCode": "US",
            },
            headers=self._headers(),
        )
        self._check(response, "magic-link")

    def confirm_link(self, link: str) -> str:
        """Step 4b: follow the magic link, grab the set-password token."""
        response = request_with_retry(self.session, "get", link)
        match = re.search(r"token=([^&]+)", str(getattr(response, "url", "")))
        if not match:
            raise ArenaProtocolError("verification link returned no set-password token")
        return match.group(1)

    def set_password(self, token: str, password: str) -> None:
        """Step 5."""
        response = request_with_retry(
            self.session, "post", f"{ARENA}/nextjs-api/auth/set-password",
            json={"password": password, "token": token},
            headers=self._headers(),
        )
        self._check(response, "set-password")

    def sign_in(self) -> bool:
        """Step 6a: email/password login (establishes the session cookie)."""
        response = request_with_retry(
            self.session, "post", f"{ARENA}/nextjs-api/sign-in/email",
            json={"email": self.email, "password": self.password},
            headers=self._headers(referer=ARENA + "/"),
        )
        return response.status_code == 200

    def get_me(self) -> Dict[str, Any]:
        response = request_with_retry(
            self.session, "get", f"{ARENA}/api/me",
            headers=self._headers(referer=ARENA + "/"),
        )
        try:
            return response.json().get("user", {}) if response.status_code == 200 else {}
        except ValueError:
            return {}

    def get_balance(
        self,
        retries: int = 4,
        delay: float = 3.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Dict[str, Any]:
        """Credits lookup (short-lived rate limit → retry, reference :388)."""
        last = ""
        for attempt in range(max(1, retries)):
            try:
                response = request_with_retry(
                    self.session, "get", f"{ARENA}/api/billing/balance",
                    headers=self._headers(referer=ARENA + "/"),
                )
                if response.status_code == 200:
                    return response.json()
                last = f"HTTP {response.status_code}"
            except Exception as exc:  # noqa: BLE001 — keep retrying
                last = str(exc)
            if attempt < retries - 1:
                sleep(delay)
        self.log(f"[!] 查额度失败({last})")
        return {}


# ── 单账号注册编排（reference arena_core.py:449-495） ──────────────────

@dataclass
class RegisterResult:
    email: str = ""
    password: str = ""
    user_id: str = ""
    credits: str = ""
    ok: bool = False
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Never let the password slip into job event payloads (plan §10.1).
        data["password"] = "***" if self.password else ""
        return data


async def register_one(
    mail_provider,
    session_factory: Optional[Callable[[], Any]] = None,
    log: Optional[Callable[[str], None]] = None,
    cancel: Optional[Callable[[], bool]] = None,
    mail_timeout: int = 90,
    domain: Optional[str] = None,
) -> RegisterResult:
    """Register one arena account end-to-end. Never raises.

    The mail provider is *owned* by this call (one provider + one arena
    session per account, both disciplines 3/6): mail goes direct (never
    proxied — 10minutemail blacklists datacenter IPs), arena goes through the
    per-account session.
    """
    log = log or (lambda msg: None)
    result = RegisterResult()

    def stopped() -> bool:
        return bool(cancel and cancel())

    try:
        mailbox = await mail_provider.create_mailbox()
        if domain and not mailbox.email.endswith("@" + domain):
            # provider ignored the requested domain — keep what it gave
            log(f"[!] provider ignored domain request: {mailbox.email}")
        result.email = mailbox.email
        log(f"[*] 邮箱: {mailbox.email}")
        if stopped():
            result.error = "cancelled"
            return result

        client = ArenaRegisterClient(
            email=mailbox.email,
            session=(session_factory() if session_factory else None),
            log=log,
        )
        client.create_user()
        log("[*] 已创建用户")
        if stopped():
            result.error = "cancelled"
            return result

        client.send_magic_link(mailbox.email, "Arena User")
        log("[*] 验证邮件已发送")

        link = await mail_provider.wait_for_link(
            mailbox, VERIFY_LINK_RE, timeout_sec=mail_timeout
        )
        if not link:
            raise ArenaProtocolError("等待验证邮件超时")
        if stopped():
            result.error = "cancelled"
            return result

        token = client.confirm_link(link)
        password = gen_password()
        client.set_password(token, password)
        result.password = password
        client.password = password
        log("[*] 密码已设置")

        # set-password is occasionally flaky server-side: retry once with the
        # same token before giving up (reference register_one:474-482).
        if not client.sign_in():
            log("[!] 首次登录失败，重新设置密码...")
            try:
                client.set_password(token, password)
                time.sleep(1)
            except ArenaProtocolError as exc:
                log(f"[!] 重设密码异常: {exc}")
            if not client.sign_in():
                raise ArenaProtocolError("注册后无法登录（密码设置失败）")
        log("[*] 登录验证通过")

        me = client.get_me()
        result.user_id = str(me.get("id", ""))
        balance = client.get_balance()
        result.credits = str(balance.get("creditsRemaining", ""))
        result.ok = True
        log(f"[+] 注册成功: {mailbox.email} | 额度 {result.credits}")
    except Exception as exc:  # noqa: BLE001 — job layer counts failures
        result.error = f"{type(exc).__name__}: {exc}"
        result.ok = False
        log(f"[!] 失败: {result.error}")
    return result


# ── 抽卡协议客户端（reference arena_draw.py:380-520） ──────────────────

class ArenaDrawClient:
    """Conversation-level draw protocol steps. Waiting policy lives in P4."""

    def __init__(
        self,
        email: str,
        password: str,
        session=None,
        timeout: float = 25.0,
        log: Optional[Callable[[str], None]] = None,
    ):
        self.email = email
        self.password = password
        self.timeout = timeout
        self.log = log or (lambda msg: None)
        self.logged = False
        self.session = session or make_session(timeout=timeout)

    def _headers(self, referer: Optional[str] = None, extra: Optional[Dict] = None):
        return arena_headers(ARENA, referer=referer or (ARENA + "/agent/"), extra=extra)

    def _req(self, method: str, url: str, **kw: Any):
        return request_with_retry(self.session, method, url, **kw)

    def login(self, force: bool = False) -> bool:
        """Sign in once per client; sessions are reused (discipline 8)."""
        if self.logged and not force:
            return True
        response = self._req(
            "post", f"{ARENA}/nextjs-api/sign-in/email",
            json={"email": self.email, "password": self.password},
            headers=self._headers(referer=ARENA + "/"),
        )
        self.logged = response.status_code == 200
        return self.logged

    def create_chat(
        self,
        recaptcha_v3_token: str,
        text: str = DRAW_TEXT,
        timezone: str = DRAW_TIMEZONE,
    ) -> str:
        """Step 3: create a conversation (one draw = one new chat)."""
        body = {
            "message": {
                "id": str(uuid.uuid4()),
                "role": "user",
                "parts": [{"type": "text", "text": text or DRAW_TEXT}],
            },
            "timezone": timezone,
            "recaptchaV3Token": recaptcha_v3_token,
        }
        response = self._req(
            "post", f"{ARENA}/nextjs-api/stream/create-chat",
            json=body, headers=self._headers(),
        )
        if response.status_code == 429:
            cf = is_cf_challenge(response.text)
            raise ArenaRateLimited(
                "429 Cloudflare 挑战（出口 IP 被挡，等待无效）" if cf else "429 限流",
                cf=cf,
            )
        if response.status_code != 200:
            if "recaptcha" in (response.text or "")[:600].lower():
                raise ArenaCaptchaRejected(
                    f"recaptcha rejected: HTTP {response.status_code}"
                )
            raise ArenaProtocolError(
                f"create-chat HTTP {response.status_code}: {response.text[:160]}"
            )
        sid = ""
        try:
            sid = str(response.json().get("id") or "")
        except ValueError:
            pass
        if not sid:
            raise ArenaProtocolError("create-chat 未返回会话 ID")
        return sid

    def session_token(self, sid: str) -> str:
        """Step 4: conversation-scoped Trigger.dev read credential."""
        response = self._req(
            "post", f"{ARENA}/api/chat/trigger-token",
            json={"sessionId": sid},
            headers=self._headers(referer=f"{ARENA}/agent/{sid}"),
        )
        if response.status_code != 200:
            raise ArenaProtocolError(
                f"trigger-token HTTP {response.status_code}: {response.text[:160]}"
            )
        token = ""
        try:
            token = str(response.json().get("token") or "")
        except ValueError:
            pass
        if not token:
            raise ArenaProtocolError("trigger-token 未返回 token")
        return token

    def read_run_token(
        self,
        sid: str,
        token: str,
        wait: float = 90.0,
        cancel: Optional[Callable[[], bool]] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> str:
        """Step 5: subscribe to the SSE out-stream, return public-access-token.

        Frames are split on blank lines and parsed with run_trace_resolver;
        tokens failing JWT validation are skipped (keep waiting) instead of
        failing the round — the reference saw noisy frames before the real
        one.
        """
        url = f"{ARENA}/ai-proxy/realtime/v1/sessions/{sid}/out"
        headers = {
            "Authorization": "Bearer " + token,
            "Accept": "text/event-stream",
            "Referer": f"{ARENA}/agent/{sid}",
            **SSE_HEADERS,
        }
        deadline = time.monotonic() + max(1.0, wait)
        with self.session.stream_get(url, headers=headers) as stream:
            if stream.status_code != 200:
                raise ArenaProtocolError(f"订阅输出流 HTTP {stream.status_code}")
            found = ""
            buf = ""
            for chunk in stream.iter_content(4096):
                if cancel and cancel():
                    raise ArenaProtocolError("用户取消")
                if not chunk:
                    if time.monotonic() > deadline:
                        break
                    continue
                buf += chunk.decode("utf-8", "replace") if isinstance(chunk, bytes) else str(chunk)
                while "\n\n" in buf:
                    frame, buf = buf.split("\n\n", 1)
                    obj = parse_sse_frame(frame)
                    if not obj:
                        continue
                    candidate = extract_public_access_token(obj)
                    if not candidate:
                        continue
                    try:
                        claims = decode_jwt_payload(candidate)
                    except ValueError:
                        continue
                    if not validate_jwt_claims(claims):
                        continue
                    if not extract_run_id_from_claims(claims):
                        continue
                    found = candidate
                if found:
                    break
                if time.monotonic() > deadline:
                    break
        if not found:
            raise ArenaProtocolError("输出流里没等到 public-access-token")
        return found

    def rename_chat(self, sid: str, title: str) -> bool:
        """Step 8a: mark a hit by renaming (kept conversations)."""
        try:
            response = self._req(
                "patch", f"{ARENA}/api/history/agentic/{sid}",
                json={"title": str(title)[:100]},
                headers=self._headers(referer=f"{ARENA}/agent/{sid}"),
            )
            return response.status_code == 200
        except Exception:  # noqa: BLE001 — best effort by design
            return False

    def archive_chat(self, sid: str, archive: bool = True) -> bool:
        """Step 8b: archive/unarchive (default miss action, gentler than delete)."""
        action = "archive" if archive else "unarchive"
        try:
            response = self._req(
                "post", f"{ARENA}/api/chat/{sid}/{action}",
                headers=self._headers(referer=f"{ARENA}/agent/{sid}"),
            )
            return response.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def delete_chat(self, sid: str) -> bool:
        """Step 8c: hard delete (fallback when archive fails)."""
        try:
            response = self._req(
                "delete", f"{ARENA}/api/chat/{sid}",
                headers=self._headers(referer=f"{ARENA}/agent/{sid}"),
            )
            return response.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    # -- Trigger.dev reads (model identification) --------------------------

    def fetch_run_events(
        self,
        run_token: str,
        run_id: str,
        want_internal: bool = False,
        retries: int = 8,
        delay: float = 3.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Dict[str, Any]:
        """Step 6: run events, retried until model labels land.

        ``want_internal`` keeps waiting for the internal config name (usage
        lands later than the model label, reference fetch_run_events).
        """
        url = f"{TRIGGER_API}/api/v1/runs/{run_id}/events"
        headers = {"Authorization": "Bearer " + run_token, "Accept": "application/json"}
        last = ""
        best: Dict[str, Any] = {}
        for attempt in range(max(1, retries)):
            try:
                response = request_with_retry(self.session, "get", url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    models = parse_models(data)
                    if models:
                        if not want_internal or models[0].get("internal"):
                            return data
                        best = data
                        last = "已拿到模型名，继续等内部配置名"
                    else:
                        last = "还没有模型标签"
                else:
                    last = f"HTTP {response.status_code}"
                    if response.status_code in (401, 403, 404):
                        break
            except Exception as exc:  # noqa: BLE001
                last = str(exc)
            if attempt < retries - 1:
                sleep(delay)
        if best:
            return best
        if last.startswith("HTTP"):
            raise ArenaProtocolError(f"读取 trace 失败({last})")
        return {}

    def fetch_span_detail(self, run_token: str, run_id: str, span_id: str) -> Dict[str, Any]:
        """Step 7: one span detail (usage numbers)."""
        url = f"{TRIGGER_API}/api/v1/runs/{run_id}/spans/{span_id}"
        response = request_with_retry(
            self.session, "get", url,
            headers={"Authorization": "Bearer " + run_token, "Accept": "application/json"},
        )
        if response.status_code == 429:
            raise ArenaRateLimited("span 详情限流")
        if response.status_code != 200:
            raise ArenaProtocolError(f"span 详情 HTTP {response.status_code}")
        return response.json()

    def read_usage(
        self,
        run_token: str,
        run_id: str,
        events: Dict[str, Any],
        max_spans: int = 8,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Dict[str, Any]:
        """Span-walk for reasoning/usage numbers (reference read_usage).

        Usage spans are authoritative; stream-span values only fill gaps.
        Any failure degrades to partial data — never breaks the draw round.
        """
        span_events = [
            e for e in (events or {}).get("events") or []
            if isinstance(e, dict) and str(e.get("message")) in SPAN_KINDS
        ]
        usage: Dict[str, Any] = {}
        weak: Dict[str, Any] = {}
        hints: List[str] = []
        stopped = ""
        for index, event in enumerate(span_events[-max_spans:]):
            if index:
                sleep(0.25)
            span_id = str(event.get("spanId") or "")
            kind = SPAN_KINDS.get(str(event.get("message")))
            try:
                detail = self.fetch_span_detail(run_token, run_id, span_id)
            except ArenaRateLimited:
                stopped = "span详情限流"
                break
            except Exception:  # noqa: BLE001 — skip unreadable spans
                continue
            if kind == "usage":
                for key, value in extract_usage(detail, "usage").items():
                    usage.setdefault(key, value)
            elif kind == "stream":
                for key, value in extract_usage(detail, "stream").items():
                    weak.setdefault(key, value)
            for hint in setting_hints(detail):
                if hint not in hints:
                    hints.append(hint)
        for key, value in weak.items():
            usage.setdefault(key, value)
        usage["settingHints"] = hints
        usage["stopped"] = stopped
        return usage


# ── JWT 辅助（复用 run_trace_resolver，两种 claims 格式都支持） ────────

def run_id_from_token(token: str) -> str:
    """run id from a public-access-token (new ``run`` claim or old scopes)."""
    try:
        claims = decode_jwt_payload(token)
    except ValueError as exc:
        raise ArenaProtocolError(f"token 解析失败: {exc}") from exc
    run_id = extract_run_id_from_claims(claims)
    if not run_id:
        raise ArenaProtocolError("token 里没有 read:runs 权限")
    return run_id
