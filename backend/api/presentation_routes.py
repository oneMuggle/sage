"""Presentation API routes — 把 SVG 幻灯片/ppt-master 项目转成原生可编辑 PPTX。

端点：

    GET  /presentation/environment     环境与技能完整性自检（guard）
    POST /presentation/render-svgs     一组 SVG 字符串 -> PPTX
    POST /presentation/render-project  已有 ppt-master 项目目录 -> PPTX

设计要点：

- 同步 def 端点，FastAPI 放入线程池执行，避免阻塞事件循环（子进程调用是阻塞的）；
- workspace 用 backend.office.storage.validate_workspace 校验，产物路径用
  resolve_within 做容器约束；
- 质量门禁不通过是**正常业务结果**（200 + success=false + blocking_errors），
  不是 HTTP 错误；仅入参非法（400）与环境不可用（503）走异常。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.office.errors import OfficePathError
from backend.office.path_safety import resolve_within
from backend.office.storage import validate_workspace
from backend.services.ppt_master_adapter import PptMasterEnvError, PptMasterRunError
from backend.services.presentation_service import (
    PresentationInputError,
    PresentationService,
    RenderResult,
)

router = APIRouter(prefix="/presentation", tags=["presentation"])

_service = PresentationService()


class RenderSvgRequest(BaseModel):
    workspace_path: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1)
    svg_slides: List[str] = Field(..., min_length=1)


class RenderProjectRequest(BaseModel):
    workspace_path: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1)
    project_path: str = Field(..., min_length=1)


class RenderResponse(BaseModel):
    success: bool
    output_path: Optional[str] = None
    quality_passed: bool
    blocking_errors: list = Field(default_factory=list)
    warnings: list = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
    message: str = ""


class EnvironmentResponse(BaseModel):
    ready: bool
    skill_root: Optional[str] = None
    python: Optional[str] = None
    error: Optional[str] = None


def _resolve_output(workspace_path: str, filename: str) -> Path:
    """校验 workspace 并解析产物绝对路径，确保落在 workspace 内。"""
    try:
        workspace = validate_workspace(Path(workspace_path))
        return resolve_within(workspace, workspace / filename)
    except OfficePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _to_response(result: RenderResult) -> RenderResponse:
    return RenderResponse(
        success=result.success,
        output_path=str(result.output_path) if result.output_path else None,
        quality_passed=result.quality_passed,
        blocking_errors=result.blocking_errors,
        warnings=result.warnings,
        summary=result.summary,
        message=result.message,
    )


@router.get("/environment", response_model=EnvironmentResponse)
def get_environment() -> EnvironmentResponse:
    try:
        info = _service.check_environment()
    except (PptMasterEnvError, PptMasterRunError) as exc:
        return EnvironmentResponse(ready=False, error=str(exc))
    return EnvironmentResponse(
        ready=True,
        skill_root=info.get("skill_root"),
        python=info.get("python"),
    )


@router.post("/render-svgs", response_model=RenderResponse)
def render_svgs_endpoint(req: RenderSvgRequest) -> RenderResponse:
<<<<<<< HEAD
    if not req.svg_slides:
        # pydantic v1 的 min_length 不作用于 list，这里显式拒绝以对齐 v2 的 422。
        raise HTTPException(status_code=422, detail="svg_slides 不能为空")
=======
>>>>>>> origin/main
    output_path = _resolve_output(req.workspace_path, req.filename)
    try:
        result = _service.render_from_svgs(req.svg_slides, output_path)
    except PresentationInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(result)


@router.post("/render-project", response_model=RenderResponse)
def render_project_endpoint(req: RenderProjectRequest) -> RenderResponse:
    try:
        workspace = validate_workspace(Path(req.workspace_path))
        project_dir = resolve_within(workspace, Path(req.project_path))
    except OfficePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    output_path = _resolve_output(req.workspace_path, req.filename)
    try:
        result = _service.render_project(project_dir, output_path)
    except PresentationInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(result)
