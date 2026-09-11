"""Gateway Routes - Telegram 网关状态与绑定管理（Round 6 MVP / Round 15 绑定管理）

只读 status + 绑定管理：前端「网关」设置卡展示状态/绑定列表，
解绑后下次消息重新建会话。
启用方式（MVP）：环境变量 TELEGRAM_BOT_TOKEN + TELEGRAM_ALLOWED_CHAT_IDS，
由 main.py lifespan 注册轮询任务；未配置时网关完全不启动。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/gateway/telegram/status")
def telegram_gateway_status():
    """Telegram 网关运行状态。

    - 200 + ``{"configured": bool, "running": bool, "stats": {...},
      "bound_chats": N}``
    """
    from backend.gateway.telegram import get_telegram_gateway

    gateway = get_telegram_gateway()
    configured = gateway is not None
    bound_chats = 0
    if gateway is not None:
        try:
            row = gateway._conn().execute(
                "SELECT COUNT(*) FROM telegram_chats"
            ).fetchone()
            bound_chats = row[0] if row else 0
        except Exception:  # noqa: BLE001 — 统计失败不影响状态上报
            bound_chats = 0
    return {
        "configured": configured,
        "running": configured,
        "bound_chats": bound_chats,
        "stats": gateway.stats.__dict__ if gateway else {},
    }


@router.get("/gateway/telegram/binds")
def list_telegram_binds():
    """列出 chat↔session 绑定（Round 15）。

    - 200 + ``{"binds": [{"chat_id", "session_id", "created_at"}]}``
    - 503 — 网关未启用（未配置 TELEGRAM_BOT_TOKEN）
    """
    from backend.gateway.telegram import get_telegram_gateway

    gateway = get_telegram_gateway()
    if gateway is None:
        raise HTTPException(
            status_code=503,
            detail={
                "type": "gateway_disabled",
                "message": "Telegram gateway not configured",
            },
        )
    try:
        rows = gateway._conn().execute(
            "SELECT chat_id, session_id, created_at FROM telegram_chats "
            "ORDER BY created_at DESC"
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — 查询失败按 500 上报
        raise HTTPException(
            status_code=500,
            detail={"type": "bind_query_failed", "message": str(exc)},
        ) from exc
    return {
        "binds": [
            {"chat_id": r[0], "session_id": r[1], "created_at": r[2]} for r in rows
        ]
    }


@router.delete("/gateway/telegram/binds/{chat_id}")
def unbind_telegram_chat(chat_id: str):
    """解绑一个 chat（下次消息重新建会话）（Round 15）。

    - 200 + ``{"chat_id": ..., "unbound": true}``
    - 503 — 网关未启用；404 — 绑定不存在
    """
    from backend.gateway.telegram import get_telegram_gateway

    gateway = get_telegram_gateway()
    if gateway is None:
        raise HTTPException(
            status_code=503,
            detail={
                "type": "gateway_disabled",
                "message": "Telegram gateway not configured",
            },
        )
    try:
        cursor = gateway._conn().execute(
            "DELETE FROM telegram_chats WHERE chat_id = ?", (chat_id,)
        )
        gateway._conn().commit()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"type": "unbind_failed", "message": str(exc)},
        ) from exc
    if cursor.rowcount == 0:
        raise HTTPException(
            status_code=404,
            detail={"type": "bind_not_found", "message": "bind not found"},
        )
    return {"chat_id": chat_id, "unbound": True}
