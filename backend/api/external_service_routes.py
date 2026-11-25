"""通用外部服务状态路由：由 ExternalServiceSpec 声明驱动。

响应只暴露 ``hasApiKey`` 布尔，绝不回显密钥；探活异常转成 ``error`` 字段
而非 500，便于设置页展示可读诊断。MinerU 等具体服务按 spec 装配即可。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from backend.services.external_services.settings import load_service_settings
from backend.services.external_services.spec import ExternalServiceSpec


async def build_service_status(spec: ExternalServiceSpec) -> Dict[str, Any]:
    """按 spec 读取配置并可选探活，返回不含密钥的状态字典。"""
    values = load_service_settings(spec)
    base_url = str(values.get("baseUrl") or "").strip()
    body: Dict[str, Any] = {
        "configured": bool(base_url),
        "enabled": bool(values.get("enabled")),
        "hasApiKey": bool(str(values.get("apiKey") or "").strip()),
        "reachable": False,
        "error": "",
        "reason": "",
    }
    if not base_url:
        body["reason"] = "not_configured"
        return body
    if spec.probe is None:
        return body
    try:
        info = await spec.probe(values)
    except Exception as exc:  # noqa: BLE001 — 探活失败必须转成可读状态
        body["error"] = str(exc) or exc.__class__.__name__
        return body
    if isinstance(info, dict):
        for key, value in info.items():
            if key == "reachable":
                body["reachable"] = bool(value)
            elif key not in body:
                body[key] = value
        body["reason"] = str(info.get("reason") or "")
    return body


def build_external_service_router(spec: ExternalServiceSpec) -> APIRouter:
    """为单个服务装配 ``/<api_prefix>/status`` 路由。"""
    prefix = f"/{spec.api_prefix or spec.name}"
    router = APIRouter(prefix=prefix, tags=[spec.name])

    @router.get("/status")
    async def service_status() -> Dict[str, Any]:
        return await build_service_status(spec)

    return router
