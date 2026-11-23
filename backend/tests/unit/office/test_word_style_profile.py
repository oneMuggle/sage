"""Unit tests for Word named style presets (样式模板预设)."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

from backend.office.errors import OfficeGenerateError
from backend.office.models import OfficeWordGenerateRequest, WordFormatSpec
from backend.office.word import generate_docx
from backend.office.word_audit import audit_word_document
from backend.office.word_rulepack_builtin import builtin_rulepacks
from backend.office.word_style_presets import (
    list_style_presets,
    resolve_effective_format_spec,
)


def _generate(tmp_path: Path, **kwargs) -> Path:
    req = OfficeWordGenerateRequest(
        workspace_path="",
        filename="preset.docx",
        title="预设文档",
        **kwargs,
    )
    return generate_docx(req, output_dir=str(tmp_path))


def _rfonts(doc: Document, style_name: str):
    rPr = doc.styles[style_name].element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    assert rFonts is not None
    return rFonts


def test_list_style_presets_contains_builtin_ids() -> None:
    presets = list_style_presets()
    ids = {item["id"] for item in presets}
    assert {"default", "report", "gb9704-gongwen", "academic-thesis"} <= ids
    for item in presets:
        assert item["name"]
        assert item["description"]


def test_unknown_preset_rejected() -> None:
    with pytest.raises(OfficeGenerateError):
        resolve_effective_format_spec("no-such-preset", None)


def test_no_preset_and_no_spec_returns_none() -> None:
    assert resolve_effective_format_spec(None, None) is None


def test_gb9704_preset_values() -> None:
    spec = resolve_effective_format_spec("gb9704-gongwen", None)
    assert spec is not None
    assert spec.page.size == "A4"
    assert spec.page.orientation == "portrait"
    assert spec.page.margins_cm.top == pytest.approx(3.7)
    assert spec.page.margins_cm.bottom == pytest.approx(3.5)
    assert spec.body.font_family == "仿宋_GB2312"
    assert spec.body.font_size_pt == pytest.approx(16)
    assert spec.body.line_spacing_pt == pytest.approx(28)
    assert spec.headings is not None
    assert spec.headings["h1"].font_family == "黑体"
    assert spec.headings["h2"].font_family == "楷体_GB2312"
    assert spec.caption is not None
    assert spec.caption.font_family == "楷体_GB2312"
    assert spec.footer is not None
    assert spec.footer.page_number is True


def test_explicit_spec_overrides_preset_fields() -> None:
    explicit = WordFormatSpec(body={"font_size_pt": 12})
    merged = resolve_effective_format_spec("gb9704-gongwen", explicit)
    assert merged is not None
    assert merged.body.font_size_pt == pytest.approx(12)
    # 预设其余字段保留（逐字段深合并，None 不覆盖）
    assert merged.body.font_family == "仿宋_GB2312"
    assert merged.body.line_spacing_pt == pytest.approx(28)
    assert merged.page.margins_cm.top == pytest.approx(3.7)
    # headings 按级别合并：只覆盖 h1 字号，其他标题字体保留
    explicit_headings = WordFormatSpec(headings={"h1": {"font_size_pt": 18}})
    merged_headings = resolve_effective_format_spec(
        "gb9704-gongwen", explicit_headings
    )
    assert merged_headings.headings["h1"].font_size_pt == pytest.approx(18)
    assert merged_headings.headings["h1"].font_family == "黑体"
    assert merged_headings.headings["h2"].font_family == "楷体_GB2312"


def test_preset_generates_styled_document(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        paragraphs=[{"text": "第一章", "heading": "h1"}, {"text": "正文"}],
        format_spec_preset="report",
    )
    doc = Document(str(path))
    assert _rfonts(doc, "Normal").get(qn("w:eastAsia")) == "宋体"
    assert doc.styles["Normal"].font.size.pt == pytest.approx(12)
    assert _rfonts(doc, "Heading 1").get(qn("w:eastAsia")) == "黑体"
    assert doc.styles["Heading 1"].font.size.pt == pytest.approx(16)
    assert doc.sections[0].top_margin.cm == pytest.approx(2.54, abs=0.01)


def test_preset_plus_explicit_override_generates(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        paragraphs=[{"text": "正文"}],
        format_spec_preset="report",
        format_spec={"body": {"font_size_pt": 11}},
    )
    normal = Document(str(path)).styles["Normal"]
    assert normal.font.size.pt == pytest.approx(11)
    assert _rfonts(Document(str(path)), "Normal").get(qn("w:eastAsia")) == "宋体"


def test_gb9704_preset_passes_gb_rulepack_audit(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        paragraphs=[
            {"text": "一、总体要求", "heading": "h1"},
            {"text": "正文内容。"},
        ],
        format_spec_preset="gb9704-gongwen",
    )
    pack = next(
        pack for pack in builtin_rulepacks() if pack.id == "gb-t-9704-general"
    )
    result = audit_word_document(path, pack)
    assert result.ok, [issue.message for issue in result.issues]
