# -*- coding: utf-8 -*-
"""Arena draw engine (plan §2.2/§2.3/§5.8, P4) — pure-protocol draw loop.

One draw = one fresh arena.ai conversation (model assignment is
conversation-level). Chain per ``reference/ArenCard/arena_draw.py``, all six
steps protocol-only, no browser on the draw path:

  1. sign in         POST /nextjs-api/sign-in/email            (session reuse)
  2. reCAPTCHA V3    arena_token_cache.get(consume=True)       (P3 window)
  3. create chat     POST /nextjs-api/stream/create-chat       -> sid
  4. session JWT     POST /api/chat/trigger-token
  5. SSE out stream  GET /ai-proxy/realtime/v1/sessions/{sid}/out
                     -> public-access-token
  6. model resolve   GET api.trigger.dev runs/{run_id}/events
                     (+ optional spans for reasoning tokens)

Frame fix vs the reference ``read_run_token`` (§5.5-D1): the reference
hand-parses SSE and accepts the first header value that *looks* like a
public-access-token, which is exactly where its 90 s "never saw the token"
mystery lives. Here parsing is delegated to ``run_trace_resolver``
(``parse_sse_frame`` handles both list-pair and dict header forms) and a
candidate is only accepted once ``decode_jwt_payload`` +
``validate_jwt_claims`` + ``extract_run_id_from_claims`` all pass — invalid
frames keep waiting instead of ending the round.

Rate-limit experience values (§2.3) are ported verbatim: per-account 429
ladder (15/30/60/90 s, decay 240 s, gap raised to min(60, 5*(lvl+1))),
Cloudflare-challenge detection (dead exit, must switch IP, CF_HOLD 180 s),
global base gap, in-round IP switch at ``switch_level``, reCAPTCHA-reject
double counting feeding the P3 cache's ``mark_rejected`` + a cooldown
circuit breaker (discipline 10: never re-run the reference's recycling
storm).
"""

from __future__ import annotations

import base64
import json
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from backend.services.arena_http import arena_headers, make_session
from backend.services.arena_trace_ext import (
    extract_internal_names,
    extract_usage,
    model_matches,
    parse_models,
    parse_tier,
    setting_hints,
    span_ids,
)
from backend.services.run_trace_resolver import (
    decode_jwt_payload,
    extract_public_access_token,
    extract_run_id_from_claims,
    parse_sse_frame,
    validate_jwt_claims,
)

ARENA = "https://arena.ai"
TRIGGER_API = "https://api.trigger.dev/api/v1"
DRAW_TEXT = "1+1="

#: 429 退避阶梯（秒）；240s 无新 429 自动降一级（参考 :134-135）
GATE_LADDER = (15.0, 30.0, 60.0, 90.0)
GATE_DECAY_AFTER = 240.0
#: 撞过 CF 挑战后 180s 内该出口视为已死（参考 :109）
CF_HOLD = 180.0


class DrawError(RuntimeError):
    """One draw round failed (counted, account stays in rotation)."""


class RateLimited(DrawError):
    """create-chat got a 429; ``switch`` tells the job layer to change IP."""

    def __init__(self, msg: str = "429 限流", cf: bool = False, switch: bool = False):
        super().__init__(msg)
        self.cf = bool(cf)
        self.switch = bool(switch)


def _sleep_cancellable(seconds: float, cancel=None, step: float = 0.4) -> None:
    end = time.monotonic() + max(0.0, float(seconds))
    while True:
        if cancel is not None and cancel():
            raise DrawError("已停止")
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(step, left))


