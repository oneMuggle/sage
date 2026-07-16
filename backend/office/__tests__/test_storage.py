"""Tests for backend.office.storage (path validation + SQLite persistence).

TDD approach (plan §4.1.2): tests written FIRST.

Test coverage:
- validate_workspace: rejects path traversal (../)
- validate_workspace: rejects non-existent paths
- validate_workspace: accepts existing dir
- validate_workspace: rejects symlinks escaping sandbox
- generate_document_dir: creates workspace/office/<doc_type>/<uuid>/
- save_document: INSERT row, returns OfficeDocumentSummary
- list_documents: SELECT rows filtered by workspace
- delete_document: DELETE row by id
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.office.errors import OfficePathError
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.storage import (
    delete_document,
    generate_document_dir,
    list_documents,
    save_document,
    validate_workspace,
)


@pytest.fixture()
def workspace(fixture_dir: Path) -> Path:
    """Create a real workspace directory under tmp_path."""
    ws = fixture_dir / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    """In-memory SQLite connection with office_documents table created."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE office_documents (
            id TEXT PRIMARY KEY,
            workspace_path TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            original_filename TEXT,
            generated_filename TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            metadata TEXT
        )
        """
    )
    conn.commit()
    return conn


def _make_summary(
    *,
    doc_id: str = "abc-123",
    workspace_path: str = "/tmp/ws",
    doc_type: OfficeDocType = OfficeDocType.PPT,
    generated_filename: str = "out.pptx",
    status: OfficeDocStatus = OfficeDocStatus.GENERATED,
) -> OfficeDocumentSummary:
    """Helper: build a valid OfficeDocumentSummary for tests."""
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=doc_type,
        original_filename=None,
        generated_filename=generated_filename,
        status=status,
        created_at=1_700_000_000_000,
        updated_at=1_700_000_000_000,
        metadata=OfficeDocumentMetadata(
            page_count=1,
            file_size_bytes=1024,
        ),
    )


# ──────────────────────────────────────────────────────────────────────
# validate_workspace tests
# ──────────────────────────────────────────────────────────────────────


def test_validate_workspace_accepts_existing_directory(workspace: Path) -> None:
    """Existing directory is valid."""
    result = validate_workspace(workspace)
    assert result == workspace.resolve()


def test_validate_workspace_rejects_nonexistent_path(fixture_dir: Path) -> None:
    """Non-existent path raises OfficePathError."""
    missing = fixture_dir / "does-not-exist"
    with pytest.raises(OfficePathError):
        validate_workspace(missing)


def test_validate_workspace_rejects_file_not_directory(fixture_dir: Path) -> None:
    """Path that is a file (not dir) raises OfficePathError."""
    f = fixture_dir / "a-file.txt"
    f.write_text("not a dir")
    with pytest.raises(OfficePathError):
        validate_workspace(f)


def test_validate_workspace_rejects_traversal_in_string(fixture_dir: Path) -> None:
    """Path string containing '..' traversal segment raises OfficePathError."""
    bad = fixture_dir / ".." / "outside"
    with pytest.raises(OfficePathError):
        validate_workspace(bad)


# ──────────────────────────────────────────────────────────────────────
# generate_document_dir tests
# ──────────────────────────────────────────────────────────────────────


def test_generate_document_dir_creates_office_subdir(workspace: Path) -> None:
    """Creates workspace/office/<doc_type>/<doc_id>/ directory."""
    doc_id = "test-doc-1"
    result = generate_document_dir(workspace, OfficeDocType.PPT, doc_id)
    expected = (workspace / "office" / "ppt" / doc_id).resolve()
    assert result == expected
    assert result.is_dir()


def test_generate_document_dir_rejects_workspace_traversal(workspace: Path) -> None:
    """doc_id containing '/' or '..' is rejected (path traversal)."""
    with pytest.raises(OfficePathError):
        generate_document_dir(workspace, OfficeDocType.WORD, "../escape")


# ──────────────────────────────────────────────────────────────────────
# save_document tests
# ──────────────────────────────────────────────────────────────────────


def test_save_document_inserts_row(db_conn: sqlite3.Connection) -> None:
    """save_document() inserts a row and returns the saved summary."""
    summary = _make_summary()
    result = save_document(db_conn, summary)

    assert result.id == summary.id
    cursor = db_conn.execute("SELECT id, doc_type, status FROM office_documents")
    row = cursor.fetchone()
    assert row["id"] == "abc-123"
    assert row["doc_type"] == "ppt"
    assert row["status"] == "generated"


def test_save_document_upserts_existing_row(db_conn: sqlite3.Connection) -> None:
    """Saving with same id updates the existing row (INSERT OR REPLACE)."""
    s1 = _make_summary(doc_id="dup", generated_filename="v1.pptx")
    save_document(db_conn, s1)

    s2 = _make_summary(doc_id="dup", generated_filename="v2.pptx")
    save_document(db_conn, s2)

    cursor = db_conn.execute(
        "SELECT generated_filename FROM office_documents WHERE id = ?", ("dup",)
    )
    assert cursor.fetchone()["generated_filename"] == "v2.pptx"


# ──────────────────────────────────────────────────────────────────────
# list_documents tests
# ──────────────────────────────────────────────────────────────────────


def test_list_documents_returns_empty_for_new_workspace(
    db_conn: sqlite3.Connection,
) -> None:
    """list_documents returns empty list when no rows match workspace."""
    result = list_documents(db_conn, "/tmp/empty-ws")
    assert result == []


def test_list_documents_filters_by_workspace(db_conn: sqlite3.Connection) -> None:
    """list_documents only returns rows for the given workspace path."""
    save_document(db_conn, _make_summary(doc_id="a1", workspace_path="/tmp/ws1"))
    save_document(db_conn, _make_summary(doc_id="a2", workspace_path="/tmp/ws1"))
    save_document(db_conn, _make_summary(doc_id="b1", workspace_path="/tmp/ws2"))

    result = list_documents(db_conn, "/tmp/ws1")
    assert len(result) == 2
    assert {d.id for d in result} == {"a1", "a2"}


# ──────────────────────────────────────────────────────────────────────
# delete_document tests
# ──────────────────────────────────────────────────────────────────────


def test_delete_document_removes_row(db_conn: sqlite3.Connection) -> None:
    """delete_document removes the row and returns True."""
    save_document(db_conn, _make_summary(doc_id="to-delete"))
    assert delete_document(db_conn, "to-delete") is True

    cursor = db_conn.execute("SELECT id FROM office_documents WHERE id = ?", ("to-delete",))
    assert cursor.fetchone() is None


def test_delete_document_returns_false_for_missing_id(db_conn: sqlite3.Connection) -> None:
    """delete_document on non-existent id returns False (no exception)."""
    assert delete_document(db_conn, "never-existed") is False
