# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Unit tests for :mod:`backend.tools.office_pdf_tool`.

覆盖（Office Parity Batch-1 item 1.1）：

- 形状声明：读两件 ``requires_tool_context = True`` + READ；写两件
  ``requires_tool_context = False`` + WRITE_LOCAL；schema 暴露
  workspace_path。
- ``office_read_pdf``：file_path 模式按页返回文本；doc_id 模式经 binding
  解析受管文档；输出剥除 summary.workspace_path；无 ctx →
  missing_tool_context；未知 doc_id → document_not_found；越界路径拒绝。
- ``office_read_pdf_form``：AcroForm 字段名/类型可见。
- ``office_generate_pdf``：工作区内落盘成功；已存在目标拒绝；缺
  paragraphs 拒绝；非法 page_size / 扩展名拒绝；越界写入拒绝。
- ``office_fill_pdf_form``：原地填充（in_place=True，字段值落盘）+
  output_path 另存（原文件不动）；data 缺失拒绝。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from backend.data.database import Database
from backend.domain.risk import RiskClass
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
from backend.tools.office_pdf_tool import (
    OfficeFillPdfFormTool,
    OfficeGeneratePdfTool,
    OfficeReadPdfFormTool,
    OfficeReadPdfTool,
)

pytestmark = pytest.mark.unit

pymupdf = pytest.importorskip("pymupdf")


# ── Helpers ───────────────────────────────────────────────────────────


def _tool(cls, **policy_kwargs):
    return cls(policy=ToolPolicy(**policy_kwargs))


def _make_doc(
    *,
    doc_id: str,
    workspace_path: str,
    doc_type: OfficeDocType = OfficeDocType.PDF,
) -> OfficeDocumentSummary:
    ext = doc_type.value
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=doc_type,
        original_filename=f"上传.{ext}",
        generated_filename=f"{doc_id}.{ext}",
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


def _make_plain_pdf(path: Path, text: str = "hello pdf") -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()
    return path


def _make_form_pdf(path: Path, field_name: str = "name") -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    widget = pymupdf.Widget()
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.field_name = field_name
    widget.rect = pymupdf.Rect(50, 50, 250, 80)
    page.add_widget(widget)
    doc.save(str(path))
    doc.close()
    return path


def _read_first_widget_value(pdf_path: Path, field_name: str):
    doc = pymupdf.open(str(pdf_path))
    try:
        for page in doc:
            for widget in page.widgets():
                if widget.field_name == field_name:
                    return widget.field_value
    finally:
        doc.close()
    return None


class _BoundWorkspace:
    """一台测试机：in-memory DB + 绑定工作区 + patch 过的 get_database。"""

    def __init__(self, tmp_path: Path, workspace_root: Optional[str] = None):
        self.db = Database(db_path=str(tmp_path / "t.db"))
        self.db.init_db()
        self.conn = self.db.get_connection()
        _seed_session(self.conn, "sess-1")
        self.work = tmp_path / "work"
        self.work.mkdir()
        self.binding = bind_session_workspace(self.conn, "sess-1", str(self.work), now_ms=1)
        self.policy_kwargs = {}
        if workspace_root is not None:
            self.policy_kwargs["workspace_root"] = workspace_root

    def patch(self):
        return patch("backend.tools.office_pdf_tool.get_database", return_value=self.db)

    def context(self):
        return _ctx("sess-1", self.binding.generation)


# ── 形状声明 ──────────────────────────────────────────────────────────


def test_read_tools_require_context_and_declare_read():
    for cls in (OfficeReadPdfTool, OfficeReadPdfFormTool):
        tool = _tool(cls)
        assert tool.requires_tool_context is True
        assert tool.risk is RiskClass.READ


def test_write_tools_skip_context_and_declare_write_local():
    for cls in (OfficeGeneratePdfTool, OfficeFillPdfFormTool):
        tool = _tool(cls)
        assert tool.requires_tool_context is False
        assert tool.risk is RiskClass.WRITE_LOCAL


def test_schemas_never_expose_workspace_path():
    for cls in (
        OfficeReadPdfTool,
        OfficeGeneratePdfTool,
        OfficeReadPdfFormTool,
        OfficeFillPdfFormTool,
    ):
        props = _tool(cls).schema.parameters["properties"]
        assert "workspace_path" not in props


# ── office_read_pdf ───────────────────────────────────────────────────


def test_read_pdf_without_context_fails_closed():
    result = _tool(OfficeReadPdfTool).execute(file_path="x.pdf")
    assert result.success is False
    assert result.error == "missing_tool_context"


