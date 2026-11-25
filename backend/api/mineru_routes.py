"""MinerU 服务状态路由：委托通用 spec 驱动构建器（只暴露 hasApiKey，绝不回显密钥）。"""

from __future__ import annotations

from backend.api.external_service_routes import build_external_service_router
from backend.services.external_services.registry import get_service

_spec = get_service("mineru")
if _spec is None:  # pragma: no cover - 内置注册表恒有 mineru
    raise RuntimeError("mineru spec 未注册")

router = build_external_service_router(_spec)
