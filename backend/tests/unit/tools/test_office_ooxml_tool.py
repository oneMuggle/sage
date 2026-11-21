"""Unit tests for the M5 ``office_ooxml`` tool."""

from __future__ import annotations

from pathlib import Path

from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.office_ooxml_tool import OfficeOoxmlTool


def _docx(tmp_path: Path) -> Path:
    from docx import Document

    document = Document()
    paragraph = document.add_paragraph()
    paragraph.add_run("Hello")
    paragraph.add_run(" ")
    paragraph.add_run("world")
    path = tmp_path / "doc.docx"
    document.save(str(path))
    return path


def _run(tool: OfficeOoxmlTool, **kwargs):
    token = set_tool_context(
        ToolExecutionContext(
            session_id="sess-ooxml",
            stream_id="stream-1",
            binding_generation=0,
            office_doc_scope=frozenset(),
        )
    )
    try:
        return tool.execute(**kwargs)
    finally:
        reset_tool_context(token)


def test_validate_action(tmp_path: Path) -> None:
    source = _docx(tmp_path)

    result = _run(OfficeOoxmlTool(), action="validate", file_path=str(source))

    assert result.success is True
    assert result.content["valid"] is True
    assert result.content["source_path"] == "doc.docx"


def test_merge_runs_action(tmp_path: Path) -> None:
    source = _docx(tmp_path)

    result = _run(OfficeOoxmlTool(), action="merge_runs", file_path=str(source))

    assert result.success is True
    assert result.content["merged_runs"] == 2
    assert result.content["output_path"] == "doc-merged.docx"


def test_merge_runs_requires_docx(tmp_path: Path) -> None:
    from openpyxl import Workbook

    path = tmp_path / "book.xlsx"
    Workbook().save(str(path))

    result = _run(OfficeOoxmlTool(), action="merge_runs", file_path=str(path))

    assert result.success is False
    assert "merge_runs_requires_docx" in (result.error or "")


def test_invalid_action(tmp_path: Path) -> None:
    source = _docx(tmp_path)

    result = _run(OfficeOoxmlTool(), action="frobnicate", file_path=str(source))

    assert result.success is False
    assert "action_invalid" in (result.error or "")


def test_requires_absolute_path(tmp_path: Path) -> None:
    _docx(tmp_path)

    result = _run(OfficeOoxmlTool(), action="validate", file_path="doc.docx")

    assert result.success is False
    assert "file_path_absolute_required" in (result.error or "")


def test_missing_context_fails_closed(tmp_path: Path) -> None:
    source = _docx(tmp_path)

    result = OfficeOoxmlTool().execute(action="validate", file_path=str(source))

    assert result.success is False
    assert result.error == "missing_tool_context"
