"""PDF read and generate using PyMuPDF (fitz) and reportlab.

Security posture mirrors ``word_template.py``:

- Every untrusted path goes through ``validate_workspace`` + ``resolve_within``
  so ``..`` traversal and symlink escapes are rejected at the boundary.
- ``_validate_pdf_file`` performs preflight size/page-count checks *before*
  fitz opens the file, matching ``_validate_docx_zip`` for DOCX.
- Catch-all ``except Exception`` blocks wrap with **generic** messages —
  internal paths and low-level exception text never reach the user.

Read fidelity (round 2 R2a): text-layer tables are extracted per page via
PyMuPDF ``page.find_tables()`` (ruled/lined tables; PyMuPDF ≥1.25 API).
Scanned / image-only PDFs still yield no tables — OCR remains a non-goal.
"""

from __future__ import annotations

import contextlib
import logging
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

logger = logging.getLogger(__name__)

# PDF preflight limits — analogous to ``MAX_DOCX_*`` in ``word_template.py``.
MAX_PDF_SIZE = 50 * 1024 * 1024  # 50 MiB
MAX_PDF_PAGES = 10_000
MAX_PDF_OUTPUT_SIZE = 200 * 1024 * 1024  # 200 MiB

#: Round 2 R2a: per-page cap on extracted table cells. Pathological PDFs
#: (huge ruled grids, or dense line art misread as tables) are truncated
#: here instead of ballooning the read result; the truncation is logged.
MAX_TABLE_CELLS_PER_PAGE = 20_000

#: CJK font for generated PDFs. The base-14 Helvetica has no CJK glyphs, so
#: Chinese text would render as blanks. STSong-Light is the Adobe CID font
#: bundled with reportlab's Asian-language support; it also covers ASCII, so
#: mixed 中英文 content renders from one font.
_CJK_PDF_FONT = "STSong-Light"


def _register_cjk_font() -> Optional[str]:
    """Register the CJK CID font and return its name, or ``None`` on failure.

    Guarded: a reportlab build without Asian font packs (or any other
    registration failure) falls back to the previous Helvetica-only
    behaviour instead of failing generation.
    """
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont

        pdfmetrics.registerFont(UnicodeCIDFont(_CJK_PDF_FONT))
        return _CJK_PDF_FONT
    except Exception:  # noqa: BLE001 — 字体注册失败必须回退，不能阻断生成
        return None


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


def _extract_page_tables(page: pymupdf.Page, *, page_number: int) -> List[List[List[str]]]:
    """Extract text-layer tables from one page via PyMuPDF ``find_tables``.

    Round 2 R2a. ``find_tables`` detects ruled/lined tables; their cells come
    back as ``str`` or ``None`` (empty), and ``None`` is normalized to ``""``.

    Guards:
    - a page whose ``find_tables()`` raises is skipped entirely (logged), so
      one bad page cannot fail the whole read;
    - a table whose ``extract()`` raises is skipped (logged);
    - extraction stops at ``MAX_TABLE_CELLS_PER_PAGE`` cells per page (the
      tables extracted first win; the truncation is logged).

    Scanned / image-only pages have no vector rules, so they yield ``[]`` —
    OCR remains a non-goal.
    """
    try:
        table_finder = page.find_tables()
    except Exception:  # noqa: BLE001 — 单页识别失败不阻断整篇读取
        logger.warning("PDF table extraction failed on page %d; page skipped", page_number)
        return []

    tables: List[List[List[str]]] = []
    cells_seen = 0
    truncated = False
    for table in table_finder.tables:
        try:
            extracted_rows = table.extract()
        except Exception:  # noqa: BLE001 — 单个表格提取失败只跳过该表
            logger.warning("PDF table extraction failed on page %d; table skipped", page_number)
            continue
        rows: List[List[str]] = []
        for row in extracted_rows:
            row_cells: List[str] = []
            for cell in row:
                if cells_seen >= MAX_TABLE_CELLS_PER_PAGE:
                    truncated = True
                    break
                row_cells.append(cell if cell else "")
                cells_seen += 1
            if row_cells:
                rows.append(row_cells)
            if truncated:
                break
        if rows:
            tables.append(rows)
        if truncated:
            break
    if truncated:
        logger.warning(
            "PDF table cells truncated at %d on page %d", MAX_TABLE_CELLS_PER_PAGE, page_number
        )
    return tables


def read_pdf(
    file_path: Path,
    *,
    workspace_path: str,
    document_id: Optional[str] = None,
) -> PdfReadResult:
    """Read a PDF file and extract text, tables, images, and metadata.

    Round 2 R2a: ``tables`` per page now comes from PyMuPDF ``find_tables``
    (text-layer ruled tables); scanned/image-only PDFs still report no tables.
    """
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
                    tables=_extract_page_tables(page, page_number=page_num + 1),
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

        # CJK-capable font with Helvetica fallback (registration failed).
        cjk_font = _register_cjk_font()
        title_font = cjk_font or "Helvetica-Bold"
        body_font = cjk_font or "Helvetica"

        for i, page_spec in enumerate(req.pages):
            if i > 0:
                c.showPage()

            y = height - 72  # Start 1 inch from top

            # Title
            if page_spec.title:
                c.setFont(title_font, 16)
                c.drawString(72, y, page_spec.title)
                y -= 30

            # Paragraphs
            c.setFont(body_font, 12)
            for para in page_spec.paragraphs:
                if y < 72:  # Bottom margin
                    c.showPage()
                    y = height - 72
                c.drawString(72, y, para)
                y -= 18

            # Tables (shallow stub — cells laid out as text rows)
            c.setFont(body_font, 12)
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
