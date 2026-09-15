"""PR-3 merge tests for ``_persist_read_summary``.

Verifies that re-reading a document preserves user/system-managed fields
on the ``office_documents`` row:

1. A fresh file read -> INSERT, archived_at=None, original_filename from req.
2. A previously archived doc is re-read -> archived_at is preserved.
3. A re-read on an already-parsed doc -> archived_at / derived_from
   preserved, updated_at advanced.
4. A re-read with original_filename=None keeps the prior row's
   original_filename (user intent). A non-None caller-supplied value
   DOES overwrite.

The helper is invoked through a tiny stub reader result so we don't need
to actually parse a real .pptx/.docx/.xlsx file. The unit under test is
the merge branch, not the file parsers.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

from backend.data import database as db_mod
from backend.data.database import Database
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.storage import get_document

# ──────────────────────────────────────────────────────────────────────
# Stub result + fixtures
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _StubResult:
    """Minimal duck-typed result with a mutable .summary attribute.

    Mirrors the relevant surface of Office{Ppt,Word,Excel}ReadResult
    without pulling in the parser pipeline.
    """

    summary: OfficeDocumentSummary


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """Inject a fresh :memory: Database into the global _db slot.

    ``_persist_read_summary`` calls ``_db()`` which delegates to
    :func:`backend.data.database.get_database`, so we install a fresh
    Database for each test. Yielding the connection lets the caller
    verify the persisted row state via direct SELECTs.
    """
    db_mod._db = Database(":memory:")
    db_mod._db.init_db()
    yield db_mod._db.get_connection()
    db_mod._db.close()
    db_mod._db = None


def _stub_result(
    *,
    doc_type: OfficeDocType,
    status: OfficeDocStatus,
    file_size_bytes: int,
    page_count: Optional[int] = None,
) -> _StubResult:
    """Build a stub result whose summary mirrors what a real reader returns."""
    now_ms = int(time.time() * 1000)
    summary = OfficeDocumentSummary(
        id="placeholder",  # overridden by _persist_read_summary
        workspace_path="placeholder",  # overridden too
        doc_type=doc_type,
        original_filename=None,
        generated_filename="placeholder",
        status=status,
        created_at=now_ms,
        updated_at=now_ms,
        metadata=OfficeDocumentMetadata(
            page_count=page_count,
            file_size_bytes=file_size_bytes,
        ),
    )
    return _StubResult(summary=summary)


def _write_existing_row(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    workspace: str,
    doc_type: OfficeDocType,
    original_filename: Optional[str],
    generated_filename: str,
    archived_at: Optional[int],
    derived_from: Optional[str],
    file_size_bytes: int,
) -> None:
    """Insert a row directly so we can stage the merge scenarios."""
    now_ms = int(time.time() * 1000)
    import json as _json

    conn.execute(
        """
        INSERT INTO office_documents (
            id, workspace_path, doc_type, original_filename,
            generated_filename, status, created_at, updated_at, metadata,
            derived_from, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            doc_id,
            workspace,
            doc_type.value,
            original_filename,
            generated_filename,
            OfficeDocStatus.PARSED.value,
            now_ms,
            now_ms,
            _json.dumps({"file_size_bytes": file_size_bytes}),
            derived_from,
            archived_at,
        ),
    )
    conn.commit()


# ──────────────────────────────────────────────────────────────────────
# Case 1: fresh file read -> INSERT, archived_at=None, original from req
# ──────────────────────────────────────────────────────────────────────


