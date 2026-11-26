"""P0 版式写入辅助：自定义纸张 / 行号 / 字符缩进 / 页眉页脚扩展。

从 ``word_layout.py`` 拆出（800 行架构棘轮）；主模块只做委托调用。
所有写入均以“未给字段不触碰”为前提，保持既有产物零变化。
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from ._docx_lazy import Cm, Inches, OxmlElement, align_map_ltr, qn
from .models import WordHeaderFooterSpec, WordPageSetupSpec

#: 命名纸张 → (宽, 高) EMU
_PAGE_SIZES = {
    "A3": (Cm(29.7), Cm(42.0)),
    "A4": (Cm(21.0), Cm(29.7)),
    "A5": (Cm(14.8), Cm(21.0)),
    "B4": (Cm(25.0), Cm(35.3)),
    "B5": (Cm(17.6), Cm(25.0)),
    "letter": (Inches(8.5), Inches(11.0)),
    "legal": (Inches(8.5), Inches(14.0)),
}

#: rFonts 上会覆盖显式字体名的 theme 引用属性
_RFONT_THEME_ATTRS = ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme")

#: sectPr 子元素 schema 顺序（插入时按序落位，避免 Word 严格校验拒绝）
_SECTPR_ORDER = (
    "w:footnotePr",
    "w:endnotePr",
    "w:type",
    "w:pgSz",
    "w:pgMar",
    "w:paperSrc",
    "w:pgBorders",
    "w:lnNumType",
    "w:pgNumType",
    "w:cols",
    "w:formProt",
    "w:vAlign",
    "w:titlePg",
    "w:textDirection",
    "w:bidi",
    "w:rtlGutter",
    "w:docGrid",
    "w:printerSettings",
)

#: pPr 中位于 w:ind 之前的元素（用于按 schema 顺序插入）
_PPR_BEFORE_IND = (
    "w:pStyle",
    "w:keepNext",
    "w:keepLines",
    "w:pageBreakBefore",
    "w:framePr",
    "w:widowControl",
    "w:numPr",
    "w:suppressLineNumbers",
    "w:pBdr",
    "w:shd",
    "w:tabs",
    "w:suppressAutoHyphens",
    "w:kinsoku",
    "w:wordWrap",
    "w:overflowPunct",
    "w:topLinePunct",
    "w:autoSpaceDE",
    "w:autoSpaceDN",
    "w:bidi",
    "w:adjustRightInd",
    "w:snapToGrid",
    "w:spacing",
)


def page_size_for(page: WordPageSetupSpec) -> Optional[Tuple[Any, Any]]:
    """返回 (width, height) EMU；自定义宽高优先于命名纸张，未匹配返回 None。"""
    if page.width_cm is not None and page.height_cm is not None:
        return Cm(page.width_cm), Cm(page.height_cm)
    return _PAGE_SIZES.get(page.size or "")


def _local_name(tag: str) -> str:
    return "w:" + tag.rsplit("}", 1)[-1]


def _insert_in_order(parent, element, order: Tuple[str, ...]) -> None:
    """按 schema 顺序把 element 插入 parent。"""
    rank = order.index(_local_name(element.tag))
    for child in parent:
        name = _local_name(child.tag)
        if name in order and order.index(name) > rank:
            child.addprevious(element)
            return
    parent.append(element)


def apply_line_numbering(section, spec: Any) -> None:
    """写节属性 ``w:lnNumType``（continuous/newPage/newSection）。"""
    sect_pr = section._sectPr
    ln = sect_pr.find(qn("w:lnNumType"))
    if ln is None:
        ln = OxmlElement("w:lnNumType")
        _insert_in_order(sect_pr, ln, _SECTPR_ORDER)
    ln.set(qn("w:countBy"), str(spec.count_by))
    ln.set(qn("w:restart"), spec.restart)
    if spec.start is not None:
        ln.set(qn("w:start"), str(spec.start))
    elif qn("w:start") in ln.attrib:
        del ln.attrib[qn("w:start")]


def apply_first_line_indent_chars(
    style, chars: int, font_size_pt: Optional[float]
) -> None:
    """按字符写首行缩进：``w:firstLineChars`` + 近似绝对值 ``w:firstLine``。

    Word 优先使用 firstLineChars（随字号缩放）；同时写 twips 值保证不识别
    chars 单位的渲染器仍按 2 字符视觉缩进。
    """
    pPr = style.element.get_or_add_pPr()
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        _insert_ppr_ind(pPr, ind)
    ind.set(qn("w:firstLineChars"), str(int(chars) * 100))
    size_pt = float(font_size_pt) if font_size_pt else 12.0
    ind.set(qn("w:firstLine"), str(int(chars * size_pt * 20)))


def _insert_ppr_ind(ppr, ind) -> None:
    for child in ppr:
        name = _local_name(child.tag)
        if name not in _PPR_BEFORE_IND:
            child.addprevious(ind)
            return
    ppr.append(ind)


def _write_rfonts(
    rpr, *, font_family: Optional[str], ascii_font: Optional[str]
) -> None:
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for theme_attr in _RFONT_THEME_ATTRS:
        qualified = qn(f"w:{theme_attr}")
        if qualified in rfonts.attrib:
            del rfonts.attrib[qualified]
    if font_family is not None:
        rfonts.set(qn("w:eastAsia"), font_family)
    if ascii_font is not None:
        rfonts.set(qn("w:ascii"), ascii_font)
        rfonts.set(qn("w:hAnsi"), ascii_font)
        rfonts.set(qn("w:cs"), ascii_font)


def _apply_spec_fonts(run_element, spec: WordHeaderFooterSpec) -> None:
    if (
        spec.font_size_pt is None
        and spec.font_family is None
        and spec.ascii_font is None
    ):
        return
    rPr = run_element.find(qn("w:rPr"))
    if rPr is None:
        rPr = OxmlElement("w:rPr")
        run_element.insert(0, rPr)
    _write_rfonts(rPr, font_family=spec.font_family, ascii_font=spec.ascii_font)
    if spec.font_size_pt is not None:
        half_points = str(int(round(float(spec.font_size_pt) * 2)))
        for tag in ("w:sz", "w:szCs"):
            el = rPr.find(qn(tag))
            if el is None:
                el = OxmlElement(tag)
                rPr.append(el)
            el.set(qn("w:val"), half_points)


def _add_right_tab(paragraph, section) -> None:
    from docx.enum.text import WD_TAB_ALIGNMENT

    width_cm = (
        section.page_width.cm - section.left_margin.cm - section.right_margin.cm
    )
    paragraph.paragraph_format.tab_stops.add_tab_stop(
        Cm(width_cm), WD_TAB_ALIGNMENT.RIGHT
    )


def _add_bottom_border(paragraph) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    if pPr.find(qn("w:pBdr")) is not None:
        return
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "auto")
    pBdr.append(bottom)
    pPr.append(pBdr)


def _append_simple_field(
    paragraph, instr: str, cached: str, spec: WordHeaderFooterSpec
) -> None:
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), instr)
    run = OxmlElement("w:r")
    _apply_spec_fonts(run, spec)
    text = OxmlElement("w:t")
    text.text = cached
    run.append(text)
    fld.append(run)
    paragraph._p.append(fld)


def write_header_footer(
    section,
    *,
    kind: str,
    spec: WordHeaderFooterSpec,
    fresh: bool = False,
) -> None:
    """按 spec 写入一节的页眉或页脚。

    ``fresh=True`` 用于分节场景：``doc.add_section`` 会让新旧两节共享同一个
    header/footer part，必须先断开引用（True）再新建（False）才能得到
    独立部件，否则会串改前一节内容。
    """
    part = section.header if kind == "header" else section.footer
    if fresh and not part.is_linked_to_previous:
        part.is_linked_to_previous = True
    if part.is_linked_to_previous:
        part.is_linked_to_previous = False
    paragraph = part.paragraphs[0] if part.paragraphs else part.add_paragraph()
    paragraph.text = spec.text or ""
    if spec.align is not None:
        paragraph.alignment = align_map_ltr()[spec.align]
    if spec.tab_right:
        _add_right_tab(paragraph, section)
    if spec.border_bottom:
        _add_bottom_border(paragraph)

    wants_number = bool(spec.page_number) or spec.page_number_style is not None
    if wants_number:
        if spec.tab_right:
            paragraph.add_run("\t")
        if spec.page_number_style == "zh":
            paragraph.add_run(" 第 ")
            _append_simple_field(paragraph, "PAGE", "1", spec)
            paragraph.add_run(" 页 共 ")
            _append_simple_field(paragraph, "NUMPAGES", "1", spec)
            paragraph.add_run(" 页")
        else:
            _append_simple_field(paragraph, "PAGE", "1", spec)

    for run in paragraph.runs:
        _apply_spec_fonts(run._r, spec)
