"""Deterministic Word audit engine (M2a).

Compiles a :class:`WordRulePack` into checks over the read-only
``DocumentProfile`` (M0) plus a few raw python-docx reads. Every issue
carries a ``scope`` and, where meaningful, a ``WordTextAnchor`` for the
M2c locator UI. This module never writes to the document.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from docx import Document
from docx.oxml.ns import qn

from .doc_profile import read_doc_profile
from .doc_profile_models import WordTextAnchor
from .errors import OfficeFileNotFoundError, OfficeParseError
from .word_lint import (
    _CITATION_MARKER_RE,
    _CROSS_REF_RESIDUE_RE,
    _HEADING_PREFIX_RE,
    _TABLE_CAPTION_RE,
    _expected_heading_prefix,
)
from .word_rulepack_models import (
    WordAuditIssue,
    WordAuditResult,
    WordAuditSummary,
    WordRulePack,
    WordRuleSpec,
)
from .word_semantic_audit import SEMANTIC_CHECKERS
from .word_template_profile import _PLACEHOLDER_RE

_PT_TO_MM = 25.4 / 72.0
_PT_TO_CM = 2.54 / 72.0
_MAX_HEADING_LEVELS = 9
_MAX_ISSUES = 1000
_PAGE_SIZES = {
    "A4": (210.0, 297.0, 1.0),
    "LETTER": (215.9, 279.4, 0.5),
}
_MARGIN_SIDES = (
    ("top", "margin_top_pt", "上"),
    ("bottom", "margin_bottom_pt", "下"),
    ("left", "margin_left_pt", "左"),
    ("right", "margin_right_pt", "右"),
)


def _anchor_of(paragraph: Dict[str, Any]) -> WordTextAnchor:
    return WordTextAnchor.model_validate(paragraph["anchor"])


def _float_param(rule: WordRuleSpec, key: str, default: Optional[float] = None) -> float:
    value = rule.params.get(key, default)
    if value is None:
        raise OfficeParseError(f"规则 {rule.id} 缺少参数 {key}")
    if isinstance(value, bool):
        raise OfficeParseError(f"规则 {rule.id} 参数 {key} 必须是数字")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise OfficeParseError(f"规则 {rule.id} 参数 {key} 必须是数字") from exc


def _int_param(rule: WordRuleSpec, key: str, default: Optional[int] = None) -> int:
    value = rule.params.get(key, default)
    if value is None:
        raise OfficeParseError(f"规则 {rule.id} 缺少参数 {key}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise OfficeParseError(f"规则 {rule.id} 参数 {key} 必须是整数") from exc


def _cm_from_pt(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value) * _PT_TO_CM, 3)


class _AuditContext:
    """Profile, raw document and emitted issues for one audit run."""

    def __init__(
        self, profile: Dict[str, Any], document: Any, pack: WordRulePack
    ) -> None:
        self.profile = profile
        self.document = document
        self.pack = pack
        self.issues: List[WordAuditIssue] = []
        self.truncated = False

    @property
    def paragraphs(self) -> List[Dict[str, Any]]:
        return self.profile["paragraphs"]

    def emit(
        self,
        rule: WordRuleSpec,
        message: str,
        *,
        expected: Optional[str] = None,
        actual: Optional[str] = None,
        anchor: Optional[WordTextAnchor] = None,
        scope: str = "document",
    ) -> None:
        if len(self.issues) >= _MAX_ISSUES:
            self.truncated = True
            return
        self.issues.append(
            WordAuditIssue(
                rule_id=rule.id,
                rule_pack_id=self.pack.id,
                category=rule.category,
                severity=rule.severity,
                scope=scope,
                message=message,
                expected=expected,
                actual=actual,
                fix_hint=rule.fix_hint,
                fixable=rule.fixable,
                source=rule.source or None,
                anchor=anchor,
            )
        )


def _outside_field_indices(document: Any) -> Set[int]:
    """Paragraph indices that are cached content inside a complex field.

    Mirrors ``word_lint._iter_paragraphs_outside_fields`` but returns
    indices so checks can join against ``DocumentProfile.paragraphs``.
    """
    inside = False
    excluded: Set[int] = set()
    for index, paragraph in enumerate(document.paragraphs):
        toggled = False
        for run in paragraph.runs:
            for fld in run._r.findall(qn("w:fldChar")):
                fld_type = fld.get(qn("w:fldCharType"))
                if fld_type == "begin":
                    inside = True
                    toggled = True
                elif fld_type == "end":
                    inside = False
                    toggled = True
        if inside and not toggled:
            excluded.add(index)
    return excluded


def _section_page_number_format(document: Any, index: int) -> Optional[str]:
    section = document.sections[index]
    pg_num = section._sectPr.find(qn("w:pgNumType"))
    return pg_num.get(qn("w:fmt")) if pg_num is not None else None


def _find_style_profile(
    profile: Dict[str, Any], style_name: str
) -> Optional[Dict[str, Any]]:
    target = style_name.strip().lower()
    for style in profile["styles"]:
        name = str(style.get("name") or "").strip().lower()
        style_id = str(style.get("style_id") or "").strip().lower()
        if target in (name, style_id):
            return style
    return None


def _find_raw_style(document: Any, style_profile: Dict[str, Any]) -> Any:
    target_name = str(style_profile.get("name") or "")
    target_id = str(style_profile.get("style_id") or "")
    for candidate in document.styles:
        if candidate.name == target_name or candidate.style_id == target_id:
            return candidate
    return None


def _style_anchor(ctx: _AuditContext, style_name: str) -> Optional[WordTextAnchor]:
    target = style_name.strip().lower()
    for paragraph in ctx.paragraphs:
        if str(paragraph.get("style") or "").strip().lower() == target:
            return _anchor_of(paragraph)
    return None


def _check_page_size(ctx: _AuditContext, rule: WordRuleSpec) -> None:
    expected_name = str(rule.params.get("size", "A4")).strip().upper()
    if expected_name not in _PAGE_SIZES:
        raise OfficeParseError(f"规则 {rule.id} 不支持页面尺寸 {expected_name}")
    expected_w, expected_h, tolerance = _PAGE_SIZES[expected_name]
    sections = ctx.profile["sections"]
    if not sections:
        ctx.emit(rule, "文档没有可读取的节", scope="section")
        return
    width_pt = sections[0].get("page_width_pt")
    height_pt = sections[0].get("page_height_pt")
    if width_pt is None or height_pt is None:
        ctx.emit(rule, "无法读取页面尺寸", scope="section")
        return
    width_mm = float(width_pt) * _PT_TO_MM
    height_mm = float(height_pt) * _PT_TO_MM
    short, long = sorted((width_mm, height_mm))
    if abs(short - expected_w) > tolerance or abs(long - expected_h) > tolerance:
        ctx.emit(
            rule,
            f"页面尺寸实测 {width_mm:.1f}×{height_mm:.1f}mm，"
            f"期望 {expected_name}（{expected_w:g}×{expected_h:g}mm）",
            expected=f"{expected_name} {expected_w:g}×{expected_h:g}mm",
            actual=f"{width_mm:.1f}×{height_mm:.1f}mm",
            scope="section",
        )


def _check_page_orientation(ctx: _AuditContext, rule: WordRuleSpec) -> None:
    expected = str(rule.params.get("orientation", "portrait")).strip().lower()
    if expected not in ("portrait", "landscape"):
        raise OfficeParseError(f"规则 {rule.id} 不支持页面方向 {expected}")
    for index, section in enumerate(ctx.profile["sections"]):
        actual = str(section.get("orientation") or "portrait").lower()
        if actual != expected:
            ctx.emit(
                rule,
                f"第 {index + 1} 节页面方向实测 {actual}，期望 {expected}",
                expected=expected,
                actual=actual,
                scope="section",
            )


def _check_page_margins(ctx: _AuditContext, rule: WordRuleSpec) -> None:
    tolerance = _float_param(rule, "tolerance_cm", 0.05)
    expected_margins = {
        side: rule.params.get(f"{side}_cm") for side, _key, _label in _MARGIN_SIDES
    }
    if all(value is None for value in expected_margins.values()):
        raise OfficeParseError(f"规则 {rule.id} 至少需要一项页边距参数")
    sections = ctx.profile["sections"]
    if not sections:
        ctx.emit(rule, "文档没有可读取的节", scope="section")
        return
    for side, key, label in _MARGIN_SIDES:
        expected_value = expected_margins[side]
        if expected_value is None:
            continue
        expected = float(expected_value)
        actual = _cm_from_pt(sections[0].get(key))
        if actual is None or abs(actual - expected) > tolerance:
            ctx.emit(
                rule,
                f"{label}页边距实测 {actual if actual is not None else '未设置'}cm，"
                f"期望 {expected:g}cm",
                expected=f"{expected:g}cm",
                actual=None if actual is None else f"{actual:g}cm",
                scope="section",
            )


def _check_page_number(ctx: _AuditContext, rule: WordRuleSpec) -> None:
    required = bool(rule.params.get("required", True))
    expected_format = rule.params.get("format")
    for index, section in enumerate(ctx.profile["sections"]):
        if required and not section.get("has_page_number_field"):
            ctx.emit(
                rule,
                f"第 {index + 1} 节页脚未检测到页码域（PAGE）",
                expected="页码域",
                actual="未设置",
                scope="section",
            )
        if expected_format:
            raw_format = _section_page_number_format(ctx.document, index)
            actual_format = raw_format or "decimal"
            if actual_format != str(expected_format):
                ctx.emit(
                    rule,
                    f"第 {index + 1} 节页码格式实测 {actual_format}，"
                    f"期望 {expected_format}",
                    expected=str(expected_format),
                    actual=actual_format,
                    scope="section",
                )


def _bool_label(value: bool) -> str:
    return "是" if value else "否"


def _check_style_font(ctx: _AuditContext, rule: WordRuleSpec) -> None:
    style_name = str(rule.params.get("style", "Normal"))
    style = _find_style_profile(ctx.profile, style_name)
    if style is None:
        ctx.emit(
            rule,
            f"文档中不存在样式 {style_name}",
            expected=style_name,
            actual="样式缺失",
            scope="style",
        )
        return
    anchor = _style_anchor(ctx, style_name)
    tolerance = _float_param(rule, "tolerance_pt", 0.01)
    for param_key, label, field in (
        ("font_ascii", "西文字体", "font_ascii"),
        ("font_east_asia", "中文字体", "font_east_asia"),
    ):
        if param_key not in rule.params:
            continue
        expected = str(rule.params[param_key])
        actual = str(style.get(field) or "")
        if actual != expected:
            ctx.emit(
                rule,
                f"样式 {style_name} 的{label}实测 {actual or '未设置'}，"
                f"期望 {expected}",
                expected=expected,
                actual=actual or "未设置",
                anchor=anchor,
                scope="style",
            )
    if "size_pt" in rule.params:
        expected_size = _float_param(rule, "size_pt")
        actual_size = style.get("size_pt")
        if actual_size is None or abs(float(actual_size) - expected_size) > tolerance:
            ctx.emit(
                rule,
                f"样式 {style_name} 字号实测 "
                f"{actual_size if actual_size is not None else '未设置'}pt，"
                f"期望 {expected_size:g}pt",
                expected=f"{expected_size:g}pt",
                actual=None if actual_size is None else f"{actual_size:g}pt",
                anchor=anchor,
                scope="style",
            )
    for param_key, label, field in (
        ("bold", "加粗", "bold"),
        ("italic", "斜体", "italic"),
        ("underline", "下划线", "underline"),
    ):
        if param_key not in rule.params:
            continue
        expected_bool = bool(rule.params[param_key])
        actual_bool = bool(style.get(field))
        if actual_bool != expected_bool:
            ctx.emit(
                rule,
                f"样式 {style_name} {label}实测 {_bool_label(actual_bool)}，"
                f"期望 {_bool_label(expected_bool)}",
                expected=_bool_label(expected_bool),
                actual=_bool_label(actual_bool),
                anchor=anchor,
                scope="style",
            )
    if "color" in rule.params:
        expected_color = str(rule.params["color"]).lstrip("#").upper()
        actual_color = str(style.get("color") or "").upper()
        if actual_color != expected_color:
            ctx.emit(
                rule,
                f"样式 {style_name} 字体颜色实测 {actual_color or '未设置'}，"
                f"期望 {expected_color}",
                expected=expected_color,
                actual=actual_color or "未设置",
                anchor=anchor,
                scope="style",
            )


def _check_style_paragraph(ctx: _AuditContext, rule: WordRuleSpec) -> None:
    style_name = str(rule.params.get("style", "Normal"))
    style_profile = _find_style_profile(ctx.profile, style_name)
    if style_profile is None:
        ctx.emit(
            rule,
            f"文档中不存在样式 {style_name}",
            expected=style_name,
            actual="样式缺失",
            scope="style",
        )
        return
    raw_style = _find_raw_style(ctx.document, style_profile)
    if raw_style is None:
        ctx.emit(
            rule,
            f"无法读取样式 {style_name} 的段落格式",
            actual="样式缺失",
            scope="style",
        )
        return
    fmt = raw_style.paragraph_format
    anchor = _style_anchor(ctx, style_name)
    if "line_spacing" in rule.params:
        expected_spacing = _float_param(rule, "line_spacing")
        actual_spacing = fmt.line_spacing
        actual_number = (
            float(actual_spacing)
            if isinstance(actual_spacing, (int, float))  # noqa: UP038 — py38 isinstance
            and not isinstance(actual_spacing, bool)
            else None
        )
        if actual_number is None or abs(actual_number - expected_spacing) > 0.01:
            ctx.emit(
                rule,
                f"样式 {style_name} 行距实测 "
                f"{actual_number if actual_number is not None else '固定值/未设置'}，"
                f"期望 {expected_spacing:g} 倍",
                expected=f"{expected_spacing:g} 倍",
                actual=(
                    f"{actual_number:g} 倍"
                    if actual_number is not None
                    else "固定值/未设置"
                ),
                anchor=anchor,
                scope="style",
            )
    if "line_spacing_pt" in rule.params:
        expected_pt = _float_param(rule, "line_spacing_pt")
        actual_spacing = fmt.line_spacing
        actual_pt = float(actual_spacing.pt) if hasattr(actual_spacing, "pt") else None
        if actual_pt is None or abs(actual_pt - expected_pt) > 0.5:
            ctx.emit(
                rule,
                f"样式 {style_name} 固定行距实测 "
                f"{actual_pt if actual_pt is not None else '未设置'}pt，"
                f"期望 {expected_pt:g}pt",
                expected=f"{expected_pt:g}pt",
                actual=None if actual_pt is None else f"{actual_pt:g}pt",
                anchor=anchor,
                scope="style",
            )
    if "first_line_indent_cm" in rule.params:
        expected_indent = _float_param(rule, "first_line_indent_cm")
        tolerance = _float_param(rule, "tolerance_cm", 0.05)
        indent = fmt.first_line_indent
        actual_indent = round(indent.cm, 3) if indent is not None else None
        if actual_indent is None or abs(actual_indent - expected_indent) > tolerance:
            ctx.emit(
                rule,
                f"样式 {style_name} 首行缩进实测 "
                f"{actual_indent if actual_indent is not None else '未设置'}cm，"
                f"期望 {expected_indent:g}cm",
                expected=f"{expected_indent:g}cm",
                actual=None if actual_indent is None else f"{actual_indent:g}cm",
                anchor=anchor,
                scope="style",
            )
    if "alignment" in rule.params:
        expected_alignment = str(rule.params["alignment"]).strip().lower()
        alignment = fmt.alignment
        actual_alignment = alignment.name.lower() if alignment is not None else "left"
        if actual_alignment != expected_alignment:
            ctx.emit(
                rule,
                f"样式 {style_name} 对齐方式实测 {actual_alignment}，"
                f"期望 {expected_alignment}",
                expected=expected_alignment,
                actual=actual_alignment,
                anchor=anchor,
                scope="style",
            )


def _check_heading_sequence(ctx: _AuditContext, rule: WordRuleSpec) -> None:
    raw_levels = rule.params.get("levels", [1, 2, 3])
    if not isinstance(raw_levels, list):
        raise OfficeParseError(f"规则 {rule.id} 参数 levels 必须是数组")
    try:
        levels = {int(level) for level in raw_levels}
    except (TypeError, ValueError) as exc:
        raise OfficeParseError(f"规则 {rule.id} 参数 levels 必须是整数数组") from exc
    if not levels or any(level < 1 or level > _MAX_HEADING_LEVELS for level in levels):
        raise OfficeParseError(f"规则 {rule.id} 参数 levels 超出 1–9")
    require_prefix = bool(rule.params.get("require_prefix", True))
    raw_skip = rule.params.get("skip_texts", ["参考文献"])
    if not isinstance(raw_skip, list):
        raise OfficeParseError(f"规则 {rule.id} 参数 skip_texts 必须是数组")
    skip_texts = {str(text).strip() for text in raw_skip}
    counters = [0] * _MAX_HEADING_LEVELS
    for paragraph in ctx.paragraphs:
        level = int(paragraph.get("level") or 0)
        if level not in levels:
            continue
        text = str(paragraph.get("text") or "").strip()
        anchor = _anchor_of(paragraph)
        if not text:
            ctx.emit(
                rule,
                f"标题段落为空（第 {paragraph.get('index')} 段）",
                expected="非空标题",
                actual="空标题",
                anchor=anchor,
                scope="paragraph",
            )
            continue
        if text in skip_texts:
            continue
        match = _HEADING_PREFIX_RE.match(text)
        if match is None:
            if require_prefix:
                ctx.emit(
                    rule,
                    f"标题缺少编号前缀: {text[:40]!r}",
                    expected="N / N.M / N.M.K",
                    actual=text[:40],
                    anchor=anchor,
                    scope="paragraph",
                )
            continue
        expected = _expected_heading_prefix(counters, level)
        if match.group(1) != expected:
            ctx.emit(
                rule,
                f"标题编号实测 {match.group(1)!r}，期望 {expected!r}: {text[:40]!r}",
                expected=expected,
                actual=match.group(1),
                anchor=anchor,
                scope="paragraph",
            )


def _check_required_headings(ctx: _AuditContext, rule: WordRuleSpec) -> None:
    headings = rule.params.get("headings")
    if not isinstance(headings, list) or not headings:
        raise OfficeParseError(f"规则 {rule.id} 参数 headings 必须是非空数组")
    mode = str(rule.params.get("match", "contains")).strip().lower()
    if mode not in ("contains", "exact"):
        raise OfficeParseError(f"规则 {rule.id} 参数 match 只能是 contains/exact")
    texts = [str(paragraph.get("text") or "").strip() for paragraph in ctx.paragraphs]
    for raw_target in headings:
        target = str(raw_target).strip()
        if not target:
            continue
        if mode == "exact":
            found = any(
                _HEADING_PREFIX_RE.sub("", text).strip() == target for text in texts
            )
        else:
            found = any(target in text for text in texts)
        if not found:
            ctx.emit(
                rule,
                f"缺少必含标题/章节: {target}",
                expected=target,
                actual="未找到",
                scope="document",
            )


def _check_placeholder_residue(ctx: _AuditContext, rule: WordRuleSpec) -> None:
    for paragraph in ctx.paragraphs:
        text = str(paragraph.get("text") or "")
        matches = [match.group(0) for match in _PLACEHOLDER_RE.finditer(text)]
        matches.extend(match.group(0) for match in _CROSS_REF_RESIDUE_RE.finditer(text))
        if matches:
            preview = ", ".join(matches[:3])
            ctx.emit(
                rule,
                f"段内存在未解析占位符: {preview}",
                actual=preview,
                anchor=_anchor_of(paragraph),
                scope="paragraph",
            )
    sdt_matches: List[str] = []
    for sdt in ctx.document.element.body.iter(qn("w:sdt")):
        text = "".join(item.text or "" for item in sdt.iter(qn("w:t")))
        sdt_matches.extend(match.group(0) for match in _PLACEHOLDER_RE.finditer(text))
        sdt_matches.extend(
            match.group(0) for match in _CROSS_REF_RESIDUE_RE.finditer(text)
        )
    if sdt_matches:
        preview = ", ".join(sdt_matches[:3])
        ctx.emit(
            rule,
            f"内容控件内存在未解析占位符: {preview}",
            actual=preview,
            scope="document",
        )


def _check_empty_paragraphs(ctx: _AuditContext, rule: WordRuleSpec) -> None:
    max_consecutive = _int_param(rule, "max_consecutive", 2)
    if max_consecutive < 0:
        raise OfficeParseError(f"规则 {rule.id} 参数 max_consecutive 不能为负")
    run_start: Optional[Dict[str, Any]] = None
    run_length = 0

    def _flush() -> None:
        nonlocal run_start, run_length
        if run_start is not None and run_length > max_consecutive:
            ctx.emit(
                rule,
                f"连续 {run_length} 个空段落（上限 {max_consecutive}）",
                expected=f"≤{max_consecutive}",
                actual=f"{run_length} 个空段落",
                anchor=_anchor_of(run_start),
                scope="paragraph",
            )
        run_start = None
        run_length = 0

    for paragraph in ctx.paragraphs:
        if str(paragraph.get("text") or "").strip() == "":
            if run_start is None:
                run_start = paragraph
            run_length += 1
        else:
            _flush()
    _flush()


def _check_caption_sequence(ctx: _AuditContext, rule: WordRuleSpec) -> None:
    labels = rule.params.get("labels", ["图", "表"])
    if not isinstance(labels, list) or not labels:
        raise OfficeParseError(f"规则 {rule.id} 参数 labels 必须是非空数组")
    excluded = _outside_field_indices(ctx.document)
    candidates = [
        paragraph for index, paragraph in enumerate(ctx.paragraphs) if index not in excluded
    ]
    for raw_label in labels:
        label = str(raw_label)
        if not label:
            continue
        pattern = re.compile(r"^" + re.escape(label) + r"(\d+)[　\s]")
        expected = 1
        for paragraph in candidates:
            text = str(paragraph.get("text") or "").strip()
            match = pattern.match(text)
            if match is None:
                continue
            actual = int(match.group(1))
            if actual != expected:
                ctx.emit(
                    rule,
                    f"{label}题注编号实测 {actual}，期望 {expected}（应从 1 连续递增）",
                    expected=str(expected),
                    actual=str(actual),
                    anchor=_anchor_of(paragraph),
                    scope="paragraph",
                )
                expected = actual
            expected += 1


def _check_citation_coverage(ctx: _AuditContext, rule: WordRuleSpec) -> None:
    excluded = _outside_field_indices(ctx.document)
    numbers: Set[int] = set()
    first_anchor: Optional[WordTextAnchor] = None
    for index, paragraph in enumerate(ctx.paragraphs):
        if index in excluded:
            continue
        if int(paragraph.get("level") or 0) > 0:
            continue
        text = str(paragraph.get("text") or "")
        if _TABLE_CAPTION_RE.match(text):
            continue
        for match in _CITATION_MARKER_RE.finditer(text):
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else start
            if end >= start:
                numbers.update(range(start, end + 1))
            if first_anchor is None:
                first_anchor = _anchor_of(paragraph)
    if not numbers:
        return
    max_seen = max(numbers)
    missing = sorted(set(range(1, max_seen + 1)) - numbers)
    if missing:
        ctx.emit(
            rule,
            f"引用标记 1..{max_seen} 中缺失 {missing}",
            expected=f"1..{max_seen} 连续",
            actual=f"缺 {len(missing)} 个",
            anchor=first_anchor,
            scope="paragraph",
        )


_CHECKERS: Dict[str, Callable[[_AuditContext, WordRuleSpec], None]] = {
    "page.size": _check_page_size,
    "page.orientation": _check_page_orientation,
    "page.margins": _check_page_margins,
    "page.page_number": _check_page_number,
    "style.font": _check_style_font,
    "style.paragraph": _check_style_paragraph,
    "structure.heading_sequence": _check_heading_sequence,
    "structure.required_headings": _check_required_headings,
    "content.placeholder_residue": _check_placeholder_residue,
    "content.empty_paragraphs": _check_empty_paragraphs,
    "content.caption_sequence": _check_caption_sequence,
    "content.citation_coverage": _check_citation_coverage,
    **SEMANTIC_CHECKERS,
}


def supported_rule_kinds() -> List[str]:
    """Return every checker kind understood by this engine."""
    return sorted(_CHECKERS)


def validate_rulepack(pack: WordRulePack) -> None:
    """Validate rule count, uniqueness and checker kinds before execution."""
    if not pack.rules:
        raise OfficeParseError("规则包至少包含 1 条规则")
    if len(pack.rules) > 500:
        raise OfficeParseError("单个规则包最多 500 条规则")
    seen: Set[str] = set()
    for rule in pack.rules:
        if rule.id in seen:
            raise OfficeParseError(f"规则 id 重复: {rule.id}")
        seen.add(rule.id)
        if rule.kind not in _CHECKERS:
            raise OfficeParseError(f"未知规则类型: {rule.kind}（规则 {rule.id}）")
        if len(rule.params) > 100:
            raise OfficeParseError(f"规则 {rule.id} 参数过多")


def audit_word_document(
    file_path: Path,
    rulepack: WordRulePack,
    *,
    workspace_path: Optional[str] = None,
) -> WordAuditResult:
    """Run deterministic checks and return anchored issues (read-only)."""
    path = Path(file_path)
    if not path.exists():
        raise OfficeFileNotFoundError(path)
    if not path.is_file():
        raise OfficeParseError("DOCX 路径不是文件")
    if path.suffix.lower() != ".docx":
        raise OfficeParseError("仅支持 .docx 文档审校")
    validate_rulepack(rulepack)
    profile = read_doc_profile(path, workspace_path=workspace_path)
    try:
        document = Document(str(path))
    except Exception as exc:  # noqa: BLE001 — map all parse failures
        raise OfficeParseError(f"Failed to parse DOCX: {exc}") from exc

    ctx = _AuditContext(profile, document, rulepack)
    for rule in rulepack.rules:
        _CHECKERS[rule.kind](ctx, rule)

    errors = [issue for issue in ctx.issues if issue.severity == "error"]
    warnings = [issue for issue in ctx.issues if issue.severity == "warning"]
    result_warnings = [dict(item) for item in profile.get("warnings", [])]
    if ctx.truncated:
        result_warnings.append(
            {
                "code": "issues_truncated",
                "message": f"问题数超过 {_MAX_ISSUES} 条，已截断",
            }
        )
    summary = WordAuditSummary(
        rules_checked=len(rulepack.rules),
        issue_count=len(ctx.issues),
        error_count=len(errors),
        warning_count=len(warnings),
        paragraphs=profile["summary"]["paragraphs"],
        tables=profile["summary"]["tables"],
        sections=profile["summary"]["sections"],
    )
    return WordAuditResult(
        ok=not errors,
        source_path=profile["source_path"],
        rule_pack_id=rulepack.id,
        rule_pack_name=rulepack.name,
        summary=summary,
        issues=ctx.issues,
        warnings=result_warnings,
    )


__all__ = [
    "audit_word_document",
    "supported_rule_kinds",
    "validate_rulepack",
]
