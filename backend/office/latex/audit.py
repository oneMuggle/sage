"""Deterministic LaTeX source audit (no TeX execution)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.office.errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficePathError,
    OfficeSizeLimitError,
)
from backend.office.path_safety import is_within

from .models import LatexAnchor, LatexDocument
from .parser import LatexLimits, parse_latex_project
from .scanner import line_col, parse_command, strip_comments

_ISSUE_SEVERITIES = ("error", "warning", "info")

_INCLUDE_WARNING_CODES = {
    "include_path_escape": ("error", "LATEX-INCLUDE"),
    "include_unsafe_target": ("error", "LATEX-INCLUDE"),
    "include_cycle": ("warning", "LATEX-INCLUDE"),
    "missing_include": ("warning", "LATEX-INCLUDE"),
    "include_too_large": ("warning", "LATEX-INCLUDE"),
    "include_depth_exceeded": ("warning", "LATEX-INCLUDE"),
    "include_file_limit": ("warning", "LATEX-INCLUDE"),
    "missing_bibliography": ("warning", "LATEX-BIBLIOGRAPHY"),
    "bibliography_parse_error": ("warning", "LATEX-BIBLIOGRAPHY"),
    "missing_image": ("warning", "LATEX-IMAGE"),
    "unsupported_image_format": ("warning", "LATEX-IMAGE"),
    "external_image": ("warning", "LATEX-IMAGE"),
    "image_too_large": ("warning", "LATEX-IMAGE"),
    "image_read_error": ("warning", "LATEX-IMAGE"),
}

_RESIDUE_PATTERNS = (
    re.compile(r"<<[^<>\n]{1,120}>>"),
    re.compile(r"\[\[[^\[\]\n]{1,120}\]\]"),
    re.compile(r"【[^【】\n]{1,120}】"),
    re.compile(r"\\todo\s*\{[^{}]{1,200}\}"),
    re.compile(r"\b(?:TODO|FIXME|XXX)\b"),
)

_UNSAFE_COMMANDS = {
    "write18",
    "openin",
    "openout",
    "read",
    "input",
    "include",
    "subfile",
    "includegraphics",
    "lstinputlisting",
    "verbatiminput",
    "import",
    "subimport",
}

# TeX command names are letters only, so ``\write18`` is parsed as ``\write``
# followed by the number 18. Detect the primitive pair explicitly.
_WRITE18_RE = re.compile(r"\\write\s*18\b")
_PIPE_INPUT_RE = re.compile(r"\\(?:input|include|openin)\s*(?:=\s*)?\|")
_BARE_INPUT_RE = re.compile(r"\\(?:input|include)\s+([^\s{]+)")


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def _anchor(file_path: Path, root: Path, text: str, pos: int) -> LatexAnchor:
    line, column = line_col(text, pos)
    return LatexAnchor(_rel(file_path, root), line, column)


def _issue(
    rule_id: str,
    severity: str,
    category: str,
    message: str,
    *,
    anchor: Optional[LatexAnchor] = None,
    fix_hint: str = "",
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if severity not in _ISSUE_SEVERITIES:
        severity = "warning"
    payload: Dict[str, Any] = {
        "rule_id": rule_id,
        "severity": severity,
        "category": category,
        "message": message,
        "fix_hint": fix_hint,
    }
    if anchor is not None:
        payload["anchor"] = anchor.to_dict()
    if evidence:
        payload["evidence"] = evidence
    return payload


def _normalize_heading(text: str) -> str:
    cleaned = re.sub(r"[*`$]", "", text or "")
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def _metadata_issues(
    doc: LatexDocument, file_path: Path, root: Path, raw: str
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    anchor = _anchor(file_path, root, raw, 0)
    if not doc.metadata.document_class:
        issues.append(
            _issue(
                "LATEX-DOC-CLASS",
                "error",
                "metadata",
                "缺少 \\documentclass",
                anchor=anchor,
                fix_hint="在导言区声明目标期刊/会议文档类",
            )
        )
    if not (doc.metadata.title or "").strip():
        issues.append(
            _issue(
                "LATEX-META-TITLE",
                "warning",
                "metadata",
                "缺少标题（\\title）",
                anchor=anchor,
                fix_hint="添加 \\title{...} 并检查 \\maketitle",
            )
        )
    if not doc.metadata.authors:
        issues.append(
            _issue(
                "LATEX-META-AUTHOR",
                "warning",
                "metadata",
                "缺少作者（\\author）",
                anchor=anchor,
                fix_hint="添加 \\author{...}；多作者用 \\and 分隔",
            )
        )
    if not (doc.metadata.abstract or "").strip():
        issues.append(
            _issue(
                "LATEX-META-ABSTRACT",
                "warning",
                "metadata",
                "缺少摘要（abstract 环境）",
                anchor=anchor,
                fix_hint="添加 \\begin{abstract}...\\end{abstract}",
            )
        )
    return issues


def _required_section_issues(
    doc: LatexDocument,
    required_sections: List[str],
    file_path: Path,
    root: Path,
    raw: str,
) -> List[Dict[str, Any]]:
    if not required_sections:
        return []
    headings = [
        _normalize_heading(block.text)
        for block in doc.blocks
        if block.type == "heading"
    ]
    issues: List[Dict[str, Any]] = []
    for required in required_sections:
        target = _normalize_heading(required)
        if not target:
            continue
        if not any(target in heading for heading in headings):
            issues.append(
                _issue(
                    "LATEX-SECTION-REQUIRED",
                    "error",
                    "structure",
                    f"缺少必需章节: {required}",
                    anchor=_anchor(file_path, root, raw, 0),
                    fix_hint=f"添加 \\section{{{required}}} 或对应期刊章节",
                    evidence={"required_section": required},
                )
            )
    return issues


def _scan_command_positions(
    text: str, names: Iterable[str]
) -> List[Tuple[str, int, List[str]]]:
    wanted = set(names)
    found: List[Tuple[str, int, List[str]]] = []
    pos = 0
    n = len(text)
    while pos < n:
        idx = text.find("\\", pos)
        if idx < 0:
            break
        cmd = parse_command(text, idx)
        if cmd is None:
            pos = idx + 1
            continue
        if cmd.name in wanted:
            found.append((cmd.name, cmd.start, list(cmd.args)))
        pos = cmd.end if cmd.end > idx else idx + 1
    return found


def _bibliography_keys(doc: LatexDocument) -> set:
    keys = set()
    for block in doc.blocks:
        if block.type == "bibliography":
            for entry in block.entries:
                key = entry.get("key")
                if key:
                    keys.add(key)
    return keys


def _citation_issues(
    doc: LatexDocument, file_path: Path, root: Path, clean: str
) -> List[Dict[str, Any]]:
    cite_keys = set(doc.citations)
    if not cite_keys:
        return []
    bib_keys = _bibliography_keys(doc)
    if not bib_keys:
        return [
            _issue(
                "LATEX-CITE-NO-BIB",
                "warning",
                "citation",
                "文档包含 \\cite 但未解析到参考文献条目",
                anchor=_anchor(file_path, root, clean, 0),
                fix_hint="添加 \\bibliography{...} / thebibliography，或检查 .bib 路径",
            )
        ]
    positions: Dict[str, Tuple[int, int]] = {}
    for _name, start, args in _scan_command_positions(
        clean, ("cite", "citep", "citet", "parencite", "textcite")
    ):
        if not args:
            continue
        for key in (item.strip() for item in args[0].split(",")):
            if key and key not in positions:
                positions[key] = line_col(clean, start)
    issues: List[Dict[str, Any]] = []
    for key in sorted(cite_keys - bib_keys):
        line, column = positions.get(key, (1, 1))
        issues.append(
            _issue(
                "LATEX-CITE-UNDEFINED",
                "error",
                "citation",
                f"引用 key 未在参考文献中找到: {key}",
                anchor=LatexAnchor(_rel(file_path, root), line, column),
                fix_hint="在 .bib 中添加该条目，或修正 \\cite key",
                evidence={"key": key},
            )
        )
    return issues


def _reference_issues(doc: LatexDocument) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for warning in doc.warnings:
        if warning.code != "undefined_reference":
            continue
        target = str(warning.detail.get("target") or "")
        issues.append(
            _issue(
                "LATEX-REF-UNDEFINED",
                "error",
                "reference",
                f"交叉引用未定义: {target}",
                anchor=warning.anchor,
                fix_hint="添加对应 \\label{...} 或修正 \\ref/\\eqref",
                evidence={"target": target},
            )
        )
    return issues


def _asset_issues(doc: LatexDocument) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for block in doc.blocks:
        if block.type == "figure":
            if not (block.caption or "").strip():
                issues.append(
                    _issue(
                        "LATEX-FIG-CAPTION",
                        "warning",
                        "figure",
                        "图缺少 caption",
                        anchor=block.anchor,
                        fix_hint="添加 \\caption{...}",
                    )
                )
            if not block.label:
                issues.append(
                    _issue(
                        "LATEX-FIG-LABEL",
                        "warning",
                        "figure",
                        "图缺少 label，正文无法交叉引用",
                        anchor=block.anchor,
                        fix_hint="添加 \\label{fig:...}",
                    )
                )
        elif block.type == "table":
            if not (block.caption or "").strip():
                issues.append(
                    _issue(
                        "LATEX-TABLE-CAPTION",
                        "warning",
                        "table",
                        "表缺少 caption",
                        anchor=block.anchor,
                        fix_hint="添加 \\caption{...}",
                    )
                )
            if not block.label:
                issues.append(
                    _issue(
                        "LATEX-TABLE-LABEL",
                        "warning",
                        "table",
                        "表缺少 label，正文无法交叉引用",
                        anchor=block.anchor,
                        fix_hint="添加 \\label{tab:...}",
                    )
                )
    return issues


def _duplicate_label_issues(
    clean: str, file_path: Path, root: Path
) -> List[Dict[str, Any]]:
    seen: Dict[str, int] = {}
    issues: List[Dict[str, Any]] = []
    for _name, start, args in _scan_command_positions(clean, ("label",)):
        if not args:
            continue
        key = args[0].strip()
        if not key:
            continue
        if key in seen:
            issues.append(
                _issue(
                    "LATEX-LABEL-DUPLICATE",
                    "warning",
                    "label",
                    f"重复 label: {key}",
                    anchor=_anchor(file_path, root, clean, start),
                    fix_hint="为每个图/表/公式/章节使用唯一 label",
                    evidence={"key": key, "first_line": seen[key]},
                )
            )
        else:
            seen[key] = line_col(clean, start)[0]
    return issues


def _residue_issues(
    raw: str, file_path: Path, root: Path
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    seen: set = set()
    for pattern in _RESIDUE_PATTERNS:
        for match in pattern.finditer(raw):
            text = match.group(0)
            pos = match.start()
            key = (text, pos)
            if key in seen:
                continue
            seen.add(key)
            issues.append(
                _issue(
                    "LATEX-TODO",
                    "warning",
                    "hygiene",
                    f"残留占位符/待办: {text[:80]}",
                    anchor=_anchor(file_path, root, raw, pos),
                    fix_hint="提交前清理 TODO/占位符，或替换为最终内容",
                )
            )
    return issues


def _is_unsafe_target(value: str) -> bool:
    target = value.strip().strip('"')
    if not target:
        return False
    if target.startswith(("http://", "https://", "|")):
        return True
    if target.startswith(("/", "\\")):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", target):
        return True
    parts = target.replace("\\", "/").split("/")
    return ".." in parts


def _unsafe_command_issues(
    clean: str, file_path: Path, root: Path
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for pattern, message in (
        (_WRITE18_RE, "危险 TeX 命令: \\write18（shell escape）"),
        (_PIPE_INPUT_RE, "危险 TeX 管道输入（|）"),
    ):
        for match in pattern.finditer(clean):
            issues.append(
                _issue(
                    "LATEX-UNSAFE-COMMAND",
                    "error",
                    "security",
                    message,
                    anchor=_anchor(file_path, root, clean, match.start()),
                    fix_hint="移除该命令；编译时使用 no-shell-escape 与 OS 级隔离",
                )
            )
    for match in _BARE_INPUT_RE.finditer(clean):
        target = match.group(1)
        if _is_unsafe_target(target):
            issues.append(
                _issue(
                    "LATEX-UNSAFE-COMMAND",
                    "error",
                    "security",
                    f"\\input/\\include 使用绝对路径/越界路径: {target}",
                    anchor=_anchor(file_path, root, clean, match.start()),
                    fix_hint="改为项目内相对路径；不要使用管道/URL/绝对路径",
                    evidence={"target": target},
                )
            )
    for name, start, args in _scan_command_positions(clean, _UNSAFE_COMMANDS):
        if name in ("write18", "openin", "openout", "read"):
            issues.append(
                _issue(
                    "LATEX-UNSAFE-COMMAND",
                    "error",
                    "security",
                    f"危险 TeX 命令: \\{name}",
                    anchor=_anchor(file_path, root, clean, start),
                    fix_hint="移除该命令；编译时使用 no-shell-escape 与 OS 级隔离",
                    evidence={"command": name},
                )
            )
            continue
        for arg in args[:1]:
            if _is_unsafe_target(arg):
                issues.append(
                    _issue(
                        "LATEX-UNSAFE-COMMAND",
                        "error",
                        "security",
                        f"\\{name} 使用绝对路径/管道/越界路径: {arg}",
                        anchor=_anchor(file_path, root, clean, start),
                        fix_hint="改为项目内相对路径；不要使用管道/URL/绝对路径",
                        evidence={"command": name, "target": arg},
                    )
                )
                break
    return issues


def _parser_warning_issues(doc: LatexDocument) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for warning in doc.warnings:
        mapping = _INCLUDE_WARNING_CODES.get(warning.code)
        if mapping is None:
            continue
        severity, rule_id = mapping
        issues.append(
            _issue(
                rule_id,
                severity,
                "include",
                warning.message,
                anchor=warning.anchor,
                fix_hint="检查路径/文件是否存在；include 必须位于项目目录内",
                evidence=dict(warning.detail),
            )
        )
    return issues


def _dedupe_and_summary(
    issues: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for issue in issues:
        anchor = issue.get("anchor") or {}
        key = (
            issue["rule_id"],
            anchor.get("file"),
            anchor.get("line"),
            issue["message"],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    severity = {"error": 0, "warning": 0, "info": 0}
    categories: Dict[str, int] = {}
    for issue in deduped:
        severity[issue["severity"]] = severity.get(issue["severity"], 0) + 1
        category = issue.get("category") or "other"
        categories[category] = categories.get(category, 0) + 1
    return deduped, {
        "count": len(deduped),
        "severity": severity,
        "categories": categories,
    }


def audit_latex_file(
    file_path: Path,
    *,
    root: Optional[Path] = None,
    required_sections: Optional[List[str]] = None,
    limits: Optional[LatexLimits] = None,
) -> Dict[str, Any]:
    """Audit a .tex project and return issues with source anchors."""
    limits = limits or LatexLimits()
    source = Path(file_path)
    root_path = Path(root).resolve() if root is not None else source.resolve().parent
    if not root_path.is_dir():
        raise OfficeParseError("LaTeX 项目根目录不存在")
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    if source.suffix.lower() not in (".tex", ".ltx"):
        raise OfficeParseError("仅支持 .tex/.ltx 审校")
    try:
        resolved = source.resolve()
    except OSError as exc:
        raise OfficeParseError("无法解析 LaTeX 路径") from exc
    if not is_within(root_path, resolved):
        raise OfficePathError("LaTeX 文件不在项目目录内", file_path=source)
    size = resolved.stat().st_size
    if size > limits.max_file_bytes:
        raise OfficeSizeLimitError(size, limits.max_file_bytes)

    raw = resolved.read_text(encoding="utf-8", errors="replace")
    clean = strip_comments(raw)
    doc = parse_latex_project(resolved, root=root_path, limits=limits)

    issues: List[Dict[str, Any]] = []
    issues.extend(_metadata_issues(doc, resolved, root_path, raw))
    issues.extend(
        _required_section_issues(
            doc, list(required_sections or []), resolved, root_path, raw
        )
    )
    issues.extend(_citation_issues(doc, resolved, root_path, clean))
    issues.extend(_reference_issues(doc))
    issues.extend(_asset_issues(doc))
    issues.extend(_duplicate_label_issues(clean, resolved, root_path))
    issues.extend(_residue_issues(raw, resolved, root_path))
    issues.extend(_unsafe_command_issues(clean, resolved, root_path))
    issues.extend(_parser_warning_issues(doc))
    issues, summary = _dedupe_and_summary(issues)

    return {
        "ok": summary["severity"]["error"] == 0,
        "source_path": _rel(resolved, root_path),
        "issues": issues,
        "summary": summary,
        "required_sections": list(required_sections or []),
    }


__all__ = ["audit_latex_file"]
