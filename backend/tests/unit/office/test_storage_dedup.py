"""Tests for content-hash duplicate detection + lineage (AI workbench, Phase 0).

Exercises the dedup helpers in ``backend.office.storage`` against an
in-memory SQLite connection:

- ``record_content_hash`` stores ``sha256:<hex>`` and returns it;
- ``get_content_hash`` reads the stored digest back;
- ``record_content_hash`` returns None (no raise) when the file is missing;
- ``find_documents_by_hash`` matches only live documents in the same
  workspace (archived rows and other workspaces are excluded);
- ``delete_content_hash`` drops the mapping;
- ``set_document_lineage`` updates ``derived_from`` and reports rowcount.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Iterator

import pytest

from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.storage import (
    delete_content_hash,
    ensure_content_hash_table,
    find_documents_by_hash,
    get_content_hash,
    record_content_hash,
    set_document_lineage,
)

NOW_MS = 1_700_000_000_000


@pytest.fixture()
def conn() -> Iterator[sqlite3.Connection]:
    """In-memory SQLite with the office_documents table (post-migration shape)."""
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
    yield connection
    connection.close()


def _insert_doc(
    conn: sqlite3.Connection,
    doc_id: str,
    workspace_path: str,
    *,
    archived: bool = False,
    created_at: int = NOW_MS,
) -> None:
    conn.execute(
        """
        INSERT INTO office_documents
            (id, workspace_path, doc_type, original_filename,
             generated_filename, status, created_at, updated_at,
             metadata, derived_from, archived_at)
        VALUES (?, ?, 'word', NULL, ?, 'parsed', ?, ?, ?, NULL, ?)
        """,
        (
            doc_id,
            workspace_path,
            f"{doc_id}.docx",
            created_at,
            created_at,
            '{"file_size_bytes": 12}',
            NOW_MS if archived else None,
        ),
    )
    conn.commit()


def _summary(doc_id: str, workspace_path: str) -> OfficeDocumentSummary:
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=OfficeDocType.WORD,
        original_filename=None,
        generated_filename=f"{doc_id}.docx",
        status=OfficeDocStatus.PARSED,
        created_at=NOW_MS,
        updated_at=NOW_MS,
        metadata=OfficeDocumentMetadata(file_size_bytes=12),
    )


# ──────────────────────────────────────────────────────────────────────
# record_content_hash / get_content_hash
# ──────────────────────────────────────────────────────────────────────


def test_record_content_hash_stores_sha256_digest(conn: sqlite3.Connection, tmp_path: Path):
    workspace = str(tmp_path)
    _insert_doc(conn, "doc-1", workspace)
    source = tmp_path / "report.docx"
    source.write_bytes(b"hello office")

    digest = record_content_hash(conn, _summary("doc-1", workspace), file_path=source)

    expected = "sha256:" + hashlib.sha256(b"hello office").hexdigest()
    assert digest == expected
    assert get_content_hash(conn, "doc-1") == expected


def test_record_content_hash_returns_none_when_file_missing(
    conn: sqlite3.Connection, tmp_path: Path
):
    workspace = str(tmp_path)
    _insert_doc(conn, "doc-1", workspace)

    digest = record_content_hash(
        conn, _summary("doc-1", workspace), file_path=tmp_path / "missing.docx"
    )

    assert digest is None
    assert get_content_hash(conn, "doc-1") is None


def test_get_content_hash_returns_none_before_table_exists(conn: sqlite3.Connection):
    assert get_content_hash(conn, "doc-1") is None


def test_delete_content_hash_drops_mapping(conn: sqlite3.Connection, tmp_path: Path):
    workspace = str(tmp_path)
    _insert_doc(conn, "doc-1", workspace)
    source = tmp_path / "report.docx"
    source.write_bytes(b"hello office")
    record_content_hash(conn, _summary("doc-1", workspace), file_path=source)

    delete_content_hash(conn, "doc-1")

    assert get_content_hash(conn, "doc-1") is None
    assert find_documents_by_hash(conn, workspace, "sha256:" + "0" * 64) == []


# ──────────────────────────────────────────────────────────────────────
# find_documents_by_hash
# ──────────────────────────────────────────────────────────────────────


def test_find_documents_by_hash_matches_same_workspace_only(
    conn: sqlite3.Connection, tmp_path: Path
):
    ws_a = str(tmp_path / "a")
    ws_b = str(tmp_path / "b")
    Path(ws_a).mkdir()
    Path(ws_b).mkdir()
    content = b"identical bytes"
    digest = "sha256:" + hashlib.sha256(content).hexdigest()

    _insert_doc(conn, "doc-a", ws_a)
    _insert_doc(conn, "doc-b", ws_b)
    source_a = Path(ws_a) / "a.docx"
    source_b = Path(ws_b) / "b.docx"
    source_a.write_bytes(content)
    source_b.write_bytes(content)
    record_content_hash(conn, _summary("doc-a", ws_a), file_path=source_a)
    record_content_hash(conn, _summary("doc-b", ws_b), file_path=source_b)

    matches = find_documents_by_hash(conn, ws_a, digest)

    assert [m.id for m in matches] == ["doc-a"]


def test_find_documents_by_hash_excludes_archived(
    conn: sqlite3.Connection, tmp_path: Path
):
    workspace = str(tmp_path)
    content = b"archived bytes"
    digest = "sha256:" + hashlib.sha256(content).hexdigest()

    _insert_doc(conn, "doc-live", workspace)
    _insert_doc(conn, "doc-archived", workspace, archived=True)
    for doc_id in ("doc-live", "doc-archived"):
        source = tmp_path / f"{doc_id}.docx"
        source.write_bytes(content)
        record_content_hash(conn, _summary(doc_id, workspace), file_path=source)

    matches = find_documents_by_hash(conn, workspace, digest)

    assert [m.id for m in matches] == ["doc-live"]


def test_find_documents_by_hash_ignores_other_digests(
    conn: sqlite3.Connection, tmp_path: Path
):
    workspace = str(tmp_path)
    _insert_doc(conn, "doc-1", workspace)
    source = tmp_path / "report.docx"
    source.write_bytes(b"some bytes")
    record_content_hash(conn, _summary("doc-1", workspace), file_path=source)

    assert find_documents_by_hash(conn, workspace, "sha256:" + "f" * 64) == []


def test_find_documents_by_hash_without_table_returns_empty(
    conn: sqlite3.Connection, tmp_path: Path
):
    # ensure_content_hash_table is called internally; a fresh DB simply has
    # no hashes yet, so the answer is "no duplicates".
    assert find_documents_by_hash(conn, str(tmp_path), "sha256:" + "a" * 64) == []


def test_ensure_content_hash_table_is_idempotent(conn: sqlite3.Connection):
    ensure_content_hash_table(conn)
    ensure_content_hash_table(conn)


# ──────────────────────────────────────────────────────────────────────
# set_document_lineage
# ──────────────────────────────────────────────────────────────────────


def test_set_document_lineage_updates_derived_from(conn: sqlite3.Connection, tmp_path: Path):
    workspace = str(tmp_path)
    _insert_doc(conn, "doc-old", workspace)
    _insert_doc(conn, "doc-new", workspace)

    assert set_document_lineage(conn, "doc-new", "doc-old") is True

    row = conn.execute(
        "SELECT derived_from FROM office_documents WHERE id = 'doc-new'"
    ).fetchone()
    assert row["derived_from"] == "doc-old"

    assert set_document_lineage(conn, "doc-new", None) is True
    row = conn.execute(
        "SELECT derived_from FROM office_documents WHERE id = 'doc-new'"
    ).fetchone()
    assert row["derived_from"] is None


def test_set_document_lineage_returns_false_for_unknown_doc(conn: sqlite3.Connection):
    assert set_document_lineage(conn, "missing", "doc-old") is False
