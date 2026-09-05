"""Unit tests for PDF read and generate."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.office.errors import (
    OfficeFileNotFoundError,
    OfficePathError,
    OfficePdfGenerateError,
    OfficePdfParseError,
    OfficeSizeLimitError,
)
from backend.office.models import PdfGenerateRequest, PdfPageSpec


@pytest.fixture()
def simple_pdf(tmp_path: Path) -> Path:
    """Create a simple PDF for testing."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

    pdf_path = tmp_path / "test.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    c.drawString(100, 750, "Hello World")
    c.setFont("STSong-Light", 12)
    c.drawString(100, 730, "这是中文测试")
    c.showPage()
    c.drawString(100, 750, "Page 2 content")
    c.showPage()
    c.save()
    return pdf_path


# ── read_pdf tests ────────────────────────────────────────────────────────


def test_read_pdf_text(simple_pdf: Path):
    from backend.office.pdf import read_pdf

    result = read_pdf(simple_pdf, workspace_path=str(simple_pdf.parent))
    assert len(result.pages) == 2
    assert "Hello World" in result.pages[0].text
    assert "中文测试" in result.pages[0].text
    assert result.pages[0].page_number == 1


def test_read_pdf_metadata(simple_pdf: Path):
    from backend.office.pdf import read_pdf

    result = read_pdf(simple_pdf, workspace_path=str(simple_pdf.parent))
    assert result.summary is not None
    assert result.summary.doc_type.value == "pdf"


def test_read_nonexistent_pdf(tmp_path: Path):
    from backend.office.pdf import read_pdf

    with pytest.raises(OfficeFileNotFoundError):
        read_pdf(Path("/nonexistent/test.pdf"), workspace_path=str(tmp_path))


def test_read_invalid_pdf(tmp_path: Path):
    from backend.office.pdf import read_pdf

    invalid = tmp_path / "bad.pdf"
    invalid.write_text("not a pdf")
    with pytest.raises(OfficePdfParseError):
        read_pdf(invalid, workspace_path=str(tmp_path))


def test_read_pdf_workspace_escape(tmp_path: Path):
    """Workspace-escape file paths must be rejected with OfficePathError."""
    from backend.office.pdf import read_pdf

    outside = tmp_path.parent / "outside.pdf"
    # Write a real PDF so the file-not-found path doesn't trigger first.
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(outside), pagesize=A4)
    c.drawString(100, 750, "outside")
    c.save()

    with pytest.raises(OfficePathError):
        read_pdf(outside, workspace_path=str(tmp_path))


