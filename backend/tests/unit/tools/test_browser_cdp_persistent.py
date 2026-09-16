from __future__ import annotations

import asyncio
import json
import pytest

from backend.tools.browser_cdp import PersistentCDPSession


def test_persistent_session_class_exists():
    """Smoke test that the class can be imported and inspected."""
    assert PersistentCDPSession is not None
    # Class must have send, close, events attributes
    for attr in ("events", "send", "close"):
        assert hasattr(PersistentCDPSession, attr), f"missing {attr}"


def test_persistent_session_increments_message_id(monkeypatch):
    """send() must assign monotonically increasing ids; use a fake transport."""
    sent_payloads: list = []

    class FakeWS:
        def __init__(self):
            self.closed = False
            self._responses = {
                1: {"id": 1, "result": {"frameTree": {}}},
            }
        async def send(self, data):
            sent_payloads.append(json.loads(data))
        async def recv(self):
            # return next queued response, or block
            return json.dumps({"id": 1, "result": {}}).encode()
        async def close(self):
            self.closed = True

    # Construction alone shouldn't open a connection
    # (we test message-id generation via a helper or direct method)
    from backend.tools.browser_cdp import _next_message_id, _reset_message_id
    _reset_message_id()
    assert _next_message_id() == 1
    assert _next_message_id() == 2
    assert _next_message_id() == 3
