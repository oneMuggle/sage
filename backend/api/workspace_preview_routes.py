"""工作区文件预览 / 批量解析路由（消息内文件引用 → 右栏预览）。

从 ``workspace_routes.py`` 拆出（feat/file-reference-preview）：该文件已接近
800 行架构上限，预览/解析是一组自洽的只读端点，独立模块更清晰。

路径安全口径与 ``/workspace/changes/file`` 一致：相对路径按会话绑定工作区根
解析，绝对路径也必须落在工作区内；``realpath`` 边界守卫防 ``../`` 与 symlink
逃逸，不信任调用方传入的根目录。
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from backend.data import artifact_reader, artifact_repo
from backend.data.database import get_database
from backend.office.models import _constrained_list
from backend.office.session_workspace import get_workspace_binding

# 无独立 prefix：由 workspace_routes.router 内嵌挂载（路径保持
# /api/v1/sessions/{session_id}/workspace/preview|resolve）
router = APIRouter(tags=["workspace"])


class WorkspaceResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # _constrained_list：win7 双版本安全范式（pydantic v1 只认 min_items）。
    paths: _constrained_list(str, min_length=1, max_length=50)


class WorkspaceResolveResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    exists: bool
    kind: Optional[str] = None


class WorkspaceResolveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: List[WorkspaceResolveResultModel]


def _connection() -> sqlite3.Connection:
    return get_database().get_connection()


def _session_exists(conn: sqlite3.Connection, session_id: str) -> bool:
    return conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is not None


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _bound_workspace_or_raise(conn: sqlite3.Connection, session_id: str) -> str:
    """取会话绑定的工作区路径；未绑定直接 403（与 workspace_routes 同口径）。"""
    if not _session_exists(conn, session_id):
        raise _error(404, "session_not_found", "会话不存在")
    binding = get_workspace_binding(conn, session_id)
    if binding is None or not binding.workspace_path:
        raise _error(403, "workspace_not_bound", "当前会话尚未绑定工作区")
    return binding.workspace_path


# ---------------------------------------------------------------------------
# 类型分派常量
# ---------------------------------------------------------------------------

#: 图片扩展名 → base64 data URL 预览（与 artifact_reader._IMAGE_MIME 同集合）
_IMAGE_PREVIEW_SUFFIXES = frozenset({"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"})
#: Office 三件套 → 结构化/HTML 轻量预览
_OFFICE_PREVIEW_SUFFIXES = frozenset({"docx", "xlsx", "pptx"})


def _resolve_workspace_target(root: str, raw_path: str) -> Path:
    """把消息里的路径解析为工作区内真实路径（相对/绝对均可）。"""
    from backend.tools.file_tool import _path_within_workspace

    raw = raw_path.strip()
    if not raw:
        raise _error(400, "invalid_path", "路径不能为空")
    target = raw if Path(raw).is_absolute() else str(Path(root) / raw)
    if not _path_within_workspace(target, root):
        raise _error(403, "path_outside_workspace", "仅支持工作区内的文件")
    return Path(os.path.realpath(target))


def _kind_for_preview(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    # html/htm 在 classify_artifact 里归为 code，预览侧需单独标记以便沙盒 iframe 渲染
    if suffix in ("html", "htm"):
        return "html"
    return artifact_repo.classify_artifact(str(path))


def _raise_preview_failure(result: dict) -> None:
    """path 版读取函数的失败码 → HTTP 状态（口径同 /changes/file）。"""
    code = str(result.get("code") or "")
    message = str(result.get("error") or "读取失败")
    if code == "file_not_found":
        raise _error(404, "file_not_found", message)
    if code == "binary_file":
        raise _error(415, "binary_file", message)
    if code == "file_too_large":
        raise _error(413, "file_too_large", message)
    raise _error(502, "file_read_error", message)


@router.get("/preview")
def preview_workspace_file(
    session_id: str,
    path: str = Query(min_length=1, max_length=1024),
) -> dict:
    """工作区文件预览（消息内文件引用 → 右栏，只读）。

    返回形状与 ``GET /sessions/{id}/artifacts/{aid}/content`` 一致：
    文本 ``{ok, kind, content, truncated}``、图片/PDF ``data_url``、
    docx/xlsx/pptx ``html`` + ``structured``（docx 另附 ``data_url`` 供
    docx-preview 版式渲染）。
    """
    root = _bound_workspace_or_raise(_connection(), session_id)
    resolved = _resolve_workspace_target(root, path)
    if not resolved.is_file():
        raise _error(404, "file_not_found", "文件不存在")

    suffix = resolved.suffix.lower().lstrip(".")
    if suffix == "pdf":
        return artifact_reader.read_pdf_path(resolved)
    if suffix in _IMAGE_PREVIEW_SUFFIXES:
        return artifact_reader.read_image_path(resolved)
    if suffix in _OFFICE_PREVIEW_SUFFIXES:
        return artifact_reader.read_office_path(resolved, kind=suffix)

    result = artifact_reader.read_text_path(resolved, kind=_kind_for_preview(resolved))
    if not result.get("ok"):
        _raise_preview_failure(result)
    return result


@router.post("/resolve", response_model=WorkspaceResolveResponse)
def resolve_workspace_files(
    session_id: str, request: WorkspaceResolveRequest
) -> WorkspaceResolveResponse:
    """批量判定路径是否为工作区内存在的文件（消息文本兜底识别用）。

    越界/不存在的路径一律返回 ``exists=False``（不抛错，便于前端批量标注）；
    单次最多 50 条（请求模型约束）。
    """
    root = _bound_workspace_or_raise(_connection(), session_id)
    results: List[WorkspaceResolveResultModel] = []
    for raw in request.paths:
        try:
            resolved = _resolve_workspace_target(root, raw)
        except HTTPException:
            results.append(WorkspaceResolveResultModel(path=raw, exists=False))
            continue
        if resolved.is_file():
            results.append(
                WorkspaceResolveResultModel(
                    path=raw, exists=True, kind=_kind_for_preview(resolved)
                )
            )
        else:
            results.append(WorkspaceResolveResultModel(path=raw, exists=False))
    return WorkspaceResolveResponse(results=results)