class Gate:
    """Per-account 429 ladder + global throttle (reference §2.3 verbatim).

    One account = one gate (1 号 1 IP). Escalation only ever slows the
    offending account; the global base gap is shared by everyone.
    """

    def __init__(self, base_gap: float = 0.0, clock: Callable[[], float] = time.monotonic):
        self._lock = threading.Lock()
        self._clock = clock
        self._base_gap = float(base_gap or 0.0)
        self._global_last = 0.0
        self._acct_last: Dict[str, float] = {}
        self._acct_gap: Dict[str, float] = {}
        self._gate: Dict[str, Dict[str, Any]] = {}
        self._rej: Dict[str, int] = {}
        self._rej_all = 0
        self._switch_at: Optional[int] = None

    # -- global pacing ------------------------------------------------------

    def set_throttle(self, seconds: float) -> None:
        """Set the global minimum request gap; clears adaptive state."""
        with self._lock:
            self._base_gap = max(0.0, float(seconds or 0))
            self._global_last = 0.0
            self._acct_last.clear()
            self._acct_gap.clear()
            self._gate.clear()

    def set_switch_level(self, level: Optional[int]) -> None:
        """Abort a round (switch IP) once the 429 ladder reaches ``level``."""
        self._switch_at = None if level is None else int(level)

    # -- reCAPTCHA reject double counting ------------------------------------

    def note_recaptcha_reject(self, key: str = "") -> None:
        with self._lock:
            self._rej_all += 1
            if key:
                self._rej[key] = self._rej.get(key, 0) + 1

    def rej_count(self, key: Optional[str] = None) -> int:
        with self._lock:
            return self._rej_all if key is None else self._rej.get(key, 0)

    def reset_rejects(self) -> None:
        with self._lock:
            self._rej.clear()
            self._rej_all = 0

    # -- 429 ladder -----------------------------------------------------------

    @staticmethod
    def is_cf_challenge(body: str) -> bool:
        """A 429 body that is a Cloudflare challenge page (waiting is useless)."""
        try:
            text = (body or "")[:800].lower()
        except Exception:  # noqa: BLE001
            return False
        if "just a moment" in text or "cf-chl" in text or "attention required" in text:
            return True
        return "cloudflare" in text and ("<html" in text or "<!doctype" in text)

    def _rec(self, key: str) -> Dict[str, Any]:
        d = self._gate.get(key)
        if d is None:
            d = {"until": 0.0, "level": 0, "last": 0.0, "cf": 0.0}
            self._gate[key] = d
        return d

    def note_rate_limited(self, key: str, why: str = "", cf: bool = False) -> None:
        now = self._clock()
        with self._lock:
            d = self._rec(key)
            if now - d["last"] > GATE_DECAY_AFTER:
                d["level"] = 0
            lvl = min(d["level"], len(GATE_LADDER) - 1)
            wait = GATE_LADDER[lvl]
            d["until"] = max(d["until"], now + wait)
            d["level"] = min(d["level"] + 1, len(GATE_LADDER))
            d["last"] = now
            if cf:
                d["cf"] = now
            self._acct_gap[key] = min(
                60.0, max(self._acct_gap.get(key, 0.0), 5.0 * (lvl + 1))
            )

    def gate_wait(self, key: str, cancel=None) -> float:
        now = self._clock()
        with self._lock:
            d = self._rec(key)
            left = d["until"] - now
            if left <= 0:
                if d["level"] and (now - d["last"]) > GATE_DECAY_AFTER:
                    d["level"] = max(0, d["level"] - 1)
                return 0.0
        _sleep_cancellable(left, cancel)
        return left

    def gate_reset(self, key: str) -> None:
        with self._lock:
            d = self._rec(key)
            d.update({"until": 0.0, "level": 0, "last": 0.0, "cf": 0.0})
            self._acct_gap.pop(key, None)

    def gate_status(self, key: Optional[str] = None) -> Dict[str, Any]:
        now = self._clock()
        with self._lock:
            if key is not None:
                d = self._rec(key)
                lvl = min(d["level"], len(GATE_LADDER) - 1)
                return {
                    "key": key,
                    "left": max(0.0, d["until"] - now),
                    "level": d["level"],
                    "gap": self._acct_gap.get(key, 0.0),
                    "wait": GATE_LADDER[lvl],
                    "cf": (now - d.get("cf", 0.0)) < CF_HOLD,
                }
            return {
                k: {
                    "left": max(0.0, d["until"] - now),
                    "level": d["level"],
                    "gap": self._acct_gap.get(k, 0.0),
                    "cf": (now - d.get("cf", 0.0)) < CF_HOLD,
                }
                for k, d in self._gate.items()
            }

    def throttle(self, key: str, cancel=None) -> None:
        """Pre-create-chat wait: own 429 backoff → global gap → raised gap."""
        self.gate_wait(key, cancel)
        while True:
            with self._lock:
                now = self._clock()
                wait = max(
                    self._base_gap - (now - self._global_last),
                    self._acct_gap.get(key, 0.0) - (now - self._acct_last.get(key, 0.0)),
                )
                if wait <= 0:
                    self._global_last = now
                    self._acct_last[key] = now
                    return
            _sleep_cancellable(wait, cancel)


def gate_key(email: str = "", proxy: str = "") -> str:
    return (email.split("@")[0] if email else "") or (proxy or "direct")