def test_read_pdf_size_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Oversized PDFs must be rejected by preflight before fitz opens them."""
    from backend.office import pdf as pdf_module
    from backend.office.pdf import read_pdf

    real_stat = Path.stat

    def big_stat(self: Path):
        """Pretend any PDF is larger than the (monkeypatched) limit."""
        st = real_stat(self)
        if self.suffix == ".pdf":
            # Patch st_size to exceed the limit.
            class _BigStat:
                st_size = pdf_module.MAX_PDF_SIZE + 1
                st_mode = st.st_mode
                st_mtime = st.st_mtime

            return _BigStat()
        return st

    monkeypatch.setattr(Path, "stat", big_stat)

    # Create a real small PDF so path validation passes.
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf_path = tmp_path / "big.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    c.drawString(100, 750, "content")
    c.save()

    with pytest.raises(OfficeSizeLimitError):
        read_pdf(pdf_path, workspace_path=str(tmp_path))


def test_read_pdf_page_count_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """PDFs with too many pages must be rejected after fitz opens them."""
    from backend.office import pdf as pdf_module
    from backend.office.pdf import read_pdf

    monkeypatch.setattr(pdf_module, "MAX_PDF_PAGES", 1)

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf_path = tmp_path / "multi.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    c.drawString(100, 750, "p1")
    c.showPage()
    c.drawString(100, 750, "p2")
    c.showPage()
    c.save()

    with pytest.raises(OfficeSizeLimitError):
        read_pdf(pdf_path, workspace_path=str(tmp_path))


def test_read_invalid_pdf_generic_message(tmp_path: Path):
    """The error message must NOT contain internal paths or low-level details."""
    from backend.office.pdf import read_pdf

    invalid = tmp_path / "corrupt.pdf"
    invalid.write_bytes(b"%PDF-1.4\ntruncated garbage that fitz cannot parse")
    with pytest.raises(OfficePdfParseError) as exc_info:
        read_pdf(invalid, workspace_path=str(tmp_path))
    assert "Failed to open PDF" in str(exc_info.value)
    # The message must not leak the internal exception text or the path.
    assert "truncated garbage" not in str(exc_info.value)


# ── generate_pdf tests ────────────────────────────────────────────────────


def test_generate_pdf_single_page(tmp_path: Path):
    from backend.office.pdf import generate_pdf

    req = PdfGenerateRequest(
        workspace_path=str(tmp_path),
        filename="output.pdf",
        pages=[
            PdfPageSpec(
                title="Test Document",
                paragraphs=["First paragraph.", "Second paragraph."],
            )
        ],
    )
    result = generate_pdf(req)
    assert result.page_count == 1
    assert Path(result.output_path).exists()
    assert result.file_size_bytes > 0


def test_generate_pdf_multi_page(tmp_path: Path):
    from backend.office.pdf import generate_pdf

    req = PdfGenerateRequest(
        workspace_path=str(tmp_path),
        filename="multi.pdf",
        pages=[
            PdfPageSpec(title="Page 1", paragraphs=["Content 1"]),
            PdfPageSpec(title="Page 2", paragraphs=["Content 2"]),
        ],
    )
    result = generate_pdf(req)
    assert result.page_count == 2


def test_generate_pdf_rejects_absolute_filename(tmp_path: Path):
    from backend.office.pdf import generate_pdf

    req = PdfGenerateRequest(
        workspace_path=str(tmp_path),
        filename="/etc/passwd",
        pages=[PdfPageSpec(title="T", paragraphs=["p"])],
    )
    with pytest.raises(OfficePdfGenerateError):
        generate_pdf(req)


def test_generate_pdf_rejects_path_traversal(tmp_path: Path):
    from backend.office.pdf import generate_pdf

    req = PdfGenerateRequest(
        workspace_path=str(tmp_path),
        filename="../escaped.pdf",
        pages=[PdfPageSpec(title="T", paragraphs=["p"])],
    )
    with pytest.raises(OfficePdfGenerateError):
        generate_pdf(req)


def test_generate_pdf_rejects_empty_filename(tmp_path: Path):
    from backend.office.pdf import generate_pdf

    req = PdfGenerateRequest(
        workspace_path=str(tmp_path),
        filename="",
        pages=[PdfPageSpec(title="T", paragraphs=["p"])],
    )
    with pytest.raises(OfficePdfGenerateError):
        generate_pdf(req)


def test_generate_pdf_rejects_existing_output_file(tmp_path: Path):
    from backend.office.pdf import generate_pdf

    # Pre-create the output file.
    (tmp_path / "exists.pdf").write_bytes(b"%PDF-1.4\n")
    req = PdfGenerateRequest(
        workspace_path=str(tmp_path),
        filename="exists.pdf",
        pages=[PdfPageSpec(title="T", paragraphs=["p"])],
    )
    with pytest.raises(OfficePdfGenerateError):
        generate_pdf(req)


def test_generate_pdf_content_verification(tmp_path: Path):
    """After generating, open the output with fitz and verify text content."""
    import pymupdf

    from backend.office.pdf import generate_pdf

    req = PdfGenerateRequest(
        workspace_path=str(tmp_path),
        filename="verify.pdf",
        pages=[
            PdfPageSpec(title="Report Title", paragraphs=["alpha", "beta"]),
            PdfPageSpec(title="Second Page", paragraphs=["gamma"]),
        ],
    )
    result = generate_pdf(req)

    doc = pymupdf.open(result.output_path)
    try:
        assert len(doc) == 2
        page0_text = doc[0].get_text()
        assert "Report Title" in page0_text
        assert "alpha" in page0_text
        assert "beta" in page0_text
        page1_text = doc[1].get_text()
        assert "Second Page" in page1_text
        assert "gamma" in page1_text
    finally:
        doc.close()
