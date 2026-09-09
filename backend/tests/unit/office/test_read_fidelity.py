"""Round-2 read-fidelity tests (plan R2 + R3).

Covers three items:

- R2a: ``read_pdf`` extracts text-layer tables via PyMuPDF ``find_tables``.
  Happy path is validated against a REAL ruled table synthesized with PyMuPDF
  drawing commands (``draw_line`` grid + ``insert_text`` cells) — chosen over
  a monkeypatched ``find_tables`` because a prototype confirmed PyMuPDF 1.28
  detects and extracts such a grid exactly. Monkeypatches are used only for
  the guard paths (find_tables raising; per-page cell cap).
- R2b: ``read_docx`` renders run-level bold/italic as ``**bold**`` /
  ``*italic*`` markers, merging consecutive runs with identical formatting;
  plain (unformatted) documents are byte-identical to the old output.
- R3: ``read_docx`` fills ``OfficeWordReadResult.comments`` (models moved to
  models.py); old payloads without the field stay valid.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from docx import Document

from backend.office.edit import update_docx
from backend.office.models import (
    OfficeDocumentSummary,
    OfficeWordReadResult,
    WordCommentContent,
    WordCommentsResult,
)
from backend.office.pdf import MAX_TABLE_CELLS_PER_PAGE, read_pdf
from backend.office.word import read_docx, read_docx_comments

pytestmark = pytest.mark.unit


# ──────────────────────────────────────────────────────────────────────
# R2a helpers — PDF synthesis
# ──────────────────────────────────────────────────────────────────────


def _make_ruled_table_pdf(path: Path) -> Path:
    """PDF whose only page contains a real ruled 3x2 table (line grid + text).

    Built with PyMuPDF itself: find_tables' "lines" strategy detects vector
    graphics, which reportlab ``drawString`` cannot produce.
    """
    doc = pymupdf.open()
    page = doc.new_page()

    cells = [
        ["Name", "Value"],
        ["Alpha", "1"],
        ["Beta", "2"],
    ]
    x0, y0, cell_w, cell_h = 72.0, 72.0, 100.0, 24.0
    n_rows, n_cols = len(cells), len(cells[0])

    for r in range(n_rows + 1):
        page.draw_line(
            pymupdf.Point(x0, y0 + r * cell_h),
            pymupdf.Point(x0 + n_cols * cell_w, y0 + r * cell_h),
        )
    for c in range(n_cols + 1):
        page.draw_line(
            pymupdf.Point(x0 + c * cell_w, y0),
            pymupdf.Point(x0 + c * cell_w, y0 + n_rows * cell_h),
        )
    for r, row in enumerate(cells):
        for c, value in enumerate(row):
            page.insert_text(
                pymupdf.Point(x0 + c * cell_w + 4, y0 + r * cell_h + 16),
                value,
                fontsize=10,
            )

    doc.save(str(path))
    doc.close()
    return path


def _make_text_only_pdf(path: Path) -> Path:
    """PDF with plain drawn text and no vector graphics (no tables to find)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    c.drawString(100, 750, "Just a plain paragraph.")
    c.drawString(100, 730, "No rules, no grid, no table.")
    c.showPage()
    c.drawString(100, 750, "Second page, still plain.")
    c.showPage()
    c.save()
    return path


# ──────────────────────────────────────────────────────────────────────
# R2a — PDF table extraction
# ──────────────────────────────────────────────────────────────────────


def test_read_pdf_extracts_ruled_table(tmp_path: Path):
    """A ruled text-layer table is extracted with exact cell values."""
    path = _make_ruled_table_pdf(tmp_path / "table.pdf")
    result = read_pdf(path, workspace_path=str(tmp_path))

    assert len(result.pages) == 1
    assert result.pages[0].tables, "ruled table must be found on page 1"
    flattened = [cell for table in result.pages[0].tables for row in table for cell in row]
    assert "Name" in flattened
    assert "Alpha" in flattened
    assert "Beta" in flattened
    assert "2" in flattened
    # First detected table carries the full grid with normalized (str) cells.
    first = result.pages[0].tables[0]
    assert all(isinstance(cell, str) for row in first for cell in row)
    assert ["Name", "Value"] in [list(r) for r in first]


def test_read_pdf_text_only_has_no_tables(tmp_path: Path):
    """A text-only PDF still yields tables=[] per page without errors."""
    path = _make_text_only_pdf(tmp_path / "plain.pdf")
    result = read_pdf(path, workspace_path=str(tmp_path))

    assert len(result.pages) == 2
    for page in result.pages:
        assert page.tables == []
    # Text extraction unchanged.
    assert "Just a plain paragraph." in result.pages[0].text


