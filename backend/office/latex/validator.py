"""Lightweight LaTeX source validation (no TeX execution)."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .scanner import line_col, strip_comments

_ENV_RE = re.compile(r"\\(begin|end)\s*\{\s*([^{}]+?)\s*\}")
_RESIDUE_PATTERNS = (
    re.compile(r"<<[^<>\n]{1,120}>>"),
    re.compile(r"\[\[[^\[\]\n]{1,120}\]\]"),
    re.compile(r"【[^【】\n]{1,120}】"),
    re.compile(r"\\todo\s*\{[^{}]{1,200}\}"),
)


def _issue(
    code: str, message: str, text: str, pos: int, severity: str = "error"
) -> Dict[str, Any]:
    line, column = line_col(text, pos)
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "line": line,
        "column": column,
    }


def validate_latex_source(text: str) -> Dict[str, Any]:
    """Validate braces, environment pairing and residual placeholders."""
    clean = strip_comments(text)
    issues: List[Dict[str, Any]] = []

    depth = 0
    i = 0
    n = len(clean)
    while i < n:
        ch = clean[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                issues.append(_issue("unbalanced_brace", "出现多余的 }", clean, i))
                depth = 0
        i += 1
    if depth != 0:
        issues.append(
            _issue("unbalanced_brace", f"花括号未闭合（剩余 {depth} 个）", clean, 0)
        )

    stack: List[tuple] = []
    for match in _ENV_RE.finditer(clean):
        kind, name = match.group(1), match.group(2).strip()
        if kind == "begin":
            stack.append((name, match.start()))
        elif not stack:  # noqa: PLR5501 — keep explicit error branches readable
            issues.append(
                _issue(
                    "unmatched_environment",
                    f"未匹配的 \\end{{{name}}}",
                    clean,
                    match.start(),
                )
            )
        elif stack[-1][0] != name:
            issues.append(
                _issue(
                    "mismatched_environment",
                    f"环境不匹配：期望 \\end{{{stack[-1][0]}}}，实际 \\end{{{name}}}",
                    clean,
                    match.start(),
                )
            )
            stack.pop()
        else:
            stack.pop()
    for name, pos in stack:
        issues.append(
            _issue("unclosed_environment", f"环境 \\begin{{{name}}} 未闭合", clean, pos)
        )

    for pattern in _RESIDUE_PATTERNS:
        for match in pattern.finditer(text):
            issues.append(
                _issue(
                    "placeholder_residue",
                    f"残留占位符：{match.group(0)[:80]}",
                    text,
                    match.start(),
                    severity="warning",
                )
            )

    has_error = any(issue["severity"] == "error" for issue in issues)
    return {"ok": not has_error, "issues": issues}


__all__ = ["validate_latex_source"]
