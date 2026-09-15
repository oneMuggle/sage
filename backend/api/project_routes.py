"""Typed HTTP routes for the projects registry (项目模块 P1, 2026-09-13).

"项目" = 用户在侧边栏显式登记的工作目录（对标 Cursor Recent Workspaces /
Claude Code 项目 → 会话归属）。路由面刻意保持最小：

- ``GET  /projects``                     清单（按最近打开排序，附会话聚合）
- ``POST /projects``                     登记目录（validate_workspace 校验，幂等）
- ``DELETE /projects/{project_id}``      从清单移除（不动磁盘与会话）
- ``POST /projects/{project_id}/open``   打开项目：复用最近会话或新建并绑定
- ``GET  /projects/{project_id}/sessions`` 项目下未归档会话（新→旧）

会话与目录的归属复用 ``session_workspace_bindings`` 活跃绑定（见
``backend/data/project_repo.py`` 模块注释），本文件不做第二份归属数据。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.data.database import get_database
from backend.data.project_material_repo import (
    MAX_MATERIAL_CONTENT_CHARS,
    ProjectMaterial,
    ProjectMaterialContentTooLargeError,
    ProjectMaterialRepository,
)
from backend.data.project_repo import (
    Project,
    ProjectNotFoundError,
    ProjectPathMissingError,
    ProjectRepository,
    open_project,
)
from backend.data.session_repo import MessageRepository
from backend.office.errors import OfficePathError
from backend.office.session_workspace import get_workspace_binding

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)


class ProjectModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    path: str
    name: str
    created_at: int
    last_opened_at: int
    description: Optional[str] = None
    instructions: Optional[str] = None
    session_count: int = 0
    last_session_id: Optional[str] = None


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: Optional[str] = Field(default=None, max_length=4000)
    instructions: Optional[str] = Field(default=None, max_length=16000)


class ProjectMaterialAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=MAX_MATERIAL_CONTENT_CHARS)
    source_message_id: Optional[str] = Field(default=None, max_length=256)


class ProjectMaterialModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    project_id: str
    source_message_id: Optional[str]
    content_hash: str
    content: str
    status: str
    wiki_page_path: Optional[str]
    error_message: Optional[str]
    created_at: int


class ProjectMaterialsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    materials: List[ProjectMaterialModel]


class MaterialMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    removed: bool


class SaveAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: str = Field(min_length=1, max_length=256)


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projects: List[ProjectModel]


class ProjectMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    removed: bool


class ProjectOpenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: ProjectModel
    session: Dict[str, Any]
    created: bool


class ProjectSessionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessions: List[Dict[str, Any]]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _with_stats(project: Project, stats: Dict[str, Any]) -> ProjectModel:
    session_count, last_session_id = stats.get(project.path, (0, None))
    data = project.to_dict()
    return ProjectModel(
        **data,
        session_count=session_count,
        last_session_id=last_session_id,
    )


def _get_project_or_404(project_id: str) -> Project:
    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")
    return project


def _material_model(material: ProjectMaterial) -> ProjectMaterialModel:
    return ProjectMaterialModel(**material.to_dict())


@router.get("", response_model=ProjectListResponse)
def list_projects() -> ProjectListResponse:
    repo = ProjectRepository()
    stats = repo.session_stats()
    return ProjectListResponse(
        projects=[_with_stats(p, stats) for p in repo.list()]
    )


@router.post("", response_model=ProjectModel)
def register_project(request: ProjectRegisterRequest) -> ProjectModel:
    try:
        project = ProjectRepository().register(request.path)
    except OfficePathError as exc:
        raise _error(400, "invalid_workspace_path", "项目路径无效或目录不存在") from exc
    stats = ProjectRepository().session_stats()
    return _with_stats(project, stats)


@router.patch("/{project_id}", response_model=ProjectModel)
def update_project(
    project_id: str, request: ProjectUpdateRequest
) -> ProjectModel:
    """更新项目概览字段。未出现在请求中的字段保持不变。"""
    repo = ProjectRepository()
    project = repo.get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    fields_set = getattr(request, "model_fields_set", request.__fields_set__)
    if "description" in fields_set:
        repo.update_description(project_id, request.description)
    if "instructions" in fields_set:
        repo.update_instructions(project_id, request.instructions)

    updated = repo.get(project_id)
    assert updated is not None
    return _with_stats(updated, repo.session_stats())


@router.get("/{project_id}/materials", response_model=ProjectMaterialsResponse)
def list_project_materials(project_id: str) -> ProjectMaterialsResponse:
    _get_project_or_404(project_id)
    materials = ProjectMaterialRepository().list_by_project(project_id)
    return ProjectMaterialsResponse(
        materials=[_material_model(material) for material in materials]
    )


@router.post(
    "/{project_id}/materials",
    response_model=ProjectMaterialModel,
    status_code=201,
)
def add_project_material(
    project_id: str, request: ProjectMaterialAddRequest
) -> ProjectMaterialModel:
    _get_project_or_404(project_id)
    try:
        material = ProjectMaterialRepository().add(
            project_id=project_id,
            content=request.content,
            source_message_id=request.source_message_id,
        )
    except ProjectMaterialContentTooLargeError as exc:
        raise _error(413, "material_too_large", str(exc)) from exc
    return _material_model(material)


@router.delete(
    "/{project_id}/materials/{material_id}",
    response_model=MaterialMutationResponse,
)
def remove_project_material(
    project_id: str, material_id: str
) -> MaterialMutationResponse:
    _get_project_or_404(project_id)
    materials = ProjectMaterialRepository()
    material = materials.get(material_id)
    if material is None or material.project_id != project_id:
        raise _error(404, "material_not_found", "资料不存在")
    if not materials.remove(material_id):
        raise _error(404, "material_not_found", "资料不存在")
    return MaterialMutationResponse(removed=True)


@router.post(
    "/{project_id}/materials/save-answer",
    response_model=ProjectMaterialModel,
    status_code=201,
)
def save_answer_as_project_material(
    project_id: str, request: SaveAnswerRequest
) -> ProjectMaterialModel:
    """把当前项目绑定会话中的可见回答保存为项目资料。"""
    project = _get_project_or_404(project_id)
    message = MessageRepository().get(request.message_id)
    if message is None:
        raise _error(404, "message_not_found", "消息不存在")

    binding = get_workspace_binding(
        get_database().get_connection(), message.session_id
    )
    if binding is None or binding.workspace_path != project.path:
        raise _error(403, "message_project_mismatch", "消息不属于该项目")

    try:
        material = ProjectMaterialRepository().add(
            project_id=project.id,
            content=message.content,
            source_message_id=message.id,
        )
    except ProjectMaterialContentTooLargeError as exc:
        raise _error(413, "material_too_large", str(exc)) from exc
    return _material_model(material)


@router.delete("/{project_id}", response_model=ProjectMutationResponse)
def remove_project(project_id: str) -> ProjectMutationResponse:
    removed = ProjectRepository().remove(project_id)
    if not removed:
        raise _error(404, "project_not_found", "项目不存在")
    return ProjectMutationResponse(removed=True)


@router.post("/{project_id}/open", response_model=ProjectOpenResponse)
def open_project_route(project_id: str) -> ProjectOpenResponse:
    """打开项目：最近活跃会话优先，否则新建会话并绑定项目目录。

    目录在磁盘上已消失 → 410 ``project_path_missing``（前端据此提示
    移除该项目或重新选择目录），不静默重建绑定。
    """
    try:
        project, session, created = open_project(project_id)
    except ProjectNotFoundError as exc:
        raise _error(404, "project_not_found", "项目不存在") from exc
    except ProjectPathMissingError as exc:
        raise _error(410, "project_path_missing", "项目目录不存在或已被移动") from exc
    stats = ProjectRepository().session_stats()
    return ProjectOpenResponse(
        project=_with_stats(project, stats),
        session=session.to_dict(),
        created=created,
    )


@router.get("/{project_id}/sessions", response_model=ProjectSessionsResponse)
def list_project_sessions(project_id: str) -> ProjectSessionsResponse:
    repo = ProjectRepository()
    project = repo.get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")
    sessions = repo.sessions_for_project(project.path)
    return ProjectSessionsResponse(sessions=[s.to_dict() for s in sessions])


__all__ = ["router"]