class DrawClient:
    """One arena account's draw client (own session, own gate key)."""

    def __init__(
        self,
        email: str,
        password: str,
        proxy: str = "",
        log: Optional[Callable[..., None]] = None,
        timeout: float = 45.0,
        session: Any = None,
        gate: Optional[Gate] = None,
        http_backend: str = "httpx",
        ua: str = "",
    ):
        self.email = email
        self.password = password
        self.timeout = timeout
        #: 出票窗口的实测 navigator.userAgent（token 快照带回）。转发的是
        #: 真实测量值而非手写 UA（纪律 2）：reCAPTCHA Enterprise 的评分
        #: 会比对解题浏览器与呈现请求的 UA 一致性。
        self.ua = str(ua or "")
        self.log = log or (lambda *a, **k: None)
        self.gate = gate or Gate()
        self._gate_key = gate_key(email, proxy)
        self.s = session if session is not None else make_session(
            proxy_url=proxy, backend=http_backend, timeout=timeout
        )
        self.logged = False

    def _h(self, referer: Optional[str] = None, extra: Optional[Dict[str, str]] = None):
        headers = arena_headers(ARENA, referer=referer, extra=extra)
        if self.ua:
            headers["User-Agent"] = self.ua  # 实测转发（见 __init__ 注释）
        return headers

    def close(self) -> None:
        try:
            self.s.close()
        except Exception:  # noqa: BLE001
            pass

    def _req(self, method: str, url: str, retries: int = 3, **kw):
        """arena.ai 偶发读超时（参考实测一天 4 次），统一网络级重试。"""
        last: Optional[Exception] = None
        for i in range(max(1, retries)):
            try:
                return self.s.request(method, url, **kw)
            except Exception as e:  # noqa: BLE001
                last = e
                if i < retries - 1:
                    time.sleep(1.5 * (i + 1))
        raise DrawError(f"网络请求失败({type(last).__name__}): {url}")

    # ── protocol steps ──────────────────────────────────────────────────

    def login(self, force: bool = False) -> bool:
        """Sign in; reuse the session afterwards (saves rate-limit budget)."""
        if self.logged and not force:
            return True
        r = self._req(
            "POST",
            ARENA + "/nextjs-api/sign-in/email",
            json={"email": self.email, "password": self.password},
            headers=self._h(ARENA + "/"),
        )
        self.logged = r.status_code == 200
        return self.logged

    def create_chat(self, tokens: Dict[str, str], text: str = DRAW_TEXT, cancel=None) -> str:
        body = {
            "message": {
                "id": str(uuid.uuid4()),
                "role": "user",
                "parts": [{"type": "text", "text": text or DRAW_TEXT}],
            },
            "timezone": "Asia/Shanghai",
        }
        body.update(tokens or {})
        self.gate.throttle(self._gate_key, cancel)
        r = self._req(
            "POST", ARENA + "/nextjs-api/stream/create-chat", json=body, headers=self._h()
        )
        if r.status_code == 429:
            cf = Gate.is_cf_challenge(getattr(r, "text", "") or "")
            self.gate.note_rate_limited(
                self._gate_key, "cloudflare" if cf else "create-chat", cf=cf
            )
            switch = False
            if self.gate._switch_at is not None:
                switch = bool(cf) or int(
                    self.gate.gate_status(self._gate_key).get("level", 0)
                ) >= int(self.gate._switch_at)
            raise RateLimited(
                "429 Cloudflare 挑战（出口 IP 被挡，等待无效）" if cf else "429 限流",
                cf=cf,
                switch=switch,
            )
        if r.status_code != 200:
            try:
                if "recaptcha" in (getattr(r, "text", "") or "")[:600].lower():
                    self.gate.note_recaptcha_reject(self._gate_key)
            except Exception:  # noqa: BLE001
                pass
            raise DrawError(f"create-chat HTTP {r.status_code}: {getattr(r, 'text', '')[:160]}")
        sid = str((r.json() or {}).get("id") or "")
        if not sid:
            raise DrawError("create-chat 未返回会话 ID")
        return sid

    def session_token(self, sid: str) -> str:
        r = self._req(
            "POST",
            ARENA + "/api/chat/trigger-token",
            json={"sessionId": sid},
            headers=self._h(ARENA + f"/agent/{sid}"),
        )
        if r.status_code != 200:
            raise DrawError(f"trigger-token HTTP {r.status_code}: {getattr(r, 'text', '')[:160]}")
        tok = str((r.json() or {}).get("token") or "")
        if not tok:
            raise DrawError("trigger-token 未返回 token")
        return tok

    def read_run_token(self, sid: str, token: str, wait: float = 90.0, cancel=None) -> str:
        """Subscribe the /out stream until a *validated* public-access-token.

        Frame fix (§5.5-D1): parse via run_trace_resolver and require the JWT
        to actually carry a run id — invalid frames keep waiting instead of
        ending the round (the reference's 90 s mystery).
        """
        url = f"{ARENA}/ai-proxy/realtime/v1/sessions/{sid}/out"
        h = {
            "Authorization": "Bearer " + token,
            "Accept": "text/event-stream",
            "Referer": ARENA + f"/agent/{sid}",
            "x-trigger-source": "sdk",
            "x-trigger-realtime-streams-version": "v2",
        }
        with self.s.stream_get(url, headers=h) as resp:
            if resp.status_code != 200:
                raise DrawError(f"订阅输出流 HTTP {resp.status_code}")
            deadline = time.monotonic() + wait
            buf = ""
            for chunk in resp.iter_content(4096):
                if cancel is not None and cancel():
                    raise DrawError("已停止")
                if not chunk:
                    if time.monotonic() > deadline:
                        break
                    continue
                buf += chunk.decode("utf-8", "replace") if isinstance(chunk, bytes) else str(chunk)
                while "\n\n" in buf:
                    frame, buf = buf.split("\n\n", 1)
                    # resolver 的 _strip_sse_prefix 会把非 data: 行（如 event:）
                    # 当正文拼进去 → 先滤出纯 data: 载荷再解析（参考 :485 同款）
                    data = "\n".join(
                        ln.strip()[5:].lstrip()
                        for ln in frame.split("\n")
                        if ln.strip().startswith("data:")
                    )
                    if not data:
                        continue
                    obj = parse_sse_frame(data)
                    if obj is None:
                        continue
                    candidate = extract_public_access_token(obj)
                    if not candidate:
                        continue
                    try:
                        claims = decode_jwt_payload(candidate)
                        if not validate_jwt_claims(claims):
                            continue
                        if not extract_run_id_from_claims(claims):
                            continue
                        return candidate
                    except Exception:  # noqa: BLE001 — 坏帧继续等，不失败
                        continue
                if time.monotonic() > deadline:
                    break
        raise DrawError("输出流里没等到 public-access-token")

    def rename_chat(self, sid: str, title: str) -> bool:
        try:
            r = self._req(
                "PATCH",
                f"{ARENA}/api/history/agentic/{sid}",
                json={"title": str(title)[:100]},
                headers=self._h(ARENA + f"/agent/{sid}"),
            )
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def archive_chat(self, sid: str, archive: bool = True) -> bool:
        action = "archive" if archive else "unarchive"
        try:
            r = self._req(
                "POST",
                f"{ARENA}/api/chat/{sid}/{action}",
                headers=self._h(ARENA + f"/agent/{sid}"),
            )
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def delete_chat(self, sid: str) -> bool:
        try:
            r = self._req(
                "DELETE",
                ARENA + f"/api/chat/{sid}",
                headers=self._h(ARENA + f"/agent/{sid}"),
            )
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False


