"""Unit tests for PDF form (AcroForm) read and fill."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.office.errors import (
    OfficeFileNotFoundError,
    OfficePathError,
    OfficePdfFormError,
    OfficePdfParseError,
    OfficeSizeLimitError,
)
from backend.office.models import PdfFormFillRequest

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_plain_pdf(path: Path, text: str = "Plain PDF") -> Path:
    """Create a minimal PDF (no AcroForm) using reportlab."""
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path))
    c.drawString(100, 750, text)
    c.save()
    return path


def _make_form_pdf(path: Path, field_names: list[str] | None = None) -> Path:
    """Create a PDF with AcroForm text fields using PyMuPDF's widget API."""
    import pymupdf

    field_names = field_names or ["name", "email"]
    doc = pymupdf.open()
    page = doc.new_page()
    for i, name in enumerate(field_names):
        widget = pymupdf.Widget()
        widget.field_name = name
        widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
        widget.rect = pymupdf.Rect(72, 72 + i * 40, 300, 100 + i * 40)
        widget.field_value = ""
        page.add_widget(widget)
    doc.save(str(path))
    doc.close()
    return path


# ── read_pdf_form tests ───────────────────────────────────────────────────


def test_read_pdf_no_form(tmp_path: Path):
    """A regular PDF without AcroForm returns an empty field list."""
    from backend.office.pdf_forms import read_pdf_form

    pdf_path = _make_plain_pdf(tmp_path / "no_form.pdf")
    result = read_pdf_form(pdf_path, workspace_path=str(tmp_path))
    assert result.fields == []
    assert result.has_xfa is False


def test_read_nonexistent_pdf_form(tmp_path: Path):
    """Requesting a missing PDF raises OfficeFileNotFoundError."""
    from backend.office.pdf_forms import read_pdf_form

    with pytest.raises(OfficeFileNotFoundError):
        read_pdf_form(
            Path("/nonexistent/form.pdf"), workspace_path=str(tmp_path)
        )


def test_read_pdf_form_with_fields(tmp_path: Path):
    """A PDF with AcroForm text fields returns the expected field descriptors."""
    from backend.office.pdf_forms import read_pdf_form

    pdf_path = _make_form_pdf(tmp_path / "form.pdf", ["name", "email"])
    result = read_pdf_form(pdf_path, workspace_path=str(tmp_path))
    assert len(result.fields) == 2
    names = {f.name for f in result.fields}
    assert names == {"name", "email"}
    for field in result.fields:
        assert field.type == "text"


def test_read_pdf_form_workspace_escape(tmp_path: Path):
    """Workspace-escape paths must be rejected."""
    from backend.office.pdf_forms import read_pdf_form

    # tmp_path is a valid workspace, but /etc/passwd escapes it.
    with pytest.raises((OfficePathError, OfficeFileNotFoundError)):
        read_pdf_form(Path("/etc/passwd"), workspace_path=str(tmp_path))


def test_read_pdf_form_invalid_workspace(tmp_path: Path):
    """A non-existent workspace is rejected."""
    from backend.office.pdf_forms import read_pdf_form

    pdf_path = _make_plain_pdf(tmp_path / "x.pdf")
    with pytest.raises(OfficePathError):
        read_pdf_form(pdf_path, workspace_path="/nonexistent/workspace")


