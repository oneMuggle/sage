"""Unit tests for M6b extraction registry and cross-document compare."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from backend.office.compare import CompareRequest, compare_documents
from backend.office.errors import OfficeParseError, OfficePathError
from backend.office.extractors import ExtractRequest, extract_document


def _docx(path: Path, text: str = "Hello world") -> Path:
    from docx import Document

    document = Document()
    document.add_heading("Title", level=1)
    document.add_paragraph(text)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "A"
    table.cell(0, 1).text = "B"
    table.cell(1, 0).text = "1"
    table.cell(1, 1).text = "2"
    document.save(str(path))
    return path


def _xlsx(path: Path, value: str = "hello") -> Path:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "数据"
    sheet["A1"] = "name"
    sheet["B1"] = "value"
    sheet["A2"] = "x"
    sheet["B2"] = value
    workbook.save(str(path))
    return path


def _pptx(path: Path) -> Path:
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Intro"
    slide.placeholders[1].text = "Bullet one"
    prs.save(str(path))
    return path


def _pdf(path: Path, text: str = "PDF hello") -> Path:
    import fitz

    document = fitz.open()
    try:
        page = document.new_page(width=400, height=300)
        page.insert_text((50, 50), text, fontname="helv", fontsize=12)
        document.save(str(path))
    finally:
        document.close()
    return path


def _extract(tmp_path: Path, path: Path, **kwargs):
    return extract_document(
        ExtractRequest(
            workspace_path=str(tmp_path),
            file_path=str(path),
            backend=kwargs.pop("backend", "light"),
            **kwargs,
        )
    )


def test_light_docx_extraction_has_blocks_and_anchors(tmp_path: Path) -> None:
    source = _docx(tmp_path / "doc.docx")

    result = _extract(tmp_path, source)

    assert result.extractor == "light"
    assert "# Title" in result.document.markdown
    assert "Hello world" in result.document.markdown
    assert "| A | B |" in result.document.markdown
    types = {block.type for block in result.document.blocks}
    assert {"heading", "paragraph", "table"} <= types
    assert any(block.anchor.get("paragraph_index") == 1 for block in result.document.blocks)


def test_light_excel_and_pptx_and_pdf(tmp_path: Path) -> None:
    excel = _extract(tmp_path, _xlsx(tmp_path / "book.xlsx"))
    assert "## 数据" in excel.document.markdown
    assert "| name | value |" in excel.document.markdown
    assert excel.document.blocks[0].anchor["sheet"] == "数据"

    ppt = _extract(tmp_path, _pptx(tmp_path / "deck.pptx"))
    assert "## Intro" in ppt.document.markdown
    assert "Bullet one" in ppt.document.markdown
    assert ppt.document.blocks[0].anchor["slide"] == 0

    pdf = _extract(tmp_path, _pdf(tmp_path / "doc.pdf"))
    assert "--- page 1 ---" in pdf.document.markdown
    assert "PDF hello" in pdf.document.markdown
    assert pdf.document.blocks[0].anchor["page"] == 1


def test_extract_truncates_markdown(tmp_path: Path) -> None:
    source = _docx(tmp_path / "long.docx", text="x" * 5000)

    result = _extract(tmp_path, source, max_chars=1000)

    assert len(result.document.markdown) == 1000
    assert any(
        warning["code"] == "markdown_truncated" for warning in result.document.warnings
    )


def test_extract_unavailable_backend(tmp_path: Path, monkeypatch) -> None:
    source = _docx(tmp_path / "doc.docx")
    monkeypatch.setattr(
        "backend.office.extractors.service.extractor_available", lambda name: False
    )

    with pytest.raises(OfficeParseError):
        extract_document(
            ExtractRequest(
                workspace_path=str(tmp_path),
                file_path=str(source),
                backend="markitdown",
            )
        )


def test_extract_rejects_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = _docx(tmp_path / "outside.docx")

    with pytest.raises(OfficePathError):
        extract_document(
            ExtractRequest(
                workspace_path=str(workspace), file_path=str(outside), backend="light"
            )
        )


def test_extract_rejects_unsupported_suffix(tmp_path: Path) -> None:
    source = tmp_path / "notes.bin"
    source.write_bytes(b"binary")

    with pytest.raises(OfficeParseError):
        extract_document(
            ExtractRequest(
                workspace_path=str(tmp_path), file_path=str(source), backend="light"
            )
        )


def test_compare_docx_reports_added_and_removed(tmp_path: Path) -> None:
    left = _docx(tmp_path / "left.docx", "Hello world")
    right = _docx(tmp_path / "right.docx", "Hello brave world")

    result = compare_documents(
        CompareRequest(
            workspace_path=str(tmp_path), left_path=str(left), right_path=str(right)
        )
    )

    assert result.format == ".docx→.docx"
    assert result.summary.added >= 1
    assert result.summary.removed >= 1
    assert "```diff" in result.report_markdown
    assert any(change.kind == "added" for change in result.changes)


def test_compare_identical_files_has_no_changes(tmp_path: Path) -> None:
    left = _docx(tmp_path / "left.docx")
    right = tmp_path / "right.docx"
    shutil.copy2(left, right)

    result = compare_documents(
        CompareRequest(
            workspace_path=str(tmp_path), left_path=str(left), right_path=str(right)
        )
    )

    assert result.summary.added == 0
    assert result.summary.removed == 0
    assert result.summary.unchanged > 0


def test_compare_xlsx_and_pdf(tmp_path: Path) -> None:
    left = _xlsx(tmp_path / "a.xlsx", "one")
    right = _xlsx(tmp_path / "b.xlsx", "two")
    result = compare_documents(
        CompareRequest(
            workspace_path=str(tmp_path), left_path=str(left), right_path=str(right)
        )
    )
    assert result.summary.added + result.summary.removed >= 1

    pdf_left = _pdf(tmp_path / "a.pdf", "alpha")
    pdf_right = _pdf(tmp_path / "b.pdf", "beta")
    pdf_result = compare_documents(
        CompareRequest(
            workspace_path=str(tmp_path),
            left_path=str(pdf_left),
            right_path=str(pdf_right),
        )
    )
    assert pdf_result.summary.added + pdf_result.summary.removed >= 1


def test_compare_rejects_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = _docx(tmp_path / "outside.docx")

    with pytest.raises(OfficePathError):
        compare_documents(
            CompareRequest(
                workspace_path=str(workspace),
                left_path=str(outside),
                right_path=str(outside),
            )
        )
