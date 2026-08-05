"""Task 6 — SSE ``/api/v1/memory/events`` endpoint tests.

Verifies (by driving the ``StreamingResponse`` generator directly):

1. The endpoint returns ``media_type="text/event-stream"`` and registers a
   ``memory_written`` listener on the app's ``HookRegistry``.
2. When the hook fires, the generator yields a serialized SSE ``data:``
   line carrying the ``MemoryWriteEvent`` fields.
3. Closing the generator (client disconnect) removes the per-connection
   listener in ``finally``.

Why generator-level rather than over HTTP: ``httpx.ASGITransport`` waits
for the ASGI response to *complete* before returning, so an infinite SSE
stream (heartbeat + queue loop) can never be consumed through it — the
request hangs until the client disconnects. Driving
``StreamingResponse.body_iterator`` exercises the exact endpoint logic
(listener wiring, serialization, heartbeat timeout, finally-cleanup)
deterministically; the real HTTP path is covered by the manual curl smoke
test in the task report.

The endpoint lives in ``backend.api.legacy_routes`` (mounted at
``/api/v1`` via ``main.py``). Tests install a fresh ``HookRegistry`` on
``app.state.hooks`` because the FastAPI lifespan (which normally sets it)
is not run by ASGITransport.
"""

import asyncio
import json
from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from backend.main import app

pytestmark = pytest.mark.asyncio


def _make_request() -> Request:
    """Build a minimal HTTP Request scope pointing at the real app."""
    async def _never() -> dict:  # is_disconnected() times out → not disconnected
        await asyncio.Event().wait()  # pragma: no cover — never resolves
        return {}  # pragma: no cover

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/memory/events",
        "raw_path": b"/api/v1/memory/events",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 123),
        "server": ("testserver", 80),
        "app": app,
    }
    # NOTE: Request.__init__ takes `receive` as an explicit kwarg (defaulting
    # to empty_receive) — it does NOT read the scope's "receive" key.
    return Request(scope, receive=_never)


async def test_sse_endpoint_streams_memory_written_events():
    """The endpoint yields a serialized data: line when memory_written fires."""
    from backend.api.legacy_routes import memory_events
    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryWriteEvent

    hooks = HookRegistry()
    app.state.hooks = hooks

    response = await memory_events(_make_request())
    assert response.media_type == "text/event-stream"

    # The listener is registered when the endpoint function runs.
    assert len(hooks._listeners.get("memory_written", [])) == 1

    gen = response.body_iterator
    read_task = asyncio.create_task(gen.__anext__())

    await hooks.emit(
        "memory_written",
        MemoryWriteEvent(
            memory_id="test-1",
            content="test fact",
            memory_type="episodic",
            memory_category="user_pref",
            session_id="s1",
            turn_id="t1",
            timestamp=datetime.now(timezone.utc),  # noqa: UP017 — py38: datetime.UTC is 3.11+
        ),
    )

    chunk = await asyncio.wait_for(read_task, timeout=5.0)
    assert chunk.startswith("data: ")
    payload = json.loads(chunk[len("data: ") :].strip())
    assert payload["memory_id"] == "test-1"
    assert payload["content"] == "test fact"
    assert payload["memory_category"] == "user_pref"
    assert payload["session_id"] == "s1"
    assert payload["turn_id"] == "t1"
    # timestamp serialized as ISO-8601
    assert payload["timestamp"].endswith("+00:00")

    # client disconnect → finally{} removes the listener
    await gen.aclose()
    await asyncio.sleep(0.05)
    assert hooks._listeners.get("memory_written", []) == []


async def test_sse_endpoint_removes_listener_on_disconnect():
    """Closing the stream (disconnect) removes the per-connection listener."""
    from backend.api.legacy_routes import memory_events
    from backend.memory.hooks import HookRegistry

    hooks = HookRegistry()
    app.state.hooks = hooks

    response = await memory_events(_make_request())
    assert len(hooks._listeners.get("memory_written", [])) == 1

    gen = response.body_iterator
    # Start the generator so it enters the try block and waits on queue.get().
    read_task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0.05)
    assert not read_task.done()

    # Simulate client disconnect: cancelling the pending read injects
    # CancelledError into the generator at its await point, which runs the
    # finally{ hooks.off } cleanup. (aclose() cannot be used while a
    # __anext__ is in-flight — "asynchronous generator is already running".)
    read_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await read_task
    await asyncio.sleep(0.05)
    assert hooks._listeners.get("memory_written", []) == []
