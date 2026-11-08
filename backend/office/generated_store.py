"""Persistence helper for generated office documents.

Extracts the summary-building logic from ``_build_summary_for_generated``
(in ``backend/api/office_routes.py``) so Task 4 (generate endpoint),
Task 5 (template-chat), and Task 6 (iterate) can share it.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING

from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.storage import save_document

if TYPE_CHECKING:
    pass

# ruff: noqa: UP006, UP007, UP035


def persist_generated_document(
    conn: sqlite3.Connection,
    *,
    file_path: Path,
    doc_type: OfficeDocType,
    workspace_path: str,
) -> OfficeDocumentSummary:
    """Persist a generated document and return its summary.

    Computes ``id`` from the parent directory name (e.g.,
    ``workspace/office/word/abc123/output.docx`` -> ``id=abc123``).
    Canonicalises ``workspace_path`` (resolved) so list queries match
    later regardless of symlink or ``.`` differences.

    Args:
        conn: SQLite connection (already initialised with the
            ``office_documents`` schema).
        file_path: Path to the generated file on disk.
        doc_type: Document type discriminator.
        workspace_path: Absolute path to the user's workspace dir.

    Returns:
        The persisted :class:`OfficeDocumentSummary`.

    Raises:
        FileNotFoundError: If ``file_path`` does not exist.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Generated file not found: {file_path}")

    now_ms = int(time.time() * 1000)
    canonical = str(Path(workspace_path).resolve())
    summary = OfficeDocumentSummary(
        id=file_path.parent.name,
        workspace_path=canonical,
        doc_type=doc_type,
        original_filename=None,
        generated_filename=file_path.name,
        status=OfficeDocStatus.GENERATED,
        created_at=now_ms,
        updated_at=now_ms,
        metadata=OfficeDocumentMetadata(file_size_bytes=file_path.stat().st_size),
    )
    save_document(conn, summary, content_file_path=file_path)
    return summary
