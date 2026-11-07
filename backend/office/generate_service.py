from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.office.models import (
    OfficeExcelGenerateRequest,
    OfficePptGenerateRequest,
    OfficeWordGenerateRequest,
    PdfGenerateRequest,
)

# ruff: noqa: UP006, UP007, UP035

_SUPPORTED_DOC_TYPES = ("word", "ppt", "excel", "pdf")

#: Payload key each doc type must supply at least one entry for.
_REQUIRED_LIST_KEY: Dict[str, str] = {
    "word": "paragraphs",
    "ppt": "slides",
    "excel": "sheets",
    "pdf": "pages",
}


def build_nl_prompt(
    *, instruction: str, doc_type: str, reference_texts: Optional[List[str]] = None
) -> str:
    """Build the LLM prompt for natural-language document generation."""
    kind = _normalize_doc_type(doc_type)
    body_key = _REQUIRED_LIST_KEY[kind]
    parts = [
        f"你是一个文档生成助手。请根据以下指令生成一份 {kind} 文档。",
        f"指令：{instruction}",
    ]
    if reference_texts:
        parts.append("参考资料：")
        for i, text in enumerate(reference_texts, 1):
            parts.append(f"[{i}] {text}")
    if kind == "word":
        parts.append(
            f'请只返回 JSON 对象，不要任何解释。结构为 {{"title": "...", "{body_key}": [...]}}。'
        )
    else:
        parts.append(f'请只返回 JSON 对象，不要任何解释。结构为 {{"{body_key}": [...]}}。')
    return "\n\n".join(parts)


def parse_llm_spec(text: str, doc_type: str) -> Dict[str, Any]:
    """Parse LLM JSON output into a validated ``{kind, ...payload}`` dict."""
    kind = _normalize_doc_type(doc_type)

    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse LLM output as JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("LLM output must be a JSON object")

    body_key = _REQUIRED_LIST_KEY[kind]
    body = data.get(body_key)
    if not isinstance(body, list) or not body:
        raise ValueError(f"LLM output yielded empty {kind} content (missing '{body_key}')")

    if kind == "word" and not data.get("title"):
        raise ValueError("LLM output yielded empty word content (missing 'title')")

    return {**data, "kind": kind}


def to_word_request(
    spec: Dict[str, Any], *, workspace_path: str, filename: str
) -> OfficeWordGenerateRequest:
    return OfficeWordGenerateRequest(
        workspace_path=workspace_path,
        filename=filename,
        title=spec["title"],
        paragraphs=spec.get("paragraphs") or [],
        tables=spec.get("tables") or [],
        images=spec.get("images") or [],
    )


def to_ppt_request(
    spec: Dict[str, Any], *, workspace_path: str, filename: str
) -> OfficePptGenerateRequest:
    return OfficePptGenerateRequest(
        workspace_path=workspace_path,
        filename=filename,
        slides=spec["slides"],
    )


def to_excel_request(
    spec: Dict[str, Any], *, workspace_path: str, filename: str
) -> OfficeExcelGenerateRequest:
    return OfficeExcelGenerateRequest(
        workspace_path=workspace_path,
        filename=filename,
        sheets=spec["sheets"],
    )


def to_pdf_request(
    spec: Dict[str, Any], *, workspace_path: str, filename: str
) -> PdfGenerateRequest:
    return PdfGenerateRequest(
        workspace_path=workspace_path,
        filename=filename,
        pages=spec["pages"],
    )


def next_iteration_filename(current: str) -> str:
    """Increment the version suffix: report.docx → report_v2.docx → report_v3.docx."""
    path = Path(current)
    match = re.match(r"^(.+?)_v(\d+)$", path.stem)
    if match:
        base = match.group(1)
        version = int(match.group(2)) + 1
    else:
        base = path.stem
        version = 2
    return f"{base}_v{version}{path.suffix}"


def _normalize_doc_type(doc_type: str) -> str:
    kind = (doc_type or "").strip().lower()
    if kind not in _SUPPORTED_DOC_TYPES:
        raise ValueError(f"Unsupported doc_type: {doc_type!r}")
    return kind
