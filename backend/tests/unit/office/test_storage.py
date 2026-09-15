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
- get_document: SELECT single row by id
- document_path: compute on-disk path from summary
- list_documents(include_archived=False): filter archived_at IS NULL
- Database.init_db migration: adds derived_from + archived_at columns
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.data.database import Database
from backend.office.errors import OfficePathError
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.storage import (
    delete_document,
    document_path,
    generate_document_dir,
    get_document,
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
            metadata TEXT,
            derived_from TEXT,
            archived_at INTEGER
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


# ──────────────────────────────────────────────────────────────────────
# M0 Task 3: nullable derived_from / archived_at + get_document +
#            document_path + archive-aware list
# ──────────────────────────────────────────────────────────────────────


def test_summary_accepts_nullable_derived_from_and_archived_at() -> None:
    """OfficeDocumentSummary accepts the new nullable fields (defaults to None)."""
    summary = OfficeDocumentSummary(
        id="doc-1",
        workspace_path="/tmp/ws",
        doc_type=OfficeDocType.PPT,
        original_filename="orig.pptx",
        generated_filename="gen.pptx",
        status=OfficeDocStatus.PARSED,
        created_at=1,
        updated_at=1,
        metadata=OfficeDocumentMetadata(file_size_bytes=1),
    )
    assert summary.derived_from is None
    assert summary.archived_at is None


def test_summary_preserves_explicit_derived_from_and_archived_at() -> None:
    """OfficeDocumentSummary preserves non-null values for derived_from / archived_at."""
    summary = OfficeDocumentSummary(
        id="doc-2",
        workspace_path="/tmp/ws",
        doc_type=OfficeDocType.WORD,
        original_filename=None,
        generated_filename="gen.docx",
        status=OfficeDocStatus.EDITED,
        created_at=1,
        updated_at=2,
        metadata=OfficeDocumentMetadata(file_size_bytes=1),
        derived_from="parent-doc-1",
        archived_at=1_700_000_000_000,
    )
    assert summary.derived_from == "parent-doc-1"
    assert summary.archived_at == 1_700_000_000_000


def test_init_db_migration_adds_derived_from_and_archived_at(tmp_path: Path) -> None:
    """init_db adds derived_from + archived_at columns to a pre-existing schema.

    Simulates a user upgrading from Phase 1.2 (no derived_from / archived_at
    columns) to M0; the migration must not raise and must add both columns.
    """
    db_path = tmp_path / "legacy.db"
    # Pre-create the office_documents table WITHOUT the new columns.
    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute(
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
    legacy_conn.execute(
        "INSERT INTO office_documents VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "legacy-1",
            "/tmp/ws1",
            "ppt",
            "orig.pptx",
            "gen.pptx",
            "parsed",
            1,
            1,
            "{}",
        ),
    )
    legacy_conn.commit()
    legacy_conn.close()

    # Run init_db on the same DB — should add the new columns idempotently.
    db = Database(db_path=str(db_path))
    db.init_db()

    conn = db.get_connection()
    cols = [row["name"] for row in conn.execute("PRAGMA table_info(office_documents)").fetchall()]
    assert "derived_from" in cols
    assert "archived_at" in cols

    # Legacy row is preserved.
    row = conn.execute(
        "SELECT id, status FROM office_documents WHERE id = ?", ("legacy-1",)
    ).fetchone()
    assert row["status"] == "parsed"


def test_get_document_returns_saved_summary(db_conn: sqlite3.Connection) -> None:
    """get_document retrieves the saved row by id."""
    save_document(db_conn, _make_summary(doc_id="lookup-1"))
    result = get_document(db_conn, "lookup-1")
    assert result is not None
    assert result.id == "lookup-1"
    assert result.generated_filename == "out.pptx"
    assert result.status == OfficeDocStatus.GENERATED


def test_get_document_returns_none_for_missing_id(db_conn: sqlite3.Connection) -> None:
    """get_document returns None for an id that does not exist."""
    assert get_document(db_conn, "never-existed") is None


def test_get_document_roundtrips_nullable_fields(db_conn: sqlite3.Connection) -> None:
    """get_document round-trips derived_from + archived_at."""
    summary = _make_summary(doc_id="nullable-1")
    summary = summary.model_copy(
        update={"derived_from": "parent", "archived_at": 1_700_000_000_000}
    )
    save_document(db_conn, summary)
    loaded = get_document(db_conn, "nullable-1")
    assert loaded is not None
    assert loaded.derived_from == "parent"
    assert loaded.archived_at == 1_700_000_000_000


def test_document_path_returns_managed_layout(tmp_path: Path) -> None:
    """document_path returns <workspace>/office/<doc_type>/<id>/<filename>."""
    summary = _make_summary(
        doc_id="managed-uuid",
        workspace_path=str(tmp_path),
        doc_type=OfficeDocType.WORD,
        generated_filename="report.docx",
    )
    expected = tmp_path / "office" / "word" / "managed-uuid" / "report.docx"
    assert document_path(summary) == expected


def test_list_documents_excludes_archived_by_default(db_conn: sqlite3.Connection) -> None:
    """list_documents(workspace, include_archived=False) hides archived rows."""
    save_document(db_conn, _make_summary(doc_id="keep-1", workspace_path="/tmp/ws"))
    archived = _make_summary(
        doc_id="arch-1",
        workspace_path="/tmp/ws",
        status=OfficeDocStatus.PARSED,
    ).model_copy(update={"archived_at": 1_700_000_000_000})
    save_document(db_conn, archived)

    result = list_documents(db_conn, "/tmp/ws")
    ids = {d.id for d in result}
    assert ids == {"keep-1"}


def test_list_documents_includes_archived_when_requested(db_conn: sqlite3.Connection) -> None:
    """list_documents(workspace, include_archived=True) returns all rows."""
    save_document(db_conn, _make_summary(doc_id="keep-2", workspace_path="/tmp/ws"))
    archived = _make_summary(
        doc_id="arch-2",
        workspace_path="/tmp/ws",
        status=OfficeDocStatus.PARSED,
    ).model_copy(update={"archived_at": 1_700_000_000_000})
    save_document(db_conn, archived)

    result = list_documents(db_conn, "/tmp/ws", include_archived=True)
    ids = {d.id for d in result}
    assert ids == {"keep-2", "arch-2"}
