"""Office document storage layer.

Two responsibilities:

1. **Path validation** — `validate_workspace()` and `generate_document_dir()`
   enforce the workspace sandbox per plan §3.3. Generated files only land in
   `<workspace>/office/<doc_type>/<doc_id>/`. Any attempt to escape the
   workspace (via `..`, absolute paths, or symlinks) raises OfficePathError.

2. **SQLite persistence** — `save_document()`, `list_documents()`, `delete_document()`
   wrap the office_documents table defined in backend/data/database.py. The
   schema is created by Database.init_db(); callers must initialize the DB
   before using these helpers.

This module is **connection-agnostic** — functions take a sqlite3.Connection
so tests can use `:memory:` and production uses the real Database.get_connection().
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import List

from .errors import OfficePathError
from .models import OfficeDocType, OfficeDocumentSummary
from .path_safety import resolve_within

_DOC_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def validate_workspace(path: Path) -> Path:
    """Validate a workspace directory.

    Raises:
        OfficePathError: path doesn't exist, isn't a directory, or contains '..'
                        segments.

    Returns:
        Resolved absolute Path (symlinks resolved).
    """
    path = Path(path)

    # Reject strings that obviously try to traverse (cheap pre-check before resolve)
    if any(part == ".." for part in path.parts):
        raise OfficePathError(f"Path contains '..' traversal segment: {path}", file_path=path)

    # Resolve to absolute (handles relative paths and existing symlinks)
    resolved = path.resolve()

    if not resolved.exists():
        raise OfficePathError(f"Workspace path does not exist: {path}", file_path=path)
    if not resolved.is_dir():
        raise OfficePathError(f"Workspace path is not a directory: {path}", file_path=path)

    return resolved


def generate_document_dir(
    workspace: Path,
    doc_type: OfficeDocType,
    doc_id: str,
) -> Path:
    """Create (and return) the per-document directory.

    Layout: ``<workspace>/office/<doc_type>/<doc_id>/``

    Containment is enforced by :func:`path_safety.resolve_within`, which
    resolves the candidate path (collapsing ``..`` and following
    symlinks) and uses ``PurePath.relative_to`` for the boundary check
    instead of brittle string-prefix comparison. This closes the
    sibling-prefix attack class (``/tmp/work-evil`` vs ``/tmp/work``)
    that the previous ``str.startswith`` guard missed.

    Raises:
        OfficePathError: doc_id is unsafe, the workspace does not exist,
                        or the resolved path escapes the workspace.
    """
    workspace = validate_workspace(workspace)

    if not _DOC_ID_PATTERN.match(doc_id):
        raise OfficePathError(
            f"doc_id contains unsafe characters (must match {_DOC_ID_PATTERN.pattern}): {doc_id!r}"
        )

    # Cross-platform containment: resolve collapses ``..`` and follows
    # symlinks; ``relative_to`` then rejects any candidate that lands
    # outside the workspace. Works identically on POSIX and Windows.
    candidate = workspace / "office" / doc_type.value / doc_id
    target = resolve_within(workspace, candidate)

    target.mkdir(parents=True, exist_ok=True)
    return target


def _summary_to_row(summary: OfficeDocumentSummary) -> tuple:
    """Convert OfficeDocumentSummary to a DB row tuple."""
    metadata_json = json.dumps(summary.metadata.model_dump(mode="json"))
    return (
        summary.id,
        summary.workspace_path,
        summary.doc_type.value,
        summary.original_filename,
        summary.generated_filename,
        summary.status.value,
        summary.created_at,
        summary.updated_at,
        metadata_json,
        summary.derived_from,
        summary.archived_at,
    )


def save_document(
    conn: sqlite3.Connection,
    summary: OfficeDocumentSummary,
) -> OfficeDocumentSummary:
    """INSERT OR REPLACE an office_documents row. Returns the saved summary."""
    row = _summary_to_row(summary)
    conn.execute(
        """
        INSERT OR REPLACE INTO office_documents (
            id, workspace_path, doc_type, original_filename,
            generated_filename, status, created_at, updated_at, metadata,
            derived_from, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        row,
    )
    conn.commit()
    return summary


