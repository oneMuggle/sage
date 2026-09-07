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


class WorkspaceChangeEntryModel(BaseModel):
    class Config:
        extra = "forbid"
    index_status: str
    worktree_status: str
    path: str


class WorkspaceChangesResponse(BaseModel):
    class Config:
        extra = "forbid"
    branch: str
    upstream: str
    ahead: int
    behind: int
    clean: bool
    changes: List[WorkspaceChangeEntryModel]


class WorkspaceDiffResponse(BaseModel):
    class Config:
        extra = "forbid"
    diff: str
    truncated: bool


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


def _bound_workspace_or_raise(conn: sqlite3.Connection, session_id: str) -> str:
    """取会话绑定的工作区路径;未绑定直接 403(变更面板前置条件)。"""
    if not _session_exists(conn, session_id):
        raise _error(404, "session_not_found", "会话不存在")
    binding = get_workspace_binding(conn, session_id)
    if binding is None or not binding.workspace_path:
        raise _error(403, "workspace_not_bound", "当前会话尚未绑定工作区")
    return binding.workspace_path


@router.get("/changes", response_model=WorkspaceChangesResponse)
def get_workspace_changes(session_id: str) -> WorkspaceChangesResponse:
    """会话工作区的 git 变更清单（U1 变更面板数据源，只读）。

    复用 LLM 工具面 ``git_status`` 的实现口径：porcelain v1 输出结构化
    解析、30s 超时、utf-8 replace 解码。非 git 仓库 / git 不可用 → 502。
    """
    from backend.domain.tool_policy import ToolPolicy
    from backend.tools.git_tool import GitStatusTool

    root = _bound_workspace_or_raise(_connection(), session_id)
    result = GitStatusTool(ToolPolicy(workspace_root=root)).execute()
    if not result.success:
        raise _error(502, "git_error", result.error or "git 命令失败")
    content = result.content if isinstance(result.content, dict) else {}
    return WorkspaceChangesResponse(
        branch=str(content.get("branch", "")),
        upstream=str(content.get("upstream", "")),
        ahead=int(content.get("ahead", 0)),
        behind=int(content.get("behind", 0)),
        clean=bool(content.get("clean", False)),
        changes=[
            WorkspaceChangeEntryModel(
                index_status=str(entry.get("index_status", "")),
                worktree_status=str(entry.get("worktree_status", "")),
                path=str(entry.get("path", "")),
            )
            for entry in content.get("changes", [])
            if isinstance(entry, dict)
        ],
    )


@router.get("/changes/diff", response_model=WorkspaceDiffResponse)
def get_workspace_change_diff(
    session_id: str,
    path: str = Query(default="", max_length=1024),
    staged: bool = False,
) -> WorkspaceDiffResponse:
    """指定文件的未提交 diff（U1 变更面板 diff 视图数据源，只读）。

    ``path`` 为相对仓库根的路径；空串取全仓库 diff（前端按文件拉取，
    避免一次性传输超大 diff）。
    """
    from backend.domain.tool_policy import ToolPolicy
    from backend.tools.git_tool import GitDiffTool

    root = _bound_workspace_or_raise(_connection(), session_id)
    result = GitDiffTool(ToolPolicy(workspace_root=root)).execute(
        staged=staged, path=path
    )
    if not result.success:
        raise _error(502, "git_error", result.error or "git 命令失败")
    content = result.content if isinstance(result.content, dict) else {}
    return WorkspaceDiffResponse(
        diff=str(content.get("diff", "")),
        truncated=bool(content.get("truncated", False)),
    )


class WorkspaceRevertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paths: List[str] = Field(min_length=1, max_length=50)
    delete_untracked: bool = False


class WorkspaceRevertEntryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    error: str


class WorkspaceRevertResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reverted: List[str]
    errors: List[WorkspaceRevertEntryModel]


class WorkspaceRevertHunksRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)
    hunk_indices: List[int] = Field(min_length=1, max_length=200)


class WorkspaceRevertHunksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reverted_hunks: int


@router.post("/changes/revert", response_model=WorkspaceRevertResponse)
def revert_workspace_changes(
    session_id: str, request: WorkspaceRevertRequest
) -> WorkspaceRevertResponse:
    """逐文件撤销工作区改动（U19，用户在变更面板显式触发，非 LLM 工具）。

    语义为 ``git checkout -- <path>``（工作区恢复到 index/HEAD，不动暂存
    区）；未跟踪文件需显式 ``delete_untracked=true``。单文件失败不阻断
    其余文件，失败明细随响应返回。
    """
    from backend.office.workspace_revert import revert_files

    root = _bound_workspace_or_raise(_connection(), session_id)
    reverted, errors = revert_files(root, request.paths, request.delete_untracked)
    return WorkspaceRevertResponse(
        reverted=reverted,
        errors=[WorkspaceRevertEntryModel(**entry) for entry in errors],
    )


@router.post("/changes/revert-hunks", response_model=WorkspaceRevertHunksResponse)
def revert_workspace_change_hunks(
    session_id: str, request: WorkspaceRevertHunksRequest
) -> WorkspaceRevertHunksResponse:
    """按 hunk 子集撤销某文件的工作区改动（U19）。

    ``hunk_indices`` 为 0-based，与 GET /changes/diff 输出的 hunk 顺序
    一致。git apply 原子：任一 hunk 应用失败则整体不动盘并返回 502。
    """
    from backend.office.workspace_revert import guard_rel_path, revert_hunks

    root = _bound_workspace_or_raise(_connection(), session_id)
    error = guard_rel_path(root, request.path)
    if error is not None:
        raise _error(400, "invalid_path", error)
    count, error = revert_hunks(root, request.path, request.hunk_indices)
    if error is not None:
        raise _error(502, "git_error", error)
    return WorkspaceRevertHunksResponse(reverted_hunks=count)


__all__ = ["router"]
