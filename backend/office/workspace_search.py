"""Deterministic, bounded search within a session's active workspace."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Set

from backend.office.errors import OfficePathError
from backend.office.models import OfficeDocType
from backend.office.path_safety import managed_document_path, resolve_within
from backend.office.session_workspace import get_workspace_binding
from backend.office.storage import list_documents
from backend.office.workspace_errors import WorkspaceNotBoundError, WorkspaceRevokedError

import logging

logger = logging.getLogger(__name__)

_MAX_QUERY_CODE_POINTS = 200
_MIN_LIMIT = 1
_MAX_LIMIT = 50
_MAX_SCAN_CANDIDATES = 5_000
_OFFICE_SUFFIXES = {
    ".pptx": OfficeDocType.PPT,
    ".docx": OfficeDocType.WORD,
    ".xlsx": OfficeDocType.EXCEL,
}


@dataclass(frozen=True)
class WorkspaceSearchResult:
    """One safe result from a session-scoped workspace search."""

    name: str
    kind: str
    doc_type: Optional[OfficeDocType]
    doc_id: Optional[str]
    size_bytes: int
    needs_import: bool
    source_path: Optional[str]


def _validate_search(query: str, limit: int) -> str:
    if len(query) > _MAX_QUERY_CODE_POINTS:
        raise ValueError("query must contain at most 200 Unicode code points")
    if limit < _MIN_LIMIT or limit > _MAX_LIMIT:
        raise ValueError("limit must be between 1 and 50")
    return query.strip().casefold()


def _directory_identity(path: Path) -> Optional[tuple]:
    try:
        stat = path.lstat()
    except OSError:
        return None
    return stat.st_dev, stat.st_ino


def _managed_results(
    conn: sqlite3.Connection, workspace: Path, query: str, limit: int, managed_paths: Set[Path]
) -> List[WorkspaceSearchResult]:
    documents = sorted(
        list_documents(conn, str(workspace)),
        key=lambda doc: (doc.generated_filename.casefold(), doc.id),
    )
    results: List[WorkspaceSearchResult] = []
    for document in documents:
        try:
            path = resolve_within(
                workspace,
                managed_document_path(
                    workspace, document.doc_type, document.id, document.generated_filename
                ),
            )
        except (OfficePathError, OSError):
            continue
        managed_paths.add(path)
        if query not in document.generated_filename.casefold():
            continue
        results.append(
            WorkspaceSearchResult(
                name=document.generated_filename,
                kind="office-" + document.doc_type.value,
                doc_type=document.doc_type,
                doc_id=document.id,
                size_bytes=document.metadata.file_size_bytes,
                needs_import=False,
                source_path=None,
            )
        )
        if len(results) == limit:
            break
    return results


def _ignore_walk_error(_error: OSError) -> None:
    """Skip one unreadable directory while allowing sibling traversal."""


def _iter_candidates(workspace: Path) -> Iterator[Path]:
    candidate_count = 0
    for root, dirnames, filenames in os.walk(
        workspace, topdown=True, onerror=_ignore_walk_error, followlinks=False
    ):
        dirnames.sort(key=str.casefold)
        entries = sorted((*dirnames, *filenames), key=str.casefold)
        for name in entries:
            candidate_count += 1
            yield Path(root) / name
            if candidate_count >= _MAX_SCAN_CANDIDATES:
                return


def search_workspace_files(
    conn: sqlite3.Connection, session_id: str, query: str, limit: int = 20
) -> List[WorkspaceSearchResult]:
    """Search managed documents first, then contained files, under one cap."""
    normalized_query = _validate_search(query, limit)
    binding = get_workspace_binding(conn, session_id)
    if binding is None:
        raise WorkspaceNotBoundError("当前会话尚未绑定工作区")
    if not normalized_query:
        return []
    stored_workspace = Path(binding.workspace_path)
    try:
        binding_identity = _directory_identity(stored_workspace)
        workspace = stored_workspace.resolve(strict=False)
    except OSError as exc:
        raise WorkspaceRevokedError("工作区已不可访问,请重新绑定") from exc
    if not workspace.is_dir() or _directory_identity(workspace) is None:
        raise WorkspaceRevokedError("工作区已不可访问,请重新绑定")
    if binding_identity is not None and _directory_identity(workspace) != binding_identity:
        raise WorkspaceRevokedError("工作区身份已变更,请重新绑定")
    managed_paths: Set[Path] = set()
    results = _managed_results(conn, workspace, normalized_query, limit, managed_paths)
    for candidate in _iter_candidates(workspace):
        if len(results) == limit:
            break
        try:
            resolved = resolve_within(workspace, candidate)
            if resolved in managed_paths or not resolved.is_file():
                continue
            relative_name = resolved.relative_to(workspace).as_posix()
            if normalized_query not in relative_name.casefold():
                continue
            size_bytes = resolved.stat().st_size
        except (OfficePathError, OSError, ValueError):
            continue
        doc_type = _OFFICE_SUFFIXES.get(resolved.suffix.casefold())
        needs_import = doc_type is not None
        results.append(
            WorkspaceSearchResult(
                name=relative_name,
                kind="office-" + doc_type.value if doc_type is not None else "file",
                doc_type=doc_type,
                doc_id=None,
                size_bytes=size_bytes,
                needs_import=needs_import,
                source_path=str(resolved) if needs_import else None,
            )
        )
    return results


__all__ = ["WorkspaceSearchResult", "search_workspace_files", "_MAX_SCAN_CANDIDATES"]
