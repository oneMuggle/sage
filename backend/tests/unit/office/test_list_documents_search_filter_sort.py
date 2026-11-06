# ruff: noqa: UP006, UP007, UP035
"""Tests for list_documents search/filter/sort (Phase 1 Item A).

Covers the extended ``list_documents()`` API with:
- ``q`` — filename substring search (matches original_filename OR generated_filename)
- ``doc_type`` — filter by document type (word/excel/ppt/pdf)
- ``sort`` — sort field + direction (``-`` prefix for descending)

These parameters are optional and composable. When omitted the function
behaves identically to the pre-existing call signature.
"""

from __future__ import annotations

import json
import sqlite3
import uuid

import pytest

from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.storage import list_documents


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    """In-memory SQLite connection with the office_documents table created."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
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
            metadata TEXT NOT NULL,
            derived_from TEXT,
            archived_at INTEGER,
            active_spec_id TEXT
        )
        """
    )
    return db


WORKSPACE = "/tmp/test-ws"


def _make_doc(
    *,
    doc_type: OfficeDocType = OfficeDocType.WORD,
    original_filename: str | None = None,
    generated_filename: str | None = None,
    created_at: int = 1000,
    updated_at: int = 1000,
    file_size_bytes: int = 1024,
    archived_at: int | None = None,
) -> OfficeDocumentSummary:
    """Build a minimal OfficeDocumentSummary for seeding."""
    return OfficeDocumentSummary(
        id=uuid.uuid4().hex,
        workspace_path=WORKSPACE,
        doc_type=doc_type,
        original_filename=original_filename,
        generated_filename=generated_filename or f"gen-{uuid.uuid4().hex[:8]}.docx",
        status=OfficeDocStatus.PARSED,
        created_at=created_at,
        updated_at=updated_at,
        metadata=OfficeDocumentMetadata(file_size_bytes=file_size_bytes),
        archived_at=archived_at,
    )