def test_persist_inserts_fresh_row_with_no_merge(
    conn: sqlite3.Connection, fixture_dir: Path
) -> None:
    """First read of a brand-new file -> full INSERT, archived_at=None, original_filename from req."""
    workspace = str(fixture_dir.resolve())
    # Stage an empty workspace/<doc_type>/<doc_id>/ layout on disk so
    # ``file_path.parent.name`` matches the document_id we expect.
    doc_id = "fresh-doc-1"
    doc_dir = fixture_dir / "office" / OfficeDocType.WORD.value / doc_id
    doc_dir.mkdir(parents=True)
    file_path = doc_dir / "Notes.docx"
    file_path.write_bytes(b"x")  # tiny content; we don't actually parse it

    result = _stub_result(
        doc_type=OfficeDocType.WORD,
        status=OfficeDocStatus.PARSED,
        file_size_bytes=1,
    )

    from backend.api.office_routes import _persist_read_summary

    _persist_read_summary(
        result,
        file_path=file_path,
        canonical_workspace=workspace,
        original_filename="MyNotes.docx",
    )

    row = get_document(conn, doc_id)
    assert row is not None
    assert row.id == doc_id
    assert row.workspace_path == workspace
    assert row.doc_type == OfficeDocType.WORD
    assert row.original_filename == "MyNotes.docx"
    assert row.generated_filename == "Notes.docx"
    assert row.archived_at is None
    assert row.derived_from is None


# ──────────────────────────────────────────────────────────────────────
# Case 2: previously archived doc re-read -> archived_at preserved
# ──────────────────────────────────────────────────────────────────────


def test_persist_preserves_archived_at_on_reread(
    conn: sqlite3.Connection, fixture_dir: Path
) -> None:
    """A re-read on an archived row must NOT re-activate the document."""
    workspace = str(fixture_dir.resolve())
    doc_id = "archived-doc-1"
    doc_dir = fixture_dir / "office" / OfficeDocType.WORD.value / doc_id
    doc_dir.mkdir(parents=True)
    file_path = doc_dir / "Old.docx"
    file_path.write_bytes(b"x")

    _write_existing_row(
        conn,
        doc_id=doc_id,
        workspace=workspace,
        doc_type=OfficeDocType.WORD,
        original_filename="Old.docx",
        generated_filename="Old.docx",
        archived_at=1_700_000_000_000,  # archived
        derived_from=None,
        file_size_bytes=42,
    )

    result = _stub_result(
        doc_type=OfficeDocType.WORD,
        status=OfficeDocStatus.PARSED,
        file_size_bytes=42,
    )

    from backend.api.office_routes import _persist_read_summary

    _persist_read_summary(
        result,
        file_path=file_path,
        canonical_workspace=workspace,
        original_filename=None,  # caller doesn't track original
    )

    row = get_document(conn, doc_id)
    assert row is not None
    assert row.archived_at == 1_700_000_000_000, "archived_at must be preserved across re-reads"


# ──────────────────────────────────────────────────────────────────────
# Case 3: re-read on parsed doc -> derived_from preserved, updated_at advances
# ──────────────────────────────────────────────────────────────────────


