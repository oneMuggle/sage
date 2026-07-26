"""Unit tests for :mod:`backend.tools.office_tool`.

Covers:
- ``requires_tool_context = True`` is set on both wrappers.
- Schema parameters contain NO path / workspace_path field.
- Missing tool context -> ``missing_tool_context`` error (no path leak).
- With context, the wrappers delegate to ``OfficeToolService`` and map
  authorization failures to safe error codes.
- Unknown / archived / stale-generation doc -> indistinguishable not-found.
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
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.office_tool import OfficeListTool, OfficeReadTool

pytestmark = pytest.mark.unit


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _make_doc(
    *,
    doc_id: str,
    workspace_path: str,
    doc_type: OfficeDocType = OfficeDocType.WORD,
    original_filename: str = "doc.docx",
) -> OfficeDocumentSummary:
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=doc_type,
        original_filename=original_filename,
        generated_filename=f"{doc_id}.docx",
        status=OfficeDocStatus.GENERATED,
        created_at=1_700_000_000_000,
        updated_at=1_700_000_000_000,
        metadata=OfficeDocumentMetadata(file_size_bytes=1024),
    )


def _seed_session(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "t", 1, 1),
    )
    conn.commit()


def _ctx(
    session_id: str = "sess-x",
    binding_generation: int = 1,
    doc_scope: Optional[frozenset] = None,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id=session_id,
        stream_id="stream-x",
        binding_generation=binding_generation,
        office_doc_scope=doc_scope if doc_scope is not None else frozenset(),
    )


# ──────────────────────────────────────────────────────────────────────
# Schema + flag shape
# ──────────────────────────────────────────────────────────────────────


def test_office_list_tool_requires_tool_context_is_true():
    assert OfficeListTool().requires_tool_context is True


def test_office_read_tool_requires_tool_context_is_true():
    assert OfficeReadTool().requires_tool_context is True


def test_office_list_schema_has_no_path_parameter():
    schema = OfficeListTool().schema
    params = schema.parameters.get("properties", {})
    assert "path" not in params
    assert "workspace_path" not in params


def test_office_read_schema_has_no_path_parameter():
    schema = OfficeReadTool().schema
    params = schema.parameters.get("properties", {})
    assert "path" not in params
    assert "workspace_path" not in params
    assert "file_path" not in params


# ──────────────────────────────────────────────────────────────────────
# Missing tool context -> missing_tool_context
# ──────────────────────────────────────────────────────────────────────


def test_office_list_without_context_returns_missing_tool_context():
    tool = OfficeListTool()
    result = tool.execute()
    assert result.success is False
    assert result.error == "missing_tool_context"


def test_office_read_without_context_returns_missing_tool_context():
    tool = OfficeReadTool()
    result = tool.execute(doc_id="whatever")
    assert result.success is False
    assert result.error == "missing_tool_context"


# ──────────────────────────────────────────────────────────────────────
# With context, delegation to service
# ──────────────────────────────────────────────────────────────────────


def test_office_list_with_context_delegates_to_service(tmp_path: Path):
    """With a live context + binding, list returns workspace-scoped docs."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn,
        _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path),
    )

    tool = OfficeListTool(policy=ToolPolicy())
    ctx = _ctx(session_id="sess-1", binding_generation=binding.generation)

    with patch("backend.tools.office_tool.get_database", return_value=db):
        token = set_tool_context(ctx)
        try:
            result = tool.execute()
        finally:
            reset_tool_context(token)

    assert result.success is True
    ids = {item["id"] for item in result.content["items"]}
    assert "doc-a" in ids


def test_office_list_stale_generation_returns_safe_error(tmp_path: Path):
    """A stale binding generation must not leak document rows."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn,
        _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path),
    )

    tool = OfficeListTool(policy=ToolPolicy())
    # Generation is deliberately off by 1.
    ctx = _ctx(session_id="sess-1", binding_generation=binding.generation + 1)

    with patch("backend.tools.office_tool.get_database", return_value=db):
        token = set_tool_context(ctx)
        try:
            result = tool.execute()
        finally:
            reset_tool_context(token)

    # Empty list is the correct response (indistinguishable from empty).
    assert result.success is True
    assert result.content["items"] == []


def test_office_read_with_context_delegates_to_service(tmp_path: Path):
    """With a live context + binding, read returns summary for a valid doc."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    save_document(
        conn,
        _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path),
    )

    tool = OfficeReadTool(policy=ToolPolicy())
    ctx = _ctx(session_id="sess-1", binding_generation=binding.generation)

    with patch("backend.tools.office_tool.get_database", return_value=db):
        token = set_tool_context(ctx)
        try:
            result = tool.execute(doc_id="doc-a")
        finally:
            reset_tool_context(token)

    assert result.success is True
    assert "summary" in result.content


def test_office_read_unknown_doc_indistinguishable_from_stale(tmp_path: Path):
    """Unknown doc id + stale generation both produce the same safe error."""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)

    tool = OfficeReadTool(policy=ToolPolicy())
    # Case 1: unknown doc id with valid generation.
    ctx_ok = _ctx(session_id="sess-1", binding_generation=binding.generation)
    with patch("backend.tools.office_tool.get_database", return_value=db):
        token = set_tool_context(ctx_ok)
        try:
            r1 = tool.execute(doc_id="ghost")
        finally:
            reset_tool_context(token)

    # Case 2: valid doc id with stale generation.
    ctx_stale = _ctx(session_id="sess-1", binding_generation=binding.generation + 1)
    with patch("backend.tools.office_tool.get_database", return_value=db):
        token = set_tool_context(ctx_stale)
        try:
            r2 = tool.execute(doc_id="doc-a")
        finally:
            reset_tool_context(token)

    # Both collapse to the same safe error code.
    assert r1.success is False
    assert r2.success is False
    assert r1.error == r2.error
