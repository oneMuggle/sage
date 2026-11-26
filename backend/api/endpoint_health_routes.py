"""2026-11-26: 端点健康快照 API（设置页健康状态展示用）。"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from backend.services.endpoint_health import get_health_registry

router = APIRouter(tags=["endpoints"])


def _configured_endpoint_ids() -> List[str]:
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json("app_settings")
        settings = to_camel(raw) if isinstance(raw, dict) else {}
        endpoints = settings.get("endpoints") or []
        return [
            ep["id"]
            for ep in endpoints
            if isinstance(ep, dict) and isinstance(ep.get("id"), str)
        ]
    except Exception:  # noqa: BLE001 — 健康 API 降级为空列表
        return []


def build_health_payload() -> Dict[str, Any]:
    return {"endpoints": get_health_registry().snapshot(_configured_endpoint_ids())}


@router.get("/endpoints/health")
def get_endpoints_health() -> Dict[str, Any]:
    return build_health_payload()
