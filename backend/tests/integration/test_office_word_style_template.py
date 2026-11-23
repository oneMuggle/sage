"""Integration tests for the Word style-profile (样式画像) engine.

Covers the style-template roadmap:

1. per-style fonts — body/heading eastAsia + ascii fonts land on the style
   definitions (and linked character styles) instead of the single global
   font;
2. exact line spacing — ``line_spacing_pt`` writes ``w:lineRule="exact"``;
3. caption style — font/size/bold/align override the historical 9pt center;
4. table text style — cell run font/size and header bold;
5. reference document — a ``.docx`` template supplies the style base
   without carrying its body text over.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from backend.office.models import OfficeWordGenerateRequest
from backend.office.word import generate_docx

_PNG_PIXEL = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 2, 2))
_PNG_PIXEL.clear_with(200)


def _generate(tmp_path: Path, **kwargs) -> Path:
    req = OfficeWordGenerateRequest(
        workspace_path="",
        filename="style.docx",
        title="测试文档",
        **kwargs,
    )
    return generate_docx(req, output_dir=str(tmp_path))


def _style_rfonts(doc: Document, style_name: str):
    rPr = doc.styles[style_name].element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    assert rFonts is not None
    return rFonts


# ──────────────────────────────────────────────────────────────────────
# Per-style fonts / exact line spacing
# ──────────────────────────────────────────────────────────────────────


def test_body_and_heading_fonts_applied(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        paragraphs=[{"text": "第一章", "heading": "h1"}, {"text": "正文"}],
        format_spec={
            "body": {"font_family": "仿宋_GB2312", "ascii_font": "Times New Roman"},
            "headings": {"h1": {"font_family": "黑体", "ascii_font": "Arial"}},
        },
    )
    doc = Document(str(path))
    normal_fonts = _style_rfonts(doc, "Normal")
    assert normal_fonts.get(qn("w:eastAsia")) == "仿宋_GB2312"
    assert normal_fonts.get(qn("w:ascii")) == "Times New Roman"
    h1_fonts = _style_rfonts(doc, "Heading 1")
    assert h1_fonts.get(qn("w:eastAsia")) == "黑体"
    assert h1_fonts.get(qn("w:ascii")) == "Arial"

    # linked character style 同步：Word 渲染时 Heading1Char 的 rFonts 会
    # 覆盖段落样式，仅改 Heading 1 不够。
    char_styles = {style.style_id: style for style in doc.styles}
    char_rPr = char_styles["Heading1Char"].element.get_or_add_rPr()
    char_fonts = char_rPr.find(qn("w:rFonts"))
    assert char_fonts is not None
    assert char_fonts.get(qn("w:eastAsia")) == "黑体"


def test_absent_font_fields_keep_global_default(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        paragraphs=[{"text": "正文"}],
        format_spec={"body": {"font_size_pt": 12}},
    )
    normal_fonts = _style_rfonts(Document(str(path)), "Normal")
    assert normal_fonts.get(qn("w:eastAsia")) == "宋体"


def test_exact_line_spacing_applied(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        paragraphs=[{"text": "正文"}],
        format_spec={"body": {"line_spacing_pt": 28}},
    )
    normal = Document(str(path)).styles["Normal"]
    assert normal.paragraph_format.line_spacing.pt == pytest.approx(28, abs=0.01)
    spacing = normal.element.get_or_add_pPr().find(qn("w:spacing"))
    assert spacing is not None
    # 28pt × 20 twips/pt = 560；固定行距必须写入 lineRule="exact"
    assert spacing.get(qn("w:line")) == "560"
    assert spacing.get(qn("w:lineRule")) == "exact"


# ──────────────────────────────────────────────────────────────────────
# Caption style
# ──────────────────────────────────────────────────────────────────────


def test_table_caption_style_applied(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        tables=[{"headers": ["A"], "rows": [["1"]], "caption": "示例表"}],
        format_spec={
            "caption": {
                "font_family": "楷体_GB2312",
                "ascii_font": "Times New Roman",
                "font_size_pt": 10.5,
                "bold": True,
                "align": "left",
            }
        },
    )
    doc = Document(str(path))
    caption = next(p for p in doc.paragraphs if p.text.startswith("表1"))
    assert caption.alignment == WD_ALIGN_PARAGRAPH.LEFT
    visible_runs = [run for run in caption.runs if run.text]
    assert visible_runs
    for run in visible_runs:
        assert run.font.size.pt == pytest.approx(10.5)
        assert run.font.bold is True
        rFonts = run._r.get_or_add_rPr().find(qn("w:rFonts"))
        assert rFonts is not None
        assert rFonts.get(qn("w:eastAsia")) == "楷体_GB2312"


def test_figure_caption_uses_spec(tmp_path: Path) -> None:
    (tmp_path / "pic.png").write_bytes(_PNG_PIXEL.tobytes("png"))
    path = _generate(
        tmp_path,
        paragraphs=[{"text": "正文"}],
        images=[{"source": "pic.png", "after_paragraph": 0, "caption": "示例图"}],
        format_spec={"caption": {"font_family": "楷体", "font_size_pt": 10}},
    )
    doc = Document(str(path))
    caption = next(p for p in doc.paragraphs if p.text.startswith("图1"))
    visible_runs = [run for run in caption.runs if run.text]
    assert visible_runs
    for run in visible_runs:
        assert run.font.size.pt == pytest.approx(10)
        rFonts = run._r.get_or_add_rPr().find(qn("w:rFonts"))
        assert rFonts is not None
        assert rFonts.get(qn("w:eastAsia")) == "楷体"


def test_caption_defaults_unchanged_without_spec(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        tables=[{"headers": ["A"], "rows": [["1"]], "caption": "默认题注"}],
    )
    caption = next(
        p for p in Document(str(path)).paragraphs if p.text.startswith("表1")
    )
    assert caption.alignment == WD_ALIGN_PARAGRAPH.CENTER
    for run in (run for run in caption.runs if run.text):
        assert run.font.size.pt == pytest.approx(9)


# ──────────────────────────────────────────────────────────────────────
# Table text style
# ──────────────────────────────────────────────────────────────────────


def test_table_text_style_applied(tmp_path: Path) -> None:
    path = _generate(
        tmp_path,
        tables=[{"headers": ["姓名", "分数"], "rows": [["张三", "90"]]}],
        format_spec={
            "table_text": {
                "font_family": "仿宋",
                "font_size_pt": 10.5,
                "header_bold": True,
            }
        },
    )
    table = Document(str(path)).tables[0]
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    assert run.font.size.pt == pytest.approx(10.5)
                    rFonts = run._r.get_or_add_rPr().find(qn("w:rFonts"))
                    assert rFonts is not None
                    assert rFonts.get(qn("w:eastAsia")) == "仿宋"

    header_runs = [
        run
        for cell in table.rows[0].cells
        for paragraph in cell.paragraphs
        for run in paragraph.runs
    ]
    assert header_runs
    assert all(run.font.bold is True for run in header_runs)

    data_runs = [
        run
        for cell in table.rows[1].cells
        for paragraph in cell.paragraphs
        for run in paragraph.runs
    ]
    assert data_runs
    assert all(not run.font.bold for run in data_runs)


# ──────────────────────────────────────────────────────────────────────
# Reference document (template_docx_path)
# ──────────────────────────────────────────────────────────────────────


def _make_reference_docx(path: Path, *, body_font: str = "华文楷体") -> Path:
    from docx.shared import Pt

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.size = Pt(13)
    rPr = normal.element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    for attr in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        if qn(f"w:{attr}") in rFonts.attrib:
            del rFonts.attrib[qn(f"w:{attr}")]
    rFonts.set(qn("w:eastAsia"), body_font)
    rFonts.set(qn("w:ascii"), "Georgia")
    # 模板残留正文必须在生成时被清空
    doc.add_paragraph("模板残留正文")
    doc.save(str(path))
    return path


def test_reference_docx_supplies_style_base(tmp_path: Path) -> None:
    template = _make_reference_docx(tmp_path / "ref.docx")
    path = _generate(
        tmp_path,
        paragraphs=[{"text": "新正文"}],
        template_docx_path=str(template),
    )
    doc = Document(str(path))
    fonts = _style_rfonts(doc, "Normal")
    assert fonts.get(qn("w:eastAsia")) == "华文楷体"
    assert fonts.get(qn("w:ascii")) == "Georgia"
    assert doc.styles["Normal"].font.size.pt == pytest.approx(13)
    texts = [p.text for p in doc.paragraphs]
    assert "模板残留正文" not in texts
    assert "新正文" in texts


def test_reference_docx_relative_path_resolves_in_workspace(tmp_path: Path) -> None:
    _make_reference_docx(tmp_path / "ref.docx")
    req = OfficeWordGenerateRequest(
        workspace_path=str(tmp_path),
        filename="relative.docx",
        title="T",
        paragraphs=[{"text": "正文"}],
        template_docx_path="ref.docx",
    )
    path = generate_docx(req, output_dir=str(tmp_path / "out"))
    fonts = _style_rfonts(Document(str(path)), "Normal")
    assert fonts.get(qn("w:eastAsia")) == "华文楷体"


def test_reference_docx_explicit_font_overrides(tmp_path: Path) -> None:
    template = _make_reference_docx(tmp_path / "ref.docx")
    path = _generate(
        tmp_path,
        paragraphs=[{"text": "正文"}],
        template_docx_path=str(template),
        font_family="宋体",
    )
    fonts = _style_rfonts(Document(str(path)), "Normal")
    assert fonts.get(qn("w:eastAsia")) == "宋体"


def test_reference_docx_rejects_non_docx(tmp_path: Path) -> None:
    bogus = tmp_path / "ref.txt"
    bogus.write_text("not a docx", encoding="utf-8")
    with pytest.raises(Exception):
        _generate(
            tmp_path,
            paragraphs=[{"text": "正文"}],
            template_docx_path=str(bogus),
        )
