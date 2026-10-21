"""Harness 组件可观测性路由 (阶段 1)。

端点
----

- ``GET  /api/v1/harness/components``                列出 harness 组件
- ``GET  /api/v1/harness/components/{id}``           获取单个组件
- ``POST /api/v1/harness/components``                注册组件（幂等）
- ``POST /api/v1/harness/components/{id}/record``    记录一次使用（effectiveness 埋点）
- ``GET  /api/v1/harness/needing-improvement``       列出效果不佳待改进的组件

设计要点
--------

- **与 API_MODE 无关**：本 router 在 ``main.py`` 中无条件挂载（与
  ``usage_router`` / ``prompt_router`` 同款），不随 hex/legacy 双轨切换。
- **DI 可覆盖**：``get_harness_service()`` 是 ``Depends`` 工厂，测试可用
  ``app.dependency_overrides[get_harness_service]`` 注入内存实现。
- **响应体为普通 dict**：绕开 pydantic v1/v2 差异（win7 跑 pydantic 1.x）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.adapters.out.harness import SqliteHarnessAdapter
from backend.application.services.harness_service import (
    HARNESS_COMPONENT_TYPES,
    HarnessService,
    InvalidComponentTypeError,
)
from backend.domain.harness_component import HarnessComponent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/harness", tags=["harness"])


def get_harness_service() -> HarnessService:
    """构造 ``HarnessService``（默认注入 SQLite adapter）。

    测试可通过 ``app.dependency_overrides[get_harness_service]`` 覆盖为
    内存实现。
    """
    return HarnessService(SqliteHarnessAdapter())


def _component_to_dict(component: HarnessComponent) -> Dict[str, Any]:
    """``HarnessComponent`` → API 响应 dict。"""
    metrics = component.effectiveness
    return {
        "id": component.id,
        "type": component.type,
        "name": component.name,
        "version": component.version,
        "config": component.config,
        "effectiveness": {
            "usage_count": metrics.usage_count,
            "success_rate": metrics.success_rate,
            "avg_latency_ms": metrics.avg_latency_ms,
            "user_satisfaction": metrics.user_satisfaction,
            "last_used_at": metrics.last_used_at,
        },
        "needs_improvement": component.needs_improvement(),
        "created_at": component.created_at,
        "updated_at": component.updated_at,
    }


@router.get("/components")
async def list_harness_components(
    type: Optional[str] = Query(  # noqa: A002 — 与 OpenAPI schema 字段名一致
        None, description=f"按类型过滤，合法值: {', '.join(HARNESS_COMPONENT_TYPES)}"
    ),
    service: HarnessService = Depends(get_harness_service),
) -> Dict[str, Any]:
    """列出 harness 组件及其 effectiveness 指标。"""
    try:
        components = await service.list_components(type)
    except InvalidComponentTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "items": [_component_to_dict(c) for c in components],
        "total": len(components),
        "component_types": list(HARNESS_COMPONENT_TYPES),
    }


@router.get("/components/{component_id}")
async def get_harness_component(
    component_id: str,
    service: HarnessService = Depends(get_harness_service),
) -> Dict[str, Any]:
    """获取单个 harness 组件。"""
    component = await service.get_component(component_id)
    if component is None:
        raise HTTPException(status_code=404, detail=f"组件不存在: {component_id}")
    return _component_to_dict(component)


@router.post("/components", status_code=201)
async def register_harness_component(
    payload: Dict[str, Any],
    service: HarnessService = Depends(get_harness_service),
) -> Dict[str, Any]:
    """注册 harness 组件（幂等：同 ID 重复注册会更新配置）。"""
    component_id = str(payload.get("id") or "").strip()
    component_type = str(payload.get("type") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not component_id or not component_type or not name:
        raise HTTPException(status_code=400, detail="id / type / name 均为必填")
    config = payload.get("config")
    if config is not None and not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="config 必须是 JSON 对象")

    try:
        component = await service.register_component(
            component_id, component_type, name, config
        )
    except InvalidComponentTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _component_to_dict(component)


@router.post("/components/{component_id}/record")
async def record_harness_usage(
    component_id: str,
    payload: Dict[str, Any],
    service: HarnessService = Depends(get_harness_service),
) -> Dict[str, Any]:
    """记录一次组件使用，累积 effectiveness 指标。

    组件不存在时返回 404（调用方应先注册组件再埋点）。
    """
    success = bool(payload.get("success", True))
    latency_ms = float(payload.get("latency_ms", 0.0) or 0.0)

    component = await service.get_component(component_id)
    if component is None:
        raise HTTPException(status_code=404, detail=f"组件不存在: {component_id}")

    await service.record_usage(component_id, success, latency_ms)
    updated = await service.get_component(component_id)
    if updated is None:  # pragma: no cover — 刚校验过存在
        raise HTTPException(status_code=404, detail=f"组件不存在: {component_id}")
    return _component_to_dict(updated)


@router.get("/needing-improvement")
async def list_harness_needing_improvement(
    service: HarnessService = Depends(get_harness_service),
) -> Dict[str, Any]:
    """列出效果不佳待改进的组件（成功率/延迟/满意度不达标）。"""
    components = await service.list_needing_improvement()
    return {
        "items": [_component_to_dict(c) for c in components],
        "total": len(components),
    }
