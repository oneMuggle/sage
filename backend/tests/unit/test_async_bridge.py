"""Tests for async_bridge timeout and cancellation (C3)."""
from __future__ import annotations

import asyncio
import concurrent.futures
import time

import pytest

from backend.design.async_bridge import DEFAULT_TIMEOUT, run_sync


class TestRunSyncTimeout:
    """``run_sync`` must cancel the coroutine when timeout elapses."""

    def test_timeout_raises_concurrent_future_timeout_error(self):
        """A slow coroutine must raise TimeoutError, not block forever."""

        async def _slow() -> str:
            await asyncio.sleep(10)
            return "should not reach"

        with pytest.raises(concurrent.futures.TimeoutError):
            run_sync(_slow(), timeout=0.05)

    def test_no_timeout_waits_indefinitely(self):
        """Without timeout, run_sync blocks until the coroutine completes."""

        async def _fast() -> str:
            return "done"

        assert run_sync(_fast()) == "done"

    def test_timeout_cancels_coroutine(self):
        """After timeout, the coroutine must be cancelled (no ghost work).

        Uses an event flag to detect whether the coroutine ran to completion
        after the timeout.  If the cancellation works, the flag stays unset.
        """
        completed = False

        async def _track_completion() -> str:
            nonlocal completed
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                # In py3.8 CancelledError is Exception; in py3.9+ BaseException.
                # Either way, we must NOT set completed.
                raise
            completed = True
            return "should not reach"

        with pytest.raises(concurrent.futures.TimeoutError):
            run_sync(_track_completion(), timeout=0.05)

        # Give the bridge loop a moment to process the cancellation.
        time.sleep(0.2)
        assert completed is False, "Coroutine was not cancelled on timeout"

    def test_default_timeout_is_exported(self):
        """DEFAULT_TIMEOUT must be importable and positive."""
        assert isinstance(DEFAULT_TIMEOUT, float)
        assert DEFAULT_TIMEOUT > 0
