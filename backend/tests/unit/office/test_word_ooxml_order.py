"""OOXML 子元素顺序回归测试（Word 严格校验不弹"文档内容有问题需要修复"）。

OOXML 的 ``CT_SectPr`` / ``CT_PPrBase`` / ``CT_RPr`` 都是 ``xsd:sequence``，
子元素顺序错乱时 Word 会判定文档损坏并弹出修复提示。本模块以独立抄录的
ECMA-376 顺序作为判据，校验 Sage 版式引擎写出的 XML 顺序合法。

对应计划 docs/plans/2026-11-26_word-layout-template-p0.md M1 的兼容性修复。
"""

from __future__ import annotations

from docx import Document
from docx.oxml.ns import qn

from backend.office.models import (
    WordFormatSpec,
    WordHeaderFooterSpec,
    WordLineNumberingSpec,
    WordPageSetupSpec,
)
from backend.office.word_layout import apply_format_spec

#: ECMA-376 CT_SectPr 子元素顺序（headerReference/footerReference 在前）
_SECTPR_ORDER = (
    "headerReference",
    "footerReference",
    "footnotePr",
    "endnotePr",
    "type",
    "pgSz",
    "pgMar",
    "paperSrc",
    "pgBorders",
    "lnNumType",
    "pgNumType",
    "cols",
    "formProt",
    "vAlign",
    "noEndnote",
    "titlePg",
    "textDirection",
    "bidi",
    "rtlGutter",
    "docGrid",
    "printerSettings",
    "sectPrChange",
)

#: ECMA-376 CT_PPrBase 子元素顺序（pBdr 在 tabs 之前）
_PPR_ORDER = (
    "pStyle",
    "keepNext",
    "keepLines",
    "pageBreakBefore",
    "framePr",
    "widowControl",
    "numPr",
    "suppressLineNumbers",
    "pBdr",
    "shd",
    "tabs",
    "suppressAutoHyphens",
    "kinsoku",
    "wordWrap",
    "overflowPunct",
    "topLinePunct",
    "autoSpaceDE",
    "autoSpaceDN",
    "bidi",
    "adjustRightInd",
    "snapToGrid",
    "spacing",
    "ind",
    "contextualSpacing",
    "mirrorIndents",
    "suppressOverlap",
    "jc",
    "textDirection",
    "textAlignment",
    "textboxTightWrap",
    "outlineLvl",
    "divId",
    "cnfStyle",
    "rPr",
    "sectPr",
    "pPrChange",
)

#: ECMA-376 CT_RPr 子元素顺序（rStyle 在 rFonts 前，sz/szCs 在 highlight 前）
_RPR_ORDER = (
    "rStyle",
    "rFonts",
    "b",
    "bCs",
    "i",
    "iCs",
    "caps",
    "smallCaps",
    "strike",
    "dstrike",
    "outline",
    "shadow",
    "emboss",
    "imprint",
    "noProof",
    "snapToGrid",
    "vanish",
    "webHidden",
    "color",
    "spacing",
    "w",
    "kern",
    "position",
    "sz",
    "szCs",
    "highlight",
    "u",
    "effect",
    "bdr",
    "shd",
    "fitText",
    "vertAlign",
    "rtl",
    "cs",
    "em",
    "lang",
    "eastAsianLayout",
    "specVanish",
    "oMath",
)


def _local_names(element) -> list:
    return [child.tag.rsplit("}", 1)[-1] for child in element]


def _assert_ordered(element, order, label: str) -> None:
    """断言 element 的子元素严格按 schema 顺序排列。"""
    names = _local_names(element)
    ranks = [order.index(name) for name in names if name in order]
    assert ranks == sorted(ranks), f"{label} 子元素顺序非法: {names}"


def test_sectpr_children_follow_schema_order() -> None:
    """节属性同时含页眉/页脚引用、脚注重排、页码格式、行号时顺序合法。"""
    doc = Document()
    apply_format_spec(
        doc,
        WordFormatSpec(
            page=WordPageSetupSpec(
                page_number_format="decimal",
                page_number_start=1,
                footnote_restart_each_section=True,
                line_numbering=WordLineNumberingSpec(
                    count_by=1, restart="continuous", start=1
                ),
            ),
            header=WordHeaderFooterSpec(text="页眉"),
            footer=WordHeaderFooterSpec(text="页脚"),
        ),
    )
    sect_pr = doc.sections[0]._sectPr
    _assert_ordered(sect_pr, _SECTPR_ORDER, "sectPr")
    # 关键元素确实都写进去了（防止顺序断言空转）
    names = _local_names(sect_pr)
    for expected in (
        "headerReference",
        "footerReference",
        "footnotePr",
        "lnNumType",
        "pgNumType",
    ):
        assert expected in names, f"sectPr 缺少 {expected}: {names}"


