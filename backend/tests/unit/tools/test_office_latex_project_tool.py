"""Unit tests for the LaTeX project zip import tool."""

from __future__ import annotations

import zipfile
from pathlib import Path

from backend.domain.tool_policy import ToolPolicy
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.office_latex_project_tool import OfficeExtractLatexProjectTool


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


def _zip(workspace: Path, name: str = "project.zip") -> Path:
    archive = workspace / name
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("paper/main.tex", "\\documentclass{article}")
        handle.writestr("paper/sections/intro.tex", "\\section{Intro}")
    return archive


def test_extract_requires_context(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    archive = _zip(workspace)
    tool = OfficeExtractLatexProjectTool(
        policy=ToolPolicy(workspace_root=str(workspace))
    )

    result = tool.execute(zip_path=str(archive))

    assert result.success is False
    assert result.error == "missing_tool_context"


def test_extract_rejects_non_zip(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    other = workspace / "paper.tex"
    other.write_text("\\documentclass{article}", encoding="utf-8")
    tool = OfficeExtractLatexProjectTool(
        policy=ToolPolicy(workspace_root=str(workspace))
    )
    token = set_tool_context(_context())
    try:
        result = tool.execute(zip_path=str(other))
    finally:
        reset_tool_context(token)

    assert result.success is False
    assert result.error == "unsupported_file_type"


def test_extract_rejects_outside_workspace(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    outside = tmp_path / "outside.zip"
    with zipfile.ZipFile(outside, "w") as handle:
        handle.writestr("main.tex", "\\documentclass{article}")
    tool = OfficeExtractLatexProjectTool(
        policy=ToolPolicy(workspace_root=str(workspace))
    )
    token = set_tool_context(_context())
    try:
        result = tool.execute(zip_path=str(outside))
    finally:
        reset_tool_context(token)

    assert result.success is False
    assert "outside" in (result.error or "") or "workspace" in (result.error or "")


def test_extract_success_returns_main_file(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    archive = _zip(workspace)
    tool = OfficeExtractLatexProjectTool(
        policy=ToolPolicy(workspace_root=str(workspace))
    )
    token = set_tool_context(_context())
    try:
        result = tool.execute(
            zip_path=str(archive), output_dir_name="imported"
        )
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert result.content["project_dir"] == "imported"
    assert result.content["main_file"] == "imported/paper/main.tex"
    assert (workspace / "imported" / "paper" / "main.tex").is_file()
