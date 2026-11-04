"""Template-document rule extraction (M3a)."""

from __future__ import annotations

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
        add_candidate(
            candidates,
            "page.page_number",
            {"required": True},
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
    return candidates


__all__ = ["extract_template_candidates"]
