"""Unit tests for the LaTeX PDF audit tool."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from backend.domain.tool_policy import ToolPolicy
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.office_latex_pdf_tool import OfficeAuditLatexPdfTool


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


def _pdf(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=595.28, height=841.89)
    page.insert_text((72, 100), "Hello")
    doc.save(str(path))
    doc.close()
    return path


def test_pdf_audit_requires_context(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    pdf = _pdf(workspace / "main.pdf")
    tool = OfficeAuditLatexPdfTool(policy=ToolPolicy(workspace_root=str(workspace)))

    result = tool.execute(file_path=str(pdf))

    assert result.success is False
    assert result.error == "missing_tool_context"


def test_pdf_audit_rejects_non_pdf(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    other = workspace / "main.tex"
    other.write_text("\\documentclass{article}", encoding="utf-8")
    tool = OfficeAuditLatexPdfTool(policy=ToolPolicy(workspace_root=str(workspace)))
    token = set_tool_context(_context())
    try:
        result = tool.execute(file_path=str(other))
    finally:
        reset_tool_context(token)

    assert result.success is False
    assert result.error == "unsupported_file_type"


def test_pdf_audit_rejects_outside_workspace(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    outside = _pdf(tmp_path / "outside.pdf")
    tool = OfficeAuditLatexPdfTool(policy=ToolPolicy(workspace_root=str(workspace)))
    token = set_tool_context(_context())
    try:
        result = tool.execute(file_path=str(outside))
    finally:
        reset_tool_context(token)

    assert result.success is False


def test_pdf_audit_returns_font_issue(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    pdf = _pdf(workspace / "main.pdf")
    tool = OfficeAuditLatexPdfTool(policy=ToolPolicy(workspace_root=str(workspace)))
    token = set_tool_context(_context())
    try:
        result = tool.execute(file_path=str(pdf))
    finally:
        reset_tool_context(token)

    assert result.success is True
    assert result.content["summary"]["pages"] == 1
    rules = {issue["rule_id"] for issue in result.content["issues"]}
    assert "PDF-FONT-NOT-EMBEDDED" in rules
