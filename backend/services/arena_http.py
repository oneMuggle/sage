"""Pluggable HTTP layer for the arena protocol clients (plan §5.4).

Design decision D3 (post-S0 reversal, docs/mcp-aren-card-port-plan.md):
    S0 measured that plain **httpx passes Cloudflare** on this host (both
    HTTP/1.1 and HTTP/2, real JSON answers from /api/me) while curl_cffi 0.16.3
    was 403-challenged in *every* impersonate variant. The reference project's
    rule "must use curl_cffi impersonate=chrome131" (arena_core.py) is therefore
    inverted for sage: **httpx is the default**, curl_cffi is an optional
    fallback to try when a proxy/datacenter exit starts returning 403
    (capabilities probe exposes both).

    The reference's other HTTP disciplines still apply verbatim:
    - no hand-written User-Agent (httpx keeps its honest default; under
      curl_cffi the UA comes from impersonate — never mix a custom UA in);
    - per-account sessions (cookie isolation) — callers create one session
      per account, this module does not cache anything;
    - transport errors retried 3x with 1.5*(i+1) backoff
      (arena.ai drops reads a few times a day, measured in the reference).

Proxy note: proxy URLs are passed through ``arena_proxy_relay.local_proxy()``
when that module exists (P2). Until then the URL is used directly — httpx
end-to-end TLS keeps the fingerprint intact either way.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any, Callable, Dict, Iterator, Optional

import httpx

logger = logging.getLogger(__name__)

#: Default per-request timeout (reference: arena_core.py timeout=25).
DEFAULT_TIMEOUT = 25.0


class ArenaHttpError(RuntimeError):
    """HTTP layer misconfiguration (unknown backend, curl_cffi missing, ...)."""


def curl_cffi_available() -> bool:
    """True when the optional curl_cffi fallback can be constructed."""
    try:
        import curl_cffi  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _resolve_proxy(proxy_url: str) -> str:
    """Route through the local CONNECT relay once it exists (P2, plan §5.6).

    The relay exists because chili-style proxies reject CONNECT requests that
    carry a Host header, which libcurl/curl_cffi always send. Until then the
    proxy URL is used as-is.
    """
    if not proxy_url:
        return ""
    try:
        from backend.services.arena_proxy_relay import local_proxy  # P2

        return local_proxy(proxy_url)
    except Exception:  # noqa: BLE001 — module not landed yet
        return proxy_url


def _httpx_client(proxy: str = "", **kwargs: Any) -> httpx.Client:
    """Build an httpx.Client across proxy-kwarg generations.

    httpx >= 0.26 takes ``proxy``; older versions (and the py3.8/win7 channel)
    only take ``proxies``. Try the modern spelling first.
    """
    if proxy:
        try:
            return httpx.Client(proxy=proxy, **kwargs)
        except TypeError:
            return httpx.Client(proxies=proxy, **kwargs)  # httpx < 0.26
    return httpx.Client(**kwargs)


class _StreamResponse:
    """Minimal streaming response: status + byte chunks (requests semantics)."""

    def __init__(self, status_code: int, chunks: Callable[[int], Iterator[bytes]]):
        self.status_code = status_code
        self._chunks = chunks

    def iter_content(self, chunk_size: int = 4096) -> Iterator[bytes]:
        return self._chunks(chunk_size)


class HttpxSession:
    """httpx wrapper exposing the SessionLike surface used by arena_protocol.

    Response objects are passed through unchanged: httpx.Response already has
    ``status_code`` / ``text`` / ``json()`` / ``url``, the same names the
    curl_cffi branch yields.
    """

    backend = "httpx"

    def __init__(
        self,
        proxy_url: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        transport: Optional[httpx.BaseTransport] = None,
        follow_redirects: bool = True,
    ):
        self._timeout = timeout
        self._client = _httpx_client(
            proxy=_resolve_proxy(proxy_url),
            timeout=timeout,
            transport=transport,
            follow_redirects=follow_redirects,
        )

    # -- SessionLike surface ------------------------------------------------

    def get(self, url: str, **kw: Any):
        kw.setdefault("timeout", self._timeout)
        return self._client.get(url, **kw)

    def post(self, url: str, **kw: Any):
        kw.setdefault("timeout", self._timeout)
        return self._client.post(url, **kw)

    def patch(self, url: str, **kw: Any):
        kw.setdefault("timeout", self._timeout)
        return self._client.patch(url, **kw)

    def delete(self, url: str, **kw: Any):
        kw.setdefault("timeout", self._timeout)
        return self._client.delete(url, **kw)

    def request(self, method: str, url: str, **kw: Any):
        kw.setdefault("timeout", self._timeout)
        return self._client.request(method, url, **kw)

    @contextlib.contextmanager
    def stream_get(self, url: str, **kw: Any):
        """GET with a streaming body (SSE). Yields a _StreamResponse."""
        kw.setdefault("timeout", self._timeout)
        with self._client.stream("GET", url, **kw) as response:
            yield _StreamResponse(
                response.status_code,
                lambda chunk_size: response.iter_bytes(),
            )

    def close(self) -> None:
        self._client.close()


class CurlCffiSession:
    """curl_cffi wrapper with the same surface (optional fallback backend).

    Only exercised on hosts where curl_cffi is installed AND the httpx path is
    being Cloudflare-blocked through a proxy exit (plan D3).
    """

    backend = "curl_cffi"

    def __init__(
        self,
        proxy_url: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        impersonate: str = "chrome131",
    ):
        try:
            from curl_cffi import requests as curl_requests
        except Exception as exc:  # noqa: BLE001
            raise ArenaHttpError(
                f"curl_cffi backend requested but not importable: {exc}"
            ) from exc
        self._timeout = timeout
        self._session = curl_requests.Session(impersonate=impersonate)
        proxy = _resolve_proxy(proxy_url)
        if proxy:
            self._session.proxies = {"http": proxy, "https": proxy}

    def _kw(self, kw: Dict[str, Any]) -> Dict[str, Any]:
        kw.setdefault("timeout", self._timeout)
        return kw

    def get(self, url: str, **kw: Any):
        return self._session.get(url, **self._kw(kw))

    def post(self, url: str, **kw: Any):
        return self._session.post(url, **self._kw(kw))

    def patch(self, url: str, **kw: Any):
        return self._session.patch(url, **self._kw(kw))

    def delete(self, url: str, **kw: Any):
        return self._session.delete(url, **self._kw(kw))

    def request(self, method: str, url: str, **kw: Any):
        return self._session.request(method, url, **self._kw(kw))

    @contextlib.contextmanager
    def stream_get(self, url: str, **kw: Any):
        kw.setdefault("timeout", self._timeout)
        response = self._session.get(url, stream=True, **kw)
        try:
            yield _StreamResponse(
                response.status_code,
                lambda chunk_size: response.iter_content(chunk_size),
            )
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def close(self) -> None:
        self._session.close()


def make_session(
    proxy_url: str = "",
    backend: str = "httpx",
    timeout: float = DEFAULT_TIMEOUT,
    impersonate: str = "chrome131",
    transport: Optional[httpx.BaseTransport] = None,
):
    """Create a per-account SessionLike client (discipline: one per account).

    ``backend``: "httpx" (default, S0-verified) | "curl_cffi" | "auto"
    ("auto" currently means httpx — switch only on measured 403 evidence).
    ``transport`` is an httpx test hook (MockTransport).
    """
    choice = (backend or "httpx").strip().lower()
    if choice == "auto":
        choice = "httpx"
    if choice == "httpx":
        return HttpxSession(
            proxy_url=proxy_url, timeout=timeout, transport=transport
        )
    if choice == "curl_cffi":
        return CurlCffiSession(
            proxy_url=proxy_url, timeout=timeout, impersonate=impersonate
        )
    raise ArenaHttpError(
        f"unknown arena http backend {backend!r}; expected 'httpx' or 'curl_cffi'"
    )


def arena_headers(
    origin: str,
    referer: Optional[str] = None,
    extra: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """JSON headers with Origin/Referer and **no User-Agent**.

    Keeping the UA out is deliberate (reference arena_core.py:330-334): under
    httpx the honest default UA passed Cloudflare in S0; under curl_cffi the
    impersonate profile owns the UA. A hand-written UA can contradict the TLS
    fingerprint and is the classic detection signal.
    """
    headers = {
        "Content-Type": "application/json",
        "Origin": origin,
        "Referer": referer or (origin + "/"),
    }
    if extra:
        headers.update(extra)
    return headers


def request_with_retry(
    session,
    method: str,
    url: str,
    retries: int = 3,
    backoff: float = 1.5,
    sleep: Callable[[float], None] = time.sleep,
    **kw: Any,
):
    """Run a request, retrying **transport** failures only (discipline 7).

    HTTP error statuses (4xx/5xx) are returned as-is — callers encode the
    protocol semantics (429 ladders, captcha bodies) and must see them.
    """
    attempts = max(1, int(retries))
    last_exc: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return getattr(session, method.lower())(url, **kw)
        except Exception as exc:  # noqa: BLE001 — transport-level only
            last_exc = exc
            if attempt < attempts:
                logger.debug(
                    "arena request %s %s attempt %d/%d failed (%s), retrying",
                    method, url, attempt, attempts, exc,
                )
                if backoff > 0:
                    sleep(backoff * attempt)
    raise ArenaHttpError(
        f"arena request failed after {attempts} attempts: {method} {url}: {last_exc}"
    )
