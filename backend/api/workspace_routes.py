"""Typed HTTP routes for session workspace binding and bounded search."""

from __future__ import annotations

import sqlite3
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.data.database import get_database
from backend.office.errors import OfficePathError
from backend.office.models import OfficeDocType
from backend.office.session_workspace import (
    SessionWorkspaceBinding,
    bind_session_workspace,
    get_workspace_binding,
    revoke_session_workspace,
)
from backend.office.workspace_errors import (
    WorkspaceBindingError,
    WorkspaceNotBoundError,
    WorkspaceRevokedError,
    WorkspaceSessionNotFoundError,
)
from backend.office.workspace_search import WorkspaceSearchResult, search_workspace_files

router = APIRouter(prefix="/sessions/{session_id}/workspace", tags=["workspace"])


class WorkspaceBindingModel(BaseModel):
    class Config:
        extra = "forbid"
    session_id: str
    workspace_path: str
    generation: int
    activated_at: int
    revoked_at: Optional[int]


class WorkspaceBindRequest(BaseModel):
    class Config:
        extra = "forbid"
    workspace_path: str = Field(min_length=1)


class WorkspaceBindingResponse(BaseModel):
    class Config:
        extra = "forbid"
    binding: Optional[WorkspaceBindingModel]


class WorkspaceRevokeResponse(BaseModel):
    class Config:
        extra = "forbid"
    revoked: bool
    generation: int


class WorkspaceSearchResultModel(BaseModel):
    class Config:
        extra = "forbid"
    name: str
    kind: str
    doc_type: Optional[OfficeDocType]
    doc_id: Optional[str]
    size_bytes: int
    needs_import: bool
    source_path: Optional[str]


class WorkspaceSearchResponse(BaseModel):
    class Config:
        extra = "forbid"
    results: List[WorkspaceSearchResultModel]
    total: int


def _connection() -> sqlite3.Connection:
    return get_database().get_connection()


def _session_exists(conn: sqlite3.Connection, session_id: str) -> bool:
    return conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is not None


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _map_workspace_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WorkspaceSessionNotFoundError):
        return _error(404, "session_not_found", "会话不存在")
    if isinstance(exc, WorkspaceNotBoundError):
        return _error(403, "workspace_not_bound", "当前会话尚未绑定工作区")
    if isinstance(exc, WorkspaceRevokedError):
        return _error(410, "workspace_revoked", "工作区已失效,请重新绑定")
    if isinstance(exc, OfficePathError):
        return _error(400, "invalid_workspace_path", "工作区路径无效")
    if isinstance(exc, WorkspaceBindingError):
        return _error(500, exc.code, "工作区操作失败")
    return _error(500, "workspace_error", "工作区操作失败")


def _binding_model(binding: SessionWorkspaceBinding) -> WorkspaceBindingModel:
    return WorkspaceBindingModel(
        session_id=binding.session_id,
        workspace_path=binding.workspace_path,
        generation=binding.generation,
        activated_at=binding.activated_at,
        revoked_at=binding.revoked_at,
    )


def _search_model(result: WorkspaceSearchResult) -> WorkspaceSearchResultModel:
    # ``name`` is already workspace-relative; ``source_path`` (renderer
    # import handle) must NEVER appear in the HTTP body. Returning the
    # name as the import handle keeps renderer wiring trivial without
    # exposing absolute paths to the cross-origin API surface.
    return WorkspaceSearchResultModel(
        name=result.name,
        kind=result.kind,
        doc_type=result.doc_type,
        doc_id=result.doc_id,
        size_bytes=result.size_bytes,
        needs_import=result.needs_import,
        source_path=result.name if result.needs_import else None,
    )


@router.put("", response_model=WorkspaceBindingResponse)
def bind_workspace(session_id: str, request: WorkspaceBindRequest) -> WorkspaceBindingResponse:
    try:
        binding = bind_session_workspace(_connection(), session_id, request.workspace_path)
    except (WorkspaceBindingError, OfficePathError) as exc:
        raise _map_workspace_error(exc) from exc
    return WorkspaceBindingResponse(binding=_binding_model(binding))


@router.get("", response_model=WorkspaceBindingResponse)
def get_workspace(session_id: str) -> WorkspaceBindingResponse:
    conn = _connection()
    if not _session_exists(conn, session_id):
        raise _error(404, "session_not_found", "会话不存在")
    binding = get_workspace_binding(conn, session_id)
    return WorkspaceBindingResponse(binding=None if binding is None else _binding_model(binding))


@router.delete("", response_model=WorkspaceRevokeResponse)
def revoke_workspace(session_id: str) -> WorkspaceRevokeResponse:
    try:
        binding = revoke_session_workspace(_connection(), session_id)
    except WorkspaceBindingError as exc:
        raise _map_workspace_error(exc) from exc
    return WorkspaceRevokeResponse(revoked=True, generation=binding.generation)


@router.get("/files", response_model=WorkspaceSearchResponse)
def search_workspace(
    session_id: str, q: str = Query(max_length=200), limit: int = Query(default=20, ge=1, le=50)
) -> WorkspaceSearchResponse:
    conn = _connection()
    if not _session_exists(conn, session_id):
        raise _error(404, "session_not_found", "会话不存在")
    try:
        results = search_workspace_files(conn, session_id, q, limit)
    except WorkspaceBindingError as exc:
        raise _map_workspace_error(exc) from exc
    except ValueError as exc:
        # ``search_workspace_files`` raises ``ValueError`` for query/limit
        # contract drift. Normalize to a 422 so callers see the same
        # surface Pydantic gives them.
        raise _error(422, "invalid_search", str(exc)) from exc
    models = [_search_model(result) for result in results]
    return WorkspaceSearchResponse(results=models, total=len(models))


__all__ = ["router"]