def _row_to_summary(row: sqlite3.Row) -> OfficeDocumentSummary:
    """Convert a DB row to OfficeDocumentSummary."""
    from .models import (  # local import to avoid circular at module load
        OfficeDocStatus,
        OfficeDocumentMetadata,
    )

    metadata_dict = json.loads(row["metadata"]) if row["metadata"] else {}
    # ``derived_from`` / ``archived_at`` are nullable columns added by the
    # M0 Task 3 migration. ``row.keys()`` lets us safely read rows from a
    # pre-migration test fixture (or a legacy DB during the brief window
    # before init_db runs again).
    row_keys = set(row.keys())
    return OfficeDocumentSummary(
        id=row["id"],
        workspace_path=row["workspace_path"],
        doc_type=OfficeDocType(row["doc_type"]),
        original_filename=row["original_filename"],
        generated_filename=row["generated_filename"],
        status=OfficeDocStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        metadata=OfficeDocumentMetadata(**metadata_dict),
        derived_from=row["derived_from"] if "derived_from" in row_keys else None,
        archived_at=row["archived_at"] if "archived_at" in row_keys else None,
    )


def list_documents(
    conn: sqlite3.Connection,
    workspace_path: str,
    include_archived: bool = False,
) -> List[OfficeDocumentSummary]:
    """SELECT all documents for the given workspace.

    Args:
        conn: SQLite connection.
        workspace_path: Absolute workspace directory.
        include_archived: When ``False`` (default) rows with ``archived_at``
            non-NULL are filtered out so the M0 management view only shows
            "live" documents. Set ``True`` for archive-restore UIs.
    """
    if include_archived:
        sql = """
            SELECT id, workspace_path, doc_type, original_filename,
                   generated_filename, status, created_at, updated_at, metadata,
                   derived_from, archived_at
            FROM office_documents
            WHERE workspace_path = ?
            ORDER BY created_at DESC
        """
        params: tuple = (workspace_path,)
    else:
        sql = """
            SELECT id, workspace_path, doc_type, original_filename,
                   generated_filename, status, created_at, updated_at, metadata,
                   derived_from, archived_at
            FROM office_documents
            WHERE workspace_path = ? AND archived_at IS NULL
            ORDER BY created_at DESC
        """
        params = (workspace_path,)
    cursor = conn.execute(sql, params)
    return [_row_to_summary(row) for row in cursor.fetchall()]


def get_document(
    conn: sqlite3.Connection,
    document_id: str,
) -> OfficeDocumentSummary | None:
    """Fetch a single office document by id.

    Returns ``None`` when the id is unknown so callers can branch on
    not-found vs. raised-error without try/except noise. Used by M0
    management endpoints to look up the canonical workspace path of a
    document before archive/delete operations.
    """
    cursor = conn.execute(
        """
        SELECT id, workspace_path, doc_type, original_filename,
               generated_filename, status, created_at, updated_at, metadata,
               derived_from, archived_at
        FROM office_documents
        WHERE id = ?
        """,
        (document_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return _row_to_summary(row)


def document_path(summary: OfficeDocumentSummary) -> Path:
    """Compute the on-disk path for a document summary.

    Mirrors the layout used by :func:`generate_document_dir` and the
    Electron import gateway:

        ``<workspace>/office/<doc_type>/<id>/<filename>``

    No filesystem access; pure path arithmetic. Lets the routes layer
    show ``open``/``reveal-in-folder`` actions without re-deriving the
    layout in each caller.
    """
    return (
        Path(summary.workspace_path)
        / "office"
        / summary.doc_type.value
        / summary.id
        / summary.generated_filename
    )


def delete_document(conn: sqlite3.Connection, doc_id: str) -> bool:
    """DELETE a document by id. Returns True if a row was removed."""
    cursor = conn.execute("DELETE FROM office_documents WHERE id = ?", (doc_id,))
    conn.commit()
    return cursor.rowcount > 0
