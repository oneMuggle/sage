"""Proxy pool / dynamic API / binding helpers for arena (plan §5.6, P2).

Ports the reference measured behaviour (reference/ArenCard):

* ``split_credentials`` — 4 paste formats disambiguated by "which segment
  looks like a port / a host" (arena_core.py:139-175);
* ``ProxyApi`` — haiwaidaili-style dynamic API, tolerating dict / list /
  str row shapes (arena_core.py:47-110);
* ``proxy_alive`` — deliberately lenient dual-endpoint probe: the old
  single-endpoint 6s version killed usable IPs on transient 502s
  (arena_draw.py:833-850); ``proxy_exit_ip`` falls back to showing the
  proxy host when the echo fails (arena_draw.py:241-255);
* ``proxy_sid`` / ``rebind`` — chili session IDs (``sid-XXXX``) inside the
  proxy URL let a renewed pool hand back the *same* exit IP
  (arena_draw.py:824-865);
* ``ProxyProvider`` — facade with pool-over-API priority, rotation modes and
  the sid blacklist from reference arena_register.py:2135-2152 (a dirty IP
  must not be handed to another account).

Security: proxy URLs carry credentials — never log them raw; use
``display_proxy`` for logs/API responses.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import List, Optional, Sequence, Tuple
from urllib.parse import quote, unquote, urlparse

import httpx

from backend.services.arena_proxy_relay import local_proxy

logger = logging.getLogger(__name__)

SID_RE = re.compile(r"sid-([A-Za-z0-9]+)")

#: Echo endpoints, tried in order (reference _ECHO_URLS).
ECHO_URLS = ("https://api.ipify.org?format=json", "https://ifconfig.me/ip")

#: Default dynamic-proxy API (reference default).
DEFAULT_API_URL = "https://api.haiwaidaili.net/abroad"


class ArenaProxyError(RuntimeError):
    """Proxy configuration / acquisition failure."""


def display_proxy(proxy_url: str) -> str:
    """Mask credentials for logs and API responses."""
    url = str(proxy_url or "")
    if "@" not in url:
        return url
    scheme_part, _, rest = url.partition("://")
    if not rest:
        return url
    credentials, _, host_part = rest.rpartition("@")
    if not credentials:
        return url
    user, _, _pw = credentials.partition(":")
    return f"{scheme_part}://{user}:***@{host_part}" if scheme_part else f"{user}:***@{host_part}"


# ── 粘贴代理池（4 格式） ───────────────────────────────────────────────

class ProxyPool:
    """Parse pasted proxy lists; collect per-line errors instead of dying.

    Deviation from the reference (which raises on the first bad line): the
    ``POST /proxies/parse`` endpoint needs *all* errors listed, so bad lines
    land in ``errors`` (with line numbers) and good lines still parse.
    """

    def __init__(self, text: str = "", protocol: str = "http", order: str = "sequential"):
        self.text = text or ""
        self.protocol = (protocol or "http").lower()
        self.order = order or "sequential"
        self.errors: List[str] = []
        self._items: List[str] = []
        self._index = 0
        self._lock = threading.Lock()
        self._parse()

    # -- parsing -----------------------------------------------------------

    @staticmethod
    def split_credentials(raw: str) -> Optional[Tuple[str, str, str, str]]:
        """Normalize the 4 chili paste formats to (host, port, user, password).

        hostname:port:username:password      <- default
        username:password:hostname:port
        username:password@hostname:port
        hostname:port@username:password

        The first two are both 4 colon segments — disambiguated by which
        segment is port-like and which is host-like.
        """

        def port_like(x: str) -> bool:
            return x.isdigit() and 1 <= int(x) <= 65535

        def host_like(x: str) -> bool:
            if not x:
                return False
            return ("." in x) or (not x.isdigit())

        raw = str(raw or "").strip()
        if not raw:
            return None
        if "@" in raw:
            left, _, right = raw.partition("@")
            lp, rp = left.split(":"), right.split(":")
            if len(lp) == 2 and port_like(lp[1]) and host_like(lp[0]):
                return lp[0], lp[1], (rp[0] if rp else ""), (rp[1] if len(rp) > 1 else "")
            if len(rp) == 2 and port_like(rp[1]) and host_like(rp[0]):
                return rp[0], rp[1], (lp[0] if lp else ""), (lp[1] if len(lp) > 1 else "")
            return None
        parts = raw.split(":")
        if len(parts) == 4:
            a_ok = port_like(parts[1]) and host_like(parts[0])  # host:port:user:pass
            b_ok = port_like(parts[3]) and host_like(parts[2])  # user:pass:host:port
            if a_ok and not b_ok:
                return parts[0], parts[1], parts[2], parts[3]
            if b_ok and not a_ok:
                return parts[2], parts[3], parts[0], parts[1]
            if a_ok and b_ok:
                return parts[0], parts[1], parts[2], parts[3]
            return None
        if len(parts) == 2 and port_like(parts[1]):
            return parts[0], parts[1], "", ""
        return None

    def _parse_line(self, raw: str) -> str:
        """One pasted entry -> normalized scheme://user:pass@host:port URL."""
        raw = str(raw or "").strip().strip('"').strip("'")
        if not raw:
            raise ArenaProxyError("代理内容为空")
        scheme = "socks5" if self.protocol == "socks5" else "http"
        if "://" not in raw:
            got = self.split_credentials(raw)
            if not got:
                raise ArenaProxyError("无法识别代理格式（支持 host:port:user:pass 等 4 种）")
            host, port, user, pw = got
            auth = f"{quote(user, safe='')}:{quote(pw, safe='')}@" if user else ""
            raw = f"{scheme}://{auth}{host}:{port}"
        parsed = urlparse(raw)
        sch = str(parsed.scheme or scheme).lower()
        if sch not in ("http", "https", "socks5", "socks5h"):
            raise ArenaProxyError("代理协议需为 http/https/socks5")
        if not parsed.hostname or not parsed.port:
            raise ArenaProxyError("代理缺少主机或端口")
        user = unquote(parsed.username or "")
        pw = unquote(parsed.password or "")
        auth = f"{quote(user, safe='')}:{quote(pw, safe='')}@" if user else ""
        return f"{sch}://{auth}{parsed.hostname}:{parsed.port}"

    def _parse(self) -> None:
        values = [v for v in re.split(r"[\r\n,;\t ]+", self.text) if v.strip()]
        seen = set()
        for index, value in enumerate(values, 1):
            try:
                url = self._parse_line(value)
            except ArenaProxyError as exc:
                self.errors.append(f"第 {index} 条：{exc}")
                continue
            if url not in seen:
                self._items.append(url)
                seen.add(url)

    # -- access ------------------------------------------------------------

    def enabled(self) -> bool:
        return bool(self._items)

    def count(self) -> int:
        return len(self._items)

    def items(self) -> List[str]:
        return list(self._items)

    def next(self) -> str:
        if not self._items:
            raise ArenaProxyError("代理池为空")
        with self._lock:
            if self.order == "random":
                import random

                return random.choice(self._items)  # noqa: S311
            url = self._items[self._index % len(self._items)]
            self._index += 1
            return url


