# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Unit tests for :mod:`backend.tools.office_ppt_template_tool`.

覆盖（PPT 模板两件套接入 LLM 工具面）：

- 形状声明：``office_analyze_ppt_template`` requires_tool_context=True +
  READ；``office_fill_ppt_template`` False + WRITE_LOCAL。
- analyze：file_path / doc_id 双模式枚举版式与占位符；无 ctx →
  missing_tool_context；非 .pptx 拒绝。
- fill：另存新文件（模板原件不动）；fills/output_filename 校验；
  页号/占位符 idx 越界 all-or-nothing；已存在输出拒绝；越界路径拒绝。
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
from backend.tools.office_ppt_template_tool import (
    OfficeAnalyzePptTemplateTool,
    OfficeFillPptTemplateTool,
)

pytestmark = pytest.mark.unit

pptx_mod = pytest.importorskip("pptx")


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
        doc_type=OfficeDocType.PPT,
        original_filename="模板.pptx",
        generated_filename=f"{doc_id}.pptx",
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


def _make_template(path: Path, title: str = "占位标题") -> Path:
    """单页模板：Title and Content 版式（占位符 idx 0 标题 / 1 正文）。"""
    presentation = pptx_mod.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = title
    path.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(str(path))
    return path


def _slide_title(path: Path) -> str:
    presentation = pptx_mod.Presentation(str(path))
    return presentation.slides[0].shapes.title.text


class _BoundWorkspace:
    """in-memory DB + 绑定工作区 + patch 过的 get_database。

    共享解析助手住在 office_template_tool（get_database 在其模块命名空间被
    调用），patch 目标随之指过去。
    """

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
    tool = _tool(OfficeAnalyzePptTemplateTool)
    assert tool.requires_tool_context is True
    assert tool.risk is RiskClass.READ


def test_fill_skips_context_and_declares_write_local():
    tool = _tool(OfficeFillPptTemplateTool)
    assert tool.requires_tool_context is False
    assert tool.risk is RiskClass.WRITE_LOCAL


def test_schemas_never_expose_workspace_path():
    for cls in (OfficeAnalyzePptTemplateTool, OfficeFillPptTemplateTool):
        props = _tool(cls).schema.parameters["properties"]
        assert "workspace_path" not in props


# ── office_analyze_ppt_template ───────────────────────────────────────


def test_analyze_without_context_fails_closed():
    result = _tool(OfficeAnalyzePptTemplateTool).execute(file_path="x.pptx")
    assert result.success is False
    assert result.error == "missing_tool_context"


def test_analyze_by_file_path_lists_layouts(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    template = _make_template(env.work / "tpl.pptx")
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeAnalyzePptTemplateTool).execute(file_path=str(template))
        finally:
            reset_tool_context(token)

    assert result.success is True
    layouts = result.content["layouts"]
    assert layouts, "默认模板应有母版版式"
    first = layouts[0]
    assert {"name", "placeholders"} <= set(first)
    assert all({"idx", "type", "is_title"} <= set(p) for p in first["placeholders"])
    assert "workspace_path" not in result.content


def test_analyze_by_doc_id_resolves_managed_document(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    managed_dir = env.work / "office" / "ppt" / "doc-t"
    managed_dir.mkdir(parents=True)
    _make_template(managed_dir / "doc-t.pptx")
    save_document(
        conn=env.conn,
        summary=_make_doc(doc_id="doc-t", workspace_path=env.binding.workspace_path),
    )

    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeAnalyzePptTemplateTool).execute(doc_id="doc-t")
        finally:
            reset_tool_context(token)

    assert result.success is True
    # doc_id 模式不回显受管绝对路径，换成受管文件名
    assert result.content["file_path"] == "doc-t.pptx"


def test_analyze_unknown_doc_id_is_document_not_found(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeAnalyzePptTemplateTool).execute(doc_id="ghost")
        finally:
            reset_tool_context(token)
    assert result.success is False
    assert result.error == "document_not_found"


def test_analyze_rejects_non_pptx_extension(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    doc = env.work / "not-a-template.docx"
    doc.write_bytes(b"PK\x03\x04fake")
    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeAnalyzePptTemplateTool).execute(file_path=str(doc))
        finally:
            reset_tool_context(token)
    assert result.success is False
    assert result.error.startswith("unsupported_file_type")


