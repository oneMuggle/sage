"""MailTmProvider tests — httpx.MockTransport，不打真实网络。"""

from __future__ import annotations

import json

import httpx
import pytest

from backend.services.temporary_mail.base import Mailbox
from backend.services.temporary_mail.mailtm import MailTmError, MailTmProvider
from backend.services.temporary_mail.registry import (
    UnknownProviderError,
    available_providers,
    create_provider,
)


class _Router:
    """按 (method, path) 返回预设响应的最小 mock 路由。"""

    def __init__(self):
        self.routes = {}
        self.requests = []

    def add(self, path, response, method="GET"):
        self.routes[(method, path)] = response

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        key = (request.method, request.url.path)
        if key not in self.routes:
            return httpx.Response(404, json={"error": "not mocked"})
        entry = self.routes[key]
        if callable(entry):
            return entry(request)
        if isinstance(entry, int):
            return httpx.Response(entry, json={})
        return httpx.Response(200, json=entry)


def _provider(router: _Router) -> MailTmProvider:
    return MailTmProvider(transport=httpx.MockTransport(router.handler))


@pytest.mark.unit()
def test_create_mailbox_happy_path():
    router = _Router()
    router.add("/domains", {"hydra:member": [{"domain": "example.mail", "isActive": True}]})
    router.add("/accounts", lambda r: httpx.Response(201, json={"id": "acc1", "address": json.loads(r.content.decode())["address"]}), method="POST")
    router.add("/token", {"token": "jwt-1"}, method="POST")

    import asyncio

    provider = _provider(router)
    mailbox = asyncio.run(provider.create_mailbox())
    assert mailbox.email.endswith("@example.mail")
    assert mailbox.provider_token == "jwt-1"
    assert mailbox.provider == "mailtm"
    assert len(mailbox.password) >= 16  # 随机生成，不回显给用户


@pytest.mark.unit()
def test_fetch_messages_hydrates_bodies():
    router = _Router()
    router.add(
        "/messages",
        {"hydra:member": [{"id": "m1", "subject": "Verify your email"}]},
    )
    router.add("/messages/m1", {"id": "m1", "subject": "Verify", "text": "link body", "createdAt": "t"})

    import asyncio

    provider = _provider(router)
    mailbox = Mailbox(email="a@b.c", password="x", provider_token="jwt", provider="mailtm")
    messages = asyncio.run(provider._fetch_messages(mailbox))
    assert len(messages) == 1
    assert messages[0]["id"] == "m1"
    assert messages[0]["body"] == "link body"
    assert messages[0]["subject"] == "Verify"


@pytest.mark.unit()
def test_fetch_messages_relogin_on_401():
    router = _Router()
    calls = {"count": 0}

    def messages_endpoint(request: httpx.Request):
        calls["count"] += 1
        if calls["count"] == 1:  # 第一次 401 → 触发用密码换 token 再重试
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"member": []})

    router.add("/messages", messages_endpoint)
    router.add("/token", {"token": "jwt-2"}, method="POST")

    import asyncio

    provider = _provider(router)
    mailbox = Mailbox(email="a@b.c", password="pw", provider_token="stale", provider="mailtm")
    messages = asyncio.run(provider._fetch_messages(mailbox))
    assert messages == []
    assert mailbox.provider_token == "jwt-2"


@pytest.mark.unit()
def test_destroy_mailbox_best_effort_never_raises():
    router = _Router()
    router.add("/me", {"id": "acc9"})
    router.add("/accounts/acc9", 500, method="DELETE")

    import asyncio

    provider = _provider(router)
    mailbox = Mailbox(email="a@b.c", password="x", provider_token="jwt", provider="mailtm")
    asyncio.run(provider.destroy_mailbox(mailbox))  # 不抛即通过


@pytest.mark.unit()
def test_create_mailbox_raises_on_api_error():
    router = _Router()
    router.add("/domains", {"hydra:member": []})

    import asyncio

    provider = _provider(router)
    with pytest.raises(MailTmError, match="无可用域名"):
        asyncio.run(provider.create_mailbox())


@pytest.mark.unit()
def test_registry_creates_mailtm_and_rejects_unknown():
    assert "mailtm" in available_providers()
    provider = create_provider("mailtm")
    assert isinstance(provider, MailTmProvider)
    with pytest.raises(UnknownProviderError):
        create_provider("nope")


@pytest.mark.unit()
def test_wait_for_message_matches_subject_and_body_pattern():
    import asyncio

    class StubProvider(MailTmProvider):
        def __init__(self, messages):
            super().__init__()
            self._messages = messages

        async def _fetch_messages(self, mailbox, since_timestamp=None):
            return list(self._messages)

    provider = StubProvider(
        [
            {"id": "1", "subject": "Welcome", "body": "no link"},
            {"id": "2", "subject": "Verify your email", "body": "open https://arena.ai/x/callback?token=1"},
        ]
    )
    mailbox = Mailbox(email="a@b.c", password="x", provider_token="j", provider="mailtm")
    message = asyncio.run(
        provider.wait_for_message(
            mailbox,
            subject_pattern=r"verify",
            body_pattern=r"https://arena\.ai/\S*callback",
            timeout_sec=2,
            poll_interval_sec=1,
        )
    )
    assert message is not None
    assert message["id"] == "2"


@pytest.mark.unit()
def test_wait_for_message_returns_none_on_timeout():
    import asyncio

    class EmptyProvider(MailTmProvider):
        async def _fetch_messages(self, mailbox, since_timestamp=None):
            return []

    provider = EmptyProvider()
    mailbox = Mailbox(email="a@b.c", password="x", provider_token="j", provider="mailtm")
    message = asyncio.run(
        provider.wait_for_message(mailbox, subject_pattern="verify", timeout_sec=1, poll_interval_sec=1)
    )
    assert message is None
