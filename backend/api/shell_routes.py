"""后台 shell 列表与输出流路由（2026-11-06 Phase 3）。

- ``GET /api/v1/shells``：列出注册表中的后台 shell（运行中 + 已退出待清理）。
- ``GET /api/v1/shells/{shell_id}/stream``：NDJSON 输出流 —— 每 0.5s
  增量读取 stdout/stderr，退出时发 ``{"type":"exit"}`` 并结束连接。

渲染端经 Electron 主进程 relay（``shell-stream-{shellId}``）消费。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.tools.bash_session import STATUS_EXITED, get_registry

router = APIRouter()

STREAM_POLL_SECONDS = 0.5
STREAM_READ_CAP = 64 * 1024


@router.get("/shells")
def list_shells() -> Dict[str, Any]:
    """列出后台 shell 快照（按注册顺序）。"""
    registry = get_registry()
    now = time.monotonic()
    items: List[Dict[str, Any]] = []
    for session in registry.list_sessions():
        items.append(
            {
                "shell_id": session.shell_id,
                "command": session.command,
                "status": session.status(),
                "pid": getattr(session.process, "pid", None),
                "age_seconds": max(0, int(now - session.started_at)),
            }
        )
    return {"shells": items}


@router.get("/shells/{shell_id}/stream")
async def stream_shell(shell_id: str) -> StreamingResponse:
    """流式输出 NDJSON；shell 不存在时 404。"""
    registry = get_registry()
    if registry.get(shell_id) is None:
        raise HTTPException(status_code=404, detail="unknown shell_id")

    async def event_generator() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        while True:
            payload = await loop.run_in_executor(
                None, lambda: registry.read_increment(shell_id, cap=STREAM_READ_CAP)
            )
            if payload is None:
                # 会话被 terminate/clear 移除
                yield json.dumps({"type": "exit", "exit_code": None}) + "\n"
                return
            stdout = payload.get("stdout") or ""
            stderr = payload.get("stderr") or ""
            if stdout:
                yield json.dumps(
                    {"type": "output", "stream": "stdout", "data": stdout}
                ) + "\n"
            if stderr:
                yield json.dumps(
                    {"type": "output", "stream": "stderr", "data": stderr}
                ) + "\n"
            if payload.get("status") == STATUS_EXITED:
                yield json.dumps(
                    {"type": "exit", "exit_code": payload.get("exit_code")}
                ) + "\n"
                return
            await asyncio.sleep(STREAM_POLL_SECONDS)

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")