# ── office_fill_ppt_template ──────────────────────────────────────────


def test_fill_saves_new_file_and_keeps_template_intact(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    template = _make_template(env.work / "tpl.pptx", title="占位标题")
    with env.patch():
        result = _tool(OfficeFillPptTemplateTool).execute(
            file_path=str(template),
            fills=[{"slide_number": 1, "placeholder_idx": 0, "text": "季度复盘"}],
            output_filename="deck",
        )

    assert result.success is True, result.error
    assert result.content["filled_count"] == 1
    out = env.work / "deck.pptx"
    assert Path(result.content["path"]) == out
    assert _slide_title(out) == "季度复盘"
    # 模板原件绝不修改
    assert _slide_title(template) == "占位标题"


def test_fill_by_doc_id(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    managed_dir = env.work / "office" / "ppt" / "doc-f"
    managed_dir.mkdir(parents=True)
    _make_template(managed_dir / "doc-f.pptx")
    save_document(
        conn=env.conn,
        summary=_make_doc(doc_id="doc-f", workspace_path=env.binding.workspace_path),
    )

    with env.patch():
        token = set_tool_context(env.context())
        try:
            result = _tool(OfficeFillPptTemplateTool).execute(
                doc_id="doc-f",
                fills=[{"slide_number": 1, "placeholder_idx": 0, "text": "标题"}],
                output_filename="filled",
            )
        finally:
            reset_tool_context(token)

    assert result.success is True, result.error
    assert _slide_title(managed_dir / "filled.pptx") == "标题"


def test_fill_requires_fills(tmp_path: Path):
    result = _tool(OfficeFillPptTemplateTool).execute(
        file_path="x.pptx", output_filename="out"
    )
    assert result.success is False
    assert result.error.startswith("fills_required")


def test_fill_requires_output_filename(tmp_path: Path):
    result = _tool(OfficeFillPptTemplateTool).execute(
        file_path="x.pptx", fills=[{"slide_number": 1, "placeholder_idx": 0, "text": "a"}]
    )
    assert result.success is False
    assert result.error.startswith("output_filename_required")


def test_fill_rejects_bad_fill_shape(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    template = _make_template(env.work / "tpl.pptx")
    with env.patch():
        result = _tool(OfficeFillPptTemplateTool).execute(
            file_path=str(template),
            fills=[{"slide_number": "one", "placeholder_idx": 0, "text": "a"}],
            output_filename="out",
        )
    assert result.success is False
    assert result.error.startswith("fills_invalid")


def test_fill_all_or_nothing_on_bad_slide_number(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    template = _make_template(env.work / "tpl.pptx")
    with env.patch():
        result = _tool(OfficeFillPptTemplateTool).execute(
            file_path=str(template),
            fills=[
                {"slide_number": 1, "placeholder_idx": 0, "text": "ok"},
                {"slide_number": 9, "placeholder_idx": 0, "text": "越界"},
            ],
            output_filename="out",
        )
    assert result.success is False
    assert result.error.startswith("fill_failed")
    assert not (env.work / "out.pptx").exists()


def test_fill_rejects_existing_output(tmp_path: Path):
    env = _BoundWorkspace(tmp_path)
    template = _make_template(env.work / "tpl.pptx")
    _make_template(env.work / "out.pptx")
    with env.patch():
        result = _tool(OfficeFillPptTemplateTool).execute(
            file_path=str(template),
            fills=[{"slide_number": 1, "placeholder_idx": 0, "text": "a"}],
            output_filename="out",
        )
    assert result.success is False
    assert result.error.startswith("fill_failed")


def test_fill_rejects_outside_policy_workspace(tmp_path: Path):
    env = _BoundWorkspace(tmp_path, workspace_root=str(tmp_path / "work"))
    outside = _make_template(tmp_path / "outside.pptx")
    with env.patch():
        result = _tool(OfficeFillPptTemplateTool, **env.policy_kwargs).execute(
            file_path=str(outside),
            fills=[{"slide_number": 1, "placeholder_idx": 0, "text": "a"}],
            output_filename="out",
        )
    assert result.success is False
    assert result.error.startswith("path_outside_workspace")