def test_section_break_sectpr_children_follow_schema_order() -> None:
    """分节场景下新节属性同样合法（页码/行号/脚注 + 独立页眉页脚）。"""
    from backend.office.word_layout import apply_section_break

    doc = Document()
    apply_section_break(
        doc,
        WordPageSetupSpec(
            page_number_format="upperRoman",
            footnote_restart_each_section=True,
            line_numbering=WordLineNumberingSpec(count_by=5, restart="newSection"),
        ),
        header=WordHeaderFooterSpec(text="节页眉"),
        footer=WordHeaderFooterSpec(page_number=True),
    )
    for index, section in enumerate(doc.sections):
        _assert_ordered(
            section._sectPr, _SECTPR_ORDER, f"sections[{index}].sectPr"
        )


def test_header_paragraph_ppr_follows_schema_order() -> None:
    """页眉同时含制表位与下边框时，pBdr 必须排在 tabs 之前。"""
    doc = Document()
    apply_format_spec(
        doc,
        WordFormatSpec(
            header=WordHeaderFooterSpec(
                text="软件名称 V1.0用户说明书",
                tab_right=True,
                border_bottom=True,
            )
        ),
    )
    paragraph = doc.sections[0].header.paragraphs[0]
    pPr = paragraph._p.find(qn("w:pPr"))
    assert pPr is not None
    _assert_ordered(pPr, _PPR_ORDER, "header pPr")
    names = _local_names(pPr)
    assert "pBdr" in names, names
    assert "tabs" in names, names


def test_footer_paragraph_ppr_follows_schema_order() -> None:
    """页脚下边框同样必须排在 tabs 之前。"""
    doc = Document()
    apply_format_spec(
        doc,
        WordFormatSpec(
            footer=WordHeaderFooterSpec(tab_right=True, border_bottom=True)
        ),
    )
    paragraph = doc.sections[0].footer.paragraphs[0]
    pPr = paragraph._p.find(qn("w:pPr"))
    assert pPr is not None
    _assert_ordered(pPr, _PPR_ORDER, "footer pPr")


def test_run_rpr_follows_schema_order() -> None:
    """run 属性：rStyle 在 rFonts 前、sz/szCs 在 highlight/u 之前。"""
    doc = Document()
    apply_format_spec(
        doc,
        WordFormatSpec(
            header=WordHeaderFooterSpec(
                text="带字体与字号的页眉",
                font_size_pt=9,
                font_family="宋体",
                ascii_font="Times New Roman",
            )
        ),
    )
    paragraph = doc.sections[0].header.paragraphs[0]
    checked = 0
    for run in paragraph.runs:
        rPr = run._r.find(qn("w:rPr"))
        if rPr is None:
            continue
        checked += 1
        _assert_ordered(rPr, _RPR_ORDER, "run rPr")
        names = _local_names(rPr)
        assert "rFonts" in names, names
        assert "sz" in names, names
    assert checked > 0, "页眉段落应有至少一个带 rPr 的 run"


def test_rpr_with_existing_rstyle_keeps_rstyle_first() -> None:
    """已带 rStyle 的 run 追加 rFonts/字号时，rStyle 仍居首。"""
    from docx.oxml import OxmlElement

    from backend.office.models import WordHeaderFooterSpec as _Spec
    from backend.office.word_layout_sections import _apply_spec_fonts

    doc = Document()
    apply_format_spec(
        doc,
        WordFormatSpec(
            header=WordHeaderFooterSpec(text="标题样式", font_size_pt=12)
        ),
    )
    paragraph = doc.sections[0].header.paragraphs[0]
    run = paragraph.runs[0]
    rPr = run._r.get_or_add_rPr()
    rStyle = OxmlElement("w:rStyle")
    rStyle.set(qn("w:val"), "Header")
    rPr.insert(0, rStyle)

    # 再跑一次字体写入（幂等路径），顺序不得被破坏
    _apply_spec_fonts(run._r, _Spec(text="标题样式", font_size_pt=12))
    _assert_ordered(rPr, _RPR_ORDER, "run rPr")
    names = _local_names(rPr)
    assert names[0] == "rStyle", names