def _seed(conn: sqlite3.Connection, doc: OfficeDocumentSummary) -> None:
    """Insert a document summary into the connection."""
    conn.execute(
        """
        INSERT INTO office_documents
            (id, workspace_path, doc_type, original_filename, generated_filename,
             status, created_at, updated_at, metadata, derived_from, archived_at, active_spec_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            doc.id,
            doc.workspace_path,
            doc.doc_type.value,
            doc.original_filename,
            doc.generated_filename,
            doc.status.value,
            doc.created_at,
            doc.updated_at,
            json.dumps(
                {
                    "file_size_bytes": doc.metadata.file_size_bytes,
                    "page_count": doc.metadata.page_count,
                    "sheet_count": doc.metadata.sheet_count,
                    "paragraph_count": doc.metadata.paragraph_count,
                    "table_count": doc.metadata.table_count,
                }
            ),
            doc.derived_from,
            doc.archived_at,
            doc.active_spec_id,
        ),
    )
    conn.commit()


# ──────────────────────────────────────────────────────────────────────
# Search (q)
# ──────────────────────────────────────────────────────────────────────


class TestListDocumentsSearch:
    """q= matches against original_filename OR generated_filename (case-insensitive)."""

    def test_search_matches_original_filename(self, conn: sqlite3.Connection) -> None:
        doc_a = _make_doc(original_filename="季度报告.docx")
        doc_b = _make_doc(original_filename="月度总结.docx")
        _seed(conn, doc_a)
        _seed(conn, doc_b)

        result = list_documents(conn, WORKSPACE, q="季度")
        assert len(result) == 1
        assert result[0].id == doc_a.id

    def test_search_matches_generated_filename(self, conn: sqlite3.Connection) -> None:
        doc = _make_doc(
            original_filename=None,
            generated_filename="auto-generated-report.docx",
        )
        _seed(conn, doc)

        result = list_documents(conn, WORKSPACE, q="generated")
        assert len(result) == 1
        assert result[0].id == doc.id

    def test_search_is_case_insensitive(self, conn: sqlite3.Connection) -> None:
        doc = _make_doc(original_filename="QuarterlyReport.docx")
        _seed(conn, doc)

        result = list_documents(conn, WORKSPACE, q="quarterly")
        assert len(result) == 1

    def test_search_no_match_returns_empty(self, conn: sqlite3.Connection) -> None:
        doc = _make_doc(original_filename="report.docx")
        _seed(conn, doc)

        result = list_documents(conn, WORKSPACE, q="nonexistent")
        assert result == []

    def test_search_empty_string_returns_all(self, conn: sqlite3.Connection) -> None:
        doc_a = _make_doc(original_filename="a.docx")
        doc_b = _make_doc(original_filename="b.docx")
        _seed(conn, doc_a)
        _seed(conn, doc_b)

        result = list_documents(conn, WORKSPACE, q="")
        assert len(result) == 2

    def test_search_excludes_archived(self, conn: sqlite3.Connection) -> None:
        doc_live = _make_doc(original_filename="report.docx")
        doc_archived = _make_doc(
            original_filename="report-archived.docx", archived_at=9999
        )
        _seed(conn, doc_live)
        _seed(conn, doc_archived)

        result = list_documents(conn, WORKSPACE, q="report")
        assert len(result) == 1
        assert result[0].id == doc_live.id

    def test_search_with_include_archived(self, conn: sqlite3.Connection) -> None:
        doc_live = _make_doc(original_filename="report.docx")
        doc_archived = _make_doc(
            original_filename="report-v2.docx", archived_at=9999
        )
        _seed(conn, doc_live)
        _seed(conn, doc_archived)

        result = list_documents(
            conn, WORKSPACE, q="report", include_archived=True
        )
        assert len(result) == 2


# ──────────────────────────────────────────────────────────────────────
# Filter (doc_type)
# ──────────────────────────────────────────────────────────────────────


class TestListDocumentsFilter:
    """doc_type= restricts results to a single document type."""

    def test_filter_by_word(self, conn: sqlite3.Connection) -> None:
        doc_word = _make_doc(doc_type=OfficeDocType.WORD)
        doc_excel = _make_doc(doc_type=OfficeDocType.EXCEL)
        _seed(conn, doc_word)
        _seed(conn, doc_excel)

        result = list_documents(conn, WORKSPACE, doc_type="word")
        assert len(result) == 1
        assert result[0].id == doc_word.id

    def test_filter_by_excel(self, conn: sqlite3.Connection) -> None:
        doc_word = _make_doc(doc_type=OfficeDocType.WORD)
        doc_excel = _make_doc(doc_type=OfficeDocType.EXCEL)
        _seed(conn, doc_word)
        _seed(conn, doc_excel)

        result = list_documents(conn, WORKSPACE, doc_type="excel")
        assert len(result) == 1
        assert result[0].id == doc_excel.id

    def test_filter_by_ppt(self, conn: sqlite3.Connection) -> None:
        doc_ppt = _make_doc(doc_type=OfficeDocType.PPT)
        doc_word = _make_doc(doc_type=OfficeDocType.WORD)
        _seed(conn, doc_ppt)
        _seed(conn, doc_word)

        result = list_documents(conn, WORKSPACE, doc_type="ppt")
        assert len(result) == 1
        assert result[0].id == doc_ppt.id

    def test_filter_no_match_returns_empty(self, conn: sqlite3.Connection) -> None:
        doc_word = _make_doc(doc_type=OfficeDocType.WORD)
        _seed(conn, doc_word)

        result = list_documents(conn, WORKSPACE, doc_type="pdf")
        assert result == []

    def test_filter_none_returns_all(self, conn: sqlite3.Connection) -> None:
        doc_word = _make_doc(doc_type=OfficeDocType.WORD)
        doc_excel = _make_doc(doc_type=OfficeDocType.EXCEL)
        _seed(conn, doc_word)
        _seed(conn, doc_excel)

        result = list_documents(conn, WORKSPACE, doc_type=None)
        assert len(result) == 2


# ──────────────────────────────────────────────────────────────────────
# Sort
# ──────────────────────────────────────────────────────────────────────


class TestListDocumentsSort:
    """sort= controls ordering. ``-`` prefix means descending."""

    def test_sort_by_created_at_desc_default(self, conn: sqlite3.Connection) -> None:
        """Default sort is created_at DESC (matches pre-existing behavior)."""
        doc_old = _make_doc(original_filename="old.docx", created_at=100)
        doc_new = _make_doc(original_filename="new.docx", created_at=200)
        _seed(conn, doc_old)
        _seed(conn, doc_new)

        result = list_documents(conn, WORKSPACE)
        assert [d.id for d in result] == [doc_new.id, doc_old.id]

    def test_sort_by_updated_at_desc(self, conn: sqlite3.Connection) -> None:
        doc_a = _make_doc(original_filename="a.docx", updated_at=100)
        doc_b = _make_doc(original_filename="b.docx", updated_at=300)
        doc_c = _make_doc(original_filename="c.docx", updated_at=200)
        _seed(conn, doc_a)
        _seed(conn, doc_b)
        _seed(conn, doc_c)

        result = list_documents(conn, WORKSPACE, sort="-updated_at")
        assert [d.id for d in result] == [doc_b.id, doc_c.id, doc_a.id]

    def test_sort_by_updated_at_asc(self, conn: sqlite3.Connection) -> None:
        doc_a = _make_doc(original_filename="a.docx", updated_at=100)
        doc_b = _make_doc(original_filename="b.docx", updated_at=300)
        _seed(conn, doc_a)
        _seed(conn, doc_b)

        result = list_documents(conn, WORKSPACE, sort="updated_at")
        assert [d.id for d in result] == [doc_a.id, doc_b.id]

    def test_sort_by_name_asc(self, conn: sqlite3.Connection) -> None:
        doc_c = _make_doc(original_filename="Charlie.docx")
        doc_a = _make_doc(original_filename="Alpha.docx")
        doc_b = _make_doc(original_filename="Beta.docx")
        _seed(conn, doc_c)
        _seed(conn, doc_a)
        _seed(conn, doc_b)

        result = list_documents(conn, WORKSPACE, sort="name")
        assert [d.original_filename for d in result] == ["Alpha.docx", "Beta.docx", "Charlie.docx"]

    def test_sort_by_name_desc(self, conn: sqlite3.Connection) -> None:
        doc_a = _make_doc(original_filename="Alpha.docx")
        doc_b = _make_doc(original_filename="Beta.docx")
        _seed(conn, doc_a)
        _seed(conn, doc_b)

        result = list_documents(conn, WORKSPACE, sort="-name")
        assert [d.original_filename for d in result] == ["Beta.docx", "Alpha.docx"]

    def test_sort_by_name_uses_generated_when_no_original(
        self, conn: sqlite3.Connection
    ) -> None:
        doc = _make_doc(original_filename=None, generated_filename="zzz-gen.docx")
        _seed(conn, doc)

        result = list_documents(conn, WORKSPACE, sort="name")
        assert result[0].generated_filename == "zzz-gen.docx"

    def test_sort_by_size_asc(self, conn: sqlite3.Connection) -> None:
        doc_small = _make_doc(original_filename="small.docx", file_size_bytes=100)
        doc_large = _make_doc(original_filename="large.docx", file_size_bytes=9000)
        _seed(conn, doc_small)
        _seed(conn, doc_large)

        result = list_documents(conn, WORKSPACE, sort="size")
        assert [d.metadata.file_size_bytes for d in result] == [100, 9000]

    def test_sort_by_size_desc(self, conn: sqlite3.Connection) -> None:
        doc_small = _make_doc(original_filename="small.docx", file_size_bytes=100)
        doc_large = _make_doc(original_filename="large.docx", file_size_bytes=9000)
        _seed(conn, doc_small)
        _seed(conn, doc_large)

        result = list_documents(conn, WORKSPACE, sort="-size")
        assert [d.metadata.file_size_bytes for d in result] == [9000, 100]

    def test_sort_invalid_field_falls_back_to_default(
        self, conn: sqlite3.Connection
    ) -> None:
        """Unknown sort fields fall back to created_at DESC (no error)."""
        doc_old = _make_doc(original_filename="old.docx", created_at=100)
        doc_new = _make_doc(original_filename="new.docx", created_at=200)
        _seed(conn, doc_old)
        _seed(conn, doc_new)

        result = list_documents(conn, WORKSPACE, sort="nonexistent")
        # Falls back to default (created_at DESC)
        assert [d.id for d in result] == [doc_new.id, doc_old.id]


# ──────────────────────────────────────────────────────────────────────
# Combined search + filter + sort
# ──────────────────────────────────────────────────────────────────────


class TestListDocumentsCombined:
    """q + doc_type + sort compose correctly."""

    def test_search_and_filter_combined(self, conn: sqlite3.Connection) -> None:
        doc_word_report = _make_doc(
            doc_type=OfficeDocType.WORD, original_filename="report-2024.docx"
        )
        doc_word_other = _make_doc(
            doc_type=OfficeDocType.WORD, original_filename="notes.docx"
        )
        doc_excel_report = _make_doc(
            doc_type=OfficeDocType.EXCEL, original_filename="report-data.xlsx"
        )
        _seed(conn, doc_word_report)
        _seed(conn, doc_word_other)
        _seed(conn, doc_excel_report)

        result = list_documents(conn, WORKSPACE, q="report", doc_type="word")
        assert len(result) == 1
        assert result[0].id == doc_word_report.id

    def test_search_filter_and_sort_combined(
        self, conn: sqlite3.Connection
    ) -> None:
        doc_a = _make_doc(
            doc_type=OfficeDocType.WORD,
            original_filename="report-a.docx",
            updated_at=100,
        )
        doc_b = _make_doc(
            doc_type=OfficeDocType.WORD,
            original_filename="report-b.docx",
            updated_at=300,
        )
        doc_c = _make_doc(
            doc_type=OfficeDocType.WORD,
            original_filename="report-c.docx",
            updated_at=200,
        )
        _seed(conn, doc_a)
        _seed(conn, doc_b)
        _seed(conn, doc_c)

        result = list_documents(
            conn, WORKSPACE, q="report", doc_type="word", sort="-updated_at"
        )
        assert [d.id for d in result] == [doc_b.id, doc_c.id, doc_a.id]
