"""Unit tests for HookRegistry (Task 4 — memory lifecycle pub/sub).

Contract from task-4-brief.md step 1:
- emit() calls all listeners (sync + async) with the payload
- listener exceptions are swallowed (never raised into caller)
- off() removes a listener so it no longer fires
- emit() with no listeners is a safe no-op
"""

from __future__ import annotations

import pytest

from backend.memory.hooks import HookRegistry

pytestmark = pytest.mark.unit


@pytest.mark.asyncio()
async def test_emit_calls_all_listeners():
    """All registered listeners (sync + async) receive the payload."""
    reg = HookRegistry()
    calls: list[tuple[str, object]] = []
    reg.on("test", lambda x: calls.append(("sync", x)))

    async def async_listener(x):
        calls.append(("async", x))

    reg.on("test", async_listener)
    await reg.emit("test", "payload")
    assert ("sync", "payload") in calls
    assert ("async", "payload") in calls


@pytest.mark.asyncio()
async def test_listener_exception_does_not_block_others():
    """A listener raising must be logged but never propagate to the caller,
    and remaining listeners still run."""

    reg = HookRegistry()
    calls: list[str] = []

    def bad(x):  # noqa: ARG001
        raise RuntimeError("boom")

    reg.on("test", bad)
    reg.on("test", lambda x: calls.append(x))
    # must NOT raise
    await reg.emit("test", "p")
    assert calls == ["p"]


@pytest.mark.asyncio()
async def test_off_removes_listener():
    """off() detaches a previously registered listener so it no longer fires."""

    reg = HookRegistry()
    calls: list[str] = []

    def cb(x):
        calls.append(x)

    reg.on("test", cb)
    reg.off("test", cb)
    await reg.emit("test", "p")
    assert calls == []


@pytest.mark.asyncio()
async def test_emit_with_no_listeners_is_noop():
    """emit() on an event with zero listeners is a safe no-op (never raises)."""

    reg = HookRegistry()
    # must NOT raise
    await reg.emit("nobody", "p")


# ----------------------------------------------------------------------------
# F6 — emit_sync (spec'd in task-4-brief.md step 3 but absent). Later Task 6
# (SSE) will consume it from synchronous call sites.
# ----------------------------------------------------------------------------


def test_emit_sync_without_running_loop_runs_to_completion():
    """emit_sync() with no running event loop runs listeners synchronously
    to completion (via asyncio.run)."""
    reg = HookRegistry()
    calls: list[str] = []
    reg.on("test", lambda x: calls.append(x))
    reg.emit_sync("test", "p")
    assert calls == ["p"]


def test_emit_sync_inside_running_loop_schedules_listeners():
    """emit_sync() called from inside a running loop must schedule the async
    listeners on that loop (fire-and-forget) without blocking the caller."""
    import asyncio

    reg = HookRegistry()
    calls: list[str] = []

    async def async_listener(x):
        calls.append(x)

    reg.on("test", async_listener)

    async def main():
        reg.emit_sync("test", "p")
        # give the scheduled task a chance to run
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(main())
    assert calls == ["p"]
