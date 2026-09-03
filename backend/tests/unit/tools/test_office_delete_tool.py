# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Unit tests for :mod:`backend.tools.office_delete_tool`.

Covers:
- ``requires_tool_context = False`` + WRITE_LOCAL risk declaration
- doc_id 模式：删除受管目录 + DB 行；未知 id → document_not_found；
  缺 tool_context → missing_tool_context
- file_path 模式：删除单个 office 文件；非 office 扩展名 / 相对路径 /
  不存在文件被拒；越界（policy.workspace_root）被拒
"""

from __future__ import annotations

from pathlib import Path
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
from backend.tools.office_delete_tool import OfficeDeleteTool

pytestmark = pytest.mark.unit


def _tool(**policy_kwargs) -> OfficeDeleteTool:
    return OfficeDeleteTool(policy=ToolPolicy(**policy_kwargs))


def _make_doc(
    *,
    doc_id: str,
    workspace_path: str,
    doc_type: OfficeDocType = OfficeDocType.WORD,
) -> OfficeDocumentSummary:
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=doc_type,
        original_filename="上传.docx",
        generated_filename=f"{doc_id}.docx",
        status=OfficeDocStatus.PARSED,
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


def _ctx(session_id: str, binding_generation: int = 1) -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id=session_id,
        stream_id="stream-x",
        binding_generation=binding_generation,
        office_doc_scope=frozenset(),
    )


# ── 形状声明 ──────────────────────────────────────────────────────────


def test_tool_declares_write_local_and_no_context_requirement():
    tool = _tool()
    assert tool.requires_tool_context is False
    from backend.domain.risk import RiskClass

    assert tool.risk is RiskClass.WRITE_LOCAL


def test_schema_exposes_only_doc_id_and_file_path():
    props = _tool().schema.parameters["properties"]
    assert set(props) == {"doc_id", "file_path"}
    assert "workspace_path" not in props


def test_requires_doc_id_or_file_path():
    result = _tool().execute()
    assert result.success is False
    assert result.error == "doc_id_or_file_path_required"


# ── doc_id 模式 ───────────────────────────────────────────────────────


def test_delete_by_doc_id_removes_files_and_row(tmp_path: Path):
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

    with patch("backend.tools.office_delete_tool.get_database", return_value=db):
        token = set_tool_context(_ctx("sess-1", binding.generation))
        try:
            result = _tool().execute(doc_id="doc-a")
        finally:
            reset_tool_context(token)

    assert result.success is True
    assert result.content == {"document_id": "doc-a", "doc_type": "word"}
    assert not managed_dir.exists()
    assert (
        conn.execute("SELECT COUNT(*) c FROM office_documents WHERE id='doc-a'").fetchone()["c"]
        == 0
    )


def test_delete_unknown_doc_is_indistinguishable_not_found(tmp_path: Path):
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)

    with patch("backend.tools.office_delete_tool.get_database", return_value=db):
        token = set_tool_context(_ctx("sess-1", binding.generation))
        try:
            result = _tool().execute(doc_id="ghost")
        finally:
            reset_tool_context(token)
    assert result.success is False
    assert result.error == "document_not_found"


def test_delete_without_context_fails_closed():
    result = _tool().execute(doc_id="doc-a")
    assert result.success is False
    assert result.error == "missing_tool_context"


def test_delete_by_doc_id_keeps_row_when_rmtree_fails(tmp_path: Path):
    """受管目录删除失败（文件被占用）→ 行保留，返回 delete_failed，状态一致。"""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-1")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-1", str(work), now_ms=1)
    managed_dir = work / "office" / "word" / "doc-a"
    managed_dir.mkdir(parents=True)
    (managed_dir / "doc-a.docx").write_bytes(b"x")
    save_document(conn, _make_doc(doc_id="doc-a", workspace_path=binding.workspace_path))

    import shutil as _shutil

    def _boom(path):
        raise OSError("file locked")

    # py3.8 兼容：不用括号化多上下文 with（3.9+ 语法）
    with patch(
        "backend.tools.office_delete_tool.get_database", return_value=db
    ), patch.object(_shutil, "rmtree", side_effect=_boom):
        token = set_tool_context(_ctx("sess-1", binding.generation))
        try:
            result = _tool().execute(doc_id="doc-a")
        finally:
            reset_tool_context(token)

    assert result.success is False
    assert result.error == "delete_failed"
    # 行仍在（与磁盘文件保持一致），list 仍可见
    assert (
        conn.execute("SELECT COUNT(*) c FROM office_documents WHERE id='doc-a'").fetchone()["c"]
        == 1
    )


# ── file_path 模式 ────────────────────────────────────────────────────


def test_delete_by_absolute_path(tmp_path: Path):
    target = tmp_path / "报告.xlsx"
    target.write_bytes(b"placeholder")
    result = _tool().execute(file_path=str(target))
    assert result.success is True
    assert result.content["deleted"] is True
    assert not target.exists()


def test_delete_by_path_rejects_non_office_extension(tmp_path: Path):
    target = tmp_path / "重要.txt"
    target.write_text("keep me")
    result = _tool().execute(file_path=str(target))
    assert result.success is False
    assert result.error.startswith("unsupported_file_type")
    assert target.exists()


def test_delete_by_path_rejects_relative():
    result = _tool().execute(file_path="a.docx")
    assert result.success is False
    assert result.error.startswith("file_path_absolute_required")


def test_delete_by_path_missing_file(tmp_path: Path):
    result = _tool().execute(file_path=str(tmp_path / "ghost.docx"))
    assert result.success is False
    assert result.error == "file_not_found"


def test_delete_by_path_outside_workspace_root_rejected(tmp_path: Path):
    """hex 链（policy.workspace_root 绑定）下越界删除直接拒绝。"""
    target = tmp_path / "outside.docx"
    target.write_bytes(b"x")
    tool = OfficeDeleteTool(policy=ToolPolicy(workspace_root=str(tmp_path / "workspace")))
    result = tool.execute(file_path=str(target))
    assert result.success is False
    assert result.error.startswith("path_outside_workspace")
    assert target.exists()
