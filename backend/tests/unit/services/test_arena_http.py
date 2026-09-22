"""Unit tests for backend/services/arena_http.py (plan §5.4, D3 reversal).

No real network: httpx paths run over MockTransport; the curl_cffi branch is
exercised only on hosts where it is installed (skipped otherwise).
"""

import httpx
import pytest

from backend.services import arena_http as ah


def test_arena_headers_shape():
    headers = ah.arena_headers("https://arena.ai", referer="https://arena.ai/agent/")
    assert headers["Content-Type"] == "application/json"
    assert headers["Origin"] == "https://arena.ai"
    assert headers["Referer"] == "https://arena.ai/agent/"
    # Discipline 2: never a hand-written User-Agent.
    assert "User-Agent" not in headers
    assert "user-agent" not in headers
    merged = ah.arena_headers("https://x.example", extra={"X-Extra": "1"})
    assert merged["X-Extra"] == "1"


def test_httpx_session_surface_and_redirects():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        if "/hop" in request.url.path:
            return httpx.Response(302, headers={"Location": "https://arena.ai/final?token=abc"})
        return httpx.Response(200, json={"ok": True})

    session = ah.make_session(transport=httpx.MockTransport(handler))
    try:
        response = session.get("https://arena.ai/hop")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert str(response.url) == "https://arena.ai/final?token=abc"  # followed
        assert ("GET", "https://arena.ai/final?token=abc") in seen
    finally:
        session.close()


def test_httpx_session_posts_json_body():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.read().decode("utf-8"))
        return httpx.Response(200, text="fine")

    session = ah.make_session(transport=httpx.MockTransport(handler))
    try:
        session.post("https://arena.ai/x", json={"a": 1}, headers=ah.arena_headers("https://arena.ai"))
        assert '"a":1' in bodies[0].replace(" ", "")
    finally:
        session.close()


def test_stream_get_yields_sse_chunks():
    payload = b"data: {\"records\": [{\"headers\": [[\"public-access-token\", \"x\"]]}]}\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, headers={"Content-Type": "text/event-stream"})

    session = ah.make_session(transport=httpx.MockTransport(handler))
    try:
        with session.stream_get("https://arena.ai/out") as stream:
            assert stream.status_code == 200
            collected = b"".join(stream.iter_content(16))
        assert collected == payload
    finally:
        session.close()


def test_request_with_retry_retries_transport_errors_only():
    calls = {"n": 0}
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, text="ok")

    session = ah.make_session(transport=httpx.MockTransport(handler))
    try:
        response = ah.request_with_retry(
            session, "get", "https://arena.ai/x",
            retries=3, backoff=1.5, sleep=sleeps.append,
        )
        assert response.status_code == 200
        assert calls["n"] == 3
        assert sleeps == [1.5, 3.0]  # 1.5*(i+1) ladder
    finally:
        session.close()


def test_request_with_retry_gives_up_after_attempts():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    session = ah.make_session(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ah.ArenaHttpError, match="after 2 attempts"):
            ah.request_with_retry(
                session, "get", "https://arena.ai/x",
                retries=2, backoff=0, sleep=lambda _s: None,
            )
    finally:
        session.close()


def test_request_with_retry_does_not_swallow_http_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    session = ah.make_session(transport=httpx.MockTransport(handler))
    try:
        response = ah.request_with_retry(
            session, "get", "https://arena.ai/x", retries=3, sleep=lambda _s: None
        )
        assert response.status_code == 429  # caller must see protocol statuses
    finally:
        session.close()


def test_make_session_unknown_backend():
    with pytest.raises(ah.ArenaHttpError, match="unknown arena http backend"):
        ah.make_session(backend="requests")


def test_make_session_default_is_httpx():
    session = ah.make_session()
    assert session.backend == "httpx"
    session.close()


@pytest.mark.skipif(ah.curl_cffi_available(), reason="curl_cffi installed — error path not reachable")
def test_curl_cffi_missing_raises_readable_error():
    with pytest.raises(ah.ArenaHttpError, match="curl_cffi backend requested but not importable"):
        ah.make_session(backend="curl_cffi")


@pytest.mark.skipif(not ah.curl_cffi_available(), reason="curl_cffi not installed on this host")
def test_curl_cffi_backend_constructs():
    session = ah.make_session(backend="curl_cffi")
    assert session.backend == "curl_cffi"
    session.close()


def test_make_session_accepts_proxy_without_connecting():
    # constructing must not contact the proxy (only per-account use does)
    session = ah.make_session(proxy_url="http://127.0.0.1:3128")
    assert session.backend == "httpx"
    session.close()
