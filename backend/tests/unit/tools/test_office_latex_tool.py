"""Unit tests for ``office_read_latex``."""

from __future__ import annotations

from pathlib import Path

from backend.domain.tool_policy import ToolPolicy
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.office_latex_tool import OfficeReadLatexTool


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id="sess",
        stream_id="stream",
        binding_generation=1,
        office_doc_scope=frozenset(),
    )


def _write_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "paper.tex").write_text(
        r"""
\documentclass{article}
\title{Tool Demo}
\begin{document}
\section{Intro}
Hello $x^2$.
\end{document}
""",
        encoding="utf-8",
    )
    return workspace


def test_read_latex_requires_tool_context(tmp_path: Path) -> None:
    workspace = _write_workspace(tmp_path)
    tool = OfficeReadLatexTool(policy=ToolPolicy(workspace_root=str(workspace)))

    result = tool.execute(file_path=str(workspace / "paper.tex"))

    assert result.success is False
    assert result.error == "missing_tool_context"


def test_read_latex_returns_structured_preview(tmp_path: Path) -> None:
    workspace = _write_workspace(tmp_path)
    tool = OfficeReadLatexTool(policy=ToolPolicy(workspace_root=str(workspace)))
    token = set_tool_context(_context())
    try:
        result = tool.execute(file_path=str(workspace / "paper.tex"))
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert result.content["kind"] == "latex"
    assert result.content["structured"]["metadata"]["title"] == "Tool Demo"
    assert any(
        block["type"] == "heading"
        for block in result.content["structured"]["blocks"]
    )


def test_read_latex_rejects_path_outside_workspace(tmp_path: Path) -> None:
    workspace = _write_workspace(tmp_path)
    outside = tmp_path / "outside.tex"
    outside.write_text("\\documentclass{article}", encoding="utf-8")
    tool = OfficeReadLatexTool(policy=ToolPolicy(workspace_root=str(workspace)))
    token = set_tool_context(_context())
    try:
        result = tool.execute(file_path=str(outside))
    finally:
        reset_tool_context(token)

    assert result.success is False
    assert "path_outside_workspace" in (result.error or "")


def test_read_latex_rejects_non_tex_suffix(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    other = workspace / "notes.md"
    other.write_text("# notes", encoding="utf-8")
    tool = OfficeReadLatexTool(policy=ToolPolicy(workspace_root=str(workspace)))
    token = set_tool_context(_context())
    try:
        result = tool.execute(file_path=str(other))
    finally:
        reset_tool_context(token)

    assert result.success is False
    assert "unsupported_file_type" in (result.error or "")
