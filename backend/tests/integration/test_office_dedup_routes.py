"""Integration tests for the office import duplicate-check routes (Phase 0).

Covers ``backend/api/office_dedup_routes.py`` end-to-end through the route
functions, with the database swapped for an in-memory SQLite connection:

- ``POST /documents/duplicates`` answers POSITIONALLY (entry *i* belongs to
  ``file_paths[i]``), reports the digest and the matching live document;
- a file that is not on disk comes back with ``content_hash=None`` instead
  of failing the whole batch;
- paths escaping the workspace and oversized batches are rejected (400);
- ``POST /documents/{id}/lineage`` sets/clears ``derived_from`` and raises
  ``OfficeFileNotFoundError`` (404) for unknown ids on either end.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from backend.api import office_dedup_routes
from backend.api.office_dedup_routes import (
    MAX_DUPLICATE_CHECK_FILES,
    OfficeDocumentLineageRequest,
    OfficeDuplicateCheckRequest,
    check_duplicates_endpoint,
    set_document_lineage_endpoint,
)
from backend.office.errors import OfficeFileNotFoundError, OfficePathError
from backend.office.storage import ensure_content_hash_table

pytestmark = pytest.mark.integration

NOW_MS = 1_700_000_000_000


class _FakeDatabase:
    """Minimal stand-in for backend.data.database.Database."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_connection(self) -> sqlite3.Connection:
        return self._conn


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def conn(monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """In-memory DB wired into the dedup route module."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
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
            archived_at INTEGER,
            active_spec_id TEXT
        )
        """
    )
    connection.commit()
    ensure_content_hash_table(connection)
    monkeypatch.setattr(office_dedup_routes, "get_database", lambda: _FakeDatabase(connection))
    yield connection
    connection.close()


def _insert_doc(conn: sqlite3.Connection, doc_id: str, workspace_path: str) -> None:
    conn.execute(
        """
        INSERT INTO office_documents
            (id, workspace_path, doc_type, original_filename,
             generated_filename, status, created_at, updated_at,
             metadata, derived_from, archived_at)
        VALUES (?, ?, 'word', NULL, ?, 'parsed', ?, ?, ?, NULL, NULL)
        """,
        (
            doc_id,
            workspace_path,
            f"{doc_id}.docx",
            NOW_MS,
            NOW_MS,
            '{"file_size_bytes": 12}',
        ),
    )
    conn.commit()


def _seed_managed_doc(
    conn: sqlite3.Connection, workspace: Path, doc_id: str, content: bytes
) -> Path:
    """Create the managed file + DB row + content hash; return the file path."""
    canonical = str(workspace.resolve())
    managed_dir = workspace / "office" / "word" / doc_id
    managed_dir.mkdir(parents=True)
    managed = managed_dir / f"{doc_id}.docx"
    managed.write_bytes(content)
    _insert_doc(conn, doc_id, canonical)
    conn.execute(
        """
        INSERT INTO office_document_hashes
            (id, workspace_path, content_hash, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            doc_id,
            canonical,
            "sha256:" + hashlib.sha256(content).hexdigest(),
            NOW_MS,
        ),
    )
    conn.commit()
    return managed


# ──────────────────────────────────────────────────────────────────────
# POST /documents/duplicates
# ──────────────────────────────────────────────────────────────────────


def test_check_duplicates_reports_matching_document(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    content = b"identical bytes"
    managed = _seed_managed_doc(conn, workspace, "doc-1", content)
    assert managed.is_file()

    staged = workspace / "staged.docx"
    staged.write_bytes(content)

    result = check_duplicates_endpoint(
        OfficeDuplicateCheckRequest(
            workspace_path=str(workspace), file_paths=[str(staged)]
        )
    )

    assert len(result.files) == 1
    entry = result.files[0]
    assert entry.file_path == str(staged.resolve())
    assert entry.content_hash == "sha256:" + hashlib.sha256(content).hexdigest()
    assert [doc.id for doc in entry.duplicates] == ["doc-1"]


def test_check_duplicates_is_positional_and_tolerates_missing_files(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    content = b"same again"
    _seed_managed_doc(conn, workspace, "doc-1", content)
    present = workspace / "present.docx"
    present.write_bytes(content)
    missing = workspace / "missing.docx"

    result = check_duplicates_endpoint(
        OfficeDuplicateCheckRequest(
            workspace_path=str(workspace),
            file_paths=[str(missing), str(present)],
        )
    )

    assert len(result.files) == 2
    assert result.files[0].file_path == str(missing.resolve())
    assert result.files[0].content_hash is None
    assert result.files[0].duplicates == []
    assert result.files[1].file_path == str(present.resolve())
    assert [doc.id for doc in result.files[1].duplicates] == ["doc-1"]


def test_check_duplicates_rejects_workspace_escape(
    conn: sqlite3.Connection, workspace: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.docx"
    outside.write_bytes(b"nope")

    with pytest.raises(OfficePathError):
        check_duplicates_endpoint(
            OfficeDuplicateCheckRequest(
                workspace_path=str(workspace), file_paths=[str(outside)]
            )
        )


def test_check_duplicates_rejects_oversized_batch(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    too_many = [
        str(workspace / f"f{i}.docx") for i in range(MAX_DUPLICATE_CHECK_FILES + 1)
    ]

    with pytest.raises(OfficePathError):
        check_duplicates_endpoint(
            OfficeDuplicateCheckRequest(workspace_path=str(workspace), file_paths=too_many)
        )


# ──────────────────────────────────────────────────────────────────────
# Lineage: set / clear derived_from on a document
# ──────────────────────────────────────────────────────────────────────


def test_set_lineage_points_new_document_at_source(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    canonical = str(workspace.resolve())
    _insert_doc(conn, "doc-old", canonical)
    _insert_doc(conn, "doc-new", canonical)

    resp = set_document_lineage_endpoint(
        "doc-new", OfficeDocumentLineageRequest(derived_from="doc-old")
    )

    assert resp.updated is True
    assert resp.document_id == "doc-new"
    assert resp.derived_from == "doc-old"
    row = conn.execute(
        "SELECT derived_from FROM office_documents WHERE id = 'doc-new'"
    ).fetchone()
    assert row["derived_from"] == "doc-old"


def test_set_lineage_can_clear_source(conn: sqlite3.Connection, workspace: Path) -> None:
    canonical = str(workspace.resolve())
    _insert_doc(conn, "doc-old", canonical)
    _insert_doc(conn, "doc-new", canonical)
    set_document_lineage_endpoint(
        "doc-new", OfficeDocumentLineageRequest(derived_from="doc-old")
    )

    resp = set_document_lineage_endpoint(
        "doc-new", OfficeDocumentLineageRequest(derived_from=None)
    )

    assert resp.derived_from is None
    row = conn.execute(
        "SELECT derived_from FROM office_documents WHERE id = 'doc-new'"
    ).fetchone()
    assert row["derived_from"] is None


def test_set_lineage_rejects_unknown_source(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    _insert_doc(conn, "doc-new", str(workspace.resolve()))

    with pytest.raises(OfficeFileNotFoundError):
        set_document_lineage_endpoint(
            "doc-new", OfficeDocumentLineageRequest(derived_from="missing-source")
        )


def test_set_lineage_rejects_unknown_target(
    conn: sqlite3.Connection, workspace: Path
) -> None:
    _insert_doc(conn, "doc-old", str(workspace.resolve()))

    with pytest.raises(OfficeFileNotFoundError):
        set_document_lineage_endpoint(
            "missing-target", OfficeDocumentLineageRequest(derived_from="doc-old")
        )
