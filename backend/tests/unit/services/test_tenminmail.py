"""Unit tests for the 10minutemail.one provider (plan §4 D4).

No network access: every request is served by ``httpx.MockTransport``.
"""

import asyncio

import httpx
import pytest

from backend.services.temporary_mail import available_providers, get_provider
from backend.services.temporary_mail.tenminmail import (
    TenMinMailError,
    TenMinMailProvider,
)

FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9." + "a" * 32 + "." + "b" * 32
PAGE_HTML = f'<html><script>window.__token="{FAKE_JWT}"</script></html>'

#: JSON-escaped ampersand, exactly as it shows up in a mail body
LINK_BODY = "Click https://arena.example/verify?token=abc\\u0026uid=42 to confirm."


def _state(**overrides):
    base = {
        "urls": [],
        "jwt_fetches": 0,
        "jwt_page_status": 200,
        "messages": [],
        "bodies": {},
        "unauthorized_remaining": 0,
        "list_status": 200,
    }
    base.update(overrides)
    return base


def _handler(state):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        state["urls"].append(url)
        if "/zh" in url and "/api/" not in url:
            state["jwt_fetches"] += 1
            if state["jwt_page_status"] != 200:
                return httpx.Response(state["jwt_page_status"], text="no token here")
            return httpx.Response(200, text=PAGE_HTML)
        parts = [p for p in request.url.path.split("/") if p]
        # /api/v1/mailbox/{email} or /api/v1/mailbox/{email}/{id}
        if len(parts) == 4:
            if state["unauthorized_remaining"] > 0:
                state["unauthorized_remaining"] -= 1
                return httpx.Response(401, json={"message": "jwt expired"})
            if state["list_status"] != 200:
                return httpx.Response(state["list_status"], text="boom")
            return httpx.Response(200, json=state["messages"])
        if len(parts) == 5:
            return httpx.Response(200, text=state["bodies"].get(parts[-1], ""))
        return httpx.Response(404, json={})

    return handler


def _provider(state, **kwargs):
    return TenMinMailProvider(transport=httpx.MockTransport(_handler(state)), **kwargs)


def test_registry_exposes_tenminmail():
    assert "tenminmail" in available_providers()
    provider = get_provider("tenminmail")
    assert isinstance(provider, TenMinMailProvider)
    assert provider.name == "tenminmail"


def test_registry_rejects_unimplemented_and_unknown():
    with pytest.raises(ValueError, match="not implemented"):
        get_provider("mailtm")
    with pytest.raises(ValueError, match="unknown mail provider"):
        get_provider("guerrilla")


def test_create_mailbox_scrapes_jwt_once_and_rotates_domains():
    state = _state()

    async def scenario():
        provider = _provider(state)
        try:
            return [await provider.create_mailbox() for _ in range(4)]
        finally:
            await provider.aclose()

    boxes = asyncio.run(scenario())
    assert state["jwt_fetches"] == 1  # scraped once, reused for every mailbox
    domains = [box.email.split("@")[1] for box in boxes]
    expected = list(TenMinMailProvider.DOMAINS)
    assert domains == expected + [expected[0]]  # round-robin rotation
    locals_ = [box.email.split("@")[0] for box in boxes]
    assert all(len(name) == TenMinMailProvider.LOCAL_LENGTH for name in locals_)
    assert len(set(locals_)) == 4
    assert all(box.provider == "tenminmail" for box in boxes)
    assert all(box.password == "" for box in boxes)  # catch-all: nothing registered
    assert all(box.provider_token == FAKE_JWT for box in boxes)


def test_custom_domains_override():
    state = _state()

    async def scenario():
        provider = _provider(state, domains=["custom.example"])
        try:
            box = await provider.create_mailbox()
        finally:
            await provider.aclose()
        return box.email

    assert asyncio.run(scenario()).endswith("@custom.example")


def test_wait_for_link_normalizes_escaped_ampersand():
    state = _state(
        messages=[{"id": "m1", "subject": "Verify your email"}],
        bodies={"m1": LINK_BODY},
    )

    async def scenario():
        provider = _provider(state)
        try:
            box = await provider.create_mailbox()
            return await provider.wait_for_link(box, timeout_sec=5, poll_interval_sec=1)
        finally:
            await provider.aclose()

    assert asyncio.run(scenario()) == "https://arena.example/verify?token=abc&uid=42"


def test_wait_for_link_returns_none_on_timeout():
    state = _state(messages=[])

    async def scenario():
        provider = _provider(state)
        try:
            box = await provider.create_mailbox()
            return await provider.wait_for_link(box, timeout_sec=2, poll_interval_sec=1)
        finally:
            await provider.aclose()

    assert asyncio.run(scenario()) is None


def test_wait_for_code_extracts_digits():
    state = _state(
        messages=[{"id": "m2", "subject": "Your verification code"}],
        bodies={"m2": "Your code is 483921 — do not share it."},
    )

    async def scenario():
        provider = _provider(state)
        try:
            box = await provider.create_mailbox()
            return await provider.wait_for_code(box, timeout_sec=5, poll_interval_sec=1)
        finally:
            await provider.aclose()

    assert asyncio.run(scenario()) == "483921"


def test_expired_jwt_refreshes_once_and_retries():
    state = _state(messages=[], unauthorized_remaining=1)

    async def scenario():
        provider = _provider(state)
        try:
            box = await provider.create_mailbox()
            messages = await provider._fetch_messages(box)
        finally:
            await provider.aclose()
        return messages

    assert asyncio.run(scenario()) == []
    assert state["jwt_fetches"] == 2  # initial scrape + refresh after 401


def test_jwt_unavailable_raises():
    state = _state(jwt_page_status=503)

    async def scenario():
        provider = _provider(state, jwt_attempts=1)
        try:
            with pytest.raises(TenMinMailError):
                await provider.create_mailbox()
        finally:
            await provider.aclose()

    asyncio.run(scenario())


def test_mailbox_list_error_raises():
    state = _state(list_status=500)

    async def scenario():
        provider = _provider(state)
        try:
            box = await provider.create_mailbox()
            with pytest.raises(TenMinMailError):
                await provider._fetch_messages(box)
        finally:
            await provider.aclose()

    asyncio.run(scenario())


def test_destroy_mailbox_is_noop():
    state = _state()

    async def scenario():
        provider = _provider(state)
        try:
            box = await provider.create_mailbox()
            assert await provider.destroy_mailbox(box) is None
        finally:
            await provider.aclose()

    asyncio.run(scenario())
