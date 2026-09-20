"""Word 格式 Linter（Round 10）——对照 FormatSpec 校验任意 .docx。

与 :func:`backend.office.word_layout.apply_format_spec` 对偶：生成器把
FormatSpec 写进文档，Linter 把文档读回来逐条比对。规则空间与
journal validator（面向期刊 spec 的 C 级校验）不重叠。

约定：
- **spec 未提供的项不产生规则**（None = 不检查），因此空 spec 输入
  恒零违规；
- 每条 issue 携带 rule_id / severity / message（实测 vs 期望）/
  fix_hint（中文修复建议），供 LLM 或用户直接行动；
- 边距/缩进类尺寸断言容差 0.05cm（docx 的 twips 取整）；
- 纯回读：不修改文档、不落盘。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List, Optional

from docx import Document
from docx.oxml.ns import qn

from .errors import OfficeParseError
from .models import (
    WordBodyStyleSpec,
    WordFormatSpec,
    WordHeadingStyleSpec,
    WordLintIssue,
    WordLintResult,
    WordPageSetupSpec,
)

#: 尺寸类断言容差（cm）——docx 边距以 twips 存储存在取整误差
_CM_TOLERANCE = 0.05

# Round 20：编号/样式检查覆盖 h1-h5。
_HEADING_STYLE_BY_LEVEL = {
    "h1": "Heading 1",
    "h2": "Heading 2",
    "h3": "Heading 3",
    "h4": "Heading 4",
    "h5": "Heading 5",
}

_HEADING_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+")
_FIGURE_CAPTION_RE = re.compile(r"^图(\d+)[　\s]")
_TABLE_CAPTION_RE = re.compile(r"^表(\d+)[　\s]")
_CITATION_MARKER_RE = re.compile(r"\[(\d+)(?:-(\d+))?\]")

#: 页码域的 OOXML 形态（与 word_layout._apply_footer 写入一致）
_PAGE_FIELD_XPATH = ".//" + qn("w:fldSimple")


def _issue(rule_id: str, severity: str, message: str, fix_hint: str = "") -> WordLintIssue:
    return WordLintIssue(rule_id=rule_id, severity=severity, message=message, fix_hint=fix_hint)


def _document_has_field_with_instr(doc: Document, token: str) -> bool:
    r"""检测文档是否存在 instr 含 token 的域（fldSimple/fldChar 双载体）。

    注意 "TOC" 是 `\c` 图/表目录域（TOF）的前缀——区分 TOC 与 TOF 用
    ``_document_has_toc_field`` 的排除逻辑，不要直接用裸 "TOC" token。
    """
    for p in doc.paragraphs:
        for fld in p._p.findall(".//" + qn("w:fldSimple")):
            if token in (fld.get(qn("w:instr")) or ""):
                return True
        for instr in p._p.findall(".//" + qn("w:instrText")):
            if token in (instr.text or ""):
                return True
    return False


def _document_has_toc_field(doc: Document) -> bool:
    """检测文档是否存在目录域（排除图/表目录域——后者 instr 也含 TOC）。"""
    for p in doc.paragraphs:
        for fld in p._p.findall(".//" + qn("w:fldSimple")):
            instr = fld.get(qn("w:instr")) or ""
            if "TOC" in instr and r"\c" not in instr:
                return True
        for instr in p._p.findall(".//" + qn("w:instrText")):
            text = instr.text or ""
            if "TOC" in text and r"\c" not in text:
                return True
    return False


def _cm(value: Optional[Any]) -> Optional[float]:
    return None if value is None else round(value.cm, 3)


def _check_page(doc: Document, page: WordPageSetupSpec, issues: List[WordLintIssue]) -> None:
    section = doc.sections[0]

    # Round 53：节内页码格式/起始号校验（spec 声明了才校验）。
    if page.page_number_format is not None or page.page_number_start is not None:
        sect_pr = section._sectPr
        pg = sect_pr.find(qn("w:pgNumType"))
        actual_fmt = pg.get(qn("w:fmt")) if pg is not None else None
        actual_start = pg.get(qn("w:start")) if pg is not None else None
        if page.page_number_format is not None and actual_fmt != page.page_number_format:
            issues.append(_issue(
                "page/numbering", "error",
                f"页码格式实测 {actual_fmt or '未设置'}，期望 {page.page_number_format}",
                f"在节属性的 pgNumType 设置 fmt={page.page_number_format}"
                "（或用 format_spec.page.page_number_format 重新生成）",
            ))
        if page.page_number_start is not None and (
            actual_start is None or int(actual_start) != page.page_number_start
        ):
            issues.append(_issue(
                "page/numbering", "error",
                f"页码起始号实测 {actual_start or '未设置'}，期望 {page.page_number_start}",
                f"在节属性的 pgNumType 设置 start={page.page_number_start}"
                "（或用 format_spec.page.page_number_start 重新生成）",
            ))
    if page.margins_cm is not None:
        margins = page.margins_cm
        actual = {
            "top": section.top_margin,
            "bottom": section.bottom_margin,
            "left": section.left_margin,
            "right": section.right_margin,
        }
        for side, expected in (
            ("top", margins.top),
            ("bottom", margins.bottom),
            ("left", margins.left),
            ("right", margins.right),
        ):
            if expected is None:
                continue
            actual_cm = _cm(actual[side])
            if actual_cm is None or abs(actual_cm - expected) > _CM_TOLERANCE:
                issues.append(_issue(
                    "page/margins", "error",
                    f"页边距 {side} 实测 {actual_cm}cm，期望 {expected}cm",
                    f"把节属性的 {side} 边距改为 {expected}cm（或用 office_create 的 "
                    f"format_spec.page.margins_cm 重新生成）",
                ))
    if page.size is not None or page.orientation is not None:
        width_mm = section.page_width.mm
        height_mm = section.page_height.mm
        landscape = width_mm > height_mm
        if page.size == "A4":
            ok_size = {210.0, 297.0} == {round(width_mm), round(height_mm)}
            if not ok_size:
                issues.append(_issue(
                    "page/size", "error",
                    f"页面尺寸实测 {round(width_mm)}x{round(height_mm)}mm，期望 A4(210x297)",
                    "把页面纸张设为 A4",
                ))
        elif page.size == "letter":
            ok_size = {215.9, 279.4} == {round(width_mm, 1), round(height_mm, 1)}
            if not ok_size:
                issues.append(_issue(
                    "page/size", "error",
                    f"页面尺寸实测 {round(width_mm, 1)}x{round(height_mm, 1)}mm，"
                    "期望 letter(215.9x279.4)",
                    "把页面纸张设为 letter",
                ))
        if page.orientation is not None:
            expected_landscape = page.orientation == "landscape"
            if landscape != expected_landscape:
                issues.append(_issue(
                    "page/orientation", "error",
                    f"页面方向实测 {'横向' if landscape else '纵向'}，"
                    f"期望 {'横向' if expected_landscape else '纵向'}",
                    "在页面设置中切换纸张方向",
                ))


def _check_body(doc: Document, body: WordBodyStyleSpec, issues: List[WordLintIssue]) -> None:
    style = doc.styles["Normal"]
    paragraph_format = style.paragraph_format
    if body.font_size_pt is not None:
        actual = style.font.size.pt if style.font.size else None
        if actual is None or abs(actual - body.font_size_pt) > 0.01:
            issues.append(_issue(
                "body/font_size", "error",
                f"正文字号实测 {actual}pt，期望 {body.font_size_pt}pt",
                f"把 Normal 样式字号改为 {body.font_size_pt}pt",
            ))
    if body.line_spacing is not None:
        actual = paragraph_format.line_spacing
        if actual is None or abs(float(actual) - body.line_spacing) > 0.01:
            issues.append(_issue(
                "body/line_spacing", "error",
                f"正文行距实测 {actual}，期望 {body.line_spacing} 倍",
                f"把 Normal 样式行距改为 {body.line_spacing} 倍",
            ))
    if body.first_line_indent_cm is not None:
        actual = _cm(paragraph_format.first_line_indent)
        if actual is None or abs(actual - body.first_line_indent_cm) > _CM_TOLERANCE:
            issues.append(_issue(
                "body/first_line_indent", "error",
                f"正文首行缩进实测 {actual}cm，期望 {body.first_line_indent_cm}cm",
                f"把 Normal 样式首行缩进改为 {body.first_line_indent_cm}cm",
            ))


def _check_heading_style(
    doc: Document,
    style_name: str,
    rule_prefix: str,
    spec: WordHeadingStyleSpec,
    issues: List[WordLintIssue],
) -> None:
    try:
        style = doc.styles[style_name]
    except KeyError:
        return
    if spec.font_size_pt is not None:
        actual = style.font.size.pt if style.font.size else None
        if actual is None or abs(actual - spec.font_size_pt) > 0.01:
            issues.append(_issue(
                f"{rule_prefix}/font_size", "error",
                f"{style_name} 字号实测 {actual}pt，期望 {spec.font_size_pt}pt",
                f"把 {style_name} 样式字号改为 {spec.font_size_pt}pt",
            ))
    if spec.bold is not None and bool(style.font.bold) != spec.bold:
        issues.append(_issue(
            f"{rule_prefix}/bold", "error",
            f"{style_name} 加粗实测 {bool(style.font.bold)}，期望 {spec.bold}",
            f"把 {style_name} 样式加粗设为 {'开' if spec.bold else '关'}",
        ))
    if spec.color is not None:
        expected = spec.color.lstrip("#").upper()
        actual = str(style.font.color.rgb) if style.font.color and style.font.color.rgb else None
        if actual != expected:
            issues.append(_issue(
                f"{rule_prefix}/color", "error",
                f"{style_name} 颜色实测 {actual}，期望 {expected}",
                f"把 {style_name} 样式字体颜色改为 #{expected}",
            ))


def _check_header_footer(doc: Document, spec: WordFormatSpec, issues: List[WordLintIssue]) -> None:
    if spec.header is not None and spec.header.text is not None:
        header = doc.sections[0].header
        actual = header.paragraphs[0].text if header.paragraphs else ""
        if actual != spec.header.text:
            issues.append(_issue(
                "header/text", "error",
                f"页眉文本实测 {actual!r}，期望 {spec.header.text!r}",
                f"把页眉文本改为 {spec.header.text!r}",
            ))
    if spec.footer is not None and spec.footer.page_number:
        footer = doc.sections[0].footer
        has_field = any(
            fld.get(qn("w:instr")) == "PAGE"
            for p in footer.paragraphs
            for fld in p._p.findall(_PAGE_FIELD_XPATH)
        )
        if not has_field:
            issues.append(_issue(
                "footer/page_number", "error",
                "页脚未检测到页码域（w:fldSimple instr=PAGE）",
                "在页脚插入页码域（或用 format_spec.footer.page_number 重新生成）",
            ))


def _expected_heading_prefix(counters: List[int], level: int) -> str:
    """与 word_layout.heading_number_prefix 同算法（跳级省略 0 段）。"""
    counters[level - 1] += 1
    for idx in range(level, len(counters)):
        counters[idx] = 0
    return ".".join(str(counters[i]) for i in range(level) if counters[i] != 0)


def _check_numbering(
    doc: Document, issues: List[WordLintIssue], bib_heading: str
) -> None:
    # Round 20：counters 扩到 5 级（Heading 4/5 也纳入编号检查）。
    counters = [0, 0, 0, 0, 0]
    for para in doc.paragraphs:
        style_name = para.style.name if para.style is not None else ""
        if style_name not in _HEADING_STYLE_BY_LEVEL.values():
            continue
        # 参考文献节标题不参与多级编号（生成器行为对偶）
        if para.text.strip() == bib_heading:
            continue
        level = int(style_name.split()[-1])
        match = _HEADING_PREFIX_RE.match(para.text)
        if match is None:
            issues.append(_issue(
                "numbering/sequence", "error",
                f"标题缺少编号前缀: {para.text[:40]!r}",
                "为标题补充 'N' / 'N.M' / 'N.M.K' 形式的编号（或用 "
                "format_spec.numbering 重新生成）",
            ))
            continue
        expected = _expected_heading_prefix(counters, level)
        if match.group(1) != expected:
            issues.append(_issue(
                "numbering/sequence", "error",
                f"标题编号实测 {match.group(1)!r}，期望 {expected!r}: {para.text[:40]!r}",
                "按出现顺序重排标题编号（多级标题应为 1 / 1.1 / 1.1.1 连续递进）",
            ))


def _iter_paragraphs_outside_fields(doc: Document):
    """跳过复杂域缓存内容中的段落（Round 42）。

    目录/图目录域（fldChar begin...end）的缓存行形如"图N　标题"，
    会被 caption/sequence 规则误判为正文题注重复——begin 与 end 之间
    的纯缓存段落不参与规则；begin/end 所在段自身文本为空，无影响。
    """
    inside_field = False
    for para in doc.paragraphs:
        has_toggle = False
        for run in para.runs:
            for fld in run._r.findall(qn("w:fldChar")):
                fld_type = fld.get(qn("w:fldCharType"))
                if fld_type == "begin":
                    inside_field = True
                    has_toggle = True
                elif fld_type == "end":
                    inside_field = False
                    has_toggle = True
        if has_toggle or not inside_field:
            yield para


def _check_captions(doc: Document, issues: List[WordLintIssue]) -> None:
    for label, regex in (("图", _FIGURE_CAPTION_RE), ("表", _TABLE_CAPTION_RE)):
        expected = 1
        seen_texts: dict = {}
        for para in _iter_paragraphs_outside_fields(doc):
            match = regex.match(para.text)
            if match is None:
                continue
            actual = int(match.group(1))
            if actual != expected:
                issues.append(_issue(
                    "caption/sequence", "error",
                    f"{label}题注编号实测 {actual}，期望 {expected}（应从 1 连续递增）",
                    f"重排{label}题注编号为 {expected}",
                ))
                expected = actual
            expected += 1
            # Round 48：重复题注文本提示（交叉引用按题注文本匹配指向
            # 首个；警告级——不阻断交付）。
            caption_text = regex.sub("", para.text, count=1).strip()
            if caption_text in seen_texts:
                issues.append(_issue(
                    "caption/duplicate", "warning",
                    f'{label}题注文本重复："{caption_text}"（第 '
                    f"{seen_texts[caption_text]} 处与当前处）",
                    "区分同类题注的标题文本，避免交叉引用指向首个",
                ))
            else:
                seen_texts[caption_text] = expected - 1


_CROSS_REF_RESIDUE_RE = re.compile(r"\{\{(fig|tbl|fn|en):[^}]+\}\}")


def _check_cross_ref_residue(doc: Document, issues: List[WordLintIssue]) -> None:
    """正文残留未解析的交叉引用占位符 → error（Round 45）。

    生成通路会 fail-fast（未命中题注即生成失败），残渍只来自手工编辑
    或外部导入的文档——此时占位符是死文本，提示直接写 图N/表N 或重新
    生成。
    """
    residue = [
        para.text
        for para in _iter_paragraphs_outside_fields(doc)
        if _CROSS_REF_RESIDUE_RE.search(para.text)
    ]
    if residue:
        issues.append(_issue(
            "cross_ref/residue", "error",
            f"存在未解析的交叉引用占位符（{len(residue)} 处，如 {residue[0][:40]}）",
            "占位符仅在 office_create 生成时解析；手工编辑请直接写 图N/表N，"
            "或用原 format_spec 重新生成",
        ))


def _check_ref_consistency(doc: Document, issues: List[WordLintIssue]) -> None:
    """脚注/尾注引用 id 必须在对应 part 有 note（Round 63）。

    正文 ``footnoteReference``/``endnoteReference`` 的 id 对照
    footnotes/endnotes part 的真实 note id 集合（系统脚注跳过）；
    无引用的文档零开销跳过。
    """
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    for kind, partname in (
        ("footnote", "/word/footnotes.xml"),
        ("endnote", "/word/endnotes.xml"),
    ):
        refs = [
            int(el.get(qn("w:id")))
            for p in doc.paragraphs
            for el in p._p.findall(f".//{{{W}}}{kind}Reference")
        ]
        if not refs:
            continue
        note_ids: set = set()
        for part in doc.part.package.iter_parts():
            if str(part.partname) != partname:
                continue
            from xml.etree import ElementTree

            root = ElementTree.fromstring(part.blob)
            for note in root.findall(f"{{{W}}}{kind}"):
                if note.get(f"{{{W}}}type") is None:
                    note_ids.add(int(note.get(f"{{{W}}}id")))
            break
        broken = sorted({r for r in refs if r not in note_ids})
        if broken:
            issues.append(_issue(
                f"{kind}/broken_ref", "error",
                f"{len(broken)} 处 {kind}Reference 引用了不存在的 note id"
                f"（{broken}）",
                "文档可能被手工改动——用原 format_spec 重新生成",
            ))


def _check_citations(doc: Document, issues: List[WordLintIssue]) -> None:
    numbers: set = set()
    for para in doc.paragraphs:
        if para.style is not None and para.style.name.startswith("Heading"):
            continue
        if _TABLE_CAPTION_RE.match(para.text):
            continue
        for match in _CITATION_MARKER_RE.finditer(para.text):
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else start
            if end >= start:
                numbers.update(range(start, end + 1))
    if not numbers:
        return
    max_seen = max(numbers)
    missing = sorted(set(range(1, max_seen + 1)) - numbers)
    if missing:
        issues.append(_issue(
            "citation/coverage", "warning",
            f"文中引用标记编号 1..{max_seen} 中缺失 {missing}",
            "补齐缺失的引用标记，或核对文末参考文献表是否完整",
        ))


def lint_docx(path: Path, spec: WordFormatSpec) -> WordLintResult:
    """对照 FormatSpec 校验 .docx，返回违规清单（纯回读）。

    spec 未提供的项不产生规则；空 spec（全 None/False）恒返回 ok。
    文件无法解析为 docx 时抛 :class:`OfficeParseError`（调用方映射 422）。
    """
    try:
        doc = Document(str(path))
    except Exception as exc:
        raise OfficeParseError(f"无法解析 docx: {exc}") from exc

    issues: List[WordLintIssue] = []
    checked: List[str] = []

    if spec.page is not None:
        checked.append("page")
        _check_page(doc, spec.page, issues)
    if spec.body is not None:
        checked.append("body")
        _check_body(doc, spec.body, issues)
    if spec.title is not None:
        checked.append("title")
        _check_heading_style(doc, "Title", "title", spec.title, issues)
    if spec.headings:
        checked.append("headings")
        for key, heading_spec in spec.headings.items():
            style_name = _HEADING_STYLE_BY_LEVEL.get(key)
            if style_name is not None:
                _check_heading_style(doc, style_name, f"headings/{key}", heading_spec, issues)
    if spec.header is not None or spec.footer is not None:
        checked.append("header_footer")
        _check_header_footer(doc, spec, issues)
    if spec.toc is not None:
        checked.append("toc")
        # Round 29 起 TOC 域为 fldChar 复杂域（instrText 载荷），兼容
        # 旧 fldSimple 形态：两种载体都检测。
        found_toc = _document_has_toc_field(doc)
        if not found_toc:
            issues.append(_issue(
                "toc/presence", "error",
                "未检测到目录域（TOC instr）",
                "在标题后插入 TOC 域（或用 format_spec.toc 重新生成）",
            ))
    # Round 44：图/表目录域在位校验（spec 声明了 index 就必须真的有
    # 对应 TOC \c 域——字面"图N"文本不算，必须可被 Word 收录）。
    if spec.figure_index is not None:
        checked.append("figure_index")
        if not _document_has_field_with_instr(doc, r'\c "图"'):
            issues.append(_issue(
                "figure_index/presence", "error",
                r'未检测到插图目录域（TOC \c "图"）',
                "用 format_spec.figure_index 重新生成（题注需 SEQ 域）",
            ))
    if spec.table_index is not None:
        checked.append("table_index")
        if not _document_has_field_with_instr(doc, r'\c "表"'):
            issues.append(_issue(
                "table_index/presence", "error",
                r'未检测到表格目录域（TOC \c "表"）',
                "用 format_spec.table_index 重新生成（题注需 SEQ 域）",
            ))
    if spec.numbering:
        checked.append("numbering")
        bib_heading = (
            spec.bibliography.heading_text if spec.bibliography is not None else "参考文献"
        )
        _check_numbering(doc, issues, bib_heading)
    if spec.page is not None or spec.body is not None or spec.headings:
        # 题注/引用连续性只在"格式化生成"语境下有意义，随结构规则一起启用
        checked.append("captions")
        _check_captions(doc, issues)
    checked.append("citations")
    _check_citations(doc, issues)
    # Round 45：交叉引用占位符残渍检查（无条件启用——残渍在任何语境
    # 下都是死文本）。
    checked.append("cross_ref")
    _check_cross_ref_residue(doc, issues)
    # Round 63：脚注/尾注引用一致性（损坏文档检出——引用 id 无对应
    # note 时 Word 打开即报"内容有问题"）。
    checked.append("ref_consistency")
    _check_ref_consistency(doc, issues)

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    return WordLintResult(
        ok=not errors,
        issue_count=len(issues),
        error_count=len(errors),
        warning_count=len(warnings),
        checked_rules=checked,
        issues=issues,
    )
