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
            generated_filename, status, created_at, updated_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    )


def list_documents(
    conn: sqlite3.Connection,
    workspace_path: str,
) -> List[OfficeDocumentSummary]:
    """SELECT all documents for the given workspace."""
    cursor = conn.execute(
        """
        SELECT id, workspace_path, doc_type, original_filename,
               generated_filename, status, created_at, updated_at, metadata
        FROM office_documents
        WHERE workspace_path = ?
        ORDER BY created_at DESC
        """,
        (workspace_path,),
    )
    return [_row_to_summary(row) for row in cursor.fetchall()]


def delete_document(conn: sqlite3.Connection, doc_id: str) -> bool:
    """DELETE a document by id. Returns True if a row was removed."""
    cursor = conn.execute("DELETE FROM office_documents WHERE id = ?", (doc_id,))
    conn.commit()
    return cursor.rowcount > 0