def test_persist_preserves_derived_from_and_advances_updated_at(
    conn: sqlite3.Connection, fixture_dir: Path
) -> None:
    """A re-read keeps derived_from lineage but refreshes updated_at + status."""
    workspace = str(fixture_dir.resolve())
    doc_id = "derived-doc-1"
    doc_dir = fixture_dir / "office" / OfficeDocType.PPT.value / doc_id
    doc_dir.mkdir(parents=True)
    file_path = doc_dir / "Slides.pptx"
    file_path.write_bytes(b"x")

    # Seed a row with a derived_from lineage link + an old updated_at.
    now_ms = int(time.time() * 1000)
    old_updated = now_ms - 60_000
    conn.execute(
        """
        INSERT INTO office_documents (
            id, workspace_path, doc_type, original_filename,
            generated_filename, status, created_at, updated_at, metadata,
            derived_from, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            doc_id,
            workspace,
            OfficeDocType.PPT.value,
            "OriginalDeck.pptx",
            "Slides.pptx",
            OfficeDocStatus.PARSED.value,
            old_updated,
            old_updated,
            '{"file_size_bytes": 100}',
            "source-doc-uuid",
        ),
    )
    conn.commit()

    result = _stub_result(
        doc_type=OfficeDocType.PPT,
        status=OfficeDocStatus.PARSED,
        file_size_bytes=100,
    )
    # Override the stub's updated_at so we can verify it advances.
    new_updated = now_ms
    result.summary.updated_at = new_updated

    from backend.api.office_routes import _persist_read_summary

    _persist_read_summary(
        result,
        file_path=file_path,
        canonical_workspace=workspace,
        original_filename=None,
    )

    row = get_document(conn, doc_id)
    assert row is not None
    assert row.derived_from == "source-doc-uuid", "derived_from must be preserved"
    assert row.updated_at == new_updated, "updated_at must advance on re-read"
    assert row.status == OfficeDocStatus.PARSED


# ──────────────────────────────────────────────────────────────────────
# Case 4: re-read with None original_filename keeps the prior value
# ──────────────────────────────────────────────────────────────────────


def test_persist_preserves_original_filename_when_caller_passes_none(
    conn: sqlite3.Connection, fixture_dir: Path
) -> None:
    """A re-read with original_filename=None must NOT clear the prior row's original_filename."""
    workspace = str(fixture_dir.resolve())
    doc_id = "original-fn-doc-1"
    doc_dir = fixture_dir / "office" / OfficeDocType.EXCEL.value / doc_id
    doc_dir.mkdir(parents=True)
    file_path = doc_dir / "Sheet.xlsx"
    file_path.write_bytes(b"x")

    _write_existing_row(
        conn,
        doc_id=doc_id,
        workspace=workspace,
        doc_type=OfficeDocType.EXCEL,
        original_filename="QuarterlyReport.xlsx",  # user-supplied name
        generated_filename="Sheet.xlsx",
        archived_at=None,
        derived_from=None,
        file_size_bytes=10,
    )

    result = _stub_result(
        doc_type=OfficeDocType.EXCEL,
        status=OfficeDocStatus.PARSED,
        file_size_bytes=10,
    )

    from backend.api.office_routes import _persist_read_summary

    # Caller passes None on the re-read (no longer tracks original name).
    _persist_read_summary(
        result,
        file_path=file_path,
        canonical_workspace=workspace,
        original_filename=None,
    )

    row = get_document(conn, doc_id)
    assert row is not None
    assert row.original_filename == "QuarterlyReport.xlsx", (
        "original_filename must NOT be cleared by a re-read with None"
    )


def test_persist_overwrites_original_filename_when_caller_supplies_new(
    conn: sqlite3.Connection, fixture_dir: Path
) -> None:
    """If the caller DOES supply a new original_filename on re-read, it wins."""
    workspace = str(fixture_dir.resolve())
    doc_id = "original-fn-doc-2"
    doc_dir = fixture_dir / "office" / OfficeDocType.EXCEL.value / doc_id
    doc_dir.mkdir(parents=True)
    file_path = doc_dir / "Sheet.xlsx"
    file_path.write_bytes(b"x")

    _write_existing_row(
        conn,
        doc_id=doc_id,
        workspace=workspace,
        doc_type=OfficeDocType.EXCEL,
        original_filename="OldName.xlsx",
        generated_filename="Sheet.xlsx",
        archived_at=None,
        derived_from=None,
        file_size_bytes=10,
    )

    result = _stub_result(
        doc_type=OfficeDocType.EXCEL,
        status=OfficeDocStatus.PARSED,
        file_size_bytes=10,
    )

    from backend.api.office_routes import _persist_read_summary

    _persist_read_summary(
        result,
        file_path=file_path,
        canonical_workspace=workspace,
        original_filename="NewName.xlsx",
    )

    row = get_document(conn, doc_id)
    assert row is not None
    assert row.original_filename == "NewName.xlsx", (
        "Non-None caller-supplied original_filename must take effect on re-read"
    )
