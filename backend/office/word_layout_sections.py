"""P0 版式写入辅助：自定义纸张 / 行号 / 字符缩进 / 页眉页脚扩展。

从 ``word_layout.py`` 拆出（800 行架构棘轮）；主模块只做委托调用。
所有写入均以“未给字段不触碰”为前提，保持既有产物零变化。
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from ._docx_lazy import Cm, Inches, OxmlElement, align_map_ltr, qn
from .errors import OfficeGenerateError
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
#:
#: CT_SectPr 是 xsd:sequence：EG_HdrFtrReferences（headerReference /
#: footerReference）必须排在 EG_SectPrContents 全部子元素之前；缺了这一段
#: 会让 headerReference 落到 pgSz 之后 —— Word 判定文档损坏并弹修复提示。
_SECTPR_ORDER = (
    "w:headerReference",
    "w:footerReference",
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
    "w:noEndnote",
    "w:titlePg",
    "w:textDirection",
    "w:bidi",
    "w:rtlGutter",
    "w:docGrid",
    "w:printerSettings",
    "w:sectPrChange",
)

#: pPr 子元素 schema 顺序（CT_PPrBase + CT_PPr 尾部元素）
#:
#: pBdr 必须排在 shd/tabs 之前 —— 直接 append 会让边框落到 tabs 之后。
_PPR_ORDER = (
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
    "w:ind",
    "w:contextualSpacing",
    "w:mirrorIndents",
    "w:suppressOverlap",
    "w:jc",
    "w:textDirection",
    "w:textAlignment",
    "w:textboxTightWrap",
    "w:outlineLvl",
    "w:divId",
    "w:cnfStyle",
    "w:rPr",
    "w:sectPr",
    "w:pPrChange",
)

#: rPr 子元素 schema 顺序（rStyle 在 rFonts 前；sz/szCs 在 highlight/u 前）
_RPR_ORDER = (
    "w:rStyle",
    "w:rFonts",
    "w:b",
    "w:bCs",
    "w:i",
    "w:iCs",
    "w:caps",
    "w:smallCaps",
    "w:strike",
    "w:dstrike",
    "w:outline",
    "w:shadow",
    "w:emboss",
    "w:imprint",
    "w:noProof",
    "w:snapToGrid",
    "w:vanish",
    "w:webHidden",
    "w:color",
    "w:spacing",
    "w:w",
    "w:kern",
    "w:position",
    "w:sz",
    "w:szCs",
    "w:highlight",
    "w:u",
    "w:effect",
    "w:bdr",
    "w:shd",
    "w:fitText",
    "w:vertAlign",
    "w:rtl",
    "w:cs",
    "w:em",
    "w:lang",
    "w:eastAsianLayout",
    "w:specVanish",
    "w:oMath",
)


def page_size_for(page: WordPageSetupSpec) -> Optional[Tuple[Any, Any]]:
    """返回 (width, height) EMU；自定义宽高优先于命名纸张，未匹配返回 None。

    自定义纸张要求宽高成对出现；只给一个维度视为配置错误（显式报错，
    避免静默 no-op）。
    """
    if (page.width_cm is None) != (page.height_cm is None):
        raise OfficeGenerateError("自定义纸张需同时提供 width_cm 与 height_cm")
    if page.width_cm is not None and page.height_cm is not None:
        return Cm(page.width_cm), Cm(page.height_cm)
    return _PAGE_SIZES.get(page.size or "")


def _local_name(tag: str) -> str:
    return "w:" + tag.rsplit("}", 1)[-1]


def _insert_in_order(parent, element, order: Tuple[str, ...]) -> None:
    """按 schema 顺序把 element 插入 parent。

    ``order`` 里没有的元素一律追加到末尾（未知 schema 位置时保守处理，
    不抛异常打断生成流程）。
    """
    name = _local_name(element.tag)
    if name not in order:
        parent.append(element)
        return
    rank = order.index(name)
    for child in parent:
        child_name = _local_name(child.tag)
        if child_name in order and order.index(child_name) > rank:
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
    _insert_in_order(ppr, ind, _PPR_ORDER)


def _write_rfonts(
    rpr, *, font_family: Optional[str], ascii_font: Optional[str]
) -> None:
    rfonts = _get_or_add_rfonts(rpr)
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


def _get_or_add_rfonts(rpr):
    """取（或按 schema 顺序插入）rPr 下的 w:rFonts。

    python-docx 的 CT_RPr 提供 ``get_or_add_rFonts``（自带正确后继顺序），
    优先复用；拿不到该接口时按本地 ``_RPR_ORDER`` 兜底插入。
    """
    getter = getattr(rpr, "get_or_add_rFonts", None)
    if getter is not None:
        return getter()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        _insert_in_order(rpr, rfonts, _RPR_ORDER)
    return rfonts


def _get_or_add_rpr_size(rpr, tag: str):
    """取（或按 schema 顺序插入）rPr 下的 w:sz / w:szCs（字号半磅值）。"""
    accessor = "get_or_add_sz" if tag == "w:sz" else "get_or_add_szCs"
    getter = getattr(rpr, accessor, None)
    if getter is not None:
        return getter()
    el = rpr.find(qn(tag))
    if el is None:
        el = OxmlElement(tag)
        _insert_in_order(rpr, el, _RPR_ORDER)
    return el


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
            el = _get_or_add_rpr_size(rPr, tag)
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
    # pBdr 必须排在 shd/tabs 之前（CT_PPrBase 是 xsd:sequence），
    # 直接 append 会让边框落到制表位之后，Word 判定文档损坏。
    _insert_in_order(pPr, pBdr, _PPR_ORDER)


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
    if spec.text is not None:
        paragraph.text = spec.text
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
