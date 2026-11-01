"""Unit tests for ``office_audit_latex``."""

from __future__ import annotations

from pathlib import Path

from backend.domain.tool_policy import ToolPolicy
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.office_latex_audit_tool import OfficeAuditLatexTool

_DOC = r"""
\documentclass{article}
\title{T}
\author{A}
\begin{document}
\begin{abstract}A\end{abstract}
\section{Introduction}
\cite{missing}
\begin{thebibliography}{9}
\bibitem{known} Known.
\end{thebibliography}
\write18{echo unsafe}
\end{document}
"""


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id="sess",
        stream_id="stream",
        binding_generation=1,
        office_doc_scope=frozenset(),
    )


def _workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    main = workspace / "paper.tex"
    main.write_text(_DOC, encoding="utf-8")
    return workspace, main


def test_audit_latex_requires_context(tmp_path: Path) -> None:
    workspace, main = _workspace(tmp_path)
    tool = OfficeAuditLatexTool(policy=ToolPolicy(workspace_root=str(workspace)))

    result = tool.execute(file_path=str(main))

    assert result.success is False
    assert result.error == "missing_tool_context"


def test_audit_latex_returns_issues(tmp_path: Path) -> None:
    workspace, main = _workspace(tmp_path)
    tool = OfficeAuditLatexTool(policy=ToolPolicy(workspace_root=str(workspace)))
    token = set_tool_context(_context())
    try:
        result = tool.execute(
            file_path=str(main),
            required_sections=["Introduction", "Conclusion"],
        )
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert result.content["ok"] is False
    rules = {issue["rule_id"] for issue in result.content["issues"]}
    assert "LATEX-CITE-UNDEFINED" in rules
    assert "LATEX-UNSAFE-COMMAND" in rules
    assert "LATEX-SECTION-REQUIRED" in rules


def test_audit_latex_rejects_outside_workspace(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path)
    outside = tmp_path / "outside.tex"
    outside.write_text(_DOC, encoding="utf-8")
    tool = OfficeAuditLatexTool(policy=ToolPolicy(workspace_root=str(workspace)))
    token = set_tool_context(_context())
    try:
        result = tool.execute(file_path=str(outside))
    finally:
        reset_tool_context(token)

    assert result.success is False
    assert "path_outside_workspace" in (result.error or "")
