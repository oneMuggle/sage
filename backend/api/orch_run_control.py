"""Orchestration run control REST endpoints.

Provides:
- GET /orch/runs/{run_id}/snapshot — current run snapshot (JSON)
- GET /orch/runs/{run_id}/events?after_seq=N — NDJSON event stream
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.orchestration.event_hub import EventHub
from backend.orchestration.snapshot_store import SnapshotStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orch/runs", tags=["orchestration"])

# Module-level singletons, wired at startup by backend.main
_snapshot_store: Optional[SnapshotStore] = None
_event_hub: Optional[EventHub] = None


def configure(
    snapshot_store: SnapshotStore,
    event_hub: EventHub,
) -> None:
    """注入运行时依赖（由 backend.main 启动时调用）。"""
    global _snapshot_store, _event_hub
    _snapshot_store = snapshot_store
    _event_hub = event_hub


@router.get("/{run_id}/snapshot")
async def get_snapshot(run_id: str) -> JSONResponse:
    """返回 run 的当前快照。"""
    if _snapshot_store is None:
        return JSONResponse({"error": "not_initialized"}, status_code=503)
    snapshot = _snapshot_store.get_run_snapshot(run_id)
    if snapshot is None:
        return JSONResponse({"error": "run_not_found"}, status_code=404)
    return JSONResponse(snapshot.to_dict())


@router.get("/{run_id}/events")
async def stream_events(
    request: Request,
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
) -> StreamingResponse:
    """NDJSON 事件流，支持 after_seq 续传。

    客户端断线后可携带上次收到的 seq 重连，服务端从 after_seq 之后
    重放保留历史，然后继续推送新事件。慢客户端不阻塞其他订阅者。
    """
    if _event_hub is None:
        return StreamingResponse(
            _error_stream("not_initialized"),
            media_type="application/x-ndjson",
        )

    async def generate():
        subscription = await _event_hub.subscribe(run_id, after_seq=after_seq)
        try:
            async for event in subscription:
                if await request.is_disconnected():
                    break
                yield json.dumps(event.to_dict(), ensure_ascii=False) + "\n"
        except asyncio.CancelledError:
            pass
        finally:
            await subscription.close()

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _error_stream(message: str):
    yield json.dumps({"error": message}) + "\n"


__all__ = ["router", "configure"]
