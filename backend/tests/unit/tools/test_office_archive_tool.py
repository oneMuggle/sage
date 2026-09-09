# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Unit tests for :mod:`backend.tools.office_archive_tool`.

Sprint 1 PR-3 mirrors the soft-delete contract from the service layer
(``OfficeToolService.archive``) into the LLM tool loop, paired with
``office_restore``. Tests cover:

- ``requires_tool_context = True`` + WRITE_LOCAL risk declaration
- schema exposes only ``doc_id`` (no file_path mode — that's reserved
  for the destructive ``office_delete``)
- ``doc_id`` missing/blank → ``doc_id_required``
- archive success → content echoes doc_id + archived_at + was_archived
- archive unknown doc → ``document_not_found``
- archive without context → ``missing_tool_context``
- archive idempotent: re-archive preserves the original timestamp
  (matches ``tool_service.archive`` re-archive branch)
- archive preserves on-disk file (soft-delete contract)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from backend.data.database import Database
from backend.domain.tool_policy import ToolPolicy
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.session_workspace import bind_session_workspace
from backend.office.storage import save_document
from backend.tools.context import ToolExecutionContext, reset_tool_context, set_tool_context
from backend.tools.office_archive_tool import OfficeArchiveTool

pytestmark = pytest.mark.unit


# ── Helpers ───────────────────────────────────────────────────────────


def _tool(**policy_kwargs) -> OfficeArchiveTool:
    return OfficeArchiveTool(policy=ToolPolicy(**policy_kwargs))


def _make_doc(
    *,
    doc_id: str,
    workspace_path: str,
    archived_at: Optional[int] = None,
    doc_type: OfficeDocType = OfficeDocType.WORD,
) -> OfficeDocumentSummary:
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=doc_type,
        original_filename="上传.docx",
        generated_filename=f"{doc_id}.docx",
        status=OfficeDocStatus.GENERATED,
        created_at=1_700_000_000_000,
        updated_at=1_700_000_000_000,
        metadata=OfficeDocumentMetadata(file_size_bytes=1024),
        archived_at=archived_at,
    )


def _seed_session(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "t", 1, 1),
    )
    conn.commit()


def _ctx(session_id: str, binding_generation: int = 1) -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id=session_id,
        stream_id="stream-x",
        binding_generation=binding_generation,
        office_doc_scope=frozenset(),
    )


# ── Shape declarations ───────────────────────────────────────────────


def test_tool_declares_write_local_and_requires_context():
    tool = _tool()
    assert tool.requires_tool_context is True
    from backend.domain.risk import RiskClass

    assert tool.risk is RiskClass.WRITE_LOCAL


def test_schema_exposes_only_doc_id():
    props = _tool().schema.parameters["properties"]
    assert set(props) == {"doc_id"}
    # Confirm no file_path / workspace_path — archive is doc_id-only
    assert "file_path" not in props
    assert "workspace_path" not in props


def test_schema_marks_doc_id_as_required():
    required = _tool().schema.parameters.get("required", [])
    assert "doc_id" in required


def test_requires_doc_id():
    """No args → doc_id_required."""
    result = _tool().execute()
    assert result.success is False
    assert result.error == "doc_id_required"


def test_blank_doc_id_is_rejected():
    """Whitespace-only doc_id is treated as missing."""
    result = _tool().execute(doc_id="   ")
    assert result.success is False
    assert result.error == "doc_id_required"


def test_non_string_doc_id_is_rejected():
    """Type guard prevents None / int / dict from sneaking past the schema."""
    result = _tool().execute(doc_id=None)
    assert result.success is False
    assert result.error == "doc_id_required"


# ── doc_id 模式 ───────────────────────────────────────────────────────


def test_archive_by_doc_id_sets_archived_at(tmp_path: Path):
    """doc_id 模式 → 调用 service.archive → DB archived_at 列被填。"""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    managed_dir = work / "office" / "word" / "doc-a"
    managed_dir.mkdir(parents=True)
    (managed_dir / "doc-a.docx").write_bytes(b"placeholder")
    save_document(conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path))

    with patch("backend.tools.office_archive_tool.get_database", return_value=db):
        token = set_tool_context(_ctx("sess-1", binding.generation))
        try:
            result = _tool().execute(doc_id="doc-a")
        finally:
            reset_tool_context(token)

    assert result.success is True
    assert result.content["document_id"] == "doc-a"
    assert result.content["was_archived"] is True
    assert isinstance(result.content["archived_at"], int)

    # Row stays (soft-delete) but archived_at is now populated
    row = conn.execute(
        "SELECT archived_at FROM office_documents WHERE id='doc-a'"
    ).fetchone()
    assert row["archived_at"] == result.content["archived_at"]
    assert row["archived_at"] > 0


def test_archive_preserves_on_disk_file(tmp_path: Path):
    """Soft-delete contract: archived doc keeps its on-disk bytes."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    managed_dir = work / "office" / "word" / "doc-a"
    managed_dir.mkdir(parents=True)
    target = managed_dir / "doc-a.docx"
    target.write_bytes(b"placeholder bytes")

    save_document(conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path))

    with patch("backend.tools.office_archive_tool.get_database", return_value=db):
        token = set_tool_context(_ctx("sess-1", binding.generation))
        try:
            _tool().execute(doc_id="doc-a")
        finally:
            reset_tool_context(token)

    # Bytes intact + directory intact (archive ≠ delete)
    assert target.exists()
    assert target.read_bytes() == b"placeholder bytes"


def test_archive_unknown_doc_is_indistinguishable_not_found(tmp_path: Path):
    """Unknown doc_id returns document_not_found, mirroring the service layer."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)

    with patch("backend.tools.office_archive_tool.get_database", return_value=db):
        token = set_tool_context(_ctx("sess-1", binding.generation))
        try:
            result = _tool().execute(doc_id="ghost")
        finally:
            reset_tool_context(token)
    assert result.success is False
    assert result.error == "document_not_found"


def test_archive_without_context_fails_closed():
    """No tool context → missing_tool_context, never touches DB."""
    result = _tool().execute(doc_id="doc-a")
    assert result.success is False
    assert result.error == "missing_tool_context"


def test_archive_stale_binding_fails_closed(tmp_path: Path):
    """binding_generation mismatch → document_not_found (no path leak)."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path))

    with patch("backend.tools.office_archive_tool.get_database", return_value=db):
        token = set_tool_context(_ctx("sess-1", binding.generation + 99))
        try:
            result = _tool().execute(doc_id="doc-a")
        finally:
            reset_tool_context(token)
    assert result.success is False
    assert result.error == "document_not_found"


def test_archive_is_idempotent_preserves_original_timestamp(tmp_path: Path):
    """Re-archiving an already-archived doc returns the original ts,
    matching the ``service.archive`` idempotent branch (no ts bump)."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn,
        _make_doc(
            doc_id="doc-a",
            workspace_path=binding.workspace_path,
            archived_at=1_700_000_000_000,  # pinned archived_at
        ),
    )

    with patch("backend.tools.office_archive_tool.get_database", return_value=db):
        token = set_tool_context(_ctx("sess-1", binding.generation))
        try:
            result = _tool().execute(doc_id="doc-a")
        finally:
            reset_tool_context(token)

    assert result.success is True
    # Original timestamp preserved verbatim (no fresh time.time() bump)
    assert result.content["archived_at"] == 1_700_000_000_000
    assert result.content["was_archived"] is True

    row = conn.execute(
        "SELECT archived_at FROM office_documents WHERE id='doc-a'"
    ).fetchone()
    assert row["archived_at"] == 1_700_000_000_000
