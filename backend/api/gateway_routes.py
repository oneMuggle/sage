"""Gateway Routes - Telegram 网关状态查询（Round 6 MVP）

只读 status 端点：前端「网关」设置卡可展示 enabled/configured/统计。
启用方式（MVP）：环境变量 TELEGRAM_BOT_TOKEN + TELEGRAM_ALLOWED_CHAT_IDS，
由 main.py lifespan 注册轮询任务；未配置时网关完全不启动。
"""

from __future__ import annotations

from fastapi import APIRouter

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
