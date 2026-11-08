"""文件引用 HTTP 路由 (P5, 2026-11-05 项目管理增强, 设计 §9.7)。

- ``GET    /projects/{id}/references``            列出项目引用
- ``POST   /projects/{id}/references``            创建引用 (rel_path 冲突 → 409)
- ``DELETE /projects/{id}/references/{ref_id}``   删除引用
- ``POST   /projects/{id}/scan``                  强制重扫并登记符号链接引用

v1 语义只读: 引用只放行读取, 不放行写入 (见 ``backend/tools/base.py`` 第 3 层)。
每次变更都写结构化审计日志 (project_id / ref_id / target / op), 不新建审计表。
"""

from __future__ import annotations

import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api.project_routes import _error, _get_project_or_404, _scan_and_sync
from backend.compat.win7.pydantic_compat import ConfigDict
from backend.data.database import make_with_db_lock
from backend.data.file_reference_repo import (
    FileReference,
    FileReferenceConflictError,
    FileReferenceRepository,
    InvalidReferencePathError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


def with_db_lock(func):
    return make_with_db_lock(globals())(func)


class FileReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    alias_name: str
    rel_path: str
    target_path: str
    kind: str
    created_at: int


class FileReferenceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    references: List[FileReferenceModel]


class FileReferenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rel_path: str = Field(min_length=1)
    target_path: str = Field(min_length=1)
    kind: Literal["file", "directory"] = "directory"
    alias_name: Optional[str] = Field(default=None, max_length=200)


class FileReferenceMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    removed: bool


class ProjectReferenceScanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    scanned: bool
    created_project_ids: List[str]
    reference_count: int


def _to_model(reference: FileReference) -> FileReferenceModel:
    return FileReferenceModel(**reference.to_dict())


@router.get(
    "/{project_id}/references", response_model=FileReferenceListResponse
)
@with_db_lock
def list_file_references(project_id: str) -> FileReferenceListResponse:
    _get_project_or_404(project_id)
    references = FileReferenceRepository().list_by_project(project_id)
    return FileReferenceListResponse(
        references=[_to_model(reference) for reference in references]
    )


@router.post(
    "/{project_id}/references",
    response_model=FileReferenceModel,
    status_code=201,
)
@with_db_lock
def create_file_reference(
    project_id: str, payload: FileReferenceCreateRequest
) -> FileReferenceModel:
    _get_project_or_404(project_id)
    try:
        reference = FileReferenceRepository().create(
            project_id,
            payload.rel_path,
            payload.target_path,
            kind=payload.kind,
            alias_name=payload.alias_name,
        )
    except FileReferenceConflictError as exc:
        raise _error(409, "reference_exists", "该虚拟位置已存在文件引用") from exc
    except InvalidReferencePathError as exc:
        raise _error(400, "invalid_reference", str(exc)) from exc
    logger.info(
        "project reference created: op=create project_id=%s ref_id=%s "
        "rel_path=%s target=%s",
        project_id,
        reference.id,
        reference.rel_path,
        reference.target_path,
    )
    return _to_model(reference)


@router.delete(
    "/{project_id}/references/{reference_id}",
    response_model=FileReferenceMutationResponse,
)
@with_db_lock
def delete_file_reference(
    project_id: str, reference_id: str
) -> FileReferenceMutationResponse:
    _get_project_or_404(project_id)
    repository = FileReferenceRepository()
    reference = repository.get(reference_id)
    if reference is None or reference.project_id != project_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "reference_not_found", "message": "文件引用不存在"},
        )
    repository.delete(reference_id)
    logger.info(
        "project reference deleted: op=delete project_id=%s ref_id=%s "
        "rel_path=%s target=%s",
        project_id,
        reference.id,
        reference.rel_path,
        reference.target_path,
    )
    return FileReferenceMutationResponse(removed=True)


@router.post(
    "/{project_id}/scan", response_model=ProjectReferenceScanResponse
)
@with_db_lock
def scan_project_references(project_id: str) -> ProjectReferenceScanResponse:
    project = _get_project_or_404(project_id)
    tree, created = _scan_and_sync(project, force=True)
    if tree is None:
        raise _error(410, "project_path_missing", "项目目录不存在或无法读取")
    references = FileReferenceRepository().list_by_project(project_id)
    logger.info(
        "project scan: op=scan project_id=%s symlinks=%d references=%d",
        project_id,
        len(tree.symlinks),
        len(references),
    )
    return ProjectReferenceScanResponse(
        project_id=project.id,
        scanned=True,
        created_project_ids=created,
        reference_count=len(references),
    )
