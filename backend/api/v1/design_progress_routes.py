"""Design progress routes — stage polling and SSE stage streaming."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.api.v1.design_shared import map_design_error, require_studio
from backend.api.v1.design_streaming import sse_event
from backend.design.errors import DesignProjectNotFoundError

router = APIRouter(prefix="/design", tags=["design"])


@router.get("/projects/{project_id}/progress")
async def get_progress(project_id: str):
    """Return the latest generation stage: idle / starting / composing /
    generating / linting / saving / complete / error."""
    studio = require_studio()
    try:
        progress = studio.get_progress(project_id)
    except DesignProjectNotFoundError as exc:
        return map_design_error(exc)
    return progress


@router.get("/projects/{project_id}/progress/stream")
async def stream_progress(project_id: str):
    """Stream generation stage changes as SSE (event: progress).

    Watches the in-memory stage map at ~500ms granularity and emits a frame
    whenever the stage (or its timestamp) changes; the stream ends after a
    ``complete`` or ``error`` stage. Renderer unlisten aborts the relay.
    """
    studio = require_studio()
    try:
        studio.get_project(project_id)
    except DesignProjectNotFoundError as exc:
        return map_design_error(exc)

    async def event_stream():
        last_key = None
        for _ in range(600):
            current = studio.get_progress(project_id)
            key = (current.get("stage"), current.get("updated_at"))
            if key != last_key:
                yield sse_event("progress", current)
                last_key = key
            if current.get("stage") in ("complete", "error"):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