def test_read_pdf_by_file_path_returns_page_text(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    pdf = _make_plain_pdf(env.work / "report.pdf", "hello parity")
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeReadPdfTool).execute(file_path=str(pdf))
        finally:
            reset_tool_context(token)

    assert result.success is True
    assert "hello parity" in result.content["pages"][0]["text"]
    # binding 绝对路径永不回显
    assert "workspace_path" not in result.content["summary"]


def test_read_pdf_by_doc_id_resolves_managed_document(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    managed_dir = env.work / "office" / "pdf" / "doc-p"
    managed_dir.mkdir(parents=True)
    _make_plain_pdf(managed_dir / "doc-p.pdf", "managed body")
    save_document(conn=env.conn, summary=_make_doc(doc_id="doc-p", workspace_path=env.binding.workspace_path))

    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeReadPdfTool).execute(doc_id="doc-p")
        finally:
            reset_tool_context(token)

    assert result.success is True
    assert "managed body" in result.content["pages"][0]["text"]
    assert result.content["summary"]["id"] == "doc-p"
    assert "workspace_path" not in result.content["summary"]


def test_read_pdf_unknown_doc_id_is_document_not_found(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeReadPdfTool).execute(doc_id="ghost")
        finally:
            reset_tool_context(token)
    assert result.success is False
    assert result.error == "document_not_found"


def test_read_pdf_rejects_path_outside_policy_workspace(tmp_path: Path):
    env = _BoundWorkspace(tmp_path, workspace_root=str(tmp_path / "work"))
    outside = tmp_path / "outside.pdf"
    _make_plain_pdf(outside)
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeReadPdfTool, **env.policy_kwargs).execute(file_path=str(outside))
        finally:
            reset_tool_context(token)
    assert result.success is False
    assert result.error.startswith("path_outside_workspace")


def test_read_pdf_requires_doc_id_or_file_path(tmp_path: Path):
    """有上下文但两个定位参数都缺 → doc_id_or_file_path_required。"""
    env = _BoundWorkspace(tmp_path)
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeReadPdfTool).execute()
        finally:
            reset_tool_context(token)
    assert result.success is False
    assert result.error == "doc_id_or_file_path_required"


def test_read_pdf_rejects_relative_path(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeReadPdfTool).execute(file_path="relative.pdf")
        finally:
            reset_tool_context(token)
    assert result.success is False
    assert result.error.startswith("file_path_absolute_required")


# ── office_read_pdf_form ──────────────────────────────────────────────


def test_read_pdf_form_without_context_fails_closed():
    result = _tool(OfficeReadPdfFormTool).execute(doc_id="x")
    assert result.success is False
    assert result.error == "missing_tool_context"


def test_read_pdf_form_lists_fields(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    pdf = _make_form_pdf(env.work / "form.pdf")
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeReadPdfFormTool).execute(file_path=str(pdf))
        finally:
            reset_tool_context(token)

    assert result.success is True
    names = [f["name"] for f in result.content["fields"]]
    assert names == ["name"]
    assert result.content["fields"][0]["type"] == "text"


# ── office_generate_pdf ───────────────────────────────────────────────


def test_generate_pdf_writes_file_inside_workspace(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    target = env.work / "generated.pdf"
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeGeneratePdfTool).execute(
                output_path=str(target),
                title="Quarterly",
                paragraphs=["line one", "line two"],
                page_size="a4",
            )
        finally:
            reset_tool_context(token)

    assert result.success is True
    assert target.exists()
    assert target.stat().st_size > 0
    assert result.content["filename"] == "generated.pdf"
    assert result.content["page_count"] == 1
    assert result.content["bytes"] == target.stat().st_size
    # 生成物可被 office_read_pdf 读回（round-trip）
    with env.patch():
        token = set_tool_context(env.context())
        try:
            read_back = _tool(OfficeReadPdfTool).execute(file_path=str(target))
        finally:
            reset_tool_context(token)
    assert read_back.success is True
    assert "line one" in read_back.content["pages"][0]["text"]


