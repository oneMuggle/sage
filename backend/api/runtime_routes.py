"""``/api/v1/runtime/*`` —— 本地开发环境助手 REST 端点。

把 3 个 runtime 工具 (runtime_probe / project_diagnose / runtime_exec)
暴露为 REST。设计上复用 ChatService.tools 路径而非新建 ToolRegistry，
原因:

- ChatService.tools 已持有 InprocToolAdapter（含 register_all_tools 全部工具
  + MemoryManager 注入 + PermissionEnforcer 分发前拦截）
- runtime_exec 走 EXEC 风险等级, 必须经过权限审批 —— 与既有 BashTool 一致;
  通过 InprocToolAdapter.execute 自动走 M1 PermissionEnforcer 矩阵,
  无需重复实现权限逻辑
- 与 chat 流共享工具注册链, 新工具接入只需 register_all_tools 一次

端点契约:

- POST /api/v1/runtime/probe   — 只读, 无需审批
- POST /api/v1/runtime/diagnose — 只读, 无需审批
- POST /api/v1/runtime/exec    — EXEC, 经 PermissionEnforcer 拦截,
                                  不可旁路审批
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runtime", tags=["runtime"])


def _get_chat_service(request: Request) -> Any:
    """从 app.state 取 ChatService。chat_service 必须由 main.py lifespan 注入。"""
    chat_service = getattr(request.app.state, "chat_service", None)
    if chat_service is None:
        raise HTTPException(
            status_code=503,
            detail="chat_service 未初始化",
        )
    return chat_service


def _require_tool(chat_service: Any, name: str) -> None:
    """工具未注册时返回 503 —— 与 InprocToolAdapter.execute 的语义一致。"""
    names = {spec.name for spec in chat_service.tools.list_tools()}
    if name not in names:
        raise HTTPException(
            status_code=503,
            detail=f"runtime 工具未注册: {name}",
        )


async def _dispatch(
    request: Request,
    tool_name: str,
    args: Dict[str, Any],
) -> Dict[str, Any]:
    chat_service = _get_chat_service(request)
    _require_tool(chat_service, tool_name)
    # InprocToolAdapter.execute 是 async, 内部走 asyncio.to_thread;
    # PermissionEnforcer 在分发前拦截 EXEC 类工具。
    result = await chat_service.tools.execute(tool_name, args)
    # ToolResult(success, output, error, metadata) -> dict
    payload: Dict[str, Any] = {
        "success": bool(getattr(result, "success", False)),
    }
    output = getattr(result, "output", None)
    if output is not None:
        # output 可能是字符串(str(content))或 dict, 原样透传
        payload["output"] = output
    error = getattr(result, "error", None)
    if error:
        payload["error"] = str(error)
    metadata = getattr(result, "metadata", None)
    if metadata:
        payload["metadata"] = dict(metadata)
    if not payload["success"]:
        # 统一用 200 + success=false 表示工具执行失败, 与 InprocToolAdapter
        # 的 fail-open 一致; 真正的 5xx 留给 chat_service 未就绪等
        # 系统级问题。LLM 看到 success=false 即可决定下一步。
        pass
    return payload


# ----- /probe -----


class ProbeRequestBody(BaseModel):
    languages: Optional[list] = Field(default=None, description="可选: 仅探测这些语言")
    include_tools: bool = Field(default=True, description="是否同时探测工具链")
    target_version: Optional[str] = Field(default=None, description="可选版本约束")
    include_paths: Optional[list] = Field(default=None, description="额外搜索路径")
    workspace_root: Optional[str] = Field(default=None, description="项目根目录")


@router.post("/probe")
async def runtime_probe(body: ProbeRequestBody, request: Request) -> Dict[str, Any]:
    """只读探测本机可用的运行时 + 工具链。无副作用。"""
    args: Dict[str, Any] = {
        "languages": body.languages,
        "include_tools": body.include_tools,
        "target_version": body.target_version,
        "include_paths": body.include_paths,
    }
    if body.workspace_root:
        args["workspace_root"] = body.workspace_root
    return await _dispatch(request, "runtime_probe", args)


# ----- /diagnose -----


class DiagnoseRequestBody(BaseModel):
    languages: Optional[list] = Field(default=None, description="可选: 仅诊断这些语言")
    include_tools: bool = Field(default=True, description="是否同时探测工具链")
    target_version: Optional[str] = Field(default=None, description="可选版本约束")
    project_root: Optional[str] = Field(default=None, description="项目根目录")


@router.post("/diagnose")
async def runtime_diagnose(body: DiagnoseRequestBody, request: Request) -> Dict[str, Any]:
    """只读诊断项目类型与运行时满足度。无副作用。"""
    args: Dict[str, Any] = {
        "languages": body.languages,
        "include_tools": body.include_tools,
        "target_version": body.target_version,
        "project_root": body.project_root,
    }
    return await _dispatch(request, "project_diagnose", args)


# ----- /exec -----


class ExecRequestBody(BaseModel):
    language: str = Field(..., description="运行时语言: python / javascript")
    runtime_path: str = Field(..., description="运行时解释器路径; 需先经 runtime_probe 探测")
    code: str = Field(..., description="待执行源代码; 通过 stdin 传入")
    cwd: Optional[str] = Field(default=None, description="工作目录; 必须位于 workspace_root 内")
    timeout: Optional[int] = Field(default=None, description="超时秒数; 默认 60, 最大 600")
    env_overrides: Optional[Dict[str, str]] = Field(
        default=None,
        description="附加环境变量; 不允许覆盖 SAGE_LOCAL_AUTH_TOKEN 等敏感凭据",
    )
    workspace_root: Optional[str] = Field(default=None, description="项目根目录")


@router.post("/exec")
async def runtime_exec(body: ExecRequestBody, request: Request) -> Dict[str, Any]:
    """在指定运行时执行代码片段。EXEC 风险, 经 PermissionEnforcer 拦截。

    与 BashTool 同等审批闸口: 默认 deny, 用户授权后才放行。被拒时返回
    success=false / error="权限拒绝: ..." —— 与 InprocToolAdapter 契约一致。
    """
    args: Dict[str, Any] = {
        "language": body.language,
        "runtime_path": body.runtime_path,
        "code": body.code,
        "cwd": body.cwd,
        "timeout": body.timeout,
        "env_overrides": body.env_overrides,
    }
    if body.workspace_root:
        args["workspace_root"] = body.workspace_root
    return await _dispatch(request, "runtime_exec", args)


__all__ = ["router"]
