"""Presentation API routes — 把 SVG 幻灯片/ppt-master 项目转成原生可编辑 PPTX。

端点：

    GET  /presentation/environment     环境与技能完整性自检（guard）
    GET  /presentation/templates       模板库列表（可按 kind 过滤）
    POST /presentation/templates/refresh  重扫模板库并重写索引
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
from backend.services.presentation_template_registry import (
    PresentationTemplateRegistry,
    TemplateEntry,
)

router = APIRouter(prefix="/presentation", tags=["presentation"])

_service = PresentationService()
_registry = PresentationTemplateRegistry()


class RenderSvgRequest(BaseModel):
    workspace_path: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1)
    svg_slides: List[str] = Field(..., min_length=1)
    template_ids: List[str] = Field(default_factory=list)


class RenderProjectRequest(BaseModel):
    workspace_path: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1)
    project_path: str = Field(..., min_length=1)
    template_ids: List[str] = Field(default_factory=list)


class RenderResponse(BaseModel):
    success: bool
    output_path: Optional[str] = None
    quality_passed: bool
    blocking_errors: list = Field(default_factory=list)
    warnings: list = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
    message: str = ""
    templates_applied: List[str] = Field(default_factory=list)


class EnvironmentResponse(BaseModel):
    ready: bool
    skill_root: Optional[str] = None
    python: Optional[str] = None
    error: Optional[str] = None


class TemplateItem(BaseModel):
    kind: str
    template_id: str
    name: str
    summary: str = ""
    primary_color: Optional[str] = None
    canvas_format: Optional[str] = None
    page_count: Optional[int] = None
    page_types: List[str] = Field(default_factory=list)
    root_path: str


class TemplateListResponse(BaseModel):
    available: bool
    error: Optional[str] = None
    templates: List[TemplateItem] = Field(default_factory=list)


class TemplateRefreshResponse(BaseModel):
    available: bool
    count: int = 0
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
        templates_applied=list(result.templates_applied),
    )


def _to_template_item(entry: TemplateEntry) -> TemplateItem:
    return TemplateItem(
        kind=entry.kind,
        template_id=entry.template_id,
        name=entry.name,
        summary=entry.summary,
        primary_color=entry.primary_color,
        canvas_format=entry.canvas_format,
        page_count=entry.page_count,
        page_types=list(entry.page_types),
        root_path=entry.root_path,
    )


def _resolve_template_roots(template_ids: List[str]) -> List[Path]:
    """把 ``kind:id`` 选择解析成模板安装根；非法选择一律 400。

    只接受库内条目标识，客户端无法借路径参数安装任意目录。
    """
    try:
        return _registry.resolve_roots(template_ids)
    except PresentationInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.get("/templates", response_model=TemplateListResponse)
def list_templates_endpoint(kind: Optional[str] = None) -> TemplateListResponse:
    """模板库列表；首次访问惰性扫描一次。技能目录缺失时 200 + available=false。"""
    try:
        _registry.ensure_fresh()
        entries = _registry.list_templates(kind)
    except PptMasterEnvError as exc:
        return TemplateListResponse(available=False, error=str(exc))
    except PresentationInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TemplateListResponse(
        available=True,
        templates=[_to_template_item(entry) for entry in entries],
    )


@router.post("/templates/refresh", response_model=TemplateRefreshResponse)
def refresh_templates_endpoint() -> TemplateRefreshResponse:
    """手动重扫模板库（技能目录更新后由前端触发）。"""
    try:
        count = _registry.refresh()
    except PptMasterEnvError as exc:
        return TemplateRefreshResponse(available=False, error=str(exc))
    return TemplateRefreshResponse(available=True, count=count)


@router.post("/render-svgs", response_model=RenderResponse)
def render_svgs_endpoint(req: RenderSvgRequest) -> RenderResponse:
    output_path = _resolve_output(req.workspace_path, req.filename)
    template_roots = _resolve_template_roots(req.template_ids)
    try:
        result = _service.render_from_svgs(
            req.svg_slides, output_path, template_roots=template_roots
        )
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
    template_roots = _resolve_template_roots(req.template_ids)
    try:
        result = _service.render_project(project_dir, output_path, template_roots=template_roots)
    except PresentationInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(result)
