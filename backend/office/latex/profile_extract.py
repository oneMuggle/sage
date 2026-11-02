"""Heuristic extraction of LaTeX compliance profiles from guideline documents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.office.errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficeSizeLimitError,
)
from backend.office.path_safety import resolve_within

from .compliance import normalize_profile

_MAX_SOURCE_BYTES = 20 * 1024 * 1024
_SOURCE_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".markdown"}
_BODY_SECTIONS = (
    "Introduction",
    "Related Work",
    "Background",
    "Methods",
    "Materials and Methods",
    "Experimental Setup",
    "Results",
    "Evaluation",
    "Discussion",
    "Conclusion",
    "Conclusions",
)
_PAGE_RANGE_RE = re.compile(
    r"(?i)(\d{1,3})\s*(?:[-–—~至到])\s*(\d{1,3})\s*(?:pages?|页)"
)
_PAGE_MAX_RE = re.compile(
    r"(?i)(?:max(?:imum)?|no more than|at most|不超过|最多|上限|限)"
    r"\D{0,16}(\d{1,3})\s*(?:pages?|页)"
)
_PAGE_MIN_RE = re.compile(
    r"(?i)(?:min(?:imum)?|at least|no less than|不少于|至少)"
    r"\D{0,16}(\d{1,3})\s*(?:pages?|页)"
)
_DPI_RE = re.compile(r"(?i)(\d{2,4})\s*dpi")
_FONT_RE = re.compile(
    r"(?i)(?:embed(?:ded|ding)?\s+(?:all\s+)?fonts|font\s+embedding|"
    r"嵌入(?:全部)?字体)"
)
_REQUIRED_WORD_RE = re.compile(
    r"(?i)(?:must|should|required|include|必需|必须|应当|应包括)"
)
_A4_RE = re.compile(r"(?i)\bA4\b")
_LETTER_RE = re.compile(r"(?i)\b(?:US\s+)?Letter\b|8\.5\s*[x×]\s*11")
_LEGAL_RE = re.compile(r"(?i)\bLegal\b")
_SECTION_PREFIX_RE = re.compile(r"^\s*(?:\d+[.)、]?\s*|[（(]\d+[）)]\s*)")


def _load_lines(path: Path, root: Path) -> List[Tuple[int, int, str]]:
    """Return (page, line_number, text) triples for a guideline document."""
    suffix = path.suffix.lower()
    lines: List[Tuple[int, int, str]] = []
    if suffix == ".pdf":
        from backend.office.pdf import read_pdf  # noqa: PLC0415 — heavy dependency

        result = read_pdf(path, workspace_path=str(root))
        for page in result.pages:
            for number, text in enumerate(page.text.splitlines(), start=1):
                lines.append((page.page_number, number, text))
        return lines
    if suffix == ".docx":
        from backend.office.word import read_docx  # noqa: PLC0415 — heavy dependency

        result = read_docx(path, workspace_path=str(root))
        for paragraph in result.paragraphs:
            for number, text in enumerate(paragraph.text.splitlines(), start=1):
                lines.append((1, number, text))
        for table in result.tables:
            for row in table.rows:
                lines.append((1, 1, " | ".join(row)))
        return lines
    text = path.read_text(encoding="utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), start=1):
        lines.append((1, number, line))
    return lines


def _evidence(
    field: str,
    value: Any,
    page: int,
    line_number: int,
    text: str,
    source: str,
) -> Dict[str, Any]:
    return {
        "field": field,
        "value": value,
        "snippet": text.strip()[:240],
        "source": source,
        "page": page,
        "line": line_number,
    }


def _page_limits(
    lines: List[Tuple[int, int, str]], source: str
) -> Tuple[Optional[int], Optional[int], List[Dict[str, Any]]]:
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    evidence: List[Dict[str, Any]] = []
    for page, number, text in lines:
        range_match = _PAGE_RANGE_RE.search(text)
        if range_match and minimum is None and maximum is None:
            low = int(range_match.group(1))
            high = int(range_match.group(2))
            if 0 < low <= high <= 5000:
                minimum, maximum = low, high
                evidence.append(
                    _evidence("required_min_pages", low, page, number, text, source)
                )
                evidence.append(
                    _evidence("required_max_pages", high, page, number, text, source)
                )
                continue
        if maximum is None:
            match = _PAGE_MAX_RE.search(text)
            if match:
                value = int(match.group(1))
                if 0 < value <= 5000:
                    maximum = value
                    evidence.append(
                        _evidence(
                            "required_max_pages", value, page, number, text, source
                        )
                    )
        if minimum is None:
            match = _PAGE_MIN_RE.search(text)
            if match:
                value = int(match.group(1))
                if 0 < value <= 5000:
                    minimum = value
                    evidence.append(
                        _evidence(
                            "required_min_pages", value, page, number, text, source
                        )
                    )
    return minimum, maximum, evidence


def _page_sizes(
    lines: List[Tuple[int, int, str]], source: str
) -> Tuple[List[str], List[Dict[str, Any]]]:
    found: List[str] = []
    evidence: List[Dict[str, Any]] = []
    for page, number, text in lines:
        for name, pattern in (
            ("A4", _A4_RE),
            ("Letter", _LETTER_RE),
            ("Legal", _LEGAL_RE),
        ):
            if name in found or not pattern.search(text):
                continue
            found.append(name)
            evidence.append(
                _evidence("allowed_page_sizes", name, page, number, text, source)
            )
    return found, evidence


def _sections(
    lines: List[Tuple[int, int, str]], source: str
) -> Tuple[List[str], List[Dict[str, Any]]]:
    found: List[str] = []
    evidence: List[Dict[str, Any]] = []
    for page, number, text in lines:
        stripped = _SECTION_PREFIX_RE.sub("", text).strip().rstrip(":：")
        for name in _BODY_SECTIONS:
            if name in found:
                continue
            if stripped.casefold() == name.casefold() and len(stripped) <= 60:
                found.append(name)
                evidence.append(
                    _evidence("required_sections", name, page, number, text, source)
                )
                continue
            if _REQUIRED_WORD_RE.search(text) and re.search(
                r"(?i)\b" + re.escape(name) + r"\b", text
            ):
                found.append(name)
                evidence.append(
                    _evidence("required_sections", name, page, number, text, source)
                )
    ordered = [name for name in _BODY_SECTIONS if name in found]
    return ordered, evidence


def _metadata_requirements(
    lines: List[Tuple[int, int, str]], source: str
) -> Tuple[List[str], List[Dict[str, Any]]]:
    found: List[str] = []
    evidence: List[Dict[str, Any]] = []
    for page, number, text in lines:
        if not _REQUIRED_WORD_RE.search(text):
            continue
        for key, pattern in (
            ("abstract", r"(?i)\babstract\b"),
            ("keywords", r"(?i)\bkey\s*words?\b|关键词"),
            ("title", r"(?i)\btitle\s+page\b|标题页"),
            ("author", r"(?i)\bauthor\s+(?:information|details)\b|作者信息"),
        ):
            if key in found or not re.search(pattern, text):
                continue
            found.append(key)
            evidence.append(
                _evidence("required_metadata", key, page, number, text, source)
            )
    return found, evidence


def _image_dpi(
    lines: List[Tuple[int, int, str]], source: str
) -> Tuple[Optional[int], List[Dict[str, Any]]]:
    for page, number, text in lines:
        match = _DPI_RE.search(text)
        if not match:
            continue
        value = int(match.group(1))
        if 72 <= value <= 1200:
            return value, [
                _evidence("min_image_dpi", value, page, number, text, source)
            ]
    return None, []


def _fonts(
    lines: List[Tuple[int, int, str]], source: str
) -> Tuple[bool, List[Dict[str, Any]]]:
    for page, number, text in lines:
        if _FONT_RE.search(text):
            return True, [
                _evidence(
                    "require_embedded_fonts", True, page, number, text, source
                )
            ]
    return False, []


def extract_latex_profile(
    source_path: Path,
    *,
    workspace: Path,
) -> Dict[str, Any]:
    """Extract a candidate compliance profile from a guideline document."""
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise OfficeParseError("工作区目录不存在")
    source = Path(source_path)
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    if source.suffix.lower() not in _SOURCE_SUFFIXES:
        raise OfficeParseError("仅支持 .pdf/.docx/.txt/.md 规范文档")
    resolved = resolve_within(root, source)
    size = resolved.stat().st_size
    if size > _MAX_SOURCE_BYTES:
        raise OfficeSizeLimitError(size, _MAX_SOURCE_BYTES)
    source_rel = resolved.relative_to(root).as_posix()

    lines = _load_lines(resolved, root)
    if not lines:
        raise OfficeParseError("规范文档没有可提取的文本")

    minimum, maximum, page_evidence = _page_limits(lines, source_rel)
    page_sizes, size_evidence = _page_sizes(lines, source_rel)
    sections, section_evidence = _sections(lines, source_rel)
    metadata, metadata_evidence = _metadata_requirements(lines, source_rel)
    dpi, dpi_evidence = _image_dpi(lines, source_rel)
    require_fonts, font_evidence = _fonts(lines, source_rel)

    profile = normalize_profile(
        {
            "required_sections": sections,
            "required_metadata": metadata,
            "allowed_page_sizes": page_sizes,
            "required_min_pages": minimum,
            "required_max_pages": maximum,
            "require_embedded_fonts": require_fonts,
            "min_image_dpi": dpi or 150,
            "forbidden_commands": [],
        }
    )
    warnings: List[Dict[str, str]] = []
    if minimum is None and maximum is None:
        warnings.append({"code": "no_page_limit", "message": "未识别到页数要求"})
    if not sections:
        warnings.append({"code": "no_sections", "message": "未识别到必需章节"})
    if dpi is None:
        warnings.append(
            {"code": "no_dpi", "message": "未识别到图片 DPI 要求，使用默认 150"}
        )
    warnings.append(
        {
            "code": "heuristic_only",
            "message": "自动抽取为启发式结果，请核对 evidence 后保存",
        }
    )
    evidence = (
        page_evidence
        + size_evidence
        + section_evidence
        + metadata_evidence
        + dpi_evidence
        + font_evidence
    )
    return {
        "ok": True,
        "source_path": source_rel,
        "profile": profile,
        "evidence": evidence,
        "warnings": warnings,
        "needs_review": True,
    }


__all__ = ["extract_latex_profile"]