def test_read_pdf_survives_find_tables_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """A page whose find_tables() raises is skipped; the read still succeeds."""
    path = _make_text_only_pdf(tmp_path / "boom.pdf")

    def _raise(self):
        raise RuntimeError("boom")

    monkeypatch.setattr(pymupdf.Page, "find_tables", _raise)
    with caplog.at_level("WARNING", logger="backend.office.pdf"):
        result = read_pdf(path, workspace_path=str(tmp_path))

    assert len(result.pages) == 2
    for page in result.pages:
        assert page.tables == []
    assert any("table extraction failed" in rec.message for rec in caplog.records)


def test_read_pdf_cell_cap_truncates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """Extraction stops at MAX_TABLE_CELLS_PER_PAGE cells per page (logged)."""
    path = _make_ruled_table_pdf(tmp_path / "capped.pdf")
    monkeypatch.setattr("backend.office.pdf.MAX_TABLE_CELLS_PER_PAGE", 4)

    with caplog.at_level("WARNING", logger="backend.office.pdf"):
        result = read_pdf(path, workspace_path=str(tmp_path))

    extracted = [cell for table in result.pages[0].tables for row in table for cell in row]
    assert len(extracted) <= 4
    assert len(extracted) > 0
    assert any("truncated" in rec.message for rec in caplog.records)


def test_read_pdf_cell_cap_default_is_20k():
    """Sanity: the shipped cap matches the documented 20k cells per page."""
    assert MAX_TABLE_CELLS_PER_PAGE == 20_000


# ──────────────────────────────────────────────────────────────────────
# R2b — run-level bold/italic markers in read_docx
# ──────────────────────────────────────────────────────────────────────


def _add_runs(para, runs):
    """Append (text, bold, italic) tuples as runs to a paragraph."""
    for text, bold, italic in runs:
        run = para.add_run(text)
        if bold is not None:
            run.bold = bold
        if italic is not None:
            run.italic = italic
    return para


def _read_single_paragraph_text(path: Path):
    result = read_docx(path, workspace_path="")
    assert len(result.paragraphs) == 1
    return result.paragraphs[0].text


def test_read_docx_bold_and_italic_markers(tmp_path: Path):
    """Bold/italic runs are wrapped in **...** / *...* markers."""
    doc = Document()
    _add_runs(
        doc.add_paragraph(), [("Bold", True, None), (" and ", None, None), ("italic", None, True)]
    )
    path = tmp_path / "styled.docx"
    doc.save(str(path))

    assert _read_single_paragraph_text(path) == "**Bold** and *italic*"


def test_read_docx_merges_consecutive_same_format_runs(tmp_path: Path):
    """Consecutive runs with identical formatting merge into one span."""
    doc = Document()
    _add_runs(doc.add_paragraph(), [("Bo", True, None), ("ld", True, None), (" tail", None, None)])
    path = tmp_path / "merged.docx"
    doc.save(str(path))

    assert _read_single_paragraph_text(path) == "**Bold** tail"


def test_read_docx_bold_italic_same_run(tmp_path: Path):
    """A run that is both bold and italic becomes ***text***."""
    doc = Document()
    _add_runs(doc.add_paragraph(), [("both", True, True), (" plain", None, None)])
    path = tmp_path / "both.docx"
    doc.save(str(path))

    assert _read_single_paragraph_text(path) == "***both*** plain"


def test_read_docx_whitespace_runs_preserved(tmp_path: Path):
    """Whitespace-only runs keep their spacing (merged into the same span)."""
    doc = Document()
    _add_runs(doc.add_paragraph(), [("Bold ", True, None), ("text", True, None)])
    path = tmp_path / "ws.docx"
    doc.save(str(path))

    assert _read_single_paragraph_text(path) == "**Bold text**"


def test_read_docx_empty_runs_produce_no_markers(tmp_path: Path):
    """Empty runs never wrap into literal '****' spans."""
    doc = Document()
    _add_runs(doc.add_paragraph(), [("", True, None), ("Bold", True, None), ("", True, None)])
    path = tmp_path / "empty.docx"
    doc.save(str(path))

    assert _read_single_paragraph_text(path) == "**Bold**"


def test_read_docx_paragraph_with_literal_double_asterisks_unwrapped(tmp_path: Path):
    """Paragraphs already containing '**' are emitted verbatim (no markers)."""
    doc = Document()
    _add_runs(doc.add_paragraph(), [("a ** b ", None, None), ("bold", True, None)])
    path = tmp_path / "literal.docx"
    doc.save(str(path))

    assert _read_single_paragraph_text(path) == "a ** b bold"