def run_id_from_token(token: str) -> str:
    """Run id from the session JWT (new ``run`` claim + legacy ``scopes``)."""
    claims = decode_jwt_payload(token)
    run_id = extract_run_id_from_claims(claims)
    if not run_id:
        raise DrawError("token 里没有 read:runs 权限")
    return run_id


def fetch_run_events(
    run_token: str,
    run_id: str,
    session: Any = None,
    retries: int = 8,
    delay: float = 3.0,
    want_internal: bool = False,
    log: Optional[Callable[..., None]] = None,
) -> Dict[str, Any]:
    """GET runs/{run_id}/events with the resolver's 8×3s retry shape.

    401/403/404 stop immediately (bad credentials / wrong id never recover).
    ``want_internal`` keeps retrying until an internal config name lands
    (usage is written later than the model label, reference read_usage note).
    """
    log = log or (lambda *a, **k: None)
    s = session
    url = f"{TRIGGER_API}/runs/{run_id}/events"
    h = {"Authorization": "Bearer " + run_token}
    best: Dict[str, Any] = {"events": []}
    last_error = ""
    for attempt in range(max(1, retries)):
        try:
            r = (s or make_session()).get(url, headers=h)
            if r.status_code in (401, 403, 404):
                last_error = f"HTTP {r.status_code}"
                break
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    best = data
                    if not want_internal or extract_internal_names(data):
                        return data
                    last_error = "internal name 尚未落盘"
                else:
                    last_error = "非 dict 响应"
            else:
                last_error = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last_error = f"{type(e).__name__}: {str(e)[:80]}"
        if attempt < retries - 1:
            time.sleep(delay)
    if best.get("events"):
        log(f"[!] run events 未完整（{last_error}），best-effort 返回")
        return best
    raise DrawError(f"读取 run events 失败: {last_error}")


def fetch_span_detail(
    run_token: str,
    run_id: str,
    span_id: str,
    session: Any = None,
    timeout: float = 25.0,
) -> Dict[str, Any]:
    s = session
    r = (s or make_session(timeout=timeout)).get(
        f"{TRIGGER_API}/runs/{run_id}/spans/{span_id}",
        headers={"Authorization": "Bearer " + run_token},
    )
    if r.status_code != 200:
        raise DrawError(f"span HTTP {r.status_code}")
    data = r.json()
    return data if isinstance(data, dict) else {}


