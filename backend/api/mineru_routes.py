"""MinerU 服务状态路由：委托通用 spec 驱动构建器（只暴露 hasApiKey，绝不回显密钥）。"""

from __future__ import annotations

from typing import Any, Dict

from backend.adapters.out.document_parse.mineru_client import MineruClient
from backend.api.external_service_routes import build_external_service_router
from backend.domain.document_parse import DEFAULT_TIMEOUT_SECONDS
from backend.services.external_services.registry import get_service

_spec = get_service("mineru")
if _spec is None:  # pragma: no cover - 内置注册表恒有 mineru
    raise RuntimeError("mineru spec 未注册")


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def _probe_mineru(values: Dict[str, Any]) -> Dict[str, Any]:
    client = MineruClient(
        base_url=str(values.get("baseUrl") or ""),
        api_key=str(values.get("apiKey") or ""),
        timeout_seconds=_as_float(values.get("timeoutSeconds"), DEFAULT_TIMEOUT_SECONDS),
    )
    return await client.probe()


router = build_external_service_router(_spec, probe=_probe_mineru)
