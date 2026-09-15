# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Unit tests for office_create / office_update self-check readback (plan 3.4).

覆盖（tractable subset：工具级生成/编辑自校验回读）：

- create word/excel/pptx → ``content["self_check"]`` ok=True 且计数正确
  （word 段落/表格/图片数 + 首段文本；excel sheet 名 + 行列数；ppt 页数 +
  首页标题）。
- excel 带 ``=`` 公式请求 → formula_cell_count；无公式请求 → 无该键。
- excel 多 sheet → 摘要 cap 5 张（sheet_count 仍为真实值）。
- reader 失败（monkeypatch reader 抛异常）→ self_check.ok=False 但
  result.success 仍 True（best-effort，镜像 snapshot 语义）。
- update file_path / doc_id 模式 → self_check 附带且计数反映编辑后状态；
  update reader 失败同样不阻断主结果。
- 受管 create（binding 委派路径）→ self_check 附带，且不回显 workspace 绝对路径。
- self_check 序列化后 < 1KB（字节预算），首段文本截断 ≤80 字符。
"""

from __future__ import annotations

import json
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
from backend.tools.office_create_tool import OfficeCreateTool
from backend.tools.office_update_tool import OfficeUpdateTool

pytestmark = pytest.mark.unit


def _create_tool(**policy_kwargs) -> OfficeCreateTool:
    return OfficeCreateTool(policy=ToolPolicy(**policy_kwargs))


def _update_tool(**policy_kwargs) -> OfficeUpdateTool:
    return OfficeUpdateTool(policy=ToolPolicy(**policy_kwargs))


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
    doc_type: OfficeDocType = OfficeDocType.WORD,
    generated_filename: Optional[str] = None,
) -> OfficeDocumentSummary:
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=doc_type,
        original_filename="上传.docx",
        generated_filename=generated_filename or f"{doc_id}.docx",
        status=OfficeDocStatus.PARSED,
        created_at=1_700_000_000_000,
        updated_at=1_700_000_000_000,
        metadata=OfficeDocumentMetadata(file_size_bytes=1024),
    )


# ── create：word ──────────────────────────────────────────────────────


def test_create_word_self_check_counts(tmp_path):
    """word 创建成功 → 回读段落/表格/图片计数 + 首段文本（≤80 字符）。"""
    result = _create_tool().execute(
        doc_type="word",
        output_dir=str(tmp_path),
        filename="report.docx",
        content={
            "title": "标题",
            "paragraphs": [{"text": "第一段"}, {"text": "第二段"}],
            "tables": [{"headers": ["A", "B"], "rows": [["1", "2"]]}],
        },
    )
    assert result.success is True
    self_check = result.content["self_check"]
    assert self_check["ok"] is True
    summary = self_check["summary"]
    # 标题以 Title 样式段落被提取（与 read_docx 语义一致）→ 3 段
    assert summary["paragraph_count"] == 3
    assert summary["table_count"] == 1
    assert summary["image_count"] == 0
    assert summary["first_paragraph"] == "标题"


def test_create_word_self_check_under_byte_budget(tmp_path):
    """首段超长 → 截断到 ≤80 字符，self_check 序列化后 < 1KB。"""
    long_text = "很" * 300
    result = _create_tool().execute(
        doc_type="word",
        output_dir=str(tmp_path),
        filename="long.docx",
        content={"title": "长文", "paragraphs": [{"text": long_text}]},
    )
    assert result.success is True
    self_check = result.content["self_check"]
    assert self_check["ok"] is True
    assert len(self_check["summary"]["first_paragraph"]) <= 80
    assert len(json.dumps(self_check, ensure_ascii=False).encode("utf-8")) < 1024


# ── create：excel ─────────────────────────────────────────────────────


def test_create_excel_self_check_sheets(tmp_path):
    """excel 创建成功 → sheet 名 + 行列数（max_row/max_col 语义）。"""
    result = _create_tool().execute(
        doc_type="excel",
        output_dir=str(tmp_path),
        filename="data.xlsx",
        content={
            "sheets": [
                {"name": "S1", "headers": ["A", "B"], "rows": [["1", "2"]]},
                {"name": "S2", "headers": ["H"], "rows": []},
            ]
        },
    )
    assert result.success is True
    self_check = result.content["self_check"]
    assert self_check["ok"] is True
    summary = self_check["summary"]
    assert summary["sheet_count"] == 2
    # 表头 + 1 数据行 → rows=2；两列 → cols=2；S2 只有表头 → rows=1/cols=1
    assert summary["sheets"][0] == {"name": "S1", "rows": 2, "cols": 2}
    assert summary["sheets"][1] == {"name": "S2", "rows": 1, "cols": 1}
    # 无公式请求 → 不出现 formula_cell_count 键
    assert "formula_cell_count" not in summary


def test_create_excel_self_check_formula_count(tmp_path):
    """请求含 '=' 公式字符串 → formula_cell_count 报告写入的公式数。"""
    result = _create_tool().execute(
        doc_type="excel",
        output_dir=str(tmp_path),
        filename="calc.xlsx",
        content={
            "sheets": [
                {
                    "name": "F",
                    "headers": ["A", "B"],
                    "rows": [["1", "=SUM(B2:B3)"], ["2", "=B2*10"]],
                }
            ]
        },
    )
    assert result.success is True
    summary = result.content["self_check"]["summary"]
    assert summary["formula_cell_count"] == 2


def test_create_excel_self_check_caps_at_five_sheets(tmp_path):
    """多 sheet → 摘要只列前 5 张，sheet_count 仍是真实总数。"""
    sheets = [
        {"name": f"S{i}", "headers": ["H"], "rows": [["v"]]} for i in range(1, 8)
    ]
    result = _create_tool().execute(
        doc_type="excel",
        output_dir=str(tmp_path),
        filename="many.xlsx",
        content={"sheets": sheets},
    )
    assert result.success is True
    summary = result.content["self_check"]["summary"]
    assert summary["sheet_count"] == 7
    assert len(summary["sheets"]) == 5
    assert summary["sheets"][4]["name"] == "S5"


# ── create：ppt ───────────────────────────────────────────────────────


def test_create_ppt_self_check(tmp_path):
    """ppt 创建成功 → 页数 + 首页标题。"""
    result = _create_tool().execute(
        doc_type="ppt",
        output_dir=str(tmp_path),
        filename="deck.pptx",
        content={
            "slides": [
                {"title": "标题", "bullets": ["点"]},
                {"title": "第二页", "bullets": []},
            ]
        },
    )
    assert result.success is True
    summary = result.content["self_check"]["summary"]
    assert summary["slide_count"] == 2
    assert summary["first_slide_title"] == "标题"


# ── create：reader 失败（best-effort 语义） ───────────────────────────


def test_create_reader_failure_keeps_result_success(tmp_path, monkeypatch):
    """回读失败 → self_check.ok=False，但主结果保持 success。"""

    def _boom(_path, **_kwargs):
        raise RuntimeError("reader exploded")

    monkeypatch.setattr("backend.tools.office_create_tool.read_docx", _boom)
    result = _create_tool().execute(
        doc_type="word",
        output_dir=str(tmp_path),
        filename="ok.docx",
        content={"title": "t", "paragraphs": [{"text": "x"}]},
    )
    # 文件已生成，主结果不因回读失败而翻转
    assert result.success is True
    assert (tmp_path / "ok.docx").exists()
    self_check = result.content["self_check"]
    assert self_check["ok"] is False
    # error 只带异常类名，不回显内部消息（防路径泄漏）
    assert self_check["error"] == "readback_failed: RuntimeError"


# ── create：受管路径（binding 委派） ──────────────────────────────────


def test_create_with_binding_self_check_no_path_leak(tmp_path, monkeypatch):
    """binding 委派创建成功 → self_check 附带；不回显 workspace 绝对路径。"""
    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-sc")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-sc", str(work), now_ms=1)
    monkeypatch.setattr("backend.tools.office_create_tool.get_database", lambda: db)

    token = set_tool_context(_ctx("sess-sc", binding.generation))
    try:
        result = _create_tool().execute(
            doc_type="word",
            output_dir=str(work),
            filename="天气.docx",
            content={"title": "天气", "paragraphs": [{"text": "晴"}]},
        )
    finally:
        reset_tool_context(token)

    assert result.success is True
    # 受管 handle trio + self_check（无 path 字段）
    assert result.content["document_id"]
    assert result.content["doc_type"] == "word"
    assert result.content["filename"] == "天气.docx"
    self_check = result.content["self_check"]
    assert self_check["ok"] is True
    assert self_check["summary"]["paragraph_count"] == 2
    full_text = json.dumps(result.content, ensure_ascii=False)
    assert str(work.resolve()) not in full_text


# ── update：file_path 模式 ────────────────────────────────────────────


def test_update_by_path_includes_self_check(tmp_path):
    """file_path 编辑成功 → self_check 反映编辑后的行数。"""
    created = _create_tool().execute(
        doc_type="excel",
        output_dir=str(tmp_path),
        filename="报表.xlsx",
        content={"sheets": [{"name": "数据", "headers": ["A"], "rows": [["1"]]}]},
    )
    assert created.success is True
    target = tmp_path / "报表.xlsx"

    result = _update_tool().execute(
        file_path=str(target),
        ops=[{"op": "append_rows", "sheet": "数据", "rows": [["2"]]}],
    )
    assert result.success is True
    self_check = result.content["self_check"]
    assert self_check["ok"] is True
    # 表头 + 原 1 行 + 新增 1 行 → 3
    assert self_check["summary"]["sheets"][0] == {"name": "数据", "rows": 3, "cols": 1}


def test_update_by_path_reader_failure_keeps_result_success(tmp_path, monkeypatch):
    """update 回读失败 → self_check.ok=False，主结果保持 success。"""
    from openpyxl import Workbook

    target = tmp_path / "简.xlsx"
    wb = Workbook()
    wb.active.title = "数据"
    wb.save(str(target))

    def _boom(_path, **_kwargs):
        raise RuntimeError("boom")

    # build_self_check 在 office_create_tool 命名空间解析 reader
    monkeypatch.setattr("backend.tools.office_create_tool.read_xlsx", _boom)

    result = _update_tool().execute(
        file_path=str(target),
        ops=[{"op": "append_rows", "sheet": "数据", "rows": [["a"]]}],
    )
    assert result.success is True
    self_check = result.content["self_check"]
    assert self_check["ok"] is False
    assert self_check["error"].startswith("readback_failed")


# ── update：doc_id 模式（受管） ───────────────────────────────────────


def test_update_by_doc_id_includes_self_check(tmp_path):
    """doc_id 编辑成功 → binding 内解析受管文档并回读编辑后状态。"""
    from docx import Document

    db = Database(db_path=str(tmp_path / "t.db"))
    db.init_db()
    conn = db.get_connection()
    _seed_session(conn, "sess-upd")
    work = tmp_path / "work"
    work.mkdir()
    binding = bind_session_workspace(conn, "sess-upd", str(work), now_ms=1)
    doc_file = work / "office" / "word" / "doc-sc"
    doc_file.mkdir(parents=True)
    d = Document()
    d.add_paragraph("旧文本")
    d.save(str(doc_file / "doc-sc.docx"))
    save_document(conn, _make_doc(doc_id="doc-sc", workspace_path=binding.workspace_path))

    with patch("backend.tools.office_update_tool.get_database", return_value=db):
        token = set_tool_context(_ctx("sess-upd", binding.generation))
        try:
            result = _update_tool().execute(
                doc_id="doc-sc",
                ops=[{"op": "replace_text", "find": "旧文本", "replace": "新文本"}],
            )
        finally:
            reset_tool_context(token)

    assert result.success is True
    assert result.content["document_id"] == "doc-sc"
    self_check = result.content["self_check"]
    assert self_check["ok"] is True
    summary = self_check["summary"]
    assert summary["paragraph_count"] == 1
    assert summary["first_paragraph"] == "新文本"
    # 不回显受管绝对路径
    assert str(work.resolve()) not in json.dumps(result.content, ensure_ascii=False)
