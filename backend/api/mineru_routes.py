"""MinerU 服务状态路由（只暴露 hasApiKey，绝不回显密钥）。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.adapters.out.document_parse.mineru_client import MineruClient
from backend.services.document_parse.config import load_mineru_settings

router = APIRouter(prefix="/mineru", tags=["mineru"])


@router.get("/status")
async def mineru_status() -> dict:
    settings = load_mineru_settings()
    body = {
        "configured": settings.configured,
        "enabled": settings.enabled,
        "hasApiKey": bool(settings.api_key),
        "reachable": False,
        "serverAuthMode": "unknown",
        "serverTiers": None,
        "serverVersion": None,
        "reason": "",
    }
    if not settings.configured:
        body["reason"] = "not_configured"
        return body
    info = await MineruClient(
        settings.base_url,
        api_key=settings.api_key,
        timeout_seconds=min(settings.timeout_seconds, 10.0),
    ).probe()
    body.update(
        reachable=bool(info.get("reachable")),
        serverAuthMode=info.get("serverAuthMode", "unknown"),
        serverTiers=info.get("serverTiers"),
        serverVersion=info.get("serverVersion"),
        reason=info.get("reason", ""),
    )
    return body