def test_read_docx_style_inherited_bold_treated_as_plain(tmp_path: Path):
    """Documented simplification: style-inherited (None) bold is not marked.

    add_heading runs carry no direct bold (it comes from the Heading style),
    so headings must read back exactly as before round 2.
    """
    doc = Document()
    doc.add_heading("Heading One", level=1)
    path = tmp_path / "heading.docx"
    doc.save(str(path))

    result = read_docx(path, workspace_path="")
    assert result.paragraphs[0].text == "Heading One"
    assert "*" not in result.paragraphs[0].text


def test_read_docx_plain_document_output_unchanged(tmp_path: Path):
    """Plain (unformatted) documents render exactly the old paragraph text."""
    doc = Document()
    doc.add_paragraph("First plain paragraph.")
    _add_runs(doc.add_paragraph(), [("split ", None, None), ("runs", None, None)])
    path = tmp_path / "plain.docx"
    doc.save(str(path))

    result = read_docx(path, workspace_path="")
    texts = [p.text for p in result.paragraphs]
    assert texts == ["First plain paragraph.", "split runs"]


# ──────────────────────────────────────────────────────────────────────
# R3 — comments merged into the read result
# ──────────────────────────────────────────────────────────────────────


def _make_commented_docx(path: Path) -> Path:
    doc = Document()
    doc.add_paragraph("This is some text to review.")
    doc.save(str(path))
    saved, results = update_docx(
        path,
        [
            {
                "op": "add_comment",
                "find": "some text",
                "comment": "请检查这句话",
                "author": "张三",
                "date": "2026-09-09T08:00:00Z",
            }
        ],
    )
    assert saved
    assert results[0]["ok"]
    return path


def test_read_docx_fills_comments(tmp_path: Path):
    """read_docx surfaces comments with author/text/anchor in the result."""
    path = _make_commented_docx(tmp_path / "commented.docx")

    result = read_docx(path, workspace_path="")
    assert len(result.comments) == 1
    comment = result.comments[0]
    assert isinstance(comment, WordCommentContent)
    assert comment.id == "0"
    assert comment.author == "张三"
    assert comment.date == "2026-09-09T08:00:00Z"
    assert comment.text == "请检查这句话"
    assert "some text" in comment.anchor_text


def test_read_docx_comments_agree_with_dedicated_reader(tmp_path: Path):
    """The merged result and read_docx_comments report identical comments."""
    path = _make_commented_docx(tmp_path / "commented.docx")

    merged = read_docx(path, workspace_path="").comments
    dedicated = read_docx_comments(path)
    assert isinstance(dedicated, WordCommentsResult)
    assert merged == dedicated.comments


def test_read_docx_without_comments_yields_empty_list(tmp_path: Path):
    """No comments part → comments == [] (and the field is always present)."""
    doc = Document()
    doc.add_paragraph("Clean document.")
    path = tmp_path / "clean.docx"
    doc.save(str(path))

    result = read_docx(path, workspace_path="")
    assert result.comments == []


def test_read_docx_marker_and_comments_combined(tmp_path: Path):
    """Bold paragraphs and comments are extracted in one pass together."""
    doc = Document()
    _add_runs(doc.add_paragraph(), [("Important", True, None), (" note", None, None)])
    path = tmp_path / "combo.docx"
    doc.save(str(path))
    saved, _ = update_docx(
        path, [{"op": "add_comment", "find": "Important", "comment": "加粗了", "author": "李四"}]
    )
    assert saved

    result = read_docx(path, workspace_path="")
    assert result.paragraphs[0].text == "**Important** note"
    assert len(result.comments) == 1
    assert result.comments[0].text == "加粗了"


def test_office_word_read_result_old_payload_still_valid():
    """extra="forbid" + default_factory: payloads without comments validate."""
    payload = {
        "summary": {
            "id": "doc-1",
            "workspace_path": "/tmp/ws",
            "doc_type": "word",
            "generated_filename": "a.docx",
            "status": "parsed",
            "created_at": 1,
            "updated_at": 1,
            "metadata": {"file_size_bytes": 10},
        },
        "paragraphs": [{"style": "Normal", "text": "hi", "level": 0}],
        "tables": [{"rows": [["A"]]}],
        "images": 0,
    }
    result = OfficeWordReadResult.model_validate(payload)
    assert result.comments == []

    # Round-trip through the full model also validates.
    assert isinstance(result.summary, OfficeDocumentSummary)


def test_comment_models_importable_from_both_modules():
    """models.py is the home; word.py keeps re-exporting for compatibility."""
    import backend.office.word as word_module
    from backend.office import models as models_module

    assert word_module.WordCommentContent is models_module.WordCommentContent
    assert word_module.WordCommentsResult is models_module.WordCommentsResult
