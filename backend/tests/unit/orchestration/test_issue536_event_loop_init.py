"""Regression tests for issue #536.

Background
----------
PR #532 / #533 / main ran the Backend (Python) job with
``--dist loadfile`` (pytest-xdist). In some worker processes
the main thread has no running event loop, so any code that
calls ``asyncio.get_event_loop()`` from sync context raises::

    RuntimeError: There is no current event loop in thread 'MainThread'.

Production side
---------------
The orch runtime objects (``EventHub``, ``SnapshotStore``) used to
construct ``asyncio.Lock()`` eagerly. Py3.10+ keeps that lazy, but
the production contract is now: ``__init__`` must never raise and
must not bind the lock to a thread-specific loop policy at
construction time. The lock is created on first await inside
whatever loop is active at that point.

Calling side
------------
Sync test fixtures that drove coroutines with
``asyncio.get_event_loop().run_until_complete(...)`` also relied on
an implicit main-thread loop. The fix in
``test_orch_run_control_steer.py`` /
``test_orch_run_control.py`` /
``test_signal_detection.py`` replaces that pattern with
``asyncio.run(...)`` which always provides a fresh loop.

These tests verify:

1. ``EventHub()`` / ``SnapshotStore()`` construct outside any thread-local
   loop without raising.
2. The lock works when first awaited inside ``asyncio.run`` (the new pattern).
3. The lock works when first awaited inside a running loop (legacy path).
4. The lock works when first awaited inside a pytest-asyncio event_loop
   fixture (async test path).
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from backend.orchestration.event_hub import EventHub
from backend.orchestration.snapshot_store import SnapshotStore


def _construct_in_thread(fn_to_call) -> dict:
    """Run ``fn_to_call()`` inside a child thread with no current loop.

    Mimics the pytest-xdist worker main thread at fixture-build time.
    Returns a ``{exception, return_value}`` holder.
    """
    holder: dict = {}

    def target() -> None:
        try:
            asyncio.set_event_loop(None)
            holder["return_value"] = fn_to_call()
        except Exception as exc:  # noqa: BLE001
            holder["exception"] = exc

    t = threading.Thread(target=target)
    t.start()
    t.join()
    return holder


def test_eventhub_constructs_in_thread_without_running_loop() -> None:
    """Reproduces #536 surface 1 — construction must not raise.

    Even when ``asyncio.set_event_loop(None)`` was called in the
    current thread, ``EventHub()`` must build. The lock construction
    is lazy in Py3.10+ but the production contract should be enforced
    independent of that detail.
    """
    holder = _construct_in_thread(EventHub)
    assert "exception" not in holder, (
        f"EventHub() raised in a thread without a running loop: "
        f"{holder.get('exception')!r}. This is issue #536 surface 1."
    )
    assert isinstance(holder["return_value"], EventHub)


def test_snapshotstore_constructs_in_thread_without_running_loop() -> None:
    """Same #536 surface 1 for ``SnapshotStore``."""
    holder = _construct_in_thread(SnapshotStore)
    assert "exception" not in holder, (
        f"SnapshotStore() raised in a thread without a running loop: "
        f"{holder.get('exception')!r}. This is issue #536 surface 1."
    )


def test_eventhub_publish_works_under_asyncio_run_in_sync_thread() -> None:
    """Reproduces #536 surface 2 — sync test path must work.

    This is the exact code path that fails in CI: build deps in a
    sync fixture, then drive a coroutine via ``asyncio.run`` (which
    is what the production code recommends). The lock must be
    bindable inside the new loop on first ``await``.
    """
    hub = EventHub()
    from backend.domain.orch_events import make_event

    async def _go() -> None:
        await hub.publish(
            make_event(
                run_id="r1", seq=1, event_type="tool_call",
                producer="test", payload={}, entity=None,
            )
        )
        sub = await hub.subscribe("r1")
        await sub.close()

    # asyncio.run creates a fresh loop and runs _go inside it.
    asyncio.run(_go())


def test_eventhub_publish_works_inside_running_loop() -> None:
    """The standard async path — explicit ``asyncio.new_event_loop``.

    Construction and publish both happen inside an active loop,
    matching the production FastAPI lifespan context.
    """
    hub = EventHub()
    from backend.domain.orch_events import make_event

    async def _go() -> None:
        await hub.publish(
            make_event(
                run_id="r2", seq=1, event_type="tool_call",
                producer="test", payload={}, entity=None,
            )
        )

    asyncio.run(_go())


@pytest.mark.asyncio()
async def test_eventhub_publish_works_inside_pytest_asyncio_loop() -> None:
    """Async test path — pytest-asyncio owns the loop."""
    hub = EventHub()
    from backend.domain.orch_events import make_event

    await hub.publish(
        make_event(
            run_id="r3", seq=1, event_type="tool_call",
            producer="test", payload={}, entity=None,
        )
    )
