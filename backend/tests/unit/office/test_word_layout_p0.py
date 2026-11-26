"""P0 版式扩展测试：自定义纸张 / 行号 / 字符缩进 / 标题行距 / 页眉页脚 / 节级页眉。

对应计划 docs/plans/2026-11-26_word-layout-template-p0.md M1（P0-2/3/4）。
"""

from __future__ import annotations

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

from backend.office.models import (
    WordBodyStyleSpec,
    WordFormatSpec,
    WordHeaderFooterSpec,
    WordHeadingStyleSpec,
    WordLineNumberingSpec,
    WordPageSetupSpec,
    WordSectionBreakSpec,
)
from backend.office.word_layout import apply_format_spec, apply_section_break


def _fld_instrs(paragraph):
    return [el.get(qn("w:instr")) for el in paragraph._p.findall(qn("w:fldSimple"))]


def test_custom_paper_size_and_line_numbering() -> None:
    doc = Document()
    spec = WordFormatSpec(
        page=WordPageSetupSpec(
            width_cm=17.6,
            height_cm=25.0,
            line_numbering=WordLineNumberingSpec(
                count_by=1, restart="continuous", start=1
            ),
        )
    )
    apply_format_spec(doc, spec)

    section = doc.sections[0]
    assert round(section.page_width.cm, 2) == 17.6
    assert round(section.page_height.cm, 2) == 25.0
    ln = section._sectPr.find(qn("w:lnNumType"))
    assert ln is not None
    assert ln.get(qn("w:countBy")) == "1"
    assert ln.get(qn("w:restart")) == "continuous"
    assert ln.get(qn("w:start")) == "1"


def test_named_a3_paper_and_landscape() -> None:
    doc = Document()
    apply_format_spec(
        doc, WordFormatSpec(page=WordPageSetupSpec(size="A3", orientation="landscape"))
    )
    section = doc.sections[0]
    assert round(section.page_width.cm, 1) == 42.0
    assert round(section.page_height.cm, 1) == 29.7


def test_first_line_indent_chars_written_to_normal_style() -> None:
    doc = Document()
    apply_format_spec(
        doc,
        WordFormatSpec(body=WordBodyStyleSpec(first_line_indent_chars=2)),
    )
    normal = doc.styles["Normal"]
    pPr = normal.element.find(qn("w:pPr"))
    assert pPr is not None
    ind = pPr.find(qn("w:ind"))
    assert ind is not None
    assert ind.get(qn("w:firstLineChars")) == "200"
    # 近似绝对值同时写入，保证不识别 firstLineChars 的渲染器仍生效
    assert int(ind.get(qn("w:firstLine"))) > 0


def test_heading_line_spacing_fixed_points() -> None:
    doc = Document()
    apply_format_spec(
        doc,
        WordFormatSpec(
            headings={
                "h1": WordHeadingStyleSpec(line_spacing_pt=28.0),
                "h2": WordHeadingStyleSpec(line_spacing=1.5),
            }
        ),
    )
    h1 = doc.styles["Heading 1"].paragraph_format
    h2 = doc.styles["Heading 2"].paragraph_format
    assert h1.line_spacing == Pt(28)
    assert h2.line_spacing == 1.5


def test_header_with_border_tab_and_zh_page_numbers() -> None:
    doc = Document()
    apply_format_spec(
        doc,
        WordFormatSpec(
            header=WordHeaderFooterSpec(
                text="软件名称 V1.0用户说明书",
                tab_right=True,
                border_bottom=True,
                font_size_pt=9,
                page_number_style="zh",
            )
        ),
    )
    paragraph = doc.sections[0].header.paragraphs[0]
    assert paragraph.text.startswith("软件名称 V1.0用户说明书")
    # 下边框
    pPr = paragraph._p.find(qn("w:pPr"))
    assert pPr.find(qn("w:pBdr")) is not None
    # 右对齐制表位
    tabs = pPr.find(qn("w:tabs"))
    assert tabs is not None
    assert tabs.find(qn("w:tab")).get(qn("w:val")) == "right"
    # PAGE + NUMPAGES 域
    instrs = _fld_instrs(paragraph)
    assert any("PAGE" in (i or "") for i in instrs)
    assert any("NUMPAGES" in (i or "") for i in instrs)
    assert "第" in paragraph.text
    assert "页" in paragraph.text


def test_footer_plain_page_number_unchanged() -> None:
    doc = Document()
    apply_format_spec(
        doc, WordFormatSpec(footer=WordHeaderFooterSpec(page_number=True))
    )
    paragraph = doc.sections[0].footer.paragraphs[0]
    assert paragraph._p.find(qn("w:fldSimple")) is not None
    assert "PAGE" in paragraph._p.find(qn("w:fldSimple")).get(qn("w:instr"))


def test_section_break_header_is_independent() -> None:
    doc = Document()
    apply_format_spec(
        doc, WordFormatSpec(header=WordHeaderFooterSpec(text="Cover Header"))
    )
    apply_section_break(
        doc,
        WordPageSetupSpec(size="A4"),
        header=WordHeaderFooterSpec(text="Body Header"),
    )
    assert doc.sections[0].header.paragraphs[0].text == "Cover Header"
    assert doc.sections[1].header.paragraphs[0].text == "Body Header"
    # 修改新节页眉不得回写前一节（共享 header part 的 detach 校验）
    doc.sections[1].header.paragraphs[0].text = "Changed Body"
    assert doc.sections[0].header.paragraphs[0].text == "Cover Header"


def test_section_break_without_page_setup() -> None:
    doc = Document()
    apply_section_break(doc, None, footer=WordHeaderFooterSpec(page_number=True))
    assert len(doc.sections) == 2
    assert doc.sections[1].footer.paragraphs[0]._p.find(qn("w:fldSimple")) is not None


def test_section_break_spec_model_accepts_headers() -> None:
    spec = WordSectionBreakSpec(
        start_paragraph=3,
        header=WordHeaderFooterSpec(text="H2"),
        footer=WordHeaderFooterSpec(page_number=True),
    )
    assert spec.page_setup is None
    assert spec.header.text == "H2"
    assert spec.footer.page_number is True
