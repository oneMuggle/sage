"""Hooks REST 路由 (Phase 1 内置钩子元数据 + Phase 4 项目信任管理)。

前端契约:

- ``GET /api/v1/hooks/builtins``
    → ``{"builtins": [{id, name, description, icon, event, matcher,
    handler, default_config}, ...]}``

- ``GET /api/v1/hooks/project/status?workspace=<abs-path>``
    → ``{"workspace": str, "trusted": bool, "config_exists": bool,
        "hook_count": int}``

- ``POST /api/v1/hooks/project/trust``     body ``{"workspace": str}``
- ``POST /api/v1/hooks/project/untrust``   body ``{"workspace": str}``
    → ``{"ok": true, "trusted": bool}``

设置页 "推荐 Hook" 区域据此渲染可一键启用的内置钩子列表; 项目级信任
状态供"该项目有钩子配置, 是否启用?"提示使用。内置钩子的 **执行** 仍由
``backend/hooks/builtin.py`` 注册表驱动 —— 本端点只是把同一份注册表暴露
给 UI, 避免前端硬编码导致元数据漂移。

安全: 信任端点授予"执行仓库携带的命令"的权限, 属高权限操作。除定向
Origin 守卫外, 还强制要求 workspace 为已存在的绝对路径目录 (拒绝相对
路径 / 不存在路径, 防止误授信或路径猜测)。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.api.permission_routes import forbidden_origin_response
from backend.data.settings_repo import SettingsRepository
from backend.hooks.builtin import list_builtins
from backend.hooks.project_config import (
    PROJECT_CONFIG_REL_PATH,
    is_workspace_trusted,
    trust_workspace,
    untrust_workspace,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hooks", tags=["hooks"])


@router.get("/history")
async def list_hook_history(
    request: Request,
    limit: int = 50,
    hook_id: str = "",
    event: str = "",
    since: str = "",
):
    """返回最近的钩子执行记录 (供设置页诊断面板)。"""
    blocked = forbidden_origin_response(request)
    if blocked is not None:
        return blocked

    from backend.hooks.history import get_history_repo

    records = get_history_repo().list_records(
        limit=limit,
        hook_id=hook_id or None,
        event=event or None,
        since=since or None,
    )
    return JSONResponse(
        {
            "records": [
                {
                    "id": r.id,
                    "occurred_at": r.occurred_at,
                    "hook_id": r.hook_id,
                    "hook_type": r.hook_type,
                    "event": r.event,
                    "tool_name": r.tool_name,
                    "decision": r.decision,
                    "duration_ms": r.duration_ms,
                    "reason": r.reason,
                    "stdout_snippet": r.stdout_snippet,
                    "stderr_snippet": r.stderr_snippet,
                    "hook_config_snapshot": r.hook_config_snapshot,
                }
                for r in records
            ]
        }
    )


@router.delete("/history")
async def clear_hook_history(request: Request):
    """清空钩子执行历史。"""
    blocked = forbidden_origin_response(request)
    if blocked is not None:
        return blocked

    from backend.hooks.history import get_history_repo

    deleted = get_history_repo().clear()
    return JSONResponse({"ok": True, "deleted": deleted})


class WorkspaceBody(BaseModel):
    """信任/解除信任请求体。"""

    workspace: str


def _validated_workspace(raw: str) -> str | None:  # noqa: UP007 — 保持与仓库既有 py3.10 写法一致
    """校验 workspace 为已存在的绝对路径目录; 非法返回 None。"""
    if not raw or not isinstance(raw, str):
        return None
    if not Path(raw).is_absolute():
        return None
    resolved = os.path.realpath(raw)
    if not os.path.isdir(resolved):
        return None
    return resolved


@router.get("/builtins")
async def get_builtin_hooks(request: Request):
    """返回所有内置钩子元数据 (供设置页渲染)。"""
    blocked = forbidden_origin_response(request)
    if blocked is not None:
        return blocked
    return JSONResponse({"builtins": list_builtins()})


@router.get("/project/status")
async def get_project_status(request: Request, workspace: str = ""):
    """查询某工作区的项目级钩子信任状态。"""
    blocked = forbidden_origin_response(request)
    if blocked is not None:
        return blocked

    resolved = _validated_workspace(workspace)
    if resolved is None:
        return JSONResponse(
            {"error": "workspace must be an existing absolute directory path"},
            status_code=400,
        )

    settings_repo = SettingsRepository()
    config_path = Path(resolved) / PROJECT_CONFIG_REL_PATH

    # 已信任时统计实际生效的钩子条数; 未信任或配置非法 → 0
    hook_count = 0
    trusted = is_workspace_trusted(settings_repo, resolved)
    if trusted:
        try:
            from backend.hooks.project_config import load_project_hooks

            hook_count = len(load_project_hooks(resolved, settings_repo))
        except Exception as exc:  # pragma: no cover — 防御性
            logger.debug("project hook count failed: %s", exc)

    return JSONResponse(
        {
            "workspace": resolved,
            "trusted": trusted,
            "config_exists": config_path.is_file(),
            "hook_count": hook_count,
        }
    )


@router.post("/project/trust")
async def trust_project(request: Request, body: WorkspaceBody):
    """把工作区加入信任列表 (启用其 .sage/hooks.json)。"""
    blocked = forbidden_origin_response(request)
    if blocked is not None:
        return blocked

    resolved = _validated_workspace(body.workspace)
    if resolved is None:
        return JSONResponse(
            {"error": "workspace must be an existing absolute directory path"},
            status_code=400,
        )

    try:
        trust_workspace(SettingsRepository(), resolved)
    except Exception as exc:
        logger.warning("hooks: trust workspace failed: %s", exc)
        return JSONResponse({"error": "failed to persist trust"}, status_code=500)

    logger.info("hooks: workspace trusted: %s", resolved)
    return JSONResponse({"ok": True, "trusted": True})


@router.post("/project/untrust")
async def untrust_project(request: Request, body: WorkspaceBody):
    """把工作区移出信任列表 (其 .sage/hooks.json 不再加载)。"""
    blocked = forbidden_origin_response(request)
    if blocked is not None:
        return blocked

    resolved = _validated_workspace(body.workspace)
    if resolved is None:
        return JSONResponse(
            {"error": "workspace must be an existing absolute directory path"},
            status_code=400,
        )

    try:
        untrust_workspace(SettingsRepository(), resolved)
    except Exception as exc:
        logger.warning("hooks: untrust workspace failed: %s", exc)
        return JSONResponse({"error": "failed to persist trust"}, status_code=500)

    logger.info("hooks: workspace untrusted: %s", resolved)
    return JSONResponse({"ok": True, "trusted": False})
