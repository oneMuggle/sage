"""Template-document rule extraction (M3a)."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from .word_rule_extract_common import (
    PT_TO_CM,
    PT_TO_MM,
    RawCandidate,
    add_candidate,
    dominant,
    is_body_style,
    template_confidence,
)


def extract_template_candidates(
    profile: Dict[str, Any],
    rel: str,
    warnings: List[Dict[str, str]],
    style_format: Optional[Dict[str, Any]] = None,
) -> List[RawCandidate]:
    candidates: List[RawCandidate] = []
    sections = profile.get("sections") or []
    first = sections[0] if sections else {}
    source = f"{rel}（范本主导值）"
    excerpt = f"{rel} 模板剖面"

    width_pt = first.get("page_width_pt")
    height_pt = first.get("page_height_pt")
    if width_pt and height_pt:
        width_mm = float(width_pt) * PT_TO_MM
        height_mm = float(height_pt) * PT_TO_MM
        short, long = sorted((width_mm, height_mm))
        if abs(short - 210.0) <= 1.0 and abs(long - 297.0) <= 1.0:
            add_candidate(candidates, "page.size", {"size": "A4"}, 0.9, source, excerpt)
        elif abs(short - 215.9) <= 0.5 and abs(long - 279.4) <= 0.5:
            add_candidate(
                candidates, "page.size", {"size": "Letter"}, 0.9, source, excerpt
            )
        else:
            warnings.append(
                {
                    "code": "template_page_size_unknown",
                    "message": f"范本页面尺寸 {short:.1f}×{long:.1f}mm 不在支持列表",
                }
            )
        add_candidate(
            candidates,
            "page.orientation",
            {"orientation": str(first.get("orientation") or "portrait")},
            0.9,
            source,
            excerpt,
        )

    margins: Dict[str, float] = {}
    for side, key in (
        ("top", "margin_top_pt"),
        ("bottom", "margin_bottom_pt"),
        ("left", "margin_left_pt"),
        ("right", "margin_right_pt"),
    ):
        value = first.get(key)
        if value is not None:
            margins[f"{side}_cm"] = round(float(value) * PT_TO_CM, 2)
    if margins:
        add_candidate(candidates, "page.margins", margins, 0.9, source, excerpt)

    normal_style = next(
        (
            style
            for style in profile.get("styles", [])
            if str(style.get("name") or "").strip().lower() == "normal"
            or str(style.get("style_id") or "").strip().lower() == "normal"
        ),
        None,
    )
    if normal_style:
        params: Dict[str, Any] = {"style": "Normal"}
        for field_name in ("font_ascii", "font_east_asia", "size_pt"):
            if normal_style.get(field_name):
                params[field_name] = normal_style[field_name]
        if len(params) > 1:
            add_candidate(candidates, "style.font", params, 0.9, source, excerpt)
    else:
        warnings.append(
            {"code": "template_normal_style_missing", "message": "范本未找到 Normal 样式"}
        )

    samples = [
        paragraph
        for paragraph in profile.get("paragraphs", [])
        if str(paragraph.get("text") or "").strip()
        and int(paragraph.get("level") or 0) == 0
        and is_body_style(str(paragraph.get("style") or ""))
    ]
    if not samples:
        warnings.append(
            {
                "code": "template_no_body_samples",
                "message": "范本没有可识别的正文段落，已跳过正文字体/段落统计",
            }
        )
    else:
        fallback = style_format or {}
        spacing_pairs: List[Tuple[Any, str]] = []
        for paragraph in samples:
            spacing = paragraph.get("line_spacing")
            rule = paragraph.get("line_spacing_rule")
            if spacing is None:
                spacing = fallback.get("line_spacing")
                rule = rule or fallback.get("line_spacing_rule")
            if spacing is not None:
                spacing_pairs.append((spacing, str(rule or "").lower()))
        fixed_values = [value for value, rule in spacing_pairs if "exact" in rule]
        multiple_values = [value for value, rule in spacing_pairs if "exact" not in rule]
        if fixed_values and len(fixed_values) >= len(multiple_values):
            value, ratio = dominant(fixed_values)
            add_candidate(
                candidates,
                "style.paragraph",
                {"style": "Normal", "line_spacing_pt": round(float(value), 1)},
                template_confidence(ratio),
                source,
                f"{rel}：固定行距主导值 {value}pt（{ratio:.0%} 正文段落）",
            )
        elif multiple_values:
            value, ratio = dominant(multiple_values)
            add_candidate(
                candidates,
                "style.paragraph",
                {"style": "Normal", "line_spacing": float(value)},
                template_confidence(ratio),
                source,
                f"{rel}：行距主导值 {value} 倍（{ratio:.0%} 正文段落）",
            )

        indent_values = []
        for paragraph in samples:
            indent_pt = paragraph.get("first_line_indent_pt")
            if indent_pt is None:
                indent_pt = fallback.get("first_line_indent_pt")
            if indent_pt is not None:
                indent_values.append(round(float(indent_pt) * PT_TO_CM, 2))
        if indent_values:
            value, ratio = dominant(indent_values)
            add_candidate(
                candidates,
                "style.paragraph",
                {"style": "Normal", "first_line_indent_cm": value},
                template_confidence(ratio),
                source,
                f"{rel}：首行缩进主导值 {value}cm（{ratio:.0%} 正文段落）",
            )

        alignment_values = []
        for paragraph in samples:
            alignment = paragraph.get("alignment") or fallback.get("alignment")
            if alignment:
                alignment_values.append(str(alignment))
        if alignment_values:
            counts = Counter(alignment_values)
            value, count = counts.most_common(1)[0]
            ratio = count / len(alignment_values)
            if ratio >= 0.6:
                add_candidate(
                    candidates,
                    "style.paragraph",
                    {"style": "Normal", "alignment": value},
                    template_confidence(ratio),
                    source,
                    f"{rel}：对齐主导值 {value}（{ratio:.0%} 正文段落）",
                )

    if any(section.get("has_page_number_field") for section in sections):
        page_number_params: Dict[str, Any] = {"required": True}
        for section in sections:
            fmt = section.get("page_number_format")
            if fmt:
                page_number_params["format"] = fmt
                break
        add_candidate(
            candidates,
            "page.page_number",
            page_number_params,
            0.9,
            source,
            excerpt,
        )

    if len(sections) > 1:
        widths = {
            round(float(section["page_width_pt"]), 1)
            for section in sections
            if section.get("page_width_pt")
        }
        if len(widths) > 1:
            warnings.append(
                {
                    "code": "template_section_variation",
                    "message": "范本多节页面尺寸不一致，页面规则取第一节",
                }
            )

    _extract_heading_styles(profile, candidates, source, excerpt)
    _extract_special_styles(profile, candidates, source, excerpt)
    _extract_caption_sequence(profile, candidates, source, excerpt)
    return candidates


_HEADING_RE = re.compile(r"^heading\s+(\d+)$", re.IGNORECASE)
_CAPTION_RE = re.compile(r"^(图|表)(\d+)")

_SPECIAL_STYLE_KEYWORDS: Dict[str, str] = {
    "作者": "作者",
    "中文作者": "作者",
    "英文作者": "作者(英文)",
    "摘要": "摘要",
    "中文摘要": "摘要",
    "关键词": "关键词",
    "图题": "图题",
    "图说": "图题",
    "表题": "表题",
    "表文字": "表文字",
    "参考文献": "参考文献",
    "Header": "页眉",
}

_PARAGRAPH_FIELDS = (
    "alignment",
    "line_spacing",
    "line_spacing_pt",
    "space_before_pt",
    "space_after_pt",
    "first_line_indent_pt",
    "left_indent_pt",
)


def _extract_paragraph_format(
    style: Dict[str, Any],
    style_label: str,
    candidates: List[RawCandidate],
    source: str,
) -> None:
    """从样式数据中提取段落格式并生成 style.paragraph 规则。"""
    params: Dict[str, Any] = {"style": style_label}
    for field_name in _PARAGRAPH_FIELDS:
        value = style.get(field_name)
        if value is None:
            continue
        if field_name in ("first_line_indent_pt", "left_indent_pt"):
            params[field_name.replace("_pt", "_cm")] = round(float(value) * PT_TO_CM, 2)
        elif field_name.endswith("_pt"):
            params[field_name] = round(float(value), 1)
        else:
            params[field_name] = value

    if len(params) > 1:
        details = []
        if params.get("alignment"):
            details.append(f"对齐={params['alignment']}")
        if params.get("line_spacing"):
            details.append(f"行距={params['line_spacing']}倍")
        if params.get("line_spacing_pt"):
            details.append(f"行距={params['line_spacing_pt']}pt")
        if params.get("space_before_pt"):
            details.append(f"段前={params['space_before_pt']}pt")
        if params.get("space_after_pt"):
            details.append(f"段后={params['space_after_pt']}pt")
        add_candidate(
            candidates,
            "style.paragraph",
            params,
            0.85,
            source,
            f"{style_label} 段落格式: {', '.join(details)}",
        )


def _extract_heading_styles(
    profile: Dict[str, Any],
    candidates: List[RawCandidate],
    source: str,
    excerpt: str,
) -> None:
    """为 Heading 1-9 样式生成 style.font 和 style.paragraph 规则。"""
    styles = profile.get("styles", [])
    heading_levels: List[Tuple[int, Dict[str, Any]]] = []

    for style in styles:
        name = str(style.get("name") or "")
        match = _HEADING_RE.match(name)
        if match:
            level = int(match.group(1))
            heading_levels.append((level, style))

    heading_levels.sort(key=lambda item: item[0])
    for level, style in heading_levels:
        params: Dict[str, Any] = {"style": f"Heading {level}"}
        for field_name in ("font_ascii", "font_east_asia", "size_pt", "bold", "italic"):
            if style.get(field_name) is not None:
                params[field_name] = style[field_name]
        if len(params) > 1:
            add_candidate(
                candidates,
                "style.font",
                params,
                0.85,
                source,
                f"Heading {level} 样式: {style.get('font_east_asia', '?')}, {style.get('size_pt', '?')}pt",
            )
        _extract_paragraph_format(style, f"Heading {level}", candidates, source)

    if heading_levels:
        levels = [level for level, _ in heading_levels]
        add_candidate(
            candidates,
            "structure.heading_sequence",
            {"levels": levels, "require_prefix": True},
            0.8,
            source,
            f"模板包含 {len(levels)} 个标题层级: {levels}",
        )


def _extract_special_styles(
    profile: Dict[str, Any],
    candidates: List[RawCandidate],
    source: str,
    excerpt: str,
) -> None:
    """为模板中的特殊样式（作者、摘要、图题、表题、参考文献等）生成 style.font 和 style.paragraph 规则。"""
    styles = profile.get("styles", [])
    seen: set[str] = set()

    for style in styles:
        name = str(style.get("name") or "")
        label = _SPECIAL_STYLE_KEYWORDS.get(name)
        if label is None:
            continue
        if label in seen:
            continue
        seen.add(label)

        params: Dict[str, Any] = {"style": label}
        for field_name in ("font_ascii", "font_east_asia", "size_pt", "bold", "italic"):
            if style.get(field_name) is not None:
                params[field_name] = style[field_name]
        if len(params) > 1:
            add_candidate(
                candidates,
                "style.font",
                params,
                0.8,
                source,
                f"{label} 样式: {style.get('font_east_asia', '?')}, {style.get('size_pt', '?')}pt",
            )
        _extract_paragraph_format(style, label, candidates, source)


def _extract_caption_sequence(
    profile: Dict[str, Any],
    candidates: List[RawCandidate],
    source: str,
    excerpt: str,
) -> None:
    """从模板段落中检测图/表题注编号，产出 content.caption_sequence 规则。"""
    found_labels: Set[str] = set()
    for paragraph in profile.get("paragraphs", []):
        text = str(paragraph.get("text") or "").strip()
        if not text:
            continue
        match = _CAPTION_RE.match(text)
        if match:
            found_labels.add(match.group(1))

    if not found_labels:
        return

    ordered = [label for label in ("图", "表") if label in found_labels]
    add_candidate(
        candidates,
        "content.caption_sequence",
        {"labels": ordered},
        0.9,
        source,
        f"模板中检测到题注标签: {', '.join(ordered)}",
    )


__all__ = ["extract_template_candidates"]
