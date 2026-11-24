"""Design Studio ↔ Office 文档库桥接。

提供从 ``office_documents`` 表拉取可作设计素材的文档列表，以及把
``doc_id`` 解析成服务器端绝对路径的能力。Design Studio 端点原本只
接受客户端传入的 ``file_path``，在 Web 模式（无 Electron 文件选择器）
或文档已经入库的场景下无法使用；新增 ``doc_id`` 入参后，前端可以
直接引用文档库中的 Word / Excel 文件，路径解析与 workspace 校验都
在服务器端完成，避免把内部路径暴露给客户端。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel

from backend.office.storage import document_path, get_document
from backend.services.default_workspace import DefaultWorkspaceResolver

ALLOWED_SOURCE_DOC_TYPES = ("word", "excel")


class OfficeSourceRef(BaseModel):
    """前端列表项：标识一个可被 Design Studio 引用的 Office 文档。"""

    doc_id: str
    doc_type: str
    original_filename: Optional[str]
    generated_filename: str
    created_at: int
    size_bytes: Optional[int] = None


class OfficeSourceNotFoundError(LookupError):
    """doc_id 不存在或不是允许的素材类型。"""

    def __init__(self, doc_id: str, reason: str = "not_found") -> None:
        super().__init__(doc_id)
        self.doc_id = doc_id
        self.reason = reason


def _default_workspace_path() -> Path:
    return Path(DefaultWorkspaceResolver().default_workspace_path())


def list_office_sources(
    conn: sqlite3.Connection,
    doc_type: Optional[str] = None,
    limit: int = 50,
) -> List[OfficeSourceRef]:
    """列出当前默认 workspace 下可作设计素材的 Office 文档。

    Args:
        conn: SQLite 连接（由调用方提供事务上下文）。
        doc_type: ``"word"`` / ``"excel"`` 过滤；``None`` 返回两者。
            其它值直接返回空列表，避免给前端制造额外分支。
        limit: 返回条数上限，避免首次渲染拉爆。
    """
    if doc_type is not None and doc_type not in ALLOWED_SOURCE_DOC_TYPES:
        return []

    workspace = _default_workspace_path()
    where = ["workspace_path = ?", "archived_at IS NULL"]
    params: List[object] = [str(workspace)]
    if doc_type is not None:
        where.append("doc_type = ?")
        params.append(doc_type)
    else:
        where.append("doc_type IN ('word', 'excel')")

    sql = f"""
        SELECT id, doc_type, original_filename, generated_filename,
               created_at, metadata
        FROM office_documents
        WHERE {' AND '.join(where)}
        ORDER BY updated_at DESC, created_at DESC
        LIMIT ?
    """
    params.append(limit)

    rows: List[OfficeSourceRef] = []
    for row in conn.execute(sql, tuple(params)):
        metadata = _safe_json(row[5])
        size = metadata.get("file_size_bytes") if isinstance(metadata, dict) else None
        rows.append(
            OfficeSourceRef(
                doc_id=row[0],
                doc_type=row[1],
                original_filename=row[2],
                generated_filename=row[3],
                created_at=row[4],
                size_bytes=size if isinstance(size, int) else None,
            )
        )
    return rows


def resolve_office_source_path(conn: sqlite3.Connection, doc_id: str) -> Path:
    """把 ``doc_id`` 解析为磁盘上的绝对路径。

    失败抛 :class:`OfficeSourceNotFoundError`，由路由层映射到 404。
    路径不存在（被用户手工删掉）同样按 not_found 处理，避免把内部
    文件系统错误泄露给前端。
    """
    if not doc_id or not str(doc_id).strip():
        raise OfficeSourceNotFoundError(doc_id or "", reason="empty")

    summary = get_document(conn, str(doc_id).strip())
    if summary is None:
        raise OfficeSourceNotFoundError(doc_id, reason="not_found")
    if summary.doc_type not in ALLOWED_SOURCE_DOC_TYPES:
        raise OfficeSourceNotFoundError(doc_id, reason="unsupported_type")

    path = document_path(summary)
    if not path.is_file():
        raise OfficeSourceNotFoundError(doc_id, reason="file_missing")
    return path


def resolve_source_input(
    conn: sqlite3.Connection,
    file_path: Optional[str],
    doc_id: Optional[str],
) -> Path:
    """二选一：``doc_id`` 优先；都不给或同时给都报错。

    返回绝对路径，调用方负责后续读取。错误统一走 ValueError，路由
    层翻译成 400。
    """
    has_path = file_path is not None and str(file_path).strip()
    has_id = doc_id is not None and str(doc_id).strip()
    if has_path and has_id:
        raise ValueError("file_path 与 doc_id 不能同时提供")
    if not has_path and not has_id:
        raise ValueError("必须提供 file_path 或 doc_id 之一")
    if has_id:
        return resolve_office_source_path(conn, str(doc_id).strip())
    return Path(str(file_path).strip()).expanduser()


def _safe_json(raw: object) -> object:
    """metadata 列在 schema 里是 TEXT；旧行可能是空串或非 JSON。"""
    if not raw:
        return {}
    if isinstance(raw, (dict, list)):  # noqa: UP038 — py38 isinstance tuple
        return raw
    try:
        import json

        return json.loads(raw)
    except (TypeError, ValueError):
        return {}
