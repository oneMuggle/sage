"""Specification-document rule extraction (M3a)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .doc_profile import read_doc_profile
from .errors import OfficeParseError
from .word_rule_extract_common import (
    CJK_FONTS,
    LATIN_FONTS,
    NUMBER,
    PT_TO_CM,
    SIDE_MAP,
    SIDE_RE,
    RawCandidate,
    add_candidate,
    parse_size_pt,
    rel_path,
)


def load_spec_paragraphs(
    path: Path, workspace_path: Optional[str]
) -> Tuple[List[Dict[str, Any]], str, List[Dict[str, str]]]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        profile = read_doc_profile(path, workspace_path=workspace_path)
        return (
            list(profile["paragraphs"]),
            str(profile["source_path"]),
            [dict(item) for item in profile.get("warnings", [])],
        )
    if suffix in (".txt", ".md"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise OfficeParseError(f"无法读取规范文本: {exc}") from exc
        paragraphs = [
            {"index": index, "text": line.strip()}
            for index, line in enumerate(text.splitlines())
            if line.strip()
        ]
        return paragraphs, rel_path(path, workspace_path), []
    raise OfficeParseError("规范文档仅支持 .docx/.txt/.md")


def extract_spec_candidates(
    paragraphs: List[Dict[str, Any]],
    rel: str,
    warnings: List[Dict[str, str]],
) -> List[RawCandidate]:
    candidates: List[RawCandidate] = []
    body_size_hint: Optional[float] = None
    for paragraph in paragraphs:
        text = str(paragraph.get("text") or "").strip()
        if not text:
            continue
        index = paragraph.get("index")
        source = f"{rel} 第 {int(index) + 1} 段" if index is not None else rel
        excerpt = text[:300]

        if re.search(r"\bA4\b|210\s*[×xX]\s*297", text):
            add_candidate(candidates, "page.size", {"size": "A4"}, 0.9, source, excerpt, index)
        elif re.search(r"\bletter\b|信纸|8\.5\s*[×xX]\s*11", text, re.I):
            add_candidate(
                candidates, "page.size", {"size": "Letter"}, 0.85, source, excerpt, index
            )

        if re.search(r"(?:页面|纸张|排版).{0,8}横向|横向(?:页面|排版)", text):
            add_candidate(
                candidates,
                "page.orientation",
                {"orientation": "landscape"},
                0.75,
                source,
                excerpt,
                index,
            )
        elif re.search(r"(?:页面|纸张|排版).{0,8}纵向|纵向(?:页面|排版)", text):
            add_candidate(
                candidates,
                "page.orientation",
                {"orientation": "portrait"},
                0.75,
                source,
                excerpt,
                index,
            )

        sides: Dict[str, float] = {}
        for match in SIDE_RE.finditer(text):
            side = SIDE_MAP[match.group(1)]
            value = float(match.group(2))
            unit = match.group(3).lower()
            if unit in ("mm", "毫米"):
                value /= 10.0
            sides[f"{side}_cm"] = round(value, 2)
        if sides:
            add_candidate(
                candidates,
                "page.margins",
                sides,
                0.55 + 0.1 * len(sides),
                source,
                excerpt,
                index,
            )

        cjk_font = next((name for name in CJK_FONTS if name in text), None)
        latin_font = next((name for name in LATIN_FONTS if name in text), None)
        size_pt = parse_size_pt(text)
        is_body_context = "正文" in text or (cjk_font is not None and "标题" not in text)
        if is_body_context and (cjk_font or latin_font or size_pt):
            params: Dict[str, Any] = {"style": "Normal"}
            if cjk_font:
                params["font_east_asia"] = cjk_font
            if latin_font:
                params["font_ascii"] = latin_font
            if size_pt:
                params["size_pt"] = size_pt
                body_size_hint = body_size_hint or size_pt
            if len(params) > 1:
                add_candidate(
                    candidates, "style.font", params, 0.85, source, excerpt, index
                )

        fixed_spacing = re.search(
            r"行距[^0-9]{0,10}" + NUMBER + r"\s*(?:磅|pt)", text, re.I
        )
        if fixed_spacing:
            add_candidate(
                candidates,
                "style.paragraph",
                {"style": "Normal", "line_spacing_pt": float(fixed_spacing.group(1))},
                0.85,
                source,
                excerpt,
                index,
            )
        else:
            multiple_spacing = re.search(r"行距[^0-9]{0,10}" + NUMBER + r"\s*倍", text)
            if multiple_spacing:
                add_candidate(
                    candidates,
                    "style.paragraph",
                    {"style": "Normal", "line_spacing": float(multiple_spacing.group(1))},
                    0.85,
                    source,
                    excerpt,
                    index,
                )

        indent = re.search(
            r"首行缩进[^0-9]{0,8}" + NUMBER + r"\s*(mm|毫米|cm|厘米|字符|字)", text
        )
        if indent:
            value = float(indent.group(1))
            unit = indent.group(2)
            if unit in ("字符", "字"):
                params = {"style": "Normal", "first_line_indent_chars": value}
            else:
                params = {
                    "style": "Normal",
                    "first_line_indent_cm": round(
                        value / 10.0 if unit in ("mm", "毫米") else value, 2
                    ),
                }
            add_candidate(
                candidates, "style.paragraph", params, 0.8, source, excerpt, index
            )

        if "页码" in text and ("页脚" in text or "页眉" in text):
            params = {"required": True}
            if "小写罗马" in text:
                params["format"] = "lowerRoman"
            elif "罗马" in text:
                params["format"] = "upperRoman"
            elif "阿拉伯" in text:
                params["format"] = "decimal"
            add_candidate(
                candidates, "page.page_number", params, 0.8, source, excerpt, index
            )

        if re.search(r"标题.{0,20}(?:编号|序号)", text) and (
            "1.1" in text or "1.1.1" in text or "多级" in text
        ):
            levels = [1, 2, 3] if "1.1.1" in text else [1, 2]
            add_candidate(
                candidates,
                "structure.heading_sequence",
                {"levels": levels, "require_prefix": True},
                0.75,
                source,
                excerpt,
                index,
            )

        required = re.search(
            r"(?:应包括|必须包含|应包含|需包含|包括)[^：:。]{0,12}[：:]\s*([^。；\n]+)",
            text,
        )
        if required:
            items = [
                item.strip(" 。.")
                for item in re.split(r"[、，,；;]|和|及", required.group(1))
                if item.strip()
            ]
            items = [item for item in items if 2 <= len(item) <= 20][:12]
            if len(items) >= 2:
                add_candidate(
                    candidates,
                    "structure.required_headings",
                    {"headings": items, "match": "contains"},
                    0.7,
                    source,
                    excerpt,
                    index,
                )

        if re.search(r"(图|表).{0,6}题注", text) and re.search(r"编号|连续|顺序", text):
            add_candidate(
                candidates,
                "content.caption_sequence",
                {"labels": ["图", "表"]},
                0.7,
                source,
                excerpt,
                index,
            )

    converted: List[RawCandidate] = []
    for candidate in candidates:
        chars = candidate.params.pop("first_line_indent_chars", None)
        if chars is not None:
            if body_size_hint is None:
                warnings.append(
                    {
                        "code": "char_indent_unconverted",
                        "message": "首行缩进按字符给出，但未识别正文字号，已跳过该候选",
                    }
                )
                continue
            candidate.params["first_line_indent_cm"] = round(
                float(chars) * body_size_hint * PT_TO_CM, 2
            )
        converted.append(candidate)
    return converted


__all__ = ["extract_spec_candidates", "load_spec_paragraphs"]
