"""Integration tests for GET /office/doc/{doc_id}/self-checks (round-3 N4).

The self-check history is the audit trail the write paths append via
``backend.office.selfcheck_history.record`` (best-effort INSERT into the
``office_self_checks`` table created by ``Database.init_db``). These tests
seed a managed document + three history rows and exercise the endpoint:

- rows come back newest first with the fixed contract keys
  ``{id, doc_id, action, ok, summary, created_at}`` (``ok`` a real bool,
  ``summary`` the deserialized readback dict);
- ``limit`` truncates (``total`` mirrors ``len(items)``);
- unknown doc ids raise ``OfficeFileNotFoundError`` (mapped to 404 by the
  registered OfficeError handler), same convention as the doc-actions
  endpoints in ``test_office_doc_actions_routes.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.api.office_routes import list_self_checks_endpoint
from backend.data.database import get_database
from backend.office.errors import OfficeFileNotFoundError
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.selfcheck_history import record
from backend.office.storage import generate_document_dir, save_document

pytestmark = pytest.mark.integration


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def _seed_doc(workspace: Path, doc_id: str = "doc-1") -> str:
    """Create a managed .docx + its DB row; return the doc id."""
    from docx import Document

    directory = generate_document_dir(workspace, OfficeDocType.WORD, doc_id)
    managed = directory / "report.docx"
    Document().save(managed)
    now = 1_700_000_000_000
    save_document(
        get_database().get_connection(),
        OfficeDocumentSummary(
            id=doc_id,
            workspace_path=str(workspace.resolve()),
            doc_type=OfficeDocType.WORD,
            original_filename=None,
            generated_filename="report.docx",
            status=OfficeDocStatus.PARSED,
            created_at=now,
            updated_at=now,
            metadata=OfficeDocumentMetadata(file_size_bytes=managed.stat().st_size),
        ),
    )
    return doc_id


def _seed_history(doc_id: str) -> None:
    """Append three self-check rows (create → update → failed apply)."""
    conn = get_database().get_connection()
    record(doc_id, "create", True, {"paragraph_count": 3}, conn=conn)
    record(doc_id, "update", True, {"paragraph_count": 4}, conn=conn)
    record(doc_id, "apply", False, {"error": "op rejected"}, conn=conn)


def test_self_checks_newest_first_with_contract_keys(workspace: Path):
    doc_id = _seed_doc(workspace)
    _seed_history(doc_id)

    payload = list_self_checks_endpoint(doc_id)

    assert payload["total"] == 3
    items = payload["items"]
    # 最新在前（同毫秒并列时按 id DESC，仍保持插入倒序）。
    assert [item["action"] for item in items] == ["apply", "update", "create"]
    for item in items:
        assert set(item.keys()) == {"id", "doc_id", "action", "ok", "summary", "created_at"}
        assert item["doc_id"] == doc_id
        assert isinstance(item["ok"], bool)
    assert items[0]["ok"] is False
    assert items[0]["summary"] == {"error": "op rejected"}
    assert items[1]["summary"] == {"paragraph_count": 4}
    assert items[2]["ok"] is True


def test_self_checks_limit_truncates_newest(workspace: Path):
    doc_id = _seed_doc(workspace)
    _seed_history(doc_id)

    payload = list_self_checks_endpoint(doc_id, limit=2)

    assert payload["total"] == 2  # total 镜像 len(items)（与 snapshots 端点一致）
    assert [item["action"] for item in payload["items"]] == ["apply", "update"]


def test_self_checks_limit_is_clamped_to_positive(workspace: Path):
    doc_id = _seed_doc(workspace)
    _seed_history(doc_id)

    payload = list_self_checks_endpoint(doc_id, limit=0)
    assert payload["total"] == 1
    assert payload["items"][0]["action"] == "apply"


def test_self_checks_empty_history_for_doc_without_rows(workspace: Path):
    doc_id = _seed_doc(workspace, "doc-quiet")

    payload = list_self_checks_endpoint(doc_id)
    assert payload == {"items": [], "total": 0}


def test_self_checks_unknown_doc_raises_404_error(workspace: Path):
    with pytest.raises(OfficeFileNotFoundError):
        list_self_checks_endpoint("ghost-id")