def test_generate_pdf_rejects_existing_target(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    target = _make_plain_pdf(env.work / "exists.pdf")
    with env.patch():
        result = _tool(OfficeGeneratePdfTool).execute(
            output_path=str(target), paragraphs=["x"]
        )
    assert result.success is False
    assert result.error.startswith("file_exists")


def test_generate_pdf_rejects_outside_policy_workspace(tmp_path: Path):
    env = _BoundWorkspace(tmp_path, workspace_root=str(tmp_path / "work"))
    with env.patch():
        result = _tool(OfficeGeneratePdfTool, **env.policy_kwargs).execute(
            output_path=str(tmp_path / "evil.pdf"), paragraphs=["x"]
        )
    assert result.success is False
    assert result.error.startswith("path_outside_workspace")


def test_generate_pdf_rejects_relative_path(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    with env.patch():
        result = _tool(OfficeGeneratePdfTool).execute(
            output_path="relative.pdf", paragraphs=["x"]
        )
    assert result.success is False
    assert result.error.startswith("output_path_absolute_required")


def test_generate_pdf_requires_paragraphs(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    with env.patch():
        result = _tool(OfficeGeneratePdfTool).execute(output_path=str(env.work / "a.pdf"))
    assert result.success is False
    assert result.error == "paragraphs_required"


def test_generate_pdf_rejects_bad_page_size_and_extension(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    with env.patch():
        bad_size = _tool(OfficeGeneratePdfTool).execute(
            output_path=str(env.work / "a.pdf"), paragraphs=["x"], page_size="a3"
        )
        bad_ext = _tool(OfficeGeneratePdfTool).execute(
            output_path=str(env.work / "a.docx"), paragraphs=["x"]
        )
    assert bad_size.success is False
    assert bad_size.error.startswith("unsupported_page_size")
    assert bad_ext.success is False
    assert bad_ext.error.startswith("unsupported_file_type")


# ── office_fill_pdf_form ──────────────────────────────────────────────


def test_fill_pdf_form_in_place(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    pdf = _make_form_pdf(env.work / "form.pdf")
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeFillPdfFormTool).execute(
                file_path=str(pdf), data={"name": "Sage"}
            )
        finally:
            reset_tool_context(token)

    assert result.success is True
    assert result.content["in_place"] is True
    assert result.content["filled_count"] == 1
    assert _read_first_widget_value(pdf, "name") == "Sage"
    # 原地填充不产生残留临时文件
    leftovers = [p.name for p in env.work.iterdir() if p.name.startswith(".fill-")]
    assert leftovers == []


def test_fill_pdf_form_to_output_path_keeps_template_intact(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    pdf = _make_form_pdf(env.work / "form.pdf")
    before = pdf.read_bytes()
    output = env.work / "filled.pdf"
    with env.patch():
        result = _tool(OfficeFillPdfFormTool).execute(
            file_path=str(pdf), data={"name": "Zhang"}, output_path=str(output)
        )

    assert result.success is True
    assert result.content["in_place"] is False
    assert output.exists()
    assert _read_first_widget_value(output, "name") == "Zhang"
    assert pdf.read_bytes() == before


def test_fill_pdf_form_by_doc_id(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    managed_dir = env.work / "office" / "pdf" / "doc-f"
    managed_dir.mkdir(parents=True)
    pdf = _make_form_pdf(managed_dir / "doc-f.pdf", field_name="city")
    save_document(conn=env.conn, summary=_make_doc(doc_id="doc-f", workspace_path=env.binding.workspace_path))

    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeFillPdfFormTool).execute(doc_id="doc-f", data={"city": "Hangzhou"})
        finally:
            reset_tool_context(token)

    assert result.success is True
    assert result.content["in_place"] is True
    assert _read_first_widget_value(pdf, "city") == "Hangzhou"


def test_fill_pdf_form_requires_data(tmp_path: Path):
    result = _tool(OfficeFillPdfFormTool).execute(file_path="x.pdf")
    assert result.success is False
    assert result.error == "data_required"


def test_fill_pdf_form_rejects_outside_policy_workspace(tmp_path: Path):
    env = _BoundWorkspace(tmp_path, workspace_root=str(tmp_path / "work"))
    outside = _make_form_pdf(tmp_path / "outside.pdf")
    with env.patch():
        result = _tool(OfficeFillPdfFormTool, **env.policy_kwargs).execute(
            file_path=str(outside), data={"name": "x"}
        )
    assert result.success is False
    assert result.error.startswith("path_outside_workspace")


def test_fill_pdf_form_rejects_existing_output(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    pdf = _make_form_pdf(env.work / "form.pdf")
    occupied = _make_plain_pdf(env.work / "occupied.pdf")
    with env.patch():
        result = _tool(OfficeFillPdfFormTool).execute(
            file_path=str(pdf), data={"name": "x"}, output_path=str(occupied)
        )
    assert result.success is False
    assert result.error.startswith("file_exists")
