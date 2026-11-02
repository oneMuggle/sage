"""Shared constants and helpers for Word rule extraction (M3a)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PT_TO_MM = 25.4 / 72.0
PT_TO_CM = 2.54 / 72.0
NUMBER = r"([0-9]+(?:\.[0-9]+)?)"
SIDE_MAP = {"上": "top", "下": "bottom", "左": "left", "右": "right"}
SIDE_RE = re.compile(
    r"(上|下|左|右)(?:方|侧)?(?:页边距|边距)?[^0-9]{0,6}" + NUMBER + r"\s*(mm|毫米|cm|厘米)",
    re.I,
)
CJK_FONTS = (
    "仿宋_GB2312",
    "仿宋",
    "宋体",
    "黑体",
    "楷体_GB2312",
    "楷体",
    "微软雅黑",
    "方正小标宋简体",
    "小标宋",
)
LATIN_FONTS = ("Times New Roman", "Arial", "Calibri")
SIZE_MAP = {
    "初号": 42.0,
    "小初": 36.0,
    "一号": 26.0,
    "小一": 24.0,
    "二号": 22.0,
    "小二": 18.0,
    "三号": 16.0,
    "小三": 15.0,
    "四号": 14.0,
    "小四": 12.0,
    "五号": 10.5,
    "小五": 9.0,
}
KIND_ORDER = (
    "page.size",
    "page.orientation",
    "page.margins",
    "page.page_number",
    "style.font",
    "style.paragraph",
    "structure.heading_sequence",
    "structure.required_headings",
    "content.caption_sequence",
)
KIND_META: Dict[str, Tuple[str, str, str, str, bool]] = {
    "page.size": ("页面尺寸", "page", "error", "页面设置 → 纸张大小", True),
    "page.orientation": ("页面方向", "page", "error", "页面设置 → 方向", True),
    "page.margins": ("页边距", "page", "error", "页面设置 → 页边距", True),
    "page.page_number": ("页码", "page", "error", "页脚插入页码域（PAGE）", True),
    "style.font": ("正文字体", "style", "error", "修改 Normal 样式字体/字号", True),
    "style.paragraph": (
        "正文段落格式",
        "style",
        "error",
        "修改 Normal 样式行距/首行缩进/对齐",
        True,
    ),
    "structure.heading_sequence": (
        "标题编号",
        "structure",
        "warning",
        "按出现顺序重排标题编号",
        False,
    ),
    "structure.required_headings": (
        "必含章节",
        "structure",
        "warning",
        "补充缺失的章节",
        False,
    ),
    "content.caption_sequence": (
        "题注编号",
        "content",
        "warning",
        "重排图/表题注编号",
        False,
    ),
}
MERGE_FIELDS = {
    "page.margins": ("top_cm", "bottom_cm", "left_cm", "right_cm", "tolerance_cm"),
    "style.font": ("style", "font_ascii", "font_east_asia", "size_pt", "tolerance_pt"),
    "style.paragraph": (
        "style",
        "line_spacing",
        "line_spacing_pt",
        "first_line_indent_cm",
        "alignment",
        "tolerance_cm",
    ),
}


@dataclass
class RawCandidate:
    """Internal candidate before rule ids / pydantic conversion."""

    kind: str
    params: Dict[str, Any]
    confidence: float
    source: str
    excerpt: str
    paragraph_index: Optional[int] = None
    conflict_group: Optional[str] = None


def rel_path(path: Path, workspace_path: Optional[str]) -> str:
    if not workspace_path:
        return path.name
    try:
        return path.resolve().relative_to(Path(workspace_path).resolve()).as_posix()
    except ValueError:
        return path.name


def add_candidate(
    candidates: List[RawCandidate],
    kind: str,
    params: Dict[str, Any],
    confidence: float,
    source: str,
    excerpt: str,
    paragraph_index: Optional[int] = None,
) -> None:
    candidates.append(
        RawCandidate(
            kind=kind,
            params=dict(params),
            confidence=max(0.0, min(1.0, confidence)),
            source=source,
            excerpt=excerpt[:300],
            paragraph_index=paragraph_index,
        )
    )


def parse_size_pt(text: str) -> Optional[float]:
    for name, value in SIZE_MAP.items():
        if name in text:
            return value
    strict = re.search(
        r"(?:字号|字体大小)[:：]?\s*" + NUMBER + r"\s*(?:pt|磅)", text, re.I
    )
    if strict:
        return float(strict.group(1))
    for match in re.finditer(NUMBER + r"\s*(?:pt|磅)", text, re.I):
        prefix = text[max(0, match.start() - 8) : match.start()]
        if re.search(r"行距|间距|段前|段后", prefix):
            continue
        return float(match.group(1))
    return None


def dominant(values: List[Any]) -> Tuple[Any, float]:
    usable = [value for value in values if value is not None]
    if not usable:
        return None, 0.0
    counts = Counter(round(float(value), 2) for value in usable)
    value, count = counts.most_common(1)[0]
    return value, count / len(usable)


def is_body_style(style_name: str) -> bool:
    name = style_name.strip().lower()
    return name in ("normal", "body text", "正文") or "body" in name or "正文" in name


def normal_style_paragraph_format(document: Any) -> Dict[str, Any]:
    style = None
    for candidate in document.styles:
        name = str(getattr(candidate, "name", "") or "").strip().lower()
        style_id = str(getattr(candidate, "style_id", "") or "").strip().lower()
        if name == "normal" or style_id == "normal":
            style = candidate
            break
    if style is None:
        return {}
    fmt = style.paragraph_format
    result: Dict[str, Any] = {}
    spacing = fmt.line_spacing
    if spacing is not None:
        if isinstance(spacing, (int, float)) and not isinstance(spacing, bool):  # noqa: UP038
            result["line_spacing"] = float(spacing)
            result["line_spacing_rule"] = (
                fmt.line_spacing_rule.name.lower()
                if fmt.line_spacing_rule
                else "multiple"
            )
        else:
            result["line_spacing"] = float(spacing.pt)
            result["line_spacing_rule"] = (
                fmt.line_spacing_rule.name.lower() if fmt.line_spacing_rule else "exactly"
            )
    if fmt.first_line_indent is not None:
        result["first_line_indent_pt"] = float(fmt.first_line_indent.pt)
    if fmt.alignment is not None:
        result["alignment"] = fmt.alignment.name.lower()
    return result


def template_confidence(ratio: float) -> float:
    return max(0.5, min(0.95, ratio))


__all__ = [
    "CJK_FONTS",
    "KIND_META",
    "KIND_ORDER",
    "LATIN_FONTS",
    "MERGE_FIELDS",
    "NUMBER",
    "PT_TO_CM",
    "PT_TO_MM",
    "RawCandidate",
    "SIDE_MAP",
    "SIDE_RE",
    "SIZE_MAP",
    "add_candidate",
    "dominant",
    "is_body_style",
    "normal_style_paragraph_format",
    "parse_size_pt",
    "rel_path",
    "template_confidence",
]
