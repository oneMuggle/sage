"""Tests for backend.office generators (Task 19, plan §4.1.4 step 19).

TDD: tests written FIRST, then implementation.
Covers: PPT/Word/Excel generate from structured Pydantic input.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.office.errors import OfficePathError
from backend.office.excel import generate_xlsx
from backend.office.models import (
    ExcelSheetSpec,
    OfficeExcelGenerateRequest,
    OfficePptGenerateRequest,
    OfficeWordGenerateRequest,
    PptSlideSpec,
    WordParagraphSpec,
    WordTableSpec,
)
from backend.office.ppt import generate_ppt
from backend.office.word import generate_docx

# ──────────────────────────────────────────────────────────────────────
# PPT generator tests
# ──────────────────────────────────────────────────────────────────────


def test_generate_ppt_creates_file_with_slides(fixture_dir: Path) -> None:
    """generate_ppt writes a .pptx with the requested slides."""
    req = OfficePptGenerateRequest(
        workspace_path=str(fixture_dir),
        filename="my-deck",
        slides=[
            PptSlideSpec(title="Intro", bullets=["Point A", "Point B"]),
            PptSlideSpec(title="Body", bullets=["Detail 1"]),
            PptSlideSpec(title="Conclusion"),
        ],
    )
    output_path = generate_ppt(req)

    assert output_path.exists()
    assert output_path.suffix == ".pptx"
    assert output_path.name == "my-deck.pptx"
    # The output path should be inside the workspace
    assert output_path.is_relative_to(fixture_dir.resolve())


def test_generate_ppt_appends_pptx_extension_if_missing(fixture_dir: Path) -> None:
    """Filename without .pptx gets the extension appended."""
    req = OfficePptGenerateRequest(
        workspace_path=str(fixture_dir),
        filename="bare-name",
        slides=[PptSlideSpec(title="Only slide")],
    )
    output_path = generate_ppt(req)
    assert output_path.suffix == ".pptx"
    assert output_path.name == "bare-name.pptx"


def test_generate_ppt_rejects_traversal_in_workspace(fixture_dir: Path) -> None:
    """workspace_path containing '..' is rejected."""
    req = OfficePptGenerateRequest(
        workspace_path=str(fixture_dir / ".." / "escape"),
        filename="evil",
        slides=[PptSlideSpec(title="x")],
    )
    with pytest.raises(OfficePathError):
        generate_ppt(req)


def test_generate_ppt_rejects_traversal_in_filename(fixture_dir: Path) -> None:
    """Filename containing path separators is rejected."""
    req = OfficePptGenerateRequest(
        workspace_path=str(fixture_dir),
        filename="../escape.pptx",
        slides=[PptSlideSpec(title="x")],
    )
    with pytest.raises(OfficePathError):
        generate_ppt(req)


# ──────────────────────────────────────────────────────────────────────
# Word generator tests
# ──────────────────────────────────────────────────────────────────────


def test_generate_docx_creates_file_with_paragraphs(fixture_dir: Path) -> None:
    """generate_docx writes a .docx with title + paragraphs."""
    req = OfficeWordGenerateRequest(
        workspace_path=str(fixture_dir),
        filename="my-report",
        title="Annual Report",
        paragraphs=[
            WordParagraphSpec(heading="h1", text="Executive Summary"),
            WordParagraphSpec(text="This is the first paragraph."),
            WordParagraphSpec(heading="h2", text="Findings"),
            WordParagraphSpec(text="We found three key things."),
        ],
    )
    output_path = generate_docx(req)

    assert output_path.exists()
    assert output_path.suffix == ".docx"
    assert output_path.name == "my-report.docx"
    assert output_path.is_relative_to(fixture_dir.resolve())


def test_generate_docx_with_table(fixture_dir: Path) -> None:
    """Word document with a table gets the table rendered."""
    req = OfficeWordGenerateRequest(
        workspace_path=str(fixture_dir),
        filename="with-table",
        title="Data",
        paragraphs=[WordParagraphSpec(text="See table below.")],
        tables=[
            WordTableSpec(
                headers=["Name", "Age"],
                rows=[["Alice", "30"], ["Bob", "25"]],
            ),
        ],
    )
    output_path = generate_docx(req)
    assert output_path.exists()


def test_generate_docx_empty_paragraphs(fixture_dir: Path) -> None:
    """Word document with no paragraphs (just title) is valid."""
    req = OfficeWordGenerateRequest(
        workspace_path=str(fixture_dir),
        filename="title-only",
        title="Just a Title",
    )
    output_path = generate_docx(req)
    assert output_path.exists()


# ──────────────────────────────────────────────────────────────────────
# Excel generator tests
# ──────────────────────────────────────────────────────────────────────


def test_generate_xlsx_creates_file_with_sheets(fixture_dir: Path) -> None:
    """generate_xlsx writes a .xlsx with the requested sheets."""
    req = OfficeExcelGenerateRequest(
        workspace_path=str(fixture_dir),
        filename="my-data",
        sheets=[
            ExcelSheetSpec(
                name="Sales",
                headers=["Quarter", "Revenue"],
                rows=[["Q1", "100"], ["Q2", "150"]],
            ),
            ExcelSheetSpec(
                name="Costs",
                headers=["Category", "Amount"],
                rows=[["Marketing", "20"]],
            ),
        ],
    )
    output_path = generate_xlsx(req)

    assert output_path.exists()
    assert output_path.suffix == ".xlsx"
    assert output_path.name == "my-data.xlsx"
    assert output_path.is_relative_to(fixture_dir.resolve())


def test_generate_xlsx_appends_xlsx_extension_if_missing(fixture_dir: Path) -> None:
    """Filename without .xlsx gets the extension appended."""
    req = OfficeExcelGenerateRequest(
        workspace_path=str(fixture_dir),
        filename="no-ext",
        sheets=[ExcelSheetSpec(name="S1", headers=["A"], rows=[["1"]])],
    )
    output_path = generate_xlsx(req)
    assert output_path.suffix == ".xlsx"


def test_generate_xlsx_empty_sheet(fixture_dir: Path) -> None:
    """Sheet with no headers/rows is valid (creates empty sheet)."""
    req = OfficeExcelGenerateRequest(
        workspace_path=str(fixture_dir),
        filename="empty-sheet",
        sheets=[ExcelSheetSpec(name="Empty")],
    )
    output_path = generate_xlsx(req)
    assert output_path.exists()