def read_usage(
    run_token: str,
    run_id: str,
    events: Dict[str, Any],
    session: Any = None,
    max_spans: int = 8,
    log: Optional[Callable[..., None]] = None,
) -> Dict[str, Any]:
    """Reasoning tokens etc. from span details (usage first, stream fallback)."""
    log = log or (lambda *a, **k: None)
    out: Dict[str, Any] = {}
    ids = span_ids(events, max_n=max_spans)
    for span_id in ids:
        try:
            detail = fetch_span_detail(run_token, run_id, span_id, session=session)
        except Exception as e:  # noqa: BLE001
            if "429" in str(e):
                break
            log(f"[!] span {span_id[:8]} 读取失败: {str(e)[:50]}")
            continue
        for kind in ("usage", "stream"):
            fields = extract_usage(detail, kind)
            if fields:
                hints = setting_hints(detail)
                if hints:
                    fields["settingHints"] = hints
                return fields
    return out


# ---------------------------------------------------------------------------
# draw round
# ---------------------------------------------------------------------------

def draw_once(
    account: Dict[str, Any],
    password: str,
    token_cache: Any,
    gate: Gate,
    keep_pattern: str = "",
    miss_action: str = "archive",
    rename_hit: bool = True,
    require_reasoning: bool = False,
    want_reasoning: bool = True,
    text: str = DRAW_TEXT,
    stream_wait: float = 90.0,
    token_wait_sec: float = 8.0,
    captcha_retries: int = 2,
    client: Optional[DrawClient] = None,
    session: Any = None,
    http_backend: str = "httpx",
    stage: Optional[Callable[..., None]] = None,
    log: Optional[Callable[..., None]] = None,
    cancel=None,
) -> Dict[str, Any]:
    """One draw for one account. Returns the result row (ok/kept/switch...).

    ``token_cache`` is the P3 ``TokenWindowCache``: the V3 token is taken
    with ``consume=True`` (V3 tokens are single-use per create_chat), waiting
    up to ``token_wait_sec`` — a timeout fails the round with
    「token 窗口不可用」 rather than degrading to paid paths.
    """
    email = str(account.get("email") or "")
    log = log or (lambda *a, **k: None)
    stage = stage or (lambda *a, **k: None)
    proxy = str(account.get("proxy_url") or "")
    res: Dict[str, Any] = {
        "email": email,
        "model": "",
        "internal": "",
        "provider": "",
        "session_id": "",
        "run_id": "",
        "kept": False,
        "ok": False,
        "error": "",
        "reasoning": "",
        "tokens_in": "",
        "tokens_out": "",
        "tier": "",
        "setting_hints": "",
        "switch": False,
    }
    c = client
    if c is None:
        c = DrawClient(
            email, password, proxy=proxy, log=log, gate=gate,
            session=session, http_backend=http_backend,
        )
    res["_client"] = c  # 复用登录态：同号后续轮次免重复登录（省限流额度）
    try:
        if not c.logged:
            stage("登录中")
            if cancel is not None and cancel():
                raise DrawError("已停止")
            if not c.login():
                raise DrawError("登录失败")

        sid = ""
        last_err = ""
        tokens: Dict[str, str] = {}
        backoffs = (0, 15, 30, 60)

        for attempt in range(1, max(1, captcha_retries) + 1):
            if not tokens:
                stage(f"取token(第{attempt}次)")
                try:
                    snap = token_cache.get(
                        wait_sec=token_wait_sec, consume=True
                    ) if token_cache is not None else None
                    if snap and snap.get("token"):
                        tokens = {"recaptchaV3Token": snap["token"]}
                        if snap.get("ua") and not getattr(c, "ua", ""):
                            c.ua = str(snap["ua"])  # 与出票窗口同 UA
                except Exception as e:  # noqa: BLE001
                    log(f"[!] token 服务不可用({str(e)[:60]})")
                if not tokens:
                    raise DrawError("token 窗口不可用（未取到新鲜 V3 token）")

            for bi, wait in enumerate(backoffs):
                if wait:
                    stage(f"限流退避 {wait}s")
                    log(f"[!] 被限流(429)，等 {wait} 秒后重试（复用同一 token）")
                    _sleep_cancellable(wait, cancel)
                try:
                    if cancel is not None and cancel():
                        raise DrawError("已停止")
                    stage("建会话中")
                    sid = c.create_chat(tokens, text, cancel=cancel)
                    break
                except RateLimited as e:
                    last_err = str(e)
                    if getattr(e, "switch", False):
                        raise  # 到档：交给上层换 IP 重跑
                    if bi == len(backoffs) - 1:
                        break
                    continue
                except DrawError as e:
                    last_err = str(e)
                    break

            if sid:
                break
            tokens = {}
            kind = (
                "recaptcha" if "recaptcha" in last_err
                else "429" if "429" in last_err
                else "other"
            )
            # reCAPTCHA 拒 → 回写 P3 cache（熔断输入）+ 退避换新 token
            if token_cache is not None and kind == "recaptcha":
                try:
                    token_cache.mark_rejected("create-chat recaptcha")
                except Exception:  # noqa: BLE001
                    pass
            if attempt < captcha_retries:
                pause = 10 if kind == "recaptcha" else 20 if kind == "429" else 0
                if pause:
                    stage(f"{'reCAPTCHA' if kind == 'recaptcha' else '限流'}退避 {pause}s")
                    _sleep_cancellable(pause, cancel)
                    continue
            raise DrawError(last_err or "建会话失败")

        res["session_id"] = sid
        log(f"[*] 会话 {sid[:8]}… 已建")
        stage("取会话凭据")
        tok = c.session_token(sid)
        stage("等待回答…")
        run_tok = c.read_run_token(sid, tok, wait=stream_wait, cancel=cancel)
        run_id = run_id_from_token(run_tok)
        res["run_id"] = run_id
        stage("读取模型名…")
        events = fetch_run_events(run_tok, run_id, session=getattr(c, "s", None), want_internal=True, log=log)
        models = parse_models(events)
        if not models:
            raise DrawError("trace 里没有模型标签")
        top = models[0]
        res["model"] = top.get("model", "")
        res["provider"] = top.get("provider", "")
        res["internal"] = top.get("internal", "")

        usage: Dict[str, Any] = {}
        if want_reasoning:
            stage("读取思考强度…")
            try:
                usage = read_usage(run_tok, run_id, events, session=getattr(c, "s", None), log=log)
            except Exception as e:  # noqa: BLE001
                log(f"[!] 读 span 详情失败: {str(e)[:50]}")
        if usage:
            res["reasoning"] = usage.get("reasoningTokens", "")
            res["tokens_in"] = usage.get("inputTokens", "")
            res["tokens_out"] = usage.get("outputTokens", "")
            if usage.get("modelName"):
                res["internal"] = str(usage["modelName"])
            _base, tier = parse_tier(res["internal"])
            res["tier"] = tier
            res["setting_hints"] = ",".join(usage.get("settingHints") or [])

        log(f"[+] 抽到 {res['model']}" + (f" (内部名 {res['internal']})" if res["internal"] else ""))

        has_reasoning = isinstance(res["reasoning"], int) and res["reasoning"] > 0
        matches = model_matches(res["model"], res["internal"], keep_pattern)
        if require_reasoning and not has_reasoning:
            if matches:
                log("[*] 模型命中但无推理 token，按「只保留有推理」规则丢弃")
            matches = False
        if matches:
            res["kept"] = True
            stage("命中保留")
            title = res["internal"] or res["model"]
            if res["reasoning"] != "":
                title = f"{title}·r{res['reasoning']}"
            if rename_hit and c.rename_chat(sid, title):
                log(f"[+] 命中！会话已改名为 {title[:100]}")
                stage("已改名 " + title[:18])
            elif rename_hit:
                log("[+] 命中保留规则（改名失败）")
        else:
            stage("未命中·" + miss_action)
            if miss_action == "keep":
                log("[*] 未命中，按策略保留会话")
            elif miss_action == "delete":
                log("[*] 未命中，删除会话")
                if not c.delete_chat(sid):
                    log("[!] 会话删除失败")
            else:
                log("[*] 未命中，归档会话")
                if c.archive_chat(sid, True):
                    log("[*] 会话已归档")
                elif c.delete_chat(sid):
                    log("[!] 归档失败，已改为删除")
                else:
                    log("[!] 归档与删除都失败")
        res["ok"] = True
    except RateLimited as e:
        if getattr(e, "switch", False):
            res["switch"] = True
            res["error"] = str(e)
            log("[!] 429 到档，交给上层换 IP 后重跑")
        else:
            res["error"] = str(e)
            log(f"[!] 抽卡失败: {e}")
    except Exception as e:  # noqa: BLE001 — 单轮失败不炸 job
        res["error"] = str(e)
        log(f"[!] 抽卡失败: {e}")
        stage("失败: " + str(e)[:24])
    return res