def test_read_pdf_form_oversized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Oversized PDFs are rejected before parsing."""
    from backend.office import pdf
    from backend.office.pdf_forms import read_pdf_form

    pdf_path = _make_plain_pdf(tmp_path / "big.pdf")
    monkeypatch.setattr(pdf, "MAX_PDF_SIZE", 1)
    with pytest.raises(OfficeSizeLimitError):
        read_pdf_form(pdf_path, workspace_path=str(tmp_path))


def test_read_pdf_form_invalid_pdf(tmp_path: Path):
    """A corrupt / non-PDF file raises OfficePdfParseError with generic msg."""
    from backend.office.pdf_forms import read_pdf_form

    bad = tmp_path / "bad.pdf"
    bad.write_text("not a pdf")
    with pytest.raises(OfficePdfParseError) as exc_info:
        read_pdf_form(bad, workspace_path=str(tmp_path))
    assert "Failed to open PDF" in str(exc_info.value)
    # Generic message must not contain internal paths.
    assert str(tmp_path) not in exc_info.value.message


# ── fill_pdf_form tests ───────────────────────────────────────────────────


def test_fill_pdf_form_no_fields(tmp_path: Path):
    """Filling a PDF without forms succeeds but fills nothing."""
    from backend.office.pdf_forms import fill_pdf_form

    pdf_path = _make_plain_pdf(tmp_path / "no_form.pdf")
    req = PdfFormFillRequest(
        workspace_path=str(tmp_path),
        template_path=str(pdf_path),
        output_filename="filled.pdf",
        data={"name": "value"},
    )
    result = fill_pdf_form(req)
    assert Path(result.output_path).exists()
    assert result.filled_count == 0
    assert result.filename == "filled.pdf"


def test_fill_pdf_form_sets_field_values(tmp_path: Path):
    """Filling a form PDF sets the field values in the output."""
    import pymupdf

    from backend.office.pdf_forms import fill_pdf_form

    pdf_path = _make_form_pdf(tmp_path / "form.pdf", ["name", "email"])
    req = PdfFormFillRequest(
        workspace_path=str(tmp_path),
        template_path=str(pdf_path),
        output_filename="filled.pdf",
        data={"name": "Alice", "email": "alice@example.com"},
    )
    result = fill_pdf_form(req)
    assert Path(result.output_path).exists()
    assert result.filled_count == 2

    # Verify field values in the output PDF.
    doc = pymupdf.open(result.output_path)
    values = {}
    for page in doc:
        for w in page.widgets():
            values[w.field_name] = w.field_value
    doc.close()
    assert values == {"name": "Alice", "email": "alice@example.com"}


def test_fill_pdf_form_flatten(tmp_path: Path):
    """Flatten=True makes fields read-only in the output."""
    import pymupdf

    from backend.office.pdf_forms import fill_pdf_form

    pdf_path = _make_form_pdf(tmp_path / "form.pdf", ["name"])
    req = PdfFormFillRequest(
        workspace_path=str(tmp_path),
        template_path=str(pdf_path),
        output_filename="flat.pdf",
        data={"name": "Bob"},
        flatten=True,
    )
    result = fill_pdf_form(req)
    assert result.filled_count == 1

    doc = pymupdf.open(result.output_path)
    for page in doc:
        for w in page.widgets():
            # Read-only is bit 0 of field_flags (PDF_FIELD_IS_READ_ONLY).
            assert w.field_flags & 1 == 1
    doc.close()


def test_fill_pdf_form_absolute_filename(tmp_path: Path):
    """Absolute output filenames are rejected."""
    from backend.office.pdf_forms import fill_pdf_form

    pdf_path = _make_plain_pdf(tmp_path / "tpl.pdf")
    req = PdfFormFillRequest(
        workspace_path=str(tmp_path),
        template_path=str(pdf_path),
        output_filename="/etc/evil.pdf",
        data={},
    )
    with pytest.raises(OfficePdfFormError, match="Invalid output filename"):
        fill_pdf_form(req)


def test_fill_pdf_form_traversal_filename(tmp_path: Path):
    """.. traversal in output filenames is rejected."""
    from backend.office.pdf_forms import fill_pdf_form

    pdf_path = _make_plain_pdf(tmp_path / "tpl.pdf")
    req = PdfFormFillRequest(
        workspace_path=str(tmp_path),
        template_path=str(pdf_path),
        output_filename="../../../etc/evil.pdf",
        data={},
    )
    with pytest.raises(OfficePdfFormError, match="Invalid output filename"):
        fill_pdf_form(req)


def test_fill_pdf_form_separator_filename(tmp_path: Path):
    """Path separators in output filenames are rejected."""
    from backend.office.pdf_forms import fill_pdf_form

    pdf_path = _make_plain_pdf(tmp_path / "tpl.pdf")
    req = PdfFormFillRequest(
        workspace_path=str(tmp_path),
        template_path=str(pdf_path),
        output_filename="sub/evil.pdf",
        data={},
    )
    with pytest.raises(OfficePdfFormError, match="Invalid output filename"):
        fill_pdf_form(req)


def test_fill_pdf_form_existing_output(tmp_path: Path):
    """An output filename that already exists is rejected (no overwrite)."""
    from backend.office.pdf_forms import fill_pdf_form

    pdf_path = _make_plain_pdf(tmp_path / "tpl.pdf")
    (tmp_path / "existing.pdf").write_text("already here")
    req = PdfFormFillRequest(
        workspace_path=str(tmp_path),
        template_path=str(pdf_path),
        output_filename="existing.pdf",
        data={},
    )
    with pytest.raises(OfficePdfFormError, match="Invalid output filename"):
        fill_pdf_form(req)


def test_fill_pdf_form_empty_filename(tmp_path: Path):
    """Empty output filenames are rejected."""
    from backend.office.pdf_forms import fill_pdf_form

    pdf_path = _make_plain_pdf(tmp_path / "tpl.pdf")
    req = PdfFormFillRequest(
        workspace_path=str(tmp_path),
        template_path=str(pdf_path),
        output_filename="",
        data={},
    )
    with pytest.raises(OfficePdfFormError, match="Invalid output filename"):
        fill_pdf_form(req)


def test_fill_pdf_form_oversized_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Oversized template PDFs are rejected before parsing."""
    from backend.office import pdf
    from backend.office.pdf_forms import fill_pdf_form

    pdf_path = _make_plain_pdf(tmp_path / "big.pdf")
    monkeypatch.setattr(pdf, "MAX_PDF_SIZE", 1)
    req = PdfFormFillRequest(
        workspace_path=str(tmp_path),
        template_path=str(pdf_path),
        output_filename="out.pdf",
        data={},
    )
    with pytest.raises(OfficeSizeLimitError):
        fill_pdf_form(req)


def test_fill_pdf_form_invalid_pdf(tmp_path: Path):
    """A corrupt template raises OfficePdfParseError with generic message."""
    from backend.office.pdf_forms import fill_pdf_form

    bad = tmp_path / "bad.pdf"
    bad.write_text("not a pdf")
    req = PdfFormFillRequest(
        workspace_path=str(tmp_path),
        template_path=str(bad),
        output_filename="out.pdf",
        data={},
    )
    with pytest.raises(OfficePdfParseError) as exc_info:
        fill_pdf_form(req)
    assert "Failed to open PDF" in str(exc_info.value)
    assert str(tmp_path) not in exc_info.value.message
