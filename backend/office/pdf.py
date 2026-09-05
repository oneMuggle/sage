"""PDF read and generate using PyMuPDF (fitz) and reportlab.

Security posture mirrors ``word_template.py``:

- Every untrusted path goes through ``validate_workspace`` + ``resolve_within``
  so ``..`` traversal and symlink escapes are rejected at the boundary.
- ``_validate_pdf_file`` performs preflight size/page-count checks *before*
  fitz opens the file, matching ``_validate_docx_zip`` for DOCX.
- Catch-all ``except Exception`` blocks wrap with **generic** messages —
  internal paths and low-level exception text never reach the user.
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import Dict, List, Optional

import pymupdf

from .errors import (
    OfficeFileNotFoundError,
    OfficePathError,
    OfficePdfGenerateError,
    OfficePdfParseError,
    OfficeSizeLimitError,
)
from .models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
    PdfGenerateRequest,
    PdfGenerateResult,
    PdfPageContent,
    PdfReadResult,
)
from .path_safety import resolve_within
from .storage import validate_workspace

# PDF preflight limits — analogous to ``MAX_DOCX_*`` in ``word_template.py``.
MAX_PDF_SIZE = 50 * 1024 * 1024  # 50 MiB
MAX_PDF_PAGES = 10_000
MAX_PDF_OUTPUT_SIZE = 200 * 1024 * 1024  # 200 MiB


def _validate_pdf_file(file_path: Path) -> None:
    """Reject oversized or malformed PDFs before fitz opens them.

    Mirrors ``word_template._validate_docx_zip``: check file size first
    (cheap stat-only), then open via fitz to enforce page count.
    """
    compressed_size = file_path.stat().st_size
    if compressed_size > MAX_PDF_SIZE:
        raise OfficeSizeLimitError(
            compressed_size,
            MAX_PDF_SIZE,
            file_path=file_path,
        )

    try:
        doc = pymupdf.open(str(file_path))
    except OfficeSizeLimitError:
        raise
    except Exception as exc:
        # GENERIC message — never interpolate ``exc`` or the path into it.
        raise OfficePdfParseError(
            "Failed to open PDF", file_path=file_path
        ) from exc

    try:
        page_count = len(doc)
        if page_count > MAX_PDF_PAGES:
            raise OfficeSizeLimitError(
                page_count,
                MAX_PDF_PAGES,
                file_path=file_path,
            )
    finally:
        doc.close()


def _build_pdf_summary(
    file_path: Path,
    *,
    document_id: str,
    workspace_path: str,
) -> OfficeDocumentSummary:
    """Build a summary for a PDF read result."""
    now_ms = int(time.time() * 1000)
    return OfficeDocumentSummary(
        id=document_id,
        workspace_path=workspace_path,
        doc_type=OfficeDocType.PDF,
        original_filename=file_path.name,
        generated_filename=file_path.name,
        status=OfficeDocStatus.PARSED,
        created_at=now_ms,
        updated_at=now_ms,
        metadata=OfficeDocumentMetadata(file_size_bytes=file_path.stat().st_size),
    )


def read_pdf(
    file_path: Path,
    *,
    workspace_path: str,
    document_id: Optional[str] = None,
) -> PdfReadResult:
    """Read a PDF file and extract text, tables, images, and metadata."""
    file_path = Path(file_path)

    # Workspace boundary — must validate before any filesystem touch.
    workspace = validate_workspace(Path(workspace_path))
    if not file_path.exists():
        raise OfficeFileNotFoundError(file_path)
    file_path = resolve_within(workspace, file_path)

    if not file_path.is_file():
        raise OfficePathError("Path is not a regular file", file_path=file_path)

    _validate_pdf_file(file_path)

    # Re-open for content extraction (preflight closed its own handle).
    try:
        doc = pymupdf.open(str(file_path))
    except Exception as exc:
        raise OfficePdfParseError("Failed to open PDF", file_path=file_path) from exc

    pages: List[PdfPageContent] = []
    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            pages.append(
                PdfPageContent(
                    page_number=page_num + 1,
                    text=text,
                    tables=[],  # Table extraction is complex; stub for now
                    images=[],
                )
            )
        metadata: Dict = dict(doc.metadata) if doc.metadata else {}
    finally:
        doc.close()

    doc_id = document_id or file_path.stem
    summary = _build_pdf_summary(
        file_path, document_id=doc_id, workspace_path=workspace_path
    )

    return PdfReadResult(
        summary=summary,
        pages=pages,
        metadata=metadata,
    )


def generate_pdf(req: PdfGenerateRequest) -> PdfGenerateResult:
    """Generate a PDF from structured data using reportlab."""
    try:
        from reportlab.lib.pagesizes import A4, LEGAL, LETTER
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise OfficePdfGenerateError("PDF generation dependency missing") from exc

    # Workspace boundary + output filename validation.
    workspace = validate_workspace(Path(req.workspace_path))

    filename = req.filename
    if not filename or Path(filename).is_absolute() or ".." in filename:
        raise OfficePdfGenerateError("Invalid output filename")
    if "/" in filename or "\\" in filename:
        raise OfficePdfGenerateError("Invalid output filename")

    try:
        output_path = resolve_within(workspace, workspace / filename)
    except OfficePathError as exc:
        raise OfficePdfGenerateError("Invalid output filename") from exc

    if output_path.is_dir():
        raise OfficePdfGenerateError("Invalid output filename")
    if output_path.exists():
        raise OfficePdfGenerateError("Invalid output filename")

    page_size_map = {
        "A4": A4,
        "Letter": LETTER,
        "Legal": LEGAL,
    }
    page_size = page_size_map.get(req.page_size, A4)

    try:
        c = canvas.Canvas(str(output_path), pagesize=page_size)
        _width, height = page_size

        for i, page_spec in enumerate(req.pages):
            if i > 0:
                c.showPage()

            y = height - 72  # Start 1 inch from top

            # Title
            if page_spec.title:
                c.setFont("Helvetica-Bold", 16)
                c.drawString(72, y, page_spec.title)
                y -= 30

            # Paragraphs
            c.setFont("Helvetica", 12)
            for para in page_spec.paragraphs:
                if y < 72:  # Bottom margin
                    c.showPage()
                    y = height - 72
                c.drawString(72, y, para)
                y -= 18

            # Tables (shallow stub — cells laid out as text rows)
            for table_data in page_spec.tables:
                if y < 72:
                    c.showPage()
                    y = height - 72
                for row in table_data:
                    x = 72
                    for cell in row:
                        c.drawString(x, y, str(cell))
                        x += 100
                    y -= 15

        c.save()
    except OfficePdfGenerateError:
        raise
    except Exception as exc:
        # GENERIC message — never interpolate ``exc`` or the path.
        raise OfficePdfGenerateError("PDF generation failed") from exc

    try:
        output_size = output_path.stat().st_size
    except OSError as exc:
        with contextlib.suppress(OSError):
            output_path.unlink()
        raise OfficePdfGenerateError("Unable to validate generated PDF") from exc

    if output_size > MAX_PDF_OUTPUT_SIZE:
        with contextlib.suppress(OSError):
            output_path.unlink()
        raise OfficePdfGenerateError("Generated PDF exceeds size limit")

    return PdfGenerateResult(
        output_path=str(output_path),
        filename=filename,
        file_size_bytes=output_size,
        page_count=len(req.pages),
    )
