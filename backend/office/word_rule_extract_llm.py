"""LLM-assisted rule candidates for spec documents (M3b).

The LLM only proposes JSON candidates; every candidate is re-validated
against a strict kind/params allowlist before it can enter the rule pack.
Invalid candidates are rejected (and counted), never trusted blindly.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .word_rule_extract_common import RawCandidate, add_candidate

MAX_CLAUSES = 40
MAX_CLAUSE_CHARS = 1000
MAX_TOTAL_CHARS = 12000
MAX_LLM_CONFIDENCE = 0.85

_ALLOWED_KINDS = (
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
_ALIGNMENTS = ("left", "center", "right", "justify", "distribute")
_PAGE_NUMBER_FORMATS = ("decimal", "upperRoman", "lowerRoman")
_HEX_COLOR_RE = re.compile(r"^[0-9A-Fa-f]{6}$")

_LLM_PROMPT = """你是 Word 规范文档的格式规则抽取器。只从给定条文中抽取可机械执行的规则。

允许的 kind 与 params（不得输出其他 kind 或字段）：
- page.size: {"size":"A4"|"Letter"}
- page.orientation: {"orientation":"portrait"|"landscape"}
- page.margins: {"top_cm"?:number,"bottom_cm"?:number,"left_cm"?:number,"right_cm"?:number}（单位 cm）
- page.page_number: {"required"?:boolean,"format"?:"decimal"|"upperRoman"|"lowerRoman"}
- style.font: {"style":"Normal","font_ascii"?:string,"font_east_asia"?:string,"size_pt"?:number}
- style.paragraph: {"style":"Normal","line_spacing"?:number,"line_spacing_pt"?:number,"first_line_indent_cm"?:number,"alignment"?:"left"|"center"|"right"|"justify"|"distribute"}
- structure.heading_sequence: {"levels":[1,2,...],"require_prefix":true}
- structure.required_headings: {"headings":["摘要","引言"],"match":"contains"}
- content.caption_sequence: {"labels":["图","表"]}

规则：
1. 只输出 JSON 数组，不要 markdown 围栏或解释。
2. 每条必须包含 clause_id、kind、params、confidence（0-1）、reason。
3. 不得编造条文中没有的数值；不确定时不要输出。
4. 没有规则时输出 []。

条文（JSON）：
{clauses}
"""


def build_clauses(paragraphs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pick a bounded set of clauses with stable ids for one LLM call."""
    clauses: List[Dict[str, Any]] = []
    total = 0
    for paragraph in paragraphs:
        text = str(paragraph.get("text") or "").strip()
        if not text:
            continue
        if len(clauses) >= MAX_CLAUSES:
            break
        chunk = text[:MAX_CLAUSE_CHARS]
        if total + len(chunk) > MAX_TOTAL_CHARS:
            break
        index = paragraph.get("index")
        clauses.append(
            {
                "clause_id": f"c{len(clauses) + 1}",
                "paragraph_index": int(index) if index is not None else 0,
                "text": chunk,
            }
        )
        total += len(chunk)
    return clauses


def parse_llm_rule_payload(text: str) -> List[Any]:
    """Parse a JSON array, tolerating markdown fences and surrounding prose."""
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("响应中没有 JSON 数组")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("响应不是 JSON 数组")
    return data


def _number(value: Any, minimum: float, maximum: float) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < minimum or number > maximum:
        return None
    return round(number, 2)


