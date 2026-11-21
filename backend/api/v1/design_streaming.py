"""SSE helpers for design routes — progress relay and error framing."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Awaitable, Callable

from backend.design.errors import (
    DesignGenerationError,
    DesignProjectNotFoundError,
    DesignTemplateKindMismatchError,
)

logger = logging.getLogger(__name__)

__all__ = ["sse_event", "stream_studio_call"]


def sse_event(event_type: str, payload: dict) -> str:
    """Format a single SSE event frame."""
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


def _sse_error_event(exc: Exception, label: str) -> str:
    """Map a studio exception to an SSE ``error`` frame."""
    if isinstance(  # noqa: UP038 — py38 兼容
        exc,
        (
            DesignProjectNotFoundError,
            DesignGenerationError,
            DesignTemplateKindMismatchError,
        ),
    ):
        return sse_event("error", {"detail": str(exc)})
    logger.exception("Design %s failed", label.lower())
    return sse_event("error", {"detail": f"{label} failed: {exc}"})


async def stream_studio_call(
    studio_call: Callable[[asyncio.Queue], Awaitable[object]],
    label: str,
):
    """Relay a studio generate/iterate call as SSE frames.

    The studio pushes ``{"stage", "message"}`` dicts to the queue at each
    stage; the result is appended as ``("complete", artifact)`` and failures
    as ``("error", exc)``.
    """
    progress_queue: asyncio.Queue = asyncio.Queue()

    async def runner():
        try:
            artifact = await studio_call(progress_queue)
            await progress_queue.put(("complete", artifact))
        except Exception as exc:
            await progress_queue.put(("error", exc))

    task = asyncio.create_task(runner())
    try:
        while True:
            item = await progress_queue.get()
            if isinstance(item, tuple):
                kind, payload = item
                if kind == "complete":
                    yield sse_event("complete", {
                        "artifact": payload.model_dump(mode="json"),
                    })
                else:
                    yield _sse_error_event(payload, label)
                break
            yield sse_event("progress", item)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
