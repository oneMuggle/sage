"""Typed HTTP routes for the projects registry (项目模块 P1, 2026-09-13).

"项目" = 用户在侧边栏显式登记的工作目录（对标 Cursor Recent Workspaces /
Claude Code 项目 → 会话归属）。路由面刻意保持最小：

- ``GET  /projects``                     清单（按最近打开排序，附会话聚合）
- ``POST /projects``                     登记目录（validate_workspace 校验，幂等）
- ``DELETE /projects/{project_id}``      从清单移除（不动磁盘与会话）
- ``POST /projects/{project_id}/open``   打开项目：复用最近会话或新建并绑定
- ``POST /projects/{project_id}/sessions`` 项目下显式新建绑定会话
- ``GET  /projects/{project_id}/sessions`` 项目下未归档会话（新→旧）

会话与目录的归属复用 ``session_workspace_bindings`` 活跃绑定（见
``backend/data/project_repo.py`` 模块注释），本文件不做第二份归属数据。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.data.project_repo import (
    Project,
    ProjectNotFoundError,
    ProjectPathMissingError,
    ProjectRepository,
    create_session_for_project,
    open_project,
)
from backend.office.errors import OfficePathError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)
    allowed_paths: Optional[List[str]] = Field(default=None, max_length=50)


class ProjectModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    path: str
    name: str
    created_at: int
    last_opened_at: int
    session_count: int = 0
    last_session_id: Optional[str] = None
    allowed_paths: List[str] = Field(default_factory=list)


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


class ProjectAllowedPathsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed_paths: List[str] = Field(max_length=50)


class ProjectAllowedPathsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    allowed_paths: List[str]


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
        project = ProjectRepository().register(
            request.path,
            allowed_paths=request.allowed_paths,
        )
    except OfficePathError as exc:
        raise _error(400, "invalid_workspace_path", "项目路径无效或目录不存在") from exc
    stats = ProjectRepository().session_stats()
    return _with_stats(project, stats)


@router.put("/{project_id}/allowed-paths", response_model=ProjectAllowedPathsResponse)
def update_project_allowed_paths(
    project_id: str,
    request: ProjectAllowedPathsRequest,
) -> ProjectAllowedPathsResponse:
    """更新项目的额外允许访问路径规则列表。

    2026-09-17 allowed_paths 扩展: 用户可以在前端项目详情面板管理
    项目的允许访问路径（除 workspace 内的文件之外）。

    Raises:
        404 ``project_not_found``: 项目 ID 不存在
    """
    repo = ProjectRepository()
    project = repo.get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    updated = repo.update_allowed_paths(project_id, request.allowed_paths)
    if not updated:
        raise _error(404, "project_not_found", "项目不存在")

    return ProjectAllowedPathsResponse(
        id=project_id,
        allowed_paths=request.allowed_paths,
    )


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


@router.post("/{project_id}/sessions", response_model=ProjectOpenResponse)
def create_project_session_route(project_id: str) -> ProjectOpenResponse:
    """项目下显式新建绑定会话（前端项目行 hover「新建会话」按钮）。

    2026-09 修复: 前端 ``projects_create_session`` 一直 POST 本路由,
    后端从未注册 → 405 Method Not Allowed, 按钮每次点击都报错。
    响应复用 ProjectOpenResponse (project/session/created), created 恒 true。
    """
    try:
        project, session = create_session_for_project(project_id)
    except ProjectNotFoundError as exc:
        raise _error(404, "project_not_found", "项目不存在") from exc
    except ProjectPathMissingError as exc:
        raise _error(410, "project_path_missing", "项目目录不存在或已被移动") from exc
    stats = ProjectRepository().session_stats()
    return ProjectOpenResponse(
        project=_with_stats(project, stats),
        session=session.to_dict(),
        created=True,
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