def validate_llm_params(kind: str, params: Any) -> Optional[Dict[str, Any]]:  # noqa: PLR0911 — per-kind allowlist
    """Strict per-kind validation; returns normalized params or None."""
    if kind not in _ALLOWED_KINDS or not isinstance(params, dict):
        return None
    if kind == "page.size":
        size = str(params.get("size") or "").strip().upper()
        return {"size": size} if size in ("A4", "LETTER") else None
    if kind == "page.orientation":
        orientation = str(params.get("orientation") or "").strip().lower()
        return (
            {"orientation": orientation}
            if orientation in ("portrait", "landscape")
            else None
        )
    if kind == "page.margins":
        result: Dict[str, Any] = {}
        for key in ("top_cm", "bottom_cm", "left_cm", "right_cm"):
            if key in params:
                number = _number(params[key], 0, 20)
                if number is None:
                    return None
                result[key] = number
        if "tolerance_cm" in params:
            number = _number(params["tolerance_cm"], 0, 2)
            if number is None:
                return None
            result["tolerance_cm"] = number
        return result or None
    if kind == "page.page_number":
        result = {}
        if "required" in params:
            result["required"] = bool(params["required"])
        if "format" in params:
            fmt = str(params["format"])
            if fmt not in _PAGE_NUMBER_FORMATS:
                return None
            result["format"] = fmt
        return result or None
    if kind == "style.font":
        result = {"style": "Normal"}
        for key in ("font_ascii", "font_east_asia"):
            if key in params:
                value = params[key]
                if not isinstance(value, str) or not value.strip():
                    return None
                result[key] = value.strip()[:100]
        if "size_pt" in params:
            number = _number(params["size_pt"], 5, 50)
            if number is None:
                return None
            result["size_pt"] = number
        for key in ("bold", "italic", "underline"):
            if key in params:
                result[key] = bool(params[key])
        if "color" in params:
            color = str(params["color"]).lstrip("#")
            if not _HEX_COLOR_RE.match(color):
                return None
            result["color"] = color.upper()
        return result if len(result) > 1 else None
    if kind == "style.paragraph":
        result = {"style": "Normal"}
        for key, minimum, maximum in (
            ("line_spacing", 0.5, 5.0),
            ("line_spacing_pt", 5.0, 100.0),
            ("first_line_indent_cm", 0.0, 5.0),
            ("tolerance_cm", 0.0, 2.0),
        ):
            if key in params:
                number = _number(params[key], minimum, maximum)
                if number is None:
                    return None
                result[key] = number
        if "alignment" in params:
            alignment = str(params["alignment"]).strip().lower()
            if alignment not in _ALIGNMENTS:
                return None
            result["alignment"] = alignment
        return result if len(result) > 1 else None
    if kind == "structure.heading_sequence":
        raw_levels = params.get("levels", [1, 2, 3])
        if not isinstance(raw_levels, list) or not raw_levels:
            return None
        try:
            levels = sorted({int(level) for level in raw_levels})
        except (TypeError, ValueError):
            return None
        if any(level < 1 or level > 9 for level in levels):
            return None
        return {"levels": levels, "require_prefix": bool(params.get("require_prefix", True))}
    if kind == "structure.required_headings":
        raw_headings = params.get("headings")
        if not isinstance(raw_headings, list):
            return None
        headings = [
            str(item).strip()
            for item in raw_headings
            if isinstance(item, str) and 2 <= len(str(item).strip()) <= 20
        ][:12]
        if not headings:
            return None
        return {"headings": headings, "match": "contains"}
    if kind == "content.caption_sequence":
        raw_labels = params.get("labels", ["图", "表"])
        if not isinstance(raw_labels, list):
            return None
        labels = [
            str(item).strip()
            for item in raw_labels
            if isinstance(item, str) and 1 <= len(str(item).strip()) <= 4
        ][:10]
        return {"labels": labels} if labels else None
    return None


async def propose_llm_candidates(
    rel_path: str,
    paragraphs: List[Dict[str, Any]],
    *,
    client: Any,
    warnings: List[Dict[str, str]],
) -> List[RawCandidate]:
    """Ask the LLM for candidates, then validate every one deterministically."""
    clauses = build_clauses(paragraphs)
    if not clauses:
        warnings.append(
            {"code": "llm_no_clauses", "message": "没有可发送给 LLM 的规范条文"}
        )
        return []
    prompt = _LLM_PROMPT.replace(
        "{clauses}", json.dumps(clauses, ensure_ascii=False)
    )
    try:
        text = await client.complete(prompt)
    except Exception as exc:  # noqa: BLE001 — LLM failures must degrade gracefully
        warnings.append(
            {"code": "llm_failed", "message": f"LLM 调用失败: {str(exc)[:300]}"}
        )
        return []
    try:
        items = parse_llm_rule_payload(text)
    except (ValueError, json.JSONDecodeError) as exc:
        warnings.append(
            {"code": "llm_parse_failed", "message": f"LLM 响应解析失败: {exc}"}
        )
        return []

    by_clause = {clause["clause_id"]: clause for clause in clauses}
    candidates: List[RawCandidate] = []
    rejected = 0
    for item in items:
        if not isinstance(item, dict):
            rejected += 1
            continue
        clause = by_clause.get(str(item.get("clause_id") or ""))
        kind = str(item.get("kind") or "")
        params = validate_llm_params(kind, item.get("params"))
        if clause is None or params is None:
            rejected += 1
            continue
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.3, min(MAX_LLM_CONFIDENCE, confidence))
        add_candidate(
            candidates,
            kind,
            params,
            confidence,
            f"{rel_path} 第 {clause['paragraph_index'] + 1} 段（LLM）",
            clause["text"],
            clause["paragraph_index"],
        )
    if rejected:
        warnings.append(
            {
                "code": "llm_candidate_rejected",
                "message": f"{rejected} 条 LLM 候选未通过确定性校验，已丢弃",
            }
        )
    return candidates


__all__ = [
    "build_clauses",
    "parse_llm_rule_payload",
    "propose_llm_candidates",
    "validate_llm_params",
]