# ── 动态代理 API ───────────────────────────────────────────────────────

class ProxyApi:
    """haiwaidaili-style dynamic proxy fetcher (dict/list/str row shapes)."""

    def __init__(
        self,
        api_url: str = DEFAULT_API_URL,
        token: str = "",
        country: str = "",
        protocol: str = "http",
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.api_url = (api_url or DEFAULT_API_URL).strip()
        self.token = (token or "").strip()
        self.country = (country or "").lower()
        self.protocol = (protocol or "http").lower()
        self.timeout = timeout
        self._transport = transport

    def fetch(self) -> str:
        """Fetch one proxy → ``scheme://host:port`` (no credentials in API mode)."""
        if not self.token:
            raise ArenaProxyError("动态代理 Token 未填写")
        params = {
            "token": self.token,
            "num": 1,
            "format": 2,
            "protocol": self.protocol,
            "country": self.country,
            "sep": 1,
            "csep": "",
        }
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                response = client.get(self.api_url, params=params)
        except httpx.HTTPError as exc:
            raise ArenaProxyError(f"代理接口请求失败: {exc}") from exc
        try:
            data = response.json()
        except ValueError:
            raise ArenaProxyError(f"代理接口返回非 JSON (HTTP {response.status_code})")
        if response.status_code >= 400 or not data.get("success", data.get("code") == 0):
            raise ArenaProxyError(f"代理接口失败: {str(data)[:150]}")
        rows = data.get("data") or []
        first = rows[0] if isinstance(rows, (list, tuple)) and rows else rows
        host, port_value = "", 0
        if isinstance(first, dict):
            host = str(first.get("ip") or first.get("host") or "").strip()
            port_value = first.get("port") or 0
        elif isinstance(first, (list, tuple)) and len(first) >= 2:
            host = str(first[0] or "").strip()
            port_value = first[1]
        elif isinstance(first, str):
            value = first.strip()
            if ":" in value:
                host, port_value = value.rsplit(":", 1)
                host = host.strip()
        try:
            port = int(port_value or 0)
        except (TypeError, ValueError):
            port = 0
        if not host or not port:
            raise ArenaProxyError(f"代理未返回 ip/port: {str(data)[:150]}")
        scheme = "socks5" if self.protocol == "socks5" else "http"
        return f"{scheme}://{host}:{port}"


# ── 探测 / sid / rebind ────────────────────────────────────────────────

def _proxied_client(proxy_url: str, timeout: float, transport=None) -> httpx.Client:
    if transport is not None:
        # Test seam: an injected transport intercepts everything. A proxy
        # mount would bypass it (httpx ignores `transport` for proxied
        # mounts, measured on 0.28) and hit the real network.
        return httpx.Client(timeout=timeout, transport=transport)
    local = local_proxy(proxy_url)
    if local:
        try:
            return httpx.Client(proxy=local, timeout=timeout)
        except TypeError:  # httpx < 0.26
            return httpx.Client(proxies=local, timeout=timeout)
    return httpx.Client(timeout=timeout)


def proxy_exit_ip(proxy_url: str, timeout: float = 12.0, transport=None) -> str:
    """Exit IP through the proxy; falls back to showing the proxy host."""
    if not proxy_url:
        return "直连"
    try:
        with _proxied_client(proxy_url, timeout, transport) as client:
            response = client.get(ECHO_URLS[0])
            if response.status_code == 200:
                return str(response.json().get("ip") or "")
    except Exception:  # noqa: BLE001 — probe only
        pass
    try:
        return proxy_url.split("@")[-1].split("://")[-1]
    except Exception:  # noqa: BLE001
        return "?"


def direct_exit_ip(timeout: float = 12.0, transport=None) -> str:
    """This machine's direct (no-proxy) exit IP; empty string when offline."""
    for url in ECHO_URLS:
        try:
            with httpx.Client(timeout=timeout, transport=transport) as client:
                response = client.get(url)
                if response.status_code != 200:
                    continue
                if "ipify" in url:
                    return str(response.json().get("ip") or "")
                text = response.text.strip()
                return text if text else ""
        except Exception:  # noqa: BLE001 — try next endpoint
            continue
    return ""


def proxy_alive(proxy_url: str, timeout: float = 8.0, transport=None) -> bool:
    """Lenient liveness probe (empty proxy = direct = alive).

    Dual endpoint on purpose: the reference's earlier single-endpoint 6s
    version declared usable IPs dead on transient 502s / echo rate limits.
    """
    if not proxy_url:
        return True
    local = local_proxy(proxy_url)
    for url in ECHO_URLS:
        try:
            with _proxied_client(proxy_url, timeout, transport) as client:
                response = client.get(url)
                if response.status_code == 200:
                    return True
        except Exception:  # noqa: BLE001 — try next endpoint
            continue
    return False


def proxy_sid(proxy_url: str) -> str:
    """Chili session id (sid-XXXX) — the key for same-IP rebinding."""
    match = SID_RE.search(str(proxy_url or ""))
    return match.group(1) if match else ""


def rebind(proxy_url: str, fresh_pool: str, protocol: str = "http") -> str:
    """Find the same sid in a renewed pool (IP continuity); else keep current."""
    sid = proxy_sid(proxy_url)
    if not sid or not fresh_pool:
        return proxy_url
    try:
        items = ProxyPool(fresh_pool, protocol=protocol).items()
    except Exception:  # noqa: BLE001
        return proxy_url
    for item in items:
        if proxy_sid(item) == sid:
            return item
    return proxy_url


# ── 门面：池优先于 API + 轮转 + sid 黑名单 ─────────────────────────────

class ProxyProvider:
    """Proxy source for jobs: pool first, dynamic API as fallback.

    ``rotation``: ``per_account`` advances on every acquire; ``per_wave``
    keeps one proxy for a whole wave (advance via :meth:`next_wave`).
    The sid blacklist (reference arena_register.py:2135-2152) stops a dirty
    exit IP from being handed to another account.
    """

    def __init__(
        self,
        pool: Optional[ProxyPool] = None,
        api: Optional[ProxyApi] = None,
        rotation: str = "per_account",
        order: str = "sequential",
        blacklist_seconds: float = 1800.0,
    ):
        self._pool = pool if pool and pool.count() else None
        self._api = api
        self._rotation = rotation if rotation in ("per_account", "per_wave") else "per_account"
        self._order = order
        self._blacklist_seconds = max(1.0, float(blacklist_seconds))
        self._lock = threading.Lock()
        self._blacklist: dict = {}  # sid (or host:port) -> expiry ts
        self._wave_index = 0
        self._api_attempts = 3

    def _key(self, proxy_url: str) -> str:
        return proxy_sid(proxy_url) or (
            (urlparse(proxy_url).hostname or "") + ":" + str(urlparse(proxy_url).port or "")
        )

    def _is_blacklisted(self, key: str) -> bool:
        return self._blacklist.get(key, 0.0) > time.time()

    def mark_bad(self, proxy_url: str, seconds: Optional[float] = None) -> None:
        """Blacklist this proxy's key for a while (dirty IP quarantine)."""
        key = self._key(proxy_url)
        if not key or key in ("", ":"):
            return
        with self._lock:
            self._blacklist[key] = time.time() + (
                seconds if seconds is not None else self._blacklist_seconds
            )
        logger.info("arena proxy blacklisted %s for %.0fs", display_proxy(proxy_url),
                    seconds if seconds is not None else self._blacklist_seconds)

    def next_wave(self) -> None:
        if self._rotation == "per_wave":
            with self._lock:
                self._wave_index += 1

    def _skip(self, candidate: str, excluded: set) -> bool:
        sid = proxy_sid(candidate)
        if sid and sid in excluded:
            return True
        return self._is_blacklisted(self._key(candidate))

    def acquire(self, exclude_sids: Optional[set] = None) -> str:
        """Next usable proxy URL, skipping excluded and blacklisted keys.

        Raises :class:`ArenaProxyError` when nothing is available.
        """
        excluded = set(exclude_sids or ())
        if self._pool is not None:
            items = self._pool.items()
            if self._rotation == "per_wave":
                with self._lock:
                    start = self._wave_index
                candidates = [items[(start + i) % len(items)] for i in range(len(items))]
                for candidate in candidates:
                    if not self._skip(candidate, excluded):
                        return candidate
            else:  # per_account: rotate through the pool cursor
                for _ in range(len(items)):
                    candidate = self._pool.next()
                    if not self._skip(candidate, excluded):
                        return candidate
            raise ArenaProxyError("代理池全部被排除或拉黑")
        if self._api is not None:
            for _ in range(self._api_attempts):
                candidate = self._api.fetch()
                if not self._skip(candidate, excluded):
                    return candidate
            raise ArenaProxyError("动态代理连续返回被排除/拉黑的地址")
        raise ArenaProxyError("没有可用代理（未配置池或 API）")


def provider_from_config(proxy_config) -> Optional[ProxyProvider]:
    """Build a ProxyProvider from ``ArenaAutomationConfig.proxy`` (or None)."""
    if proxy_config is None or not getattr(proxy_config, "enabled", False):
        return None
    pool = None
    if (proxy_config.pool_text or "").strip():
        pool = ProxyPool(
            proxy_config.pool_text,
            protocol=proxy_config.protocol,
            order=proxy_config.order,
        )
    api = None
    if (proxy_config.api_url or "").strip() and (proxy_config.api_token or "").strip():
        api = ProxyApi(
            api_url=proxy_config.api_url,
            token=proxy_config.api_token,
            country=proxy_config.country,
            protocol=proxy_config.protocol,
        )
    if pool is None and api is None:
        return None
    return ProxyProvider(
        pool=pool, api=api, rotation=proxy_config.rotation, order=proxy_config.order
    )