# ---------------------------------------------------------------------------
# job layer
# ---------------------------------------------------------------------------

from backend.services.arena_jobs import JobStore  # noqa: E402

_JOB_STORE: Optional[JobStore] = None
_JOB_STORE_LOCK = threading.Lock()


def get_job_store() -> JobStore:
    global _JOB_STORE
    with _JOB_STORE_LOCK:
        if _JOB_STORE is None:
            _JOB_STORE = JobStore()
        return _JOB_STORE


def _reset_store_for_tests() -> None:
    global _JOB_STORE
    with _JOB_STORE_LOCK:
        _JOB_STORE = None


def _stage_logger(job_store: "JobStore", job_id: str):
    def log(message: str, level: str = "info", kind: str = "log") -> None:
        try:
            job_store.append_event(job_id, level=level, kind=kind, message=str(message))
        except Exception:  # noqa: BLE001 — 事件失败不影响抽卡
            pass
    return log


def _acquire_proxy(provider: Any, exclude_sids: set) -> Optional[str]:
    """Acquire a live proxy (None = direct). Never raises."""
    if provider is None:
        return None
    try:
        from backend.services.arena_proxies import proxy_alive

        for _ in range(3):
            url = provider.acquire(exclude_sids=exclude_sids)
            if not url:
                return None
            if proxy_alive(url):
                return url
    except Exception:  # noqa: BLE001
        return None
    return None


