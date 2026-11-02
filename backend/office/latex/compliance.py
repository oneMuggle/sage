"""Deterministic journal-compliance check (TeX source + optional PDF)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .audit import audit_latex_file
from .models import LatexDocument
from .parser import LatexLimits, parse_latex_project
from .pdf_audit import audit_pdf
from .scanner import line_col, strip_comments

_METADATA_KEYS = {
    "document_class",
    "title",
    "author",
    "abstract",
    "keywords",
    "affiliation",
    "email",
    "date",
}
_PAGE_SIZES = {"a4": "A4", "letter": "Letter", "legal": "Legal"}
_GENERIC_META_RULES = {
    "title": "LATEX-META-TITLE",
    "author": "LATEX-META-AUTHOR",
    "abstract": "LATEX-META-ABSTRACT",
}


def _norm_list(value: Any) -> List[str]:
    if not isinstance(value, (list, tuple)):  # noqa: UP038 — py38 runtime isinstance
        return []
    items: List[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in items:
            items.append(text)
    return items


def _positive_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def normalize_profile(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    allowed_pages: List[str] = []
    for item in _norm_list(data.get("allowed_page_sizes")):
        canonical = _PAGE_SIZES.get(item.lower())
        if canonical and canonical not in allowed_pages:
            allowed_pages.append(canonical)
    try:
        dpi = float(data.get("min_image_dpi", 150.0))
    except (TypeError, ValueError):
        dpi = 150.0
    return {
        "required_sections": _norm_list(data.get("required_sections")),
        "required_metadata": _norm_list(data.get("required_metadata")),
        "allowed_page_sizes": allowed_pages,
        "required_min_pages": _positive_int(data.get("required_min_pages")),
        "required_max_pages": _positive_int(data.get("required_max_pages")),
        "require_embedded_fonts": bool(data.get("require_embedded_fonts", True)),
        "min_image_dpi": max(1.0, min(dpi, 2400.0)),
        "forbidden_commands": [
            item.lstrip("\\").strip()
            for item in _norm_list(data.get("forbidden_commands"))
            if item.lstrip("\\").strip()
        ],
    }


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def _issue(
    source: str,
    rule_id: str,
    severity: str,
    category: str,
    message: str,
    *,
    anchor: Optional[Dict[str, Any]] = None,
    fix_hint: str = "",
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source": source,
        "rule_id": rule_id,
        "severity": severity,
        "category": category,
        "message": message,
        "fix_hint": fix_hint,
    }
    if anchor:
        payload["anchor"] = anchor
    if evidence:
        payload["evidence"] = evidence
    return payload


def _metadata_present(doc: LatexDocument, key: str) -> bool:  # noqa: PLR0911
    if key == "document_class":
        return bool((doc.metadata.document_class or "").strip())
    if key == "title":
        return bool((doc.metadata.title or "").strip())
    if key == "author":
        return bool(doc.metadata.authors)
    if key == "abstract":
        return bool((doc.metadata.abstract or "").strip())
    if key == "keywords":
        return bool(doc.metadata.keywords)
    if key == "affiliation":
        return bool(doc.metadata.affiliations)
    if key == "email":
        return bool(doc.metadata.emails)
    if key == "date":
        return bool(doc.metadata.date)
    return False


def _metadata_issues(
    doc: LatexDocument,
    required: List[str],
    tex_rel: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    issues: List[Dict[str, Any]] = []
    profile_issues: List[Dict[str, Any]] = []
    for key in required:
        if key not in _METADATA_KEYS:
            profile_issues.append(
                _issue(
                    "profile",
                    "LATEX-COMPLIANCE-PROFILE",
                    "warning",
                    "profile",
                    f"未知的必需元数据键: {key}",
                    fix_hint="可用键: " + ", ".join(sorted(_METADATA_KEYS)),
                )
            )
            continue
        if _metadata_present(doc, key):
            continue
        issues.append(
            _issue(
                "tex",
                "LATEX-META-REQUIRED",
                "error",
                "metadata",
                f"缺少必需元数据: {key}",
                anchor={"file": tex_rel, "line": 1, "column": 1},
                fix_hint=f"补充 {key} 对应的导言区/正文声明",
                evidence={"key": key},
            )
        )
    return issues, profile_issues


def _forbidden_command_issues(
    clean: str,
    commands: List[str],
    tex_rel: str,
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for name in commands:
        pattern = re.compile(r"\\" + re.escape(name) + r"(?![A-Za-z@])")
        for match in pattern.finditer(clean):
            line, column = line_col(clean, match.start())
            issues.append(
                _issue(
                    "tex",
                    "LATEX-COMMAND-FORBIDDEN",
                    "error",
                    "compliance",
                    f"使用了禁用的 TeX 命令: \\{name}",
                    anchor={"file": tex_rel, "line": line, "column": column},
                    fix_hint="按期刊要求移除该命令",
                    evidence={"command": name},
                )
            )
    return issues


def _page_size_issues(
    pdf_result: Dict[str, Any],
    allowed: List[str],
) -> List[Dict[str, Any]]:
    if not allowed:
        return []
    size = pdf_result["summary"]["page_size"]
    label = str(size.get("label") or "Custom")
    base = label.replace(" (landscape)", "").strip()
    allowed_lower = {item.lower() for item in allowed}
    if base.lower() in allowed_lower:
        return []
    return [
        _issue(
            "pdf",
            "PDF-PAGE-SIZE-NOT-ALLOWED",
            "error",
            "pdf-page-size",
            f"页面尺寸 {label} 不在允许范围: {', '.join(allowed)}",
            anchor={"file": pdf_result["source_path"], "page": 1},
            fix_hint="按期刊要求调整页面尺寸后重新导出",
            evidence={"label": label, "allowed": allowed},
        )
    ]


def _dedupe(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in issues:
        anchor = item.get("anchor") or {}
        key = (
            item.get("source"),
            item.get("rule_id"),
            anchor.get("file"),
            anchor.get("line"),
            anchor.get("page"),
            item.get("message"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _check(
    check_id: str,
    label: str,
    issues: List[Dict[str, Any]],
    *,
    skipped: Optional[str] = None,
) -> Dict[str, Any]:
    if skipped is not None:
        return {
            "id": check_id,
            "label": label,
            "status": "skipped",
            "message": skipped,
            "rule_ids": [],
        }
    rule_ids = sorted({str(item.get("rule_id")) for item in issues})
    if any(item.get("severity") == "error" for item in issues):
        status, message = "fail", f"{len(issues)} 个问题"
    elif any(item.get("severity") == "warning" for item in issues):
        status, message = "warn", f"{len(issues)} 个问题"
    else:
        status, message = "pass", ""
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "message": message,
        "rule_ids": rule_ids,
    }


def _summary(issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    severity = {"error": 0, "warning": 0, "info": 0}
    categories: Dict[str, int] = {}
    for item in issues:
        severity[item["severity"]] = severity.get(item["severity"], 0) + 1
        category = item.get("category") or "other"
        categories[category] = categories.get(category, 0) + 1
    return {
        "count": len(issues),
        "severity": severity,
        "categories": categories,
    }


def check_latex_compliance(
    tex_path: Path,
    *,
    root: Path,
    pdf_path: Optional[Path] = None,
    profile: Optional[Dict[str, Any]] = None,
    limits: Optional[LatexLimits] = None,
) -> Dict[str, Any]:
    """Check a .tex project (and optional PDF) against a compliance profile."""
    limits = limits or LatexLimits()
    root_path = Path(root).resolve()
    tex = Path(tex_path)
    tex_rel = _rel(tex, root_path)
    normalized = normalize_profile(profile)

    audit = audit_latex_file(
        tex,
        root=root_path,
        required_sections=normalized["required_sections"],
        limits=limits,
    )
    metadata_required = normalized["required_metadata"]
    generic_rules = {
        _GENERIC_META_RULES[key]
        for key in metadata_required
        if key in _GENERIC_META_RULES
    }
    tex_issues: List[Dict[str, Any]] = [
        dict(item, source="tex")
        for item in audit["issues"]
        if item["rule_id"] not in generic_rules
    ]

    doc = parse_latex_project(tex, root=root_path, limits=limits)
    if metadata_required:
        meta_issues, meta_profile_issues = _metadata_issues(
            doc, metadata_required, tex_rel
        )
        tex_issues.extend(meta_issues)
        tex_issues.extend(meta_profile_issues)

    forbidden = normalized["forbidden_commands"]
    if forbidden:
        raw = tex.read_text(encoding="utf-8", errors="replace")
        clean = strip_comments(raw)
        tex_issues.extend(_forbidden_command_issues(clean, forbidden, tex_rel))

    pdf_result: Optional[Dict[str, Any]] = None
    pdf_issues: List[Dict[str, Any]] = []
    if pdf_path is not None:
        pdf_result = audit_pdf(
            Path(pdf_path),
            root=root_path,
            required_min_pages=normalized["required_min_pages"],
            required_max_pages=normalized["required_max_pages"],
            min_image_dpi=normalized["min_image_dpi"],
        )
        pdf_issues = [dict(item, source="pdf") for item in pdf_result["issues"]]
        if not normalized["require_embedded_fonts"]:
            pdf_issues = [
                item
                for item in pdf_issues
                if item["rule_id"] != "PDF-FONT-NOT-EMBEDDED"
            ]
        pdf_issues.extend(
            _page_size_issues(pdf_result, normalized["allowed_page_sizes"])
        )

    def of(
        rule_ids: Tuple[str, ...], items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        wanted = set(rule_ids)
        return [item for item in items if item["rule_id"] in wanted]

    has_pdf = pdf_result is not None
    page_count_required = (
        normalized["required_min_pages"] is not None
        or normalized["required_max_pages"] is not None
    )
    if not has_pdf:
        font_skip = "未提供 PDF"
    elif not normalized["require_embedded_fonts"]:
        font_skip = "未要求字体嵌入"
    else:
        font_skip = None
    checks = [
        _check(
            "tex.sections",
            "必需章节",
            of(("LATEX-SECTION-REQUIRED",), tex_issues),
            skipped=None if normalized["required_sections"] else "未配置必需章节",
        ),
        _check(
            "tex.metadata",
            "必需元数据",
            of(("LATEX-META-REQUIRED", "LATEX-DOC-CLASS"), tex_issues),
            skipped=None if metadata_required else "未配置必需元数据",
        ),
        _check(
            "tex.commands",
            "禁用命令",
            of(("LATEX-COMMAND-FORBIDDEN",), tex_issues),
            skipped=None if forbidden else "未配置禁用命令",
        ),
        _check(
            "pdf.page_count",
            "页数",
            of(("PDF-PAGE-COUNT",), pdf_issues),
            skipped=(
                "未提供 PDF"
                if not has_pdf
                else (None if page_count_required else "未配置页数要求")
            ),
        ),
        _check(
            "pdf.page_size",
            "页面尺寸",
            of(
                (
                    "PDF-PAGE-SIZE-NOT-ALLOWED",
                    "PDF-PAGE-SIZE-MIXED",
                    "PDF-PAGE-SIZE-UNUSUAL",
                ),
                pdf_issues,
            ),
            skipped=None if has_pdf else "未提供 PDF",
        ),
        _check(
            "pdf.fonts",
            "字体嵌入",
            of(("PDF-FONT-NOT-EMBEDDED",), pdf_issues),
            skipped=font_skip,
        ),
        _check(
            "pdf.images",
            "图片 DPI",
            of(("PDF-IMAGE-LOW-DPI",), pdf_issues),
            skipped=None if has_pdf else "未提供 PDF",
        ),
    ]

    issues = _dedupe(tex_issues + pdf_issues)
    summary = _summary(issues)
    return {
        "ok": summary["severity"]["error"] == 0,
        "tex_path": tex_rel,
        "pdf_path": _rel(Path(pdf_path), root_path) if pdf_path is not None else None,
        "profile": normalized,
        "checks": checks,
        "issues": issues,
        "summary": summary,
    }


__all__ = ["check_latex_compliance", "normalize_profile"]
