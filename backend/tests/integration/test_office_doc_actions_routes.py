"""Integration tests for office doc actions (2026-09-09 方案 Item 1.7 / 1.2).

Covers the new HTTP endpoints end-to-end through the route functions:
- ``POST /doc/{id}/archive`` / ``POST /doc/{id}/restore``: soft-delete flips
  visibility in ``GET /documents`` (``include_archived`` query param).
- ``GET /doc/{id}/snapshots`` + ``POST /doc/{id}/snapshots/{sid}/restore``:
  snapshot list + revert with a seeded pre-edit snapshot.
- ``POST /pdf/read`` now persists a ``parsed`` row so PDFs show up in the
  document list like pptx/docx/xlsx.
- Unknown doc ids raise ``OfficeFileNotFoundError`` (mapped to 404 by the
  registered exception handler).
"""

from __future__ import annotations

from pathlib import Path
from typing import Set

import pytest

from backend.api.office_routes import (
    archive_document_endpoint,
    list_documents_endpoint,
    list_snapshots_endpoint,
    read_pdf_endpoint,
    restore_document_endpoint,
    restore_snapshot_endpoint,
)
from backend.data.database import get_database
from backend.office.errors import OfficeFileNotFoundError
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
    PdfReadRequest,
)
from backend.office.storage import (
    document_path,
    generate_document_dir,
    snapshot_pre_edit,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def _seed_docx(workspace: Path, *, content: bytes = b"seed docx bytes") -> str:
    """Create a managed .docx + its DB row; return the doc id."""
    from docx import Document

    doc_id = "doc-1"
    directory = generate_document_dir(workspace, OfficeDocType.WORD, doc_id)
    managed = directory / "report.docx"
    Document().save(managed)
    managed.write_bytes(content)
    now = 1_700_000_000_000
    save_summary = OfficeDocumentSummary(
        id=doc_id,
        workspace_path=str(workspace.resolve()),
        doc_type=OfficeDocType.WORD,
        original_filename=None,
        generated_filename="report.docx",
        status=OfficeDocStatus.PARSED,
        created_at=now,
        updated_at=now,
        metadata=OfficeDocumentMetadata(file_size_bytes=len(content)),
    )
    from backend.office.storage import save_document

    save_document(get_database().get_connection(), save_summary)
    return doc_id


def _list_ids(workspace: Path, *, include_archived: bool) -> Set[str]:
    resp = list_documents_endpoint(
        workspace_path=str(workspace), include_archived=include_archived
    )
    return {d.id for d in resp.documents}


# ──────────────────────────────────────────────────────────────────────
# archive / restore + include_archived
# ──────────────────────────────────────────────────────────────────────


def test_archive_hides_from_default_list_and_restore_brings_back(workspace: Path):
    doc_id = _seed_docx(workspace)

    resp = archive_document_endpoint(doc_id)
    assert resp.ok is True
    assert resp.summary.archived_at is not None

    assert doc_id not in _list_ids(workspace, include_archived=False)
    assert doc_id in _list_ids(workspace, include_archived=True)

    resp = restore_document_endpoint(doc_id)
    assert resp.ok is True
    assert resp.summary.archived_at is None
    assert doc_id in _list_ids(workspace, include_archived=False)


def test_archive_unknown_doc_raises_404_error(workspace: Path):
    with pytest.raises(OfficeFileNotFoundError):
        archive_document_endpoint("ghost-id")


# ──────────────────────────────────────────────────────────────────────
# snapshots list + restore
# ──────────────────────────────────────────────────────────────────────


def test_snapshot_list_and_restore_roundtrip(workspace: Path):
    doc_id = _seed_docx(workspace, content=b"version-1-bytes")
    conn = get_database().get_connection()
    from backend.office.storage import get_document

    summary = get_document(conn, doc_id)
    assert summary is not None

    # 模拟一次编辑前快照（tool_service.update 在真实流程里做的事）
    snapshot_pre_edit(summary, now_ms=1_700_000_002_000)
    # 编辑：主文件内容改变
    managed = document_path(summary)
    managed.write_bytes(b"version-2-bytes")

    listed = list_snapshots_endpoint(doc_id)
    assert listed.total == 1
    assert listed.snapshots[0].snapshot_id == "1700000002000-report.docx"
    assert listed.snapshots[0].size_bytes == len(b"version-1-bytes")

    resp = restore_snapshot_endpoint(doc_id, "1700000002000-report.docx")
    assert resp.ok is True
    assert managed.read_bytes() == b"version-1-bytes"
    # 恢复前状态（v2）也留了安全快照
    listed2 = list_snapshots_endpoint(doc_id)
    assert {s.snapshot_id for s in listed2.snapshots} >= {
        "1700000002000-report.docx",
    }
    assert listed2.total >= 1


def test_snapshot_restore_unknown_doc_raises(workspace: Path):
    with pytest.raises(OfficeFileNotFoundError):
        list_snapshots_endpoint("ghost-id")
    with pytest.raises(OfficeFileNotFoundError):
        restore_snapshot_endpoint("ghost-id", "1000-x.docx")


# ──────────────────────────────────────────────────────────────────────
# pdf read persists a row (Item 1.2)
# ──────────────────────────────────────────────────────────────────────


def test_pdf_read_persists_document_row(workspace: Path):
    import fitz

    doc_id = "pdf-1"
    directory = generate_document_dir(workspace, OfficeDocType.PDF, doc_id)
    managed = directory / "input.pdf"
    pdf = fitz.open()
    pdf.new_page()
    pdf.save(str(managed))
    pdf.close()

    result = read_pdf_endpoint(
        PdfReadRequest(workspace_path=str(workspace), file_path=str(managed))
    )
    row = get_database().get_connection().execute(
        "SELECT doc_type, status FROM office_documents WHERE id = ?", (doc_id,)
    ).fetchone()
    assert row is not None
    assert row["doc_type"] == "pdf"
    assert row["status"] == "parsed"
    assert result.summary.id == doc_id
    # 出现在默认列表里
    assert doc_id in _list_ids(workspace, include_archived=False)
