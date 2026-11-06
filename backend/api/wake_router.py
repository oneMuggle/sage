"""会话唤醒 REST 路由（2026-11-05）。

把既有的 A4 Suspend-Resume 能力暴露给非 LLM 调用方（前端 / 外部脚本）：
``POST /api/v1/sessions/{session_id}/wake`` 注册一条 TIMER wake，
到点由 ``WakeScheduler`` 恢复会话并注入续跑消息。

与 LLM 工具 ``wake_session_at`` 共用同一个 ``WakeStore`` 单一事实源。
"""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.application.services.chat_service import ChatService

ChatServiceGetter = Callable[[], Optional[ChatService]]


class WakeIn(BaseModel):
    """唤醒请求体：``seconds`` 与 ``at`` 二选一。"""

    seconds: Optional[float] = None
    at: Optional[str] = None
    note: str = ""


def build_router(get_service: ChatServiceGetter) -> APIRouter:
    router = APIRouter()

    def service_dep() -> ChatService:
        svc = get_service()
        if svc is None:
            raise HTTPException(status_code=503, detail="chat service not initialised")
        return svc

    @router.post("/sessions/{session_id}/wake")
    async def schedule_wake(
        session_id: str,
        payload: WakeIn,
        svc: ChatService = Depends(service_dep),
    ) -> dict:
        if (payload.seconds is None) == (payload.at is None):
            raise HTTPException(
                status_code=422,
                detail="exactly one of 'seconds' or 'at' is required",
            )
        try:
            if payload.seconds is not None:
                wake = await svc.sleep_for(session_id, payload.seconds, note=payload.note)
            else:
                wake = await svc.sleep_until(session_id, payload.at or "", note=payload.note)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if wake is None:
            raise HTTPException(status_code=503, detail="wake store not configured")
        return {
            "ok": True,
            "wake_id": wake.id,
            "session_id": wake.session_id,
            "fire_at": wake.fire_at,
        }

    return router
