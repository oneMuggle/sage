"""In-memory reCAPTCHA V3 token cache fed by the Electron token window (P3).

Push model (plan §5.9/§5.10): the hidden Electron window polls
``GET /api/v1/arena/token-window/state``; when the backend raises ``needed``
(a draw thread is waiting) or on warmup, the window mints a fresh V3 token
and POSTs it to ``/token-window/push``. Draw threads block on the condition
variable until a fresh-enough token arrives (plan §5.8 ``token_wait_sec``,
consumed by the P4 draw engine).

Reference: ``reference/ArenCard/token_server.py`` (pull model). The
reference's hard-won semantics preserved here:

- ``ready`` is only a hint — the *window* mints even when its own ready flag
  is stale, retrying after a reload; the *cache* simply reports whether a
  fresh token exists (``health.ready``).
- reCAPTCHA V3 tokens live ~2 min → ``max_age_sec`` (default 110) bounds
  usability; a pushed token older than that is never handed to a draw.
- proxy switching goes through the *backend* relay: Chromium ignores proxy
  credentials, so ``request_proxy_change`` maps the upstream proxy onto the
  local CONNECT relay (``arena_proxy_relay.local_proxy``) before the window
  sees it in ``state.proxy_url``. ``token_window.use_proxy`` (config) is
  consumed by the P4 draw engine, which owns the blocking proxy acquire;
  P3 delivers the mechanism with the window running direct.

All state is process-local and in-memory; nothing here touches disk.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


class ArenaTokenWindowError(ValueError):
    """Invalid push payload (token shape) — maps to HTTP 400."""


class TokenWindowCache:
    """Thread-safe token cache with condition-variable wake for draw threads."""

    def __init__(
        self,
        max_age_sec: float = 110.0,
        poll_interval_sec: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_age = float(max_age_sec)
        self._poll_interval = float(poll_interval_sec)
        self._clock = clock
        self._cond = threading.Condition(threading.Lock())
        self._token: Optional[str] = None
        self._received_at: Optional[float] = None
        self._exit_ip: str = ""
        self._ua: str = ""
        self._count: int = 0
        self._error: str = ""
        self._needed: bool = False
        self._reject_count: int = 0
        self._want_proxy: bool = False
        self._proxy_url: str = ""
        self._started_at = time.time()

    # ── Electron window side ───────────────────────────────────────────

    def push(
        self,
        token: str,
        exit_ip: Optional[str] = None,
        ua: Optional[str] = None,
    ) -> Dict:
        """Store a freshly minted token; returns ``{ok, age_sec}``.

        ``age_sec`` is how old the *replaced* token was (refresh telemetry);
        ``0`` on the first push.
        """
        token = str(token or "")
        # reCAPTCHA V3 tokens are long signed JWT-ish strings (P1 measured
        # 2489/2617 chars). Anything tiny or enormous is a protocol error.
        if not 50 <= len(token) <= 20000:
            raise ArenaTokenWindowError("token 长度异常（应为 reCAPTCHA V3 形态）")
        now = self._clock()
        with self._cond:
            prev_age = 0.0
            if self._received_at is not None:
                prev_age = max(0.0, now - self._received_at)
            self._token = token
            self._received_at = now
            if exit_ip:
                self._exit_ip = str(exit_ip)[:64]
            if ua:
                self._ua = str(ua)[:256]
            self._count += 1
            self._error = ""
            self._needed = False
            self._cond.notify_all()
            return {"ok": True, "age_sec": round(prev_age, 3)}

    # ── draw side (consumed by the P4 draw engine) ─────────────────────

    def get(
        self,
        max_age_sec: Optional[float] = None,
        wait_sec: float = 0.0,
        consume: bool = False,
    ) -> Optional[Dict]:
        """Return a fresh token snapshot, waiting up to ``wait_sec``.

        While waiting, ``needed`` is raised so the window pre-mints; a push
        wakes this call immediately. ``None`` when no fresh token arrived in
        time (draw round must fail with "token 窗口不可用", plan §6.3).

        ``consume=True`` (draw path): V3 tokens are single-use per
        create_chat, so the snapshot is returned once and the slot cleared —
        the next ``get`` raises ``needed`` and the window pre-mints. Without
        it the same fresh token may be re-read (diagnostics / warm reads).
        """
        max_age = self._max_age if max_age_sec is None else float(max_age_sec)
        with self._cond:
            end = self._clock() + max(0.0, float(wait_sec))
            while True:
                if self._token is not None and self._received_at is not None:
                    age = self._clock() - self._received_at
                    if age <= max_age:
                        snapshot = {
                            "token": self._token,
                            "exit_ip": self._exit_ip,
                            "ua": self._ua,
                            "age_sec": round(age, 3),
                        }
                        if consume:
                            self._token = None
                            self._received_at = None
                        return snapshot
                if self._clock() >= end:
                    return None
                # A draw is waiting → the window should mint right now.
                self._needed = True
                self._cond.wait(min(end - self._clock(), 0.5))

    # ── control / diagnostics ──────────────────────────────────────────

    def mark_needed(self) -> None:
        """Raise ``needed`` explicitly (draw engine about to ask for a token)."""
        with self._cond:
            self._needed = True

    def mark_rejected(self, reason: str = "") -> None:
        """Count a reCAPTCHA rejection at create_chat (熔断 input, plan §5.8)."""
        with self._cond:
            self._reject_count += 1
            if reason:
                self._error = str(reason)[:200]

    def request_proxy_change(self, proxy_url: str = "") -> None:
        """Ask the window to switch exit proxy; empty URL returns to direct.

        The upstream proxy is mapped onto the local CONNECT relay here —
        Chromium ignores proxy credentials, so the window must only ever see
        a credential-less ``http://127.0.0.1:<relay port>`` address.
        """
        mapped = ""
        if proxy_url:
            from backend.services.arena_proxy_relay import local_proxy

            mapped = local_proxy(proxy_url)
        with self._cond:
            self._want_proxy = bool(mapped)
            self._proxy_url = mapped
            self._cond.notify_all()

    def record_error(self, message: str) -> None:
        """Last push/protocol error, surfaced via ``health``."""
        with self._cond:
            self._error = str(message)[:200]

    def state(self, enabled: bool) -> Dict:
        """What the window polls: drive mints, proxy switches, stop."""
        with self._cond:
            return {
                "enabled": bool(enabled),
                "needed": self._needed,
                "reject_count": self._reject_count,
                "want_proxy": self._want_proxy,
                "proxy_url": self._proxy_url,
                "poll_interval_sec": self._poll_interval,
            }

    def health(self) -> Dict:
        """Diagnostics for the UI status card (plan §5.10)."""
        with self._cond:
            age = None
            ready = False
            if self._received_at is not None:
                age = max(0.0, self._clock() - self._received_at)
                ready = age <= self._max_age and bool(self._token)
            return {
                "ready": ready,
                "count": self._count,
                "error": self._error,
                "exit_ip": self._exit_ip,
                "ua": self._ua,
                "uptime": round(time.time() - self._started_at, 1),
                "last_push_age": round(age, 3) if age is not None else None,
            }


#: Module-level singleton, built lazily from the arena config.
_cache: Optional[TokenWindowCache] = None
_cache_lock = threading.Lock()


def get_token_window_cache(config: Optional[object] = None) -> TokenWindowCache:
    """Return the process-wide cache, building it from ``config.token_window``."""
    global _cache
    with _cache_lock:
        if _cache is None:
            sub = getattr(config, "token_window", None) if config is not None else None
            _cache = TokenWindowCache(
                max_age_sec=getattr(sub, "max_age_sec", 110.0),
                poll_interval_sec=getattr(sub, "poll_interval_sec", 2.0),
            )
        return _cache


def reset_token_window_cache_for_tests() -> None:
    """Drop the singleton so the next getter rebuilds from a fresh config."""
    global _cache
    with _cache_lock:
        _cache = None
