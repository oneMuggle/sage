"""Unit tests for LaTeX template analyze/fill tools."""

from __future__ import annotations

from pathlib import Path

from backend.domain.tool_policy import ToolPolicy
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.office_latex_template_tool import (
    OfficeAnalyzeLatexTemplateTool,
    OfficeFillLatexTemplateTool,
)

_TEMPLATE = r"""
\documentclass{article}
\title{Old}
\author{Old Author}
\begin{document}
\begin{abstract}
Old abstract.
\end{abstract}
<<note>>
\end{document}
"""


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(
        session_id="sess",
        stream_id="stream",
        binding_generation=1,
        office_doc_scope=frozenset(),
    )


def _workspace(tmp_path: Path) -> tuple:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    template = workspace / "paper.tex"
    template.write_text(_TEMPLATE, encoding="utf-8")
    return workspace, template


def test_analyze_latex_template_requires_context(tmp_path: Path) -> None:
    workspace, template = _workspace(tmp_path)
    tool = OfficeAnalyzeLatexTemplateTool(
        policy=ToolPolicy(workspace_root=str(workspace))
    )

    result = tool.execute(file_path=str(template))

    assert result.success is False
    assert result.error == "missing_tool_context"


def test_analyze_latex_template_returns_slots(tmp_path: Path) -> None:
    workspace, template = _workspace(tmp_path)
    tool = OfficeAnalyzeLatexTemplateTool(
        policy=ToolPolicy(workspace_root=str(workspace))
    )
    token = set_tool_context(_context())
    try:
        result = tool.execute(file_path=str(template))
    finally:
        reset_tool_context(token)

    assert result.success is True
    names = {slot["name"] for slot in result.content["slots"]}
    assert {"title", "author", "abstract"}.issubset(names)


def test_fill_latex_template_writes_new_file(tmp_path: Path) -> None:
    workspace, template = _workspace(tmp_path)
    tool = OfficeFillLatexTemplateTool(
        policy=ToolPolicy(workspace_root=str(workspace))
    )
    profile_tool = OfficeAnalyzeLatexTemplateTool(
        policy=ToolPolicy(workspace_root=str(workspace))
    )
    token = set_tool_context(_context())
    try:
        profile = profile_tool.execute(file_path=str(template))
        placeholder = next(
            slot["name"]
            for slot in profile.content["slots"]
            if slot["kind"] == "placeholder"
        )
        result = tool.execute(
            template_path=str(template),
            output_filename="paper-filled.tex",
            data={
                "title": "New",
                "author": ["Alice", "Bob"],
                "abstract": "New abstract.",
                placeholder: "Note",
            },
        )
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert result.content["filled_count"] == 4
    output = workspace / "paper-filled.tex"
    assert output.is_file()
    assert "New" in output.read_text(encoding="utf-8")


def test_fill_latex_template_reports_missing_required_slot(tmp_path: Path) -> None:
    workspace, template = _workspace(tmp_path)
    tool = OfficeFillLatexTemplateTool(
        policy=ToolPolicy(workspace_root=str(workspace))
    )
    token = set_tool_context(_context())
    try:
        result = tool.execute(
            template_path=str(template),
            output_filename="out.tex",
            data={"title": "Only title"},
        )
    finally:
        reset_tool_context(token)

    assert result.success is False
    assert "latex_template_fill_failed" in (result.error or "")
