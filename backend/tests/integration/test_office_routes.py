"""Integration tests for office routes (M0 Task 3: read persistence).

Covers the end-to-end flow where a Chat-native caller:

1. imports (or generates) a managed file under
   ``<workspace>/office/<doc_type>/<doc_id>/<filename>``;
2. POSTs a read request with ``workspace_path`` + ``file_path``;
3. receives an ``OfficeXxxReadResult`` whose ``summary.id`` matches the
   managed directory name;
4. and observes a corresponding ``office_documents`` row with
   ``status='parsed'`` and ``generated_filename`` matching the on-disk file.

Also covers workspace-path canonicalization for list/delete endpoints so
``/tmp/./ws`` and ``/tmp/ws`` resolve to the same managed documents.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from backend.api.office_routes import (
    list_documents_endpoint,
    read_excel_endpoint,
    read_ppt_endpoint,
    read_word_endpoint,
)
from backend.data.database import get_database
from backend.office.models import OfficeDocType, OfficeReadRequest
from backend.office.path_safety import managed_document_path
from backend.office.storage import generate_document_dir, list_documents as list_documents_storage


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Per-test scratch workspace containing a freshly-created managed dir."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def _seed_managed_pptx(workspace: Path) -> Path:
    """Create a real .pptx under <workspace>/office/ppt/<uuid>/ and return its path."""
    doc_id = uuid.uuid4().hex
    directory = generate_document_dir(workspace, OfficeDocType.PPT, doc_id)
    managed_path = directory / "input.pptx"
    # Build a minimal PPTX with python-pptx (same library the reader uses).
    from pptx import Presentation

    Presentation().save(managed_path)
    return managed_path


def _seed_managed_docx(workspace: Path) -> Path:
    """Create a real .docx under <workspace>/office/word/<uuid>/ and return its path."""
    doc_id = uuid.uuid4().hex
    directory = generate_document_dir(workspace, OfficeDocType.WORD, doc_id)
    managed_path = directory / "input.docx"
    from docx import Document

    Document().save(managed_path)
    return managed_path


def _seed_managed_xlsx(workspace: Path) -> Path:
    """Create a real .xlsx under <workspace>/office/excel/<uuid>/ and return its path."""
    doc_id = uuid.uuid4().hex
    directory = generate_document_dir(workspace, OfficeDocType.EXCEL, doc_id)
    managed_path = directory / "input.xlsx"
    from openpyxl import Workbook

    Workbook().save(managed_path)
    return managed_path


# ──────────────────────────────────────────────────────────────────────
# Read persistence
# ──────────────────────────────────────────────────────────────────────


def test_read_ppt_persists_summary_row(workspace: Path) -> None:
    """POST /office/ppt/read writes a parsed row keyed by the managed dir UUID."""
    managed_file = _seed_managed_pptx(workspace)
    expected_doc_id = managed_file.parent.name  # managed directory UUID

    result = read_ppt_endpoint(
        OfficeReadRequest(
            workspace_path=str(workspace),
            file_path=str(managed_file),
            original_filename="upload.pptx",
        )
    )

    assert result.summary.id == expected_doc_id
    assert result.summary.generated_filename == managed_file.name

    conn = get_database().get_connection()
    row = conn.execute(
        "SELECT id, status, generated_filename, original_filename "
        "FROM office_documents WHERE id = ?",
        (expected_doc_id,),
    ).fetchone()
    assert row is not None
    assert row["status"] == "parsed"
    assert row["generated_filename"] == managed_file.name
    assert row["original_filename"] == "upload.pptx"


def test_read_word_persists_summary_row(workspace: Path) -> None:
    """POST /office/word/read writes a parsed row keyed by the managed dir UUID."""
    managed_file = _seed_managed_docx(workspace)
    expected_doc_id = managed_file.parent.name

    result = read_word_endpoint(
        OfficeReadRequest(
            workspace_path=str(workspace),
            file_path=str(managed_file),
        )
    )

    assert result.summary.id == expected_doc_id
    conn = get_database().get_connection()
    row = conn.execute(
        "SELECT status FROM office_documents WHERE id = ?",
        (expected_doc_id,),
    ).fetchone()
    assert row is not None
    assert row["status"] == "parsed"


def test_read_excel_persists_summary_row(workspace: Path) -> None:
    """POST /office/excel/read writes a parsed row keyed by the managed dir UUID."""
    managed_file = _seed_managed_xlsx(workspace)
    expected_doc_id = managed_file.parent.name

    result = read_excel_endpoint(
        OfficeReadRequest(
            workspace_path=str(workspace),
            file_path=str(managed_file),
        )
    )

    assert result.summary.id == expected_doc_id
    conn = get_database().get_connection()
    row = conn.execute(
        "SELECT status FROM office_documents WHERE id = ?",
        (expected_doc_id,),
    ).fetchone()
    assert row is not None
    assert row["status"] == "parsed"


# ──────────────────────────────────────────────────────────────────────
# workspace_path canonicalization
# ──────────────────────────────────────────────────────────────────────


def test_list_documents_canonicalizes_workspace_path(workspace: Path) -> None:
    """GET /office/documents matches the stored row even with a non-canonical path."""
    # Seed a row using the canonical path (set up by read_ppt_endpoint).
    managed_file = _seed_managed_pptx(workspace)
    read_ppt_endpoint(
        OfficeReadRequest(
            workspace_path=str(workspace),
            file_path=str(managed_file),
        )
    )

    # Call the list endpoint with a non-canonical workspace_path that
    # resolves to the same directory — should still find the seeded row.
    non_canonical = str(workspace) + "/."
    response = list_documents_endpoint(non_canonical)
    assert response.total == 1
    assert response.documents[0].id == managed_file.parent.name


def test_save_document_writes_archived_at_null_for_fresh_read(workspace: Path) -> None:
    """Fresh read summaries have archived_at NULL so list_documents returns them."""
    managed_file = _seed_managed_pptx(workspace)
    read_ppt_endpoint(
        OfficeReadRequest(
            workspace_path=str(workspace),
            file_path=str(managed_file),
        )
    )
    docs = list_documents_storage(get_database().get_connection(), str(workspace))
    assert len(docs) == 1
    assert docs[0].archived_at is None


# ──────────────────────────────────────────────────────────────────────
# managed_document_path contract (sanity check the helper used by the
# Electron import gateway; guards against the contract drifting)
# ──────────────────────────────────────────────────────────────────────


def test_managed_document_path_matches_storage_layout(workspace: Path) -> None:
    """managed_document_path produces the path that read routes resolve."""
    doc_id = "fixed-uuid"
    path = managed_document_path(workspace, OfficeDocType.PPT, doc_id, "note.pptx")
    assert path == workspace / "office" / "ppt" / doc_id / "note.pptx"
