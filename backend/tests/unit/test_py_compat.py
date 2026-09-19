"""Python compatibility helper tests."""

from contextvars import ContextVar

import pytest

from backend.utils import py_compat


@pytest.mark.asyncio()
async def test_py38_to_thread_propagates_context(monkeypatch) -> None:
    marker: ContextVar[str] = ContextVar("py38_test_marker", default="missing")
    token = marker.set("session-ctx")
    try:
        monkeypatch.setattr(py_compat, "_has_native_to_thread", False)
        observed = await py_compat.to_thread(marker.get)
    finally:
        marker.reset(token)

    assert observed == "session-ctx"