def start_draw_job(
    params: Dict[str, Any],
    accounts_service: Any,
    config: Any,
    job_store: Optional[JobStore] = None,
    proxy_provider: Any = None,
    token_cache: Any = None,
) -> str:
    """Launch a draw job; returns the job id immediately (worker in background).

    ``params`` keys: account_ids (list) | all_accounts (bool),
    rounds_per_account, keep_pattern, require_reasoning, want_reasoning,
    miss_action, rename_hit, base_gap_sec, switch_level.
    Empty/None values inherit from ``config.draw``.
    """
    store = job_store or get_job_store()
    draw_cfg = config.draw

    account_ids: List[str] = [str(a) for a in (params.get("account_ids") or [])]
    if params.get("all_accounts"):
        account_ids = []
    if not account_ids and not params.get("all_accounts"):
        raise ValueError("account_ids 与 all_accounts 至少提供一个")

    miss_action = str(params.get("miss_action") or draw_cfg.miss_action or "archive")
    if miss_action not in ("archive", "delete", "keep"):
        raise ValueError(f"invalid miss_action: {miss_action!r}")
    rounds = int(params.get("rounds_per_account") or 1)
    if not 1 <= rounds <= 100:
        raise ValueError("rounds_per_account 应在 1-100")
    keep_pattern = str(params.get("keep_pattern") or draw_cfg.keep_pattern or "")
    require_reasoning = bool(
        draw_cfg.require_reasoning
        if params.get("require_reasoning") is None
        else params["require_reasoning"]
    )
    want_reasoning = bool(params.get("want_reasoning", True))
    rename_hit = bool(params.get("rename_hit", True))
    base_gap = float(
        draw_cfg.base_gap_sec if params.get("base_gap_sec") is None else params["base_gap_sec"]
    )
    switch_level = (
        draw_cfg.switch_level if params.get("switch_level") is None else params["switch_level"]
    )
    token_wait_sec = float(getattr(draw_cfg, "token_wait_sec", 8.0))
    reject_threshold = int(getattr(draw_cfg, "reject_threshold", 10))
    cooldown_sec = float(getattr(draw_cfg, "cooldown_sec", 120.0))

    accounts: List[Dict[str, Any]] = []
    if account_ids:
        for account_id in account_ids:
            acct = accounts_service.get_account(account_id)
            if acct is None:
                raise ValueError(f"unknown account: {account_id}")
            accounts.append(acct)
    else:
        accounts = [
            a
            for a in (accounts_service.list_accounts() or [])
            if str(a.get("state") or "") == "available"
        ]
    if not accounts:
        raise ValueError("没有可用账号（account_ids 为空或账号池无 available 账号）")

    total = len(accounts) * rounds
    job = store.create(
        "draw",
        total=total,
        params={
            "accounts": [a.get("email") or a.get("id") for a in accounts],
            "rounds": rounds,
            "keep_pattern": keep_pattern,
            "miss_action": miss_action,
            "require_reasoning": require_reasoning,
            "switch_level": switch_level,
        },
    )
    log = _stage_logger(store, job.id)

    def cancel() -> bool:
        return store.is_stop_requested(job.id)

    def worker() -> None:
        gate = Gate(base_gap=base_gap)
        gate.set_switch_level(switch_level)
        ok = failed = hits = 0
        clients: Dict[str, DrawClient] = {}
        try:
            for round_no in range(1, rounds + 1):
                for account in accounts:
                    if cancel():
                        raise DrawError("已停止")
                    account_id = str(account.get("id"))
                    email = str(account.get("email") or account_id)
                    # 熔断：全局 reCAPTCHA 拒绝超阈值 → 冷却 + 建议 token 窗口换 IP
                    if reject_threshold and gate.rej_count() >= reject_threshold:
                        log(
                            f"[!] reCAPTCHA 全局拒绝 {gate.rej_count()} 次 ≥ {reject_threshold}，"
                            f"冷却 {cooldown_sec:.0f}s（建议 token 窗口更换出口 IP）",
                            level="warning",
                        )
                        if token_cache is not None and proxy_provider is not None:
                            url = _acquire_proxy(proxy_provider, set())
                            if url and token_cache is not None:
                                try:
                                    token_cache.request_proxy_change(url)
                                    log("[*] 已下发 token 窗口换 IP")
                                except Exception:  # noqa: BLE001
                                    pass
                        _sleep_cancellable(cooldown_sec, cancel)
                        gate.reset_rejects()

                    res = draw_once(
                        account,
                        # 明文密码只进登录调用，不落日志/事件（spec §10）
                        accounts_service.get_secret(account_id) or "",
                        token_cache=token_cache,
                        gate=gate,
                        keep_pattern=keep_pattern,
                        miss_action=miss_action,
                        rename_hit=rename_hit,
                        require_reasoning=require_reasoning,
                        want_reasoning=want_reasoning,
                        token_wait_sec=token_wait_sec,
                        client=clients.get(email),
                    )
                    if res.get("_client") is not None:
                        clients[email] = res["_client"]

                    if res.get("switch"):
                        # 换 IP：换绑代理 → gate 复位 → 本轮重跑（不计失败）
                        log(f"[!] {email} 429 到档，尝试换 IP 重跑")
                        if proxy_provider is not None:
                            new_proxy = _acquire_proxy(proxy_provider, set())
                            if new_proxy:
                                accounts_service.update_binding(
                                    account_id, proxy_url=new_proxy
                                )
                                account = dict(account, proxy_url=new_proxy)
                                clients.pop(email, None)
                                gate.gate_reset(gate_key(email, new_proxy))
                                log("[*] 已换绑代理，重跑本轮")
                                redo = draw_once(
                                    account,
                                    accounts_service.get_secret(account_id) or "",
                                    token_cache=token_cache,
                                    gate=gate,
                                    keep_pattern=keep_pattern,
                                    miss_action=miss_action,
                                    rename_hit=rename_hit,
                                    require_reasoning=require_reasoning,
                                    want_reasoning=want_reasoning,
                                    token_wait_sec=token_wait_sec,
                                )
                                res = redo
                        if res.get("switch"):
                            log(f"[!] {email} 换 IP 后仍到档，计一次失败", level="warning")

                    # 账号级失败隔离（既有语义，阈值 3）
                    if res.get("ok"):
                        ok += 1
                        if res.get("kept"):
                            hits += 1
                        accounts_service.release_account(account_id)
                    else:
                        failed += 1
                        if "429" in str(res.get("error") or ""):
                            accounts_service.record_failure(account_id, "rate_limited")
                        elif "登录失败" in str(res.get("error") or ""):
                            accounts_service.record_failure(account_id, "login_failed")
                        else:
                            accounts_service.record_failure(account_id, "draw_error")

                    payload = {
                        k: res.get(k, "")
                        for k in (
                            "email", "model", "internal", "provider", "session_id",
                            "run_id", "kept", "ok", "error", "reasoning",
                            "tokens_in", "tokens_out", "tier", "setting_hints",
                        )
                    }
                    accounts_service.record_draw(account_id, payload)
                    store.append_event(
                        job.id,
                        level="info" if res.get("ok") else "warning",
                        kind="draw",
                        message=(
                            f"抽到 {res.get('model') or '?'}"
                            + ("（命中）" if res.get("kept") else "（未命中）")
                            if res.get("ok")
                            else f"失败: {str(res.get('error'))[:80]}"
                        ),
                        data=payload,
                    )
                    if res.get("ok") and res.get("model"):
                        log(
                            f"[+] 第 {round_no} 轮 {email}: {res['model']}"
                            + (f" / {res['internal']}" if res.get("internal") else "")
                        )
        except DrawError as e:
            log(f"job 终止: {e}", level="warning")
        except Exception as e:  # noqa: BLE001 — worker 兜底
            log(f"job 异常: {type(e).__name__}: {e}", level="error")
        finally:
            for c in clients.values():
                if c is not None:
                    c.close()
            final_status = "stopped" if cancel() else "done"
            store.finish(job.id, final_status, ok, failed)
            store.append_event(
                job.id,
                "info",
                "done",
                f"job {final_status}: 成功 {ok} / 失败 {failed} / 命中 {hits} / 共 {total}",
                data={"hits": hits},
            )

    threading.Thread(target=worker, name=f"arena-draw-{job.id[:8]}", daemon=True).start()
    return job.id
