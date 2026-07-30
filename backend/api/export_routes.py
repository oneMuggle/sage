"""
会话 HTML 导出路由 (U18)

``POST /api/v1/sessions/{session_id}/export``

- 默认返回 JSON 信封 ``{"html": ..., "filename": ...}`` —— Electron IPC
  桥 (electron/invoke.ts) 对响应恒定 ``res.json()``,渲染进程拿到 HTML
  文本后用 Blob 触发下载;
- 请求头 ``Accept: text/html`` (且未同时要求 JSON) 时直接返回 HTML
  文件 (``Content-Disposition: attachment``),便于 curl / 浏览器直取。

产物为自包含离线 HTML,详见
``backend/application/services/session_export.py``。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from backend.application.services.session_export import (
    DEFAULT_THEME,
    VALID_THEMES,
    SessionNotFoundError,
    export_session_to_html,
)

router = APIRouter(tags=["export"])


class ExportSessionRequest(BaseModel):
    """导出请求体(整体可省略,缺省 auto 主题)。"""

    theme: str = Field(
        default=DEFAULT_THEME,
        description="导出主题: auto(跟随系统) / dark / light,非法值归一化为 auto",
    )

    class Config:
        # 与 IPC 桥约定:body 只允许已知字段,避免 camelToSnake 残留键
        extra = "forbid"


@router.post("/sessions/{session_id}/export")
def export_session(
    session_id: str,
    body: Optional[ExportSessionRequest] = None,
    accept: Optional[str] = Header(default=None),
):
    """导出会话为自包含 HTML。

    用同步 ``def`` 而非 ``async def``:导出含全量 sqlite 读 + 多文件读 +
    大 JSON 序列化 + ~200KB 拼接,属阻塞重活。声明为同步后 FastAPI 把它丢
    进线程池,避免在事件循环线程上卡住同 loop 的 SSE 聊天流。

    Returns:
        JSON 信封 ``{html, filename, session_id, message_count, theme}``;
        或 ``Accept: text/html`` 时直接返回 HTML 文件。
    """
    request = body or ExportSessionRequest()
    theme = request.theme if request.theme in VALID_THEMES else DEFAULT_THEME

    try:
        result = export_session_to_html(session_id, theme=theme)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在")

    if accept and "text/html" in accept and "application/json" not in accept:
        return HTMLResponse(
            content=result.html,
            headers={
                "Content-Disposition": 'attachment; filename="{}"'.format(result.filename)
            },
        )

    return {
        "html": result.html,
        "filename": result.filename,
        "session_id": result.session_id,
        "message_count": result.message_count,
        "theme": result.theme,
    }
