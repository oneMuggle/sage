"""Hooks REST 路由 (Phase 1: 内置钩子元数据)。

前端契约:

- ``GET /api/v1/hooks/builtins``
    → ``{"builtins": [{id, name, description, icon, event, matcher,
    handler, default_config}, ...]}``

设置页 "推荐 Hook" 区域据此渲染可一键启用的内置钩子列表。内置钩子的
**执行** 仍由 ``backend/hooks/builtin.py`` 注册表驱动 —— 本端点只是把
同一份注册表暴露给 UI, 避免前端硬编码导致元数据漂移。

安全: 只读元数据 (不含用户配置), 但仍加定向 Origin 守卫以对齐审批类
端点的纵深防御姿态。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.api.permission_routes import forbidden_origin_response
from backend.hooks.builtin import list_builtins

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hooks", tags=["hooks"])


@router.get("/builtins")
async def get_builtin_hooks(request: Request):
    """返回所有内置钩子元数据 (供设置页渲染)。"""
    blocked = forbidden_origin_response(request)
    if blocked is not None:
        return blocked
    return JSONResponse({"builtins": list_builtins()})
