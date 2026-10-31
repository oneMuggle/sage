"""Unit tests for the LaTeX compliance tool."""

from __future__ import annotations

from pathlib import Path

from backend.domain.tool_policy import ToolPolicy
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.office_latex_compliance_tool import (
    OfficeCheckLatexComplianceTool,
)

_GOOD_TEX = r"""
\documentclass{article}
\title{T}
\author{A}
\begin{document}
\begin{abstract}Abs\end{abstract}
\section{Introduction}
Text.
\end{document}
"""


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id="sess",
        stream_id="stream",
        binding_generation=1,
        office_doc_scope=frozenset(),
    )


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _tex(workspace: Path) -> Path:
    path = workspace / "paper.tex"
    path.write_text(_GOOD_TEX, encoding="utf-8")
    return path


def test_compliance_requires_context(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    tex = _tex(workspace)
    tool = OfficeCheckLatexComplianceTool(
        policy=ToolPolicy(workspace_root=str(workspace))
    )

    result = tool.execute(tex_path=str(tex))

    assert result.success is False
    assert result.error == "missing_tool_context"


def test_compliance_rejects_non_tex(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    other = workspace / "main.pdf"
    other.write_bytes(b"%PDF-1.4")
    tool = OfficeCheckLatexComplianceTool(
        policy=ToolPolicy(workspace_root=str(workspace))
    )
    token = set_tool_context(_context())
    try:
        result = tool.execute(tex_path=str(other))
    finally:
        reset_tool_context(token)

    assert result.success is False
    assert result.error == "unsupported_file_type"


def test_compliance_rejects_outside_workspace(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    outside = tmp_path / "outside.tex"
    outside.write_text(_GOOD_TEX, encoding="utf-8")
    tool = OfficeCheckLatexComplianceTool(
        policy=ToolPolicy(workspace_root=str(workspace))
    )
    token = set_tool_context(_context())
    try:
        result = tool.execute(tex_path=str(outside))
    finally:
        reset_tool_context(token)

    assert result.success is False


def test_compliance_returns_checks(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    tex = _tex(workspace)
    tool = OfficeCheckLatexComplianceTool(
        policy=ToolPolicy(workspace_root=str(workspace))
    )
    token = set_tool_context(_context())
    try:
        result = tool.execute(
            tex_path=str(tex),
            required_sections=["Introduction", "Conclusion"],
            required_metadata=["title", "author", "abstract"],
        )
    finally:
        reset_tool_context(token)

    assert result.success is True
    checks = {item["id"]: item for item in result.content["checks"]}
    assert checks["tex.sections"]["status"] == "fail"
    assert checks["tex.metadata"]["status"] == "pass"
    assert result.content["ok"] is False
