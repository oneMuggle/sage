# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Unit tests for office self-check history (round-3 Office parity, N4).

覆盖：

- ``record`` + ``list_for_document`` round-trip：newest first、summary dict
  JSON round-trip、``ok`` 布尔回读、按 doc_id 隔离、``limit`` 生效、
  ``summary=None`` 存 NULL 读回 None。
- ``record`` 缺表（fresh in-memory conn，未跑迁移）→ 吞掉异常不 raise。
- ``record`` summary 不可 JSON 序列化 → 同样吞掉（best-effort 契约）。
- ``conn=None`` → 懒解析全局 ``get_database()`` 连接落行。
- 迁移：真实 database.py init 路径（conftest autouse ``setup_test_db``）
  建表 + (doc_id, created_at) 索引；重复 ``init_db`` 幂等不报错。
- 写点：office_create（legacy output_dir 与 binding 委派两条路径）、
  office_archive / office_restore、office_update（file_path 模式）、
  apply_doc_update 各落一行对应 action 的历史。
"""

from __future__ import annotations

import sqlite3
from typing import Optional
from unittest.mock import patch

import pytest

from backend.data.database import Database
from backend.domain.tool_policy import ToolPolicy
from backend.office.apply_update import apply_doc_update
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.selfcheck_history import list_for_document, record
from backend.office.session_workspace import bind_session_workspace
from backend.office.storage import save_document
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.office_archive_tool import OfficeArchiveTool
from backend.tools.office_create_tool import OfficeCreateTool
from backend.tools.office_restore_tool import OfficeRestoreTool
from backend.tools.office_update_tool import OfficeUpdateTool

pytestmark = pytest.mark.unit


# ── Helpers（镜像 test_office_selfcheck / test_office_archive_tool） ──


def _seed_session(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "t", 1, 1),
    )
    conn.commit()


def _ctx(session_id: str, binding_generation: int) -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id=session_id,
        stream_id="stream-x",
        binding_generation=binding_generation,
        office_doc_scope=frozenset(),
    )


def _make_doc(
    *,
    doc_id: str,
    workspace_path: str,
    archived_at: Optional[int] = None,
) -> OfficeDocumentSummary:
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=OfficeDocType.WORD,
        original_filename="上传.docx",
        generated_filename=f"{doc_id}.docx",
        status=OfficeDocStatus.PARSED,
        created_at=1_700_000_000_000,
        updated_at=1_700_000_000_000,
        metadata=OfficeDocumentMetadata(file_size_bytes=1024),
        archived_at=archived_at,
    )


# ── record + list round-trip ─────────────────────────────────────────


def test_record_and_list_roundtrip_newest_first(setup_test_db):
    """记录 → 读回：newest first、summary dict round-trip、按 doc_id 隔离。"""
    conn = setup_test_db.get_connection()
    record("doc-1", "create", True, {"paragraph_count": 3}, conn=conn)
    record("doc-1", "update", False, {"error": "readback_failed: RuntimeError"}, conn=conn)
    record("doc-2", "archive", True, {"archived_count": 1}, conn=conn)

    items = list_for_document(conn, "doc-1")
    # newest first（同毫秒内按 id DESC 兜底排序，插入序即新→旧）
    assert [item["action"] for item in items] == ["update", "create"]
    newest, oldest = items[0], items[1]
    assert newest["ok"] is False
    assert newest["summary"] == {"error": "readback_failed: RuntimeError"}
    assert oldest["ok"] is True
    assert oldest["summary"] == {"paragraph_count": 3}
    for item in items:
        assert item["doc_id"] == "doc-1"
        assert isinstance(item["id"], int)
        assert isinstance(item["created_at"], int)

    # doc_id 隔离：doc-2 的行不串台
    doc2 = list_for_document(conn, "doc-2")
    assert [item["action"] for item in doc2] == ["archive"]


def test_list_respects_limit(setup_test_db):
    """limit 截断且仍保持 newest first。"""
    conn = setup_test_db.get_connection()
    for i in range(5):
        record("doc-limit", "update", True, {"i": i}, conn=conn)
    items = list_for_document(conn, "doc-limit", limit=3)
    assert len(items) == 3
    assert items[0]["summary"] == {"i": 4}
    assert items[1]["summary"] == {"i": 3}
    assert items[2]["summary"] == {"i": 2}


def test_record_none_summary_stores_null(setup_test_db):
    """summary=None → SQL NULL → 读回 None（ok=False 的失败回读形态）。"""
    conn = setup_test_db.get_connection()
    record("doc-null", "restore", False, None, conn=conn)
    items = list_for_document(conn, "doc-null")
    assert len(items) == 1
    assert items[0]["ok"] is False
    assert items[0]["summary"] is None


def test_record_without_conn_uses_global_db(setup_test_db):
    """conn=None → 懒解析 get_database() 连接，行落入全局测试库。"""
    record("doc-global", "create", True, {"sheet_count": 1})
    conn = setup_test_db.get_connection()
    items = list_for_document(conn, "doc-global")
    assert len(items) == 1
    assert items[0]["action"] == "create"
    assert items[0]["ok"] is True
    assert items[0]["summary"] == {"sheet_count": 1}


# ── best-effort 契约：绝不 raise ─────────────────────────────────────


def test_record_missing_table_is_swallowed():
    """fresh in-memory conn 未跑迁移 → 缺表 OperationalError 被吞掉。"""
    raw_conn = sqlite3.connect(":memory:")
    # 不迁移、不建表 —— record 必须静默降级，绝不打断调用方
    record("doc-x", "create", True, {"a": 1}, conn=raw_conn)
    record("doc-x", "snapshot_restore", False, None, conn=raw_conn)


def test_record_unserializable_summary_is_swallowed(setup_test_db):
    """summary 不可 JSON 序列化 → 吞掉异常，不落行、不 raise。"""
    conn = setup_test_db.get_connection()
    record("doc-y", "apply", True, {"bad": object()}, conn=conn)
    assert list_for_document(conn, "doc-y") == []


# ── 迁移（真实 database.py init 路径） ────────────────────────────────


def test_migration_creates_table_and_index(setup_test_db):
    """init_db 后 office_self_checks 表 + (doc_id, created_at) 索引存在。"""
    conn = setup_test_db.get_connection()
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='office_self_checks'"
    ).fetchone()
    assert table is not None
    index = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name='idx_office_self_checks_doc'"
    ).fetchone()
    assert index is not None


def test_migration_is_idempotent(setup_test_db):
    """对已初始化的库再次 init_db 不得报错（CREATE TABLE IF NOT EXISTS）。"""
    setup_test_db.init_db()
    conn = setup_test_db.get_connection()
    record("doc-z", "create", True, {"ok": 1}, conn=conn)
    assert len(list_for_document(conn, "doc-z")) == 1


# ── 写点：office_create（legacy output_dir 路径） ─────────────────────


def test_office_create_legacy_path_records_history(tmp_path, setup_test_db):
    """legacy output_dir 创建 → 落一行 action='create'（doc_id=""，纯审计）。"""
    result = OfficeCreateTool(policy=ToolPolicy()).execute(
        doc_type="word",
        output_dir=str(tmp_path),
        filename="history.docx",
        content={"title": "历史", "paragraphs": [{"text": "正文"}]},
    )
    assert result.success is True
    assert result.content["self_check"]["ok"] is True

    conn = setup_test_db.get_connection()
    items = list_for_document(conn, "")
    assert len(items) == 1
    assert items[0]["action"] == "create"
    assert items[0]["ok"] is True
    # 落库 summary 与结果里附带的 self_check.summary 一致（dict round-trip）
    assert items[0]["summary"] == result.content["self_check"]["summary"]


# ── 写点：office_create（binding 委派路径） ───────────────────────────


def test_office_create_binding_path_records_history(tmp_path, monkeypatch):
    """受管创建 → 历史行挂在真实 document_id 上，summary 可回读。"""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-hist-create")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-hist-create", str(work), now_ms=1)
    monkeypatch.setattr("backend.tools.office_create_tool.get_database", lambda: db)

    token = set_tool_context(_ctx("sess-hist-create", binding.generation))
    try:
        result = OfficeCreateTool(policy=ToolPolicy()).execute(
            doc_type="word",
            output_dir=str(work),
            filename="绑定.docx",
            content={"title": "绑定", "paragraphs": [{"text": "晴"}]},
        )
    finally:
        reset_tool_context(token)

    assert result.success is True
    doc_id = result.content["document_id"]
    items = list_for_document(conn, doc_id)
    assert len(items) == 1
    assert items[0]["action"] == "create"
    assert items[0]["ok"] is True
    assert items[0]["summary"]["paragraph_count"] == 2


# ── 写点：office_archive / office_restore ────────────────────────────


def test_office_archive_and_restore_record_history(tmp_path):
    """archive → action='archive'；restore → action='restore'（newest first）。"""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-hist-arch")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-hist-arch", str(work), now_ms=1)
    managed_dir = work / "office" / "word" / "doc-hist"
    managed_dir.mkdir(parents=True)
    (managed_dir / "doc-hist.docx").write_bytes(b"placeholder")
    save_document(conn, _make_doc(doc_id="doc-hist", workspace_path=binding.workspace_path))

    with patch(
        "backend.tools.office_archive_tool.get_database", return_value=db
    ), patch("backend.tools.office_restore_tool.get_database", return_value=db):
        token = set_tool_context(_ctx("sess-hist-arch", binding.generation))
        try:
            archived = OfficeArchiveTool(policy=ToolPolicy()).execute(doc_id="doc-hist")
            restored = OfficeRestoreTool(policy=ToolPolicy()).execute(doc_id="doc-hist")
        finally:
            reset_tool_context(token)

    assert archived.success is True
    assert restored.success is True
    items = list_for_document(conn, "doc-hist")
    assert [item["action"] for item in items] == ["restore", "archive"]
    assert all(item["ok"] is True for item in items)


# ── 写点：office_update（file_path 模式；dry_run 不落历史） ───────────


def test_office_update_by_path_records_history(tmp_path, setup_test_db):
    """file_path 编辑成功 → 落一行 action='update'（doc_id=""，纯审计）。"""
    created = OfficeCreateTool(policy=ToolPolicy()).execute(
        doc_type="excel",
        output_dir=str(tmp_path),
        filename="报表.xlsx",
        content={"sheets": [{"name": "数据", "headers": ["A"], "rows": [["1"]]}]},
    )
    assert created.success is True
    target = tmp_path / "报表.xlsx"

    result = OfficeUpdateTool(policy=ToolPolicy()).execute(
        file_path=str(target),
        ops=[{"op": "append_rows", "sheet": "数据", "rows": [["2"]]}],
    )
    assert result.success is True

    conn = setup_test_db.get_connection()
    # 同一测试库里 legacy create 也记了一行 "" → 两条，newest first 是 update
    items = list_for_document(conn, "")
    assert [item["action"] for item in items] == ["update", "create"]


def test_office_update_dry_run_records_no_history(tmp_path, setup_test_db):
    """dry_run=true 只读预览 → 不落任何历史行。"""
    created = OfficeCreateTool(policy=ToolPolicy()).execute(
        doc_type="excel",
        output_dir=str(tmp_path),
        filename="dry.xlsx",
        content={"sheets": [{"name": "S", "headers": ["A"], "rows": [["1"]]}]},
    )
    assert created.success is True
    target = tmp_path / "dry.xlsx"

    result = OfficeUpdateTool(policy=ToolPolicy()).execute(
        file_path=str(target),
        ops=[{"op": "append_rows", "sheet": "S", "rows": [["2"]]}],
        dry_run=True,
    )
    assert result.success is True
    assert result.content.get("dry_run") is True

    conn = setup_test_db.get_connection()
    items = list_for_document(conn, "")
    assert [item["action"] for item in items] == ["create"]  # 只有 create 那一行


# ── 写点：apply_doc_update（编辑预览对话框的「应用」） ────────────────


def test_apply_doc_update_records_history(tmp_path):
    """apply_doc_update 成功 → 落一行 action='apply' 挂在 doc.id 上。"""
    from docx import Document

    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    work = tmp_path / "work"
    doc_dir = work / "office" / "word" / "doc-apply"
    doc_dir.mkdir(parents=True)
    d = Document()
    d.add_paragraph("旧文本")
    d.save(str(doc_dir / "doc-apply.docx"))
    doc = _make_doc(doc_id="doc-apply", workspace_path=str(work))

    result = apply_doc_update(
        conn, doc, [{"op": "replace_text", "find": "旧文本", "replace": "新文本"}]
    )
    assert result.ok is True

    items = list_for_document(conn, "doc-apply")
    assert len(items) == 1
    assert items[0]["action"] == "apply"
    assert items[0]["ok"] is True
    assert items[0]["summary"]["paragraph_count"] == 1
