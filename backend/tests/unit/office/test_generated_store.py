"""Tests for ``backend.office.generated_store.persist_generated_document``.

Verifies that the persistence helper:
1. Computes id from the parent directory name.
2. Canonicalises the workspace path (resolved).
3. Sets ``generated_filename`` to the file's basename.
4. Sets ``original_filename`` to None (generated, not uploaded).
5. Sets ``status`` to ``OfficeDocStatus.GENERATED``.
6. Records ``file_size_bytes`` in the nested ``metadata`` object.
7. Persists the row via ``save_document`` (fetchable afterwards).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.data.database import Database
from backend.office.generated_store import persist_generated_document
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
)
from backend.office.storage import get_document

# ruff: noqa: UP006, UP007, UP035


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """Fresh in-memory DB with the office_documents schema."""
    db = Database(":memory:")
    db.init_db()
    yield db.get_connection()
    db.close()


def test_persist_generated_document_word(conn: sqlite3.Connection, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    doc_dir = workspace / "office" / "word" / "abc123"
    doc_dir.mkdir(parents=True)
    file_path = doc_dir / "output.docx"
    file_path.write_bytes(b"fake docx content")

    summary = persist_generated_document(
        conn,
        file_path=file_path,
        doc_type=OfficeDocType.WORD,
        workspace_path=str(workspace),
    )

    assert summary.id == "abc123"
    assert summary.doc_type == OfficeDocType.WORD
    assert summary.generated_filename == "output.docx"
    assert summary.original_filename is None
    assert summary.status == OfficeDocStatus.GENERATED
    assert summary.workspace_path == str(workspace.resolve())
    assert summary.metadata.file_size_bytes == len(b"fake docx content")
    assert summary.created_at > 0
    assert summary.updated_at >= summary.created_at

    # Verify persisted -- fetchable via get_document
    fetched = get_document(conn, summary.id)
    assert fetched is not None
    assert fetched.generated_filename == "output.docx"
    assert fetched.status == OfficeDocStatus.GENERATED


def test_persist_generated_document_ppt(conn: sqlite3.Connection, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    doc_dir = workspace / "office" / "ppt" / "xyz789"
    doc_dir.mkdir(parents=True)
    file_path = doc_dir / "slides.pptx"
    file_path.write_bytes(b"fake pptx content bytes!!")

    summary = persist_generated_document(
        conn,
        file_path=file_path,
        doc_type=OfficeDocType.PPT,
        workspace_path=str(workspace),
    )

    assert summary.id == "xyz789"
    assert summary.doc_type == OfficeDocType.PPT
    assert summary.generated_filename == "slides.pptx"
    assert summary.original_filename is None
    assert summary.status == OfficeDocStatus.GENERATED
    assert summary.metadata.file_size_bytes == len(b"fake pptx content bytes!!")


def test_persist_generated_document_canonical_workspace(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Workspace path with ``.`` segments is resolved to canonical form."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    doc_dir = workspace / "docs" / "canon01"
    doc_dir.mkdir(parents=True)
    file_path = doc_dir / "out.xlsx"
    file_path.write_bytes(b"xlsx")

    # ``./office/..`` resolves back to the workspace root
    non_canonical = str(workspace / "." / "office" / "..")
    summary = persist_generated_document(
        conn,
        file_path=file_path,
        doc_type=OfficeDocType.EXCEL,
        workspace_path=non_canonical,
    )

    assert summary.workspace_path == str(workspace.resolve())
