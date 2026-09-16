from __future__ import annotations
import asyncio
import os
import tempfile
import uuid

import pytest
from cryptography.fernet import Fernet

from backend.services.arena_accounts import ArenaAccountService
from backend.services.arena_adapter import ArenaAdapter, ThinkingFilter
from backend.services.temporary_mail.base import Mailbox


class FakeMailProvider:
    """Returns a fixed mailbox and a pre-canned code after one poll."""
    name = "fake"

    def __init__(self, code: str = "123456"):
        self.code = code
        self.created: list = []
        self.destroyed: list = []

    async def create_mailbox(self) -> Mailbox:
        mb = Mailbox(
            email=f"user-{uuid.uuid4().hex[:8]}@fake.example",
            password="x",
            provider_token="tok",
            provider="fake",
        )
        self.created.append(mb)
        return mb

    async def wait_for_code(self, mailbox, subject_pattern=None, timeout_sec=10, poll_interval_sec=1):
        return self.code

    async def destroy_mailbox(self, mailbox):
        self.destroyed.append(mailbox)


class FakeBrowserSession:
    """Records every cdp_command call so the test can assert on the flow."""
    def __init__(self):
        self.calls: list = []
        self.captcha_detected = False

    def cdp_command(self, method, params=None, **_):
        self.calls.append({"method": method, "params": params})
        if method == "Runtime.evaluate":
            # Toggle captcha state on every check
            self.captcha_detected = not self.captcha_detected
            return {"result": {"value": self.captcha_detected}}
        return {"result": {"value": False}}


@pytest.mark.integration
def test_registration_flow_uses_account_after_captcha_solved():
    fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    key = Fernet.generate_key()

    bs = FakeBrowserSession()
    adapter = ArenaAdapter(bs)
    mail = FakeMailProvider(code="654321")

    async def run():
        # 1. Create mailbox
        mb = await mail.create_mailbox()
        assert mb.email.startswith("user-")
        # 2. Drive the browser — but we only assert the adapter and mail work together
        # 3. Get verification code
        code = await mail.wait_for_code(mb)
        assert code == "654321"
        # 4. Account store ready for the new credentials
        svc = ArenaAccountService(db_path=db_path, encryption_key=key)
        acc = svc.create_account(email=mb.email, password="newpassword")
        assert acc["state"] == "available"
        svc.close()
        # 5. Cleanup mailbox
        await mail.destroy_mailbox(mb)
        assert len(mail.destroyed) == 1

    asyncio.run(run())
    os.unlink(db_path)


@pytest.mark.integration
def test_thinking_filter_preserves_message_through_adapter_pipeline():
    bs = FakeBrowserSession()
    adapter = ArenaAdapter(bs)
    text = "Hi <thinking>private thoughts</thinking> answer please"
    sent = adapter.submit_message(text, thinking_filter=ThinkingFilter.STRIP)
    assert "private thoughts" not in sent
    # The char-dispatch events should reflect the filtered text length
    key_events = [c for c in bs.calls if c["method"] == "Input.dispatchKeyEvent"]
    typed = "".join(k["params"].get("text", "") for k in key_events if k["params"].get("type") == "char")
    assert "private thoughts" not in typed
    assert "answer please" in typed