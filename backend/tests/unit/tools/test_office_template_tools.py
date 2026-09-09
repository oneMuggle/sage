# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Unit tests for :mod:`backend.tools.office_template_tool`.

覆盖（Office Parity Batch-1 item 1.1）：

- 形状声明：``office_analyze_word_template`` requires_tool_context=True +
  READ；``office_fill_word_template`` False + WRITE_LOCAL。
- analyze：file_path / doc_id 双模式列出 {{占位符}}（名称/类型/位置）；
  无 ctx → missing_tool_context；非 .docx 拒绝。
- fill：文本占位符原地填充（in_place=True）；output_path 另存（模板
  原文件不动）；images 支持工作区图片路径；未填充占位符回传；
  data 缺失 / 越界路径 / 已存在输出拒绝。
"""

from __future__ import annotations

import base64
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
from backend.tools.office_template_tool import (
    OfficeAnalyzeWordTemplateTool,
    OfficeFillWordTemplateTool,
)

pytestmark = pytest.mark.unit

docx = pytest.importorskip("docx")
pytest.importorskip("docxtpl")

# 1x1 PNG（透明像素），给 images 参数用
_PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


# ── Helpers ───────────────────────────────────────────────────────────


def _tool(cls, **policy_kwargs):
    return cls(policy=ToolPolicy(**policy_kwargs))


def _make_doc(
    *,
    doc_id: str,
    workspace_path: str,
) -> OfficeDocumentSummary:
    return OfficeDocumentSummary(
        id=doc_id,
        workspace_path=workspace_path,
        doc_type=OfficeDocType.WORD,
        original_filename="模板.docx",
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


def _make_template(path: Path, body: str = "Hello {{name}}!") -> Path:
    document = docx.Document()
    document.add_paragraph(body)
    document.save(str(path))
    return path


def _docx_text(path: Path) -> str:
    document = docx.Document(str(path))
    return "\n".join(p.text for p in document.paragraphs)


class _BoundWorkspace:
    """in-memory DB + 绑定工作区 + patch 过的 get_database。"""

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
        return patch("backend.tools.office_template_tool.get_database", return_value=self.db)

    def context(self):
        return _ctx("sess-1", self.binding.generation)


# ── 形状声明 ──────────────────────────────────────────────────────────


def test_analyze_requires_context_and_declares_read():
    tool = _tool(OfficeAnalyzeWordTemplateTool)
    assert tool.requires_tool_context is True
    assert tool.risk is RiskClass.READ


def test_fill_skips_context_and_declares_write_local():
    tool = _tool(OfficeFillWordTemplateTool)
    assert tool.requires_tool_context is False
    assert tool.risk is RiskClass.WRITE_LOCAL


def test_schemas_never_expose_workspace_path():
    for cls in (OfficeAnalyzeWordTemplateTool, OfficeFillWordTemplateTool):
        props = _tool(cls).schema.parameters["properties"]
        assert "workspace_path" not in props


# ── office_analyze_word_template ──────────────────────────────────────


def test_analyze_without_context_fails_closed():
    result = _tool(OfficeAnalyzeWordTemplateTool).execute(file_path="x.docx")
    assert result.success is False
    assert result.error == "missing_tool_context"


def test_analyze_by_file_path_lists_placeholders(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    template = _make_template(
        env.work / "tpl.docx", "Dear {{name}}, date {{日期}} in {{intro}} body."
    )
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeAnalyzeWordTemplateTool).execute(file_path=str(template))
        finally:
            reset_tool_context(token)

    assert result.success is True
    names = {p["name"] for p in result.content["placeholders"]}
    assert names == {"name", "日期", "intro"}
    by_name = {p["name"]: p for p in result.content["placeholders"]}
    assert by_name["name"]["type"] == "text"
    assert by_name["name"]["location"] == "body"
    # binding 绝对路径永不回显
    assert "workspace_path" not in result.content["summary"]


def test_analyze_by_doc_id_resolves_managed_document(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    managed_dir = env.work / "office" / "word" / "doc-t"
    managed_dir.mkdir(parents=True)
    _make_template(managed_dir / "doc-t.docx", "Hi {{name}}")
    save_document(conn=env.conn, summary=_make_doc(doc_id="doc-t", workspace_path=env.binding.workspace_path))

    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeAnalyzeWordTemplateTool).execute(doc_id="doc-t")
        finally:
            reset_tool_context(token)

    assert result.success is True
    # doc_id 模式不回显受管绝对路径，换成受管文件名
    assert result.content["file_path"] == "doc-t.docx"
    assert {p["name"] for p in result.content["placeholders"]} == {"name"}


def test_analyze_unknown_doc_id_is_document_not_found(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeAnalyzeWordTemplateTool).execute(doc_id="ghost")
        finally:
            reset_tool_context(token)
    assert result.success is False
    assert result.error == "document_not_found"


def test_analyze_rejects_non_docx_extension(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    pdf = env.work / "not-a-template.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeAnalyzeWordTemplateTool).execute(file_path=str(pdf))
        finally:
            reset_tool_context(token)
    assert result.success is False
    assert result.error.startswith("unsupported_file_type")


# ── office_fill_word_template ─────────────────────────────────────────


def test_fill_word_template_in_place(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    template = _make_template(env.work / "tpl.docx", "Hello {{name}}!")
    with env.patch():
        result = _tool(OfficeFillWordTemplateTool).execute(
            file_path=str(template), data={"name": "Sage"}
        )

    assert result.success is True
    assert result.content["in_place"] is True
    assert result.content["filled_count"] == 1
    text = _docx_text(template)
    assert "Sage" in text
    assert "{{name}}" not in text
    leftovers = [p.name for p in env.work.iterdir() if p.name.startswith(".fill-")]
    assert leftovers == []


def test_fill_word_template_to_output_path_keeps_template_intact(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    template = _make_template(env.work / "tpl.docx", "Hello {{name}}!")
    before = template.read_bytes()
    output = env.work / "filled.docx"
    with env.patch():
        result = _tool(OfficeFillWordTemplateTool).execute(
            file_path=str(template), data={"name": "Zhang"}, output_path=str(output)
        )

    assert result.success is True
    assert result.content["in_place"] is False
    assert "Zhang" in _docx_text(output)
    assert template.read_bytes() == before


def test_fill_word_template_reports_unfilled_placeholders(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    template = _make_template(env.work / "tpl.docx", "{{a}} and {{b}}")
    with env.patch():
        result = _tool(OfficeFillWordTemplateTool).execute(
            file_path=str(template), data={"a": "A"}
        )
    assert result.success is True
    assert result.content["unfilled_placeholders"] == ["b"]


def test_fill_word_template_by_doc_id(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    managed_dir = env.work / "office" / "word" / "doc-f"
    managed_dir.mkdir(parents=True)
    template = _make_template(managed_dir / "doc-f.docx", "Hi {{name}}")
    save_document(conn=env.conn, summary=_make_doc(doc_id="doc-f", workspace_path=env.binding.workspace_path))

    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeFillWordTemplateTool).execute(doc_id="doc-f", data={"name": "M3"})
        finally:
            reset_tool_context(token)

    assert result.success is True
    assert "M3" in _docx_text(template)


def test_fill_word_template_with_workspace_image(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    image = env.work / "logo.png"
    image.write_bytes(_PNG_1PX)
    template = _make_template(env.work / "tpl.docx", "Logo: {{logo}}")
    with env.patch():
        result = _tool(OfficeFillWordTemplateTool).execute(
            file_path=str(template),
            data={"ignored": "x"},
            images={"logo": str(image)},
        )

    assert result.success is True, result.error
    # 图片占位符被 InlineImage 消费，不再以 {{logo}} 文本残留
    assert "{{logo}}" not in _docx_text(template)


def test_fill_word_template_requires_data(tmp_path: Path):
    result = _tool(OfficeFillWordTemplateTool).execute(file_path="x.docx")
    assert result.success is False
    assert result.error == "data_required"


def test_fill_word_template_rejects_outside_policy_workspace(tmp_path: Path):
    env = _BoundWorkspace(tmp_path, workspace_root=str(tmp_path / "work"))
    outside = _make_template(tmp_path / "outside.docx")
    with env.patch():
        result = _tool(OfficeFillWordTemplateTool, **env.policy_kwargs).execute(
            file_path=str(outside), data={"name": "x"}
        )
    assert result.success is False
    assert result.error.startswith("path_outside_workspace")


def test_fill_word_template_rejects_existing_output(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    template = _make_template(env.work / "tpl.docx")
    occupied = _make_template(env.work / "occupied.docx")
    with env.patch():
        result = _tool(OfficeFillWordTemplateTool).execute(
            file_path=str(template), data={"name": "x"}, output_path=str(occupied)
        )
    assert result.success is False
    assert result.error.startswith("file_exists")
