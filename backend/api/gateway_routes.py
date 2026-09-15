"""Gateway Routes - Telegram 网关状态与绑定管理（Round 6 MVP / Round 15 绑定管理）

只读 status + 绑定管理：前端「网关」设置卡展示状态/绑定列表，
解绑后下次消息重新建会话。
启用方式（MVP）：环境变量 TELEGRAM_BOT_TOKEN + TELEGRAM_ALLOWED_CHAT_IDS，
由 main.py lifespan 注册轮询任务；未配置时网关完全不启动。
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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


# ---------------------------------------------------------------------------
# Round 19: 网关配置读写（settings 持久化，前端设置卡入口）
# ---------------------------------------------------------------------------


def _mask_token(token: str) -> str:
    if not token:
        return ""
    return "****" + token[-4:]


def _read_telegram_settings() -> dict:
    from backend.data.settings_repo import SettingsRepository

    app_settings = SettingsRepository().get_json("app_settings") or {}
    node = app_settings.get("telegram") if isinstance(app_settings, dict) else None
    return node if isinstance(node, dict) else {}


@router.get("/gateway/telegram/config")
def get_telegram_config():
    """当前网关配置（token 打码，只回尾 4 位）。

    - 200 + ``{"configured": bool, "enabled": bool, "bot_token_masked": str,
      "allowed_chat_ids": [...], "source": "settings"|"env"|"none"}``
    """
    import os


    env_token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    node = _read_telegram_settings()
    settings_token = str(node.get("bot_token") or "").strip()
    if env_token:
        source = "env"
        token = env_token
        enabled = True
    elif settings_token and node.get("enabled") is not False:
        source = "settings"
        token = settings_token
        enabled = True
    else:
        source = "none"
        token = settings_token or env_token
        enabled = False
    raw_ids = node.get("allowed_chat_ids")
    if env_token:
        raw_ids = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS") or []
        raw_ids = raw_ids.split(",") if raw_ids else []
    if isinstance(raw_ids, str):
        raw_ids = raw_ids.split(",")
    return {
        "configured": bool(token),
        "enabled": enabled,
        "source": source,
        "bot_token_masked": _mask_token(token),
        "allowed_chat_ids": [str(c).strip() for c in raw_ids if str(c).strip()],
    }


class TelegramConfigUpdate(BaseModel):
    """``PUT /gateway/telegram/config`` 请求体（Round 19）。

    bot_token 传空串 = 清除（关闭网关）。
    """

    bot_token: str = ""
    allowed_chat_ids: List[str] = []
    enabled: bool = True


@router.put("/gateway/telegram/config")
def update_telegram_config(data: TelegramConfigUpdate):
    """保存网关配置到 app_settings.telegram（settings 持久化）。

    - 200 + ``{"saved": true, "restart_required": true}``
      （轮询线程在 lifespan 启动时创建，改配置后需重启后端生效——
      restart_required 提示前端）
    """
    from backend.data.settings_repo import SettingsRepository

    repo = SettingsRepository()
    app_settings = repo.get_json("app_settings") or {}
    if not isinstance(app_settings, dict):
        app_settings = {}
    app_settings["telegram"] = {
        "bot_token": data.bot_token.strip(),
        "allowed_chat_ids": [
            str(c).strip() for c in data.allowed_chat_ids if str(c).strip()
        ],
        "enabled": bool(data.enabled),
    }
    repo.set_json("app_settings", app_settings)
    return {"saved": True, "restart_required": True}
