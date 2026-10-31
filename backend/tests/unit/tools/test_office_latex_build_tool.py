"""Unit tests for LaTeX compile/latexdiff tools (degraded paths)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.office_latex_build_tool import (
    OfficeCompileLatexTool,
    OfficeLatexdiffTool,
)


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
    main.write_text(
        "\\documentclass{article}\\title{T}\\author{A}\\begin{document}"
        "\\begin{abstract}A\\end{abstract}Hi\\end{document}",
        encoding="utf-8",
    )
    revised = workspace / "v2.tex"
    revised.write_text(main.read_text(encoding="utf-8"), encoding="utf-8")
    return workspace, main, revised


def test_compile_requires_context(tmp_path: Path) -> None:
    workspace, main, _ = _workspace(tmp_path)
    tool = OfficeCompileLatexTool(policy=ToolPolicy(workspace_root=str(workspace)))

    result = tool.execute(file_path=str(main))

    assert result.success is False
    assert result.error == "missing_tool_context"


def test_compile_without_engine_returns_no_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, main, _ = _workspace(tmp_path)
    monkeypatch.setattr(
        "backend.office.latex.compile.shutil.which", lambda name: None
    )
    tool = OfficeCompileLatexTool(policy=ToolPolicy(workspace_root=str(workspace)))
    token = set_tool_context(_context())
    try:
        result = tool.execute(file_path=str(main), output_filename="out.pdf")
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert result.content["ok"] is False
    assert result.content["code"] == "no_engine"


def test_latexdiff_requires_context(tmp_path: Path) -> None:
    workspace, main, revised = _workspace(tmp_path)
    tool = OfficeLatexdiffTool(policy=ToolPolicy(workspace_root=str(workspace)))

    result = tool.execute(original_path=str(main), revised_path=str(revised))

    assert result.success is False
    assert result.error == "missing_tool_context"


def test_latexdiff_without_tool_returns_no_latexdiff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, main, revised = _workspace(tmp_path)
    monkeypatch.setattr(
        "backend.office.latex.diff.shutil.which", lambda name: None
    )
    tool = OfficeLatexdiffTool(policy=ToolPolicy(workspace_root=str(workspace)))
    token = set_tool_context(_context())
    try:
        result = tool.execute(
            original_path=str(main),
            revised_path=str(revised),
            output_filename="diff.tex",
        )
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert result.content["ok"] is False
    assert result.content["code"] == "no_latexdiff"
