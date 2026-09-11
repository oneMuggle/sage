"""6 类规则校验：body_font / heading_font / line_spacing / margins / headings / citations。

容差：
- 字体同族算匹配（按 _FONT_FAMILY_ALIASES 归一化）
- 字号 ±0.5pt
- 边距 ±0.3cm

每条规则返回 Optional[JournalViolation]；validate_document 聚合所有规则 + 额外章节完整性警告。
"""
from __future__ import annotations

from typing import List, Optional

from docx import Document
from docx.oxml.ns import qn

from backend.office.journal.models import (
    CitationStyle,
    JournalSpec,
    JournalViolation,
    ViolationSeverity,
)

_TOLERANCE_PT = 0.5
_TOLERANCE_CM = 0.3


def _normalize(name: Optional[str]) -> str:
    if not name:
        return ""
    from backend.office.journal.parser import _FONT_FAMILY_ALIASES

    return _FONT_FAMILY_ALIASES.get(name.strip(), name.strip())


def _style_eastasia(style) -> str:
    if style is None:
        return ""
    rPr = style._element.find(qn("w:rPr"))
    if rPr is None:
        return ""
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        return ""
    return (rFonts.get(qn("w:eastAsia")) or "").strip()


def _style_pt(style) -> float:
    if style is None:
        return 0.0
    rPr = style._element.find(qn("w:rPr"))
    if rPr is None:
        return 0.0
    sz = rPr.find(qn("w:sz"))
    if sz is None:
        return 0.0
    val = sz.get(qn("w:val")) or "0"
    try:
        return float(val) / 2.0
    except ValueError:
        return 0.0


def check_body_font(doc: Document, spec: JournalSpec) -> Optional[JournalViolation]:
    normal = doc.styles["Normal"]
    actual_ea = _normalize(_style_eastasia(normal))
    expected_ea = _normalize(spec.font_body.eastasia)
    if not expected_ea:
        return None
    if actual_ea == expected_ea:
        return None
    return JournalViolation(
        rule_id="body_font",
        severity=ViolationSeverity.ERROR,
        message=f"正文 East Asian 字体应为 {expected_ea!r}，实际为 {actual_ea or '<unset>'}",
        location="Normal style",
        suggestion=f"将 Normal 样式 w:eastAsia 改为 {expected_ea}",
    )


def check_heading_font(doc: Document, spec: JournalSpec) -> Optional[JournalViolation]:
    heading_style = None
    for s in doc.styles:
        if s.name == "Heading 1":
            heading_style = s
            break
    if heading_style is None:
        return None  # 没 Heading 1 由 check_headings 报
    actual_ea = _normalize(_style_eastasia(heading_style))
    expected_ea = _normalize(spec.font_heading.eastasia) or _normalize(spec.font_body.eastasia)
    if not expected_ea or actual_ea == expected_ea:
        return None
    return JournalViolation(
        rule_id="heading_font",
        severity=ViolationSeverity.ERROR,
        message=f"标题字体应为 {expected_ea!r}，实际为 {actual_ea or '<unset>'}",
        location="Heading 1 style",
        suggestion=f"将 Heading 1 样式 w:eastAsia 改为 {expected_ea}",
    )


def check_body_size(doc: Document, spec: JournalSpec) -> Optional[JournalViolation]:
    normal = doc.styles["Normal"]
    actual_pt = _style_pt(normal)
    if actual_pt == 0.0 or spec.body_pt == 0.0:
        return None
    if abs(actual_pt - spec.body_pt) <= _TOLERANCE_PT:
        return None
    return JournalViolation(
        rule_id="body_size",
        severity=ViolationSeverity.ERROR,
        message=f"正文字号应为 {spec.body_pt}pt，实际为 {actual_pt}pt（容差 ±{_TOLERANCE_PT}pt）",
        location="Normal style",
        suggestion=f"将 Normal 样式 w:sz 改为 {int(spec.body_pt * 2)} (half-pt)",
    )


def check_line_spacing(doc: Document, spec: JournalSpec) -> Optional[JournalViolation]:
    normal = doc.styles["Normal"]
    pf = normal.paragraph_format
    actual = pf.line_spacing
    if actual is None:
        return None
    if isinstance(actual, (int, float)) and abs(float(actual) - spec.line_spacing) <= 0.05:  # noqa: UP038 - Py3.8
        return None
    return JournalViolation(
        rule_id="line_spacing",
        severity=ViolationSeverity.ERROR,
        message=f"正文行距应为 {spec.line_spacing} 倍，实际为 {actual} 倍",
        location="Normal paragraph_format",
        suggestion=f"将 line_spacing 改为 {spec.line_spacing}",
    )


def check_margins(doc: Document, spec: JournalSpec) -> Optional[JournalViolation]:
    if not doc.sections:
        return None
    section = doc.sections[0]
    actual_cm = (float(section.left_margin) / 360000.0) if section.left_margin else 0.0
    if actual_cm == 0.0 or spec.margins_cm == 0.0:
        return None
    if abs(actual_cm - spec.margins_cm) <= _TOLERANCE_CM:
        return None
    return JournalViolation(
        rule_id="margins",
        severity=ViolationSeverity.ERROR,
        message=f"页边距应为 {spec.margins_cm}cm，实际为 {actual_cm:.2f}cm（容差 ±{_TOLERANCE_CM}cm）",
        location="section 0",
        suggestion=f"将页边距改为 {spec.margins_cm}cm",
    )


def check_headings(doc: Document, spec: JournalSpec) -> Optional[JournalViolation]:
    present = [
        p.text.strip()
        for p in doc.paragraphs
        if p.style and p.style.name and p.style.name.startswith("Heading")
    ]
    missing = [h.keyword for h in spec.headings if h.keyword not in present]
    if not missing:
        return None
    return JournalViolation(
        rule_id="headings_missing",
        severity=ViolationSeverity.WARNING,
        message=f"缺失章节: {', '.join(missing)}",
        location="body",
        suggestion="按 spec.headings 顺序补充章节",
    )


def check_citations(doc: Document, spec: JournalSpec) -> Optional[JournalViolation]:
    """引用风格检测（info 级）。仅当 spec.citation_style != UNKNOWN 时运行。"""
    if spec.citation_style == CitationStyle.UNKNOWN:
        return None
    from backend.office.journal.parser import _detect_citation_style

    detected = _detect_citation_style(doc)
    if detected in {CitationStyle.UNKNOWN, spec.citation_style}:
        return None
    return JournalViolation(
        rule_id="citation_style",
        severity=ViolationSeverity.WARNING,
        message=f"引用风格应为 {spec.citation_style.value}，实际检测到 {detected.value}",
        location="body",
        suggestion=f"按 {spec.citation_style.value} 统一引用格式",
    )


def validate_document(doc: Document, spec: JournalSpec) -> List[JournalViolation]:
    """主入口：聚合 6 类规则结果。"""
    checks = [
        check_body_font,
        check_heading_font,
        check_body_size,
        check_line_spacing,
        check_margins,
        check_headings,
        check_citations,
    ]
    out: List[JournalViolation] = []
    for fn in checks:
        v = fn(doc, spec)
        if v is not None:
            out.append(v)
    return out


__all__ = [
    "validate_document",
    "check_body_font",
    "check_heading_font",
    "check_body_size",
    "check_line_spacing",
    "check_margins",
    "check_headings",
    "check_citations",
]
