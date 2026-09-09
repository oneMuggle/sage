"""PDF → Word (text-level) converter — Office parity round 3, item N3.

Rebuilds a *text-layer* PDF as a .docx using PyMuPDF (reading) and
python-docx (writing). The plan (2026-09-09 round 3, N3) scopes this to
**text-level fidelity**; the documented approximations are:

- **Fidelity boundary**: only the text layer is converted. Scanned /
  image-only PDFs produce a nearly empty document — OCR remains a
  non-goal (plan N8). Images are *counted* per page and reported in
  :attr:`PdfToWordResult.image_count` but never embedded.
- **Heading heuristic**: for every text block the *largest span size in
  the block* is compared against the document-level body size (the most
  frequent span size weighted by character count, fallback 12.0pt):
  ``size >= body * HEADING1_SIZE_RATIO (1.6)`` → ``Heading 1``,
  ``size >= body * HEADING2_SIZE_RATIO (1.3)`` → ``Heading 2``, else a
  normal paragraph. This is intentionally coarse — real PDFs carry no
  outline semantics — but reliably maps "big title line → Heading 1,
  slightly larger section line → Heading 2" for typical documents.
- **Reading order**: blocks are walked in the order PyMuPDF reports them
  (``page.get_text("dict")``), and all lines inside a block are joined
  into one Word paragraph (soft line breaks inside the paragraph, so
  re-wrapped PDF lines don't explode into one paragraph per visual line).
- **Tables**: extracted per page with the round-2 text-layer extraction
  (:func:`backend.office.pdf._extract_page_tables`, PyMuPDF
  ``find_tables``) and rendered as docx tables **after all text blocks
  of that page** — the intra-page interleaving of tables and paragraphs
  is not preserved (documented approximation). Text blocks whose center
  falls inside a *rendered* table region are skipped from the paragraph
  stream so cell text is not duplicated; if table extraction is
  truncated or fails, the blocks stay (duplication over content loss).
- **Preflight guards** mirror ``pdf.py``: ``MAX_PDF_SIZE`` /
  ``MAX_PDF_PAGES`` are re-imported from there (single source of truth).

Output lands in the managed layout
``<workspace>/office/word/<uuid>/<out_filename>`` via the same helpers
the other generators use (``storage.generate_document_dir`` +
``path_safety.managed_document_path``). Nothing is registered in the DB
here — the route persists the row (like ``/pdf/generate`` does) so it
can attach ``derived_from`` lineage.

Contract: :func:`convert_pdf_to_word` **never raises**. Every failure —
missing source, workspace escape, oversized PDF, fitz/docx crash — comes
back as ``PdfToWordResult(ok=False, error=...)`` and is logged.

Python 3.8-compatible syntax (typing.* generics, no PEP 604) per the
backend guardrail.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pymupdf
from docx import Document
from pydantic import BaseModel, ConfigDict, Field

from .errors import OfficeError
from .models import OfficeDocType
from .path_safety import managed_document_path, resolve_within
from .pdf import MAX_PDF_PAGES, MAX_PDF_SIZE
from .storage import generate_document_dir, validate_workspace
from .word import set_doc_default_font

logger = logging.getLogger(__name__)

__all__ = [
    "PdfToWordRequest",
    "PdfToWordResult",
    "convert_pdf_to_word",
]

#: 標題启发式阈值（相对正文字号）：block 内最大字号 ≥ 正文×1.6 → Heading 1。
HEADING1_SIZE_RATIO = 1.6
#: block 内最大字号 ≥ 正文×1.3（且未达 H1 阈值）→ Heading 2。
HEADING2_SIZE_RATIO = 1.3

#: 字号统计兜底值：PDF 完全无文本层（扫描件）时把正文按 12pt 处理。
_FALLBACK_BODY_SIZE = 12.0


class PdfToWordRequest(BaseModel):
    """POST /api/v1/office/pdf/to-word."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(description="Absolute path to the workspace dir")
    file_path: str = Field(description="Absolute path to the source .pdf file")
    out_filename: Optional[str] = Field(
        default=None,
        description=(
            "Output .docx filename; defaults to '<pdf-stem>.docx'. Extension "
            "is auto-appended when omitted."
        ),
    )
    source_doc_id: Optional[str] = Field(
        default=None,
        description=(
            "Managed doc id of the source PDF. When given, the generated "
            "Word row is persisted with ``derived_from`` set to it."
        ),
    )


class PdfToWordResult(BaseModel):
    """Result of a PDF → Word conversion (never-raise contract).

    All stat fields are ``None`` unless ``ok`` is ``True``; ``error`` is
    ``None`` unless ``ok`` is ``False``.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    output_path: Optional[str] = Field(default=None, description="生成的 .docx 绝对路径")
    filename: Optional[str] = Field(default=None, description="生成的文件名（含扩展名）")
    file_size_bytes: Optional[int] = Field(default=None, ge=0)
    paragraph_count: Optional[int] = Field(default=None, ge=0)
    table_count: Optional[int] = Field(default=None, ge=0)
    image_count: Optional[int] = Field(
        default=None,
        ge=0,
        description="源 PDF 中的图片数量（转换跳过图片，仅计数上报）",
    )
    page_count: Optional[int] = Field(default=None, ge=0)
    error: Optional[str] = Field(default=None, description="失败原因；成功时为 None")


def _body_font_size(pdf: pymupdf.Document) -> float:
    """Estimate the document-level body font size (char-weighted mode).

    Walks every span once and accumulates character counts per rounded
    span size; the size carrying the most characters wins. Using the
    whole document (not per page) keeps the baseline stable on pages
    that contain only a title. Falls back to ``_FALLBACK_BODY_SIZE``
    when the PDF has no text layer at all (scanned document).
    """
    char_counts: Dict[float, int] = {}
    try:
        for page in pdf:
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text") or ""
                        if not text.strip():
                            continue
                        size = round(float(span.get("size") or 0.0), 1)
                        char_counts[size] = char_counts.get(size, 0) + len(text)
    except Exception:  # noqa: BLE001 — 统计失败走兜底字号，不阻断转换
        logger.warning("body font size estimation failed; using fallback", exc_info=True)
        return _FALLBACK_BODY_SIZE
    if not char_counts:
        return _FALLBACK_BODY_SIZE
    return max(char_counts.items(), key=lambda item: item[1])[0]


def _heading_level(max_size: float, body_size: float) -> int:
    """Map a block's largest span size to a Word heading level (0 = body)."""
    if body_size > 0 and max_size >= body_size * HEADING1_SIZE_RATIO:
        return 1
    if body_size > 0 and max_size >= body_size * HEADING2_SIZE_RATIO:
        return 2
    return 0


def _block_text(block: dict) -> str:
    """Join a PDF text block into one paragraph string.

    Lines are joined with ``\\n`` — python-docx renders newlines inside a
    run as Word soft line breaks, so re-wrapped PDF lines stay inside a
    single paragraph. Span order inside a line is preserved.
    """
    line_texts: List[str] = []
    for line in block.get("lines", []):
        parts = [span.get("text") or "" for span in line.get("spans", [])]
        line_text = "".join(parts)
        if line_text:
            line_texts.append(line_text)
    return "\n".join(line_texts)


def _block_max_font_size(block: dict) -> float:
    """Largest span size inside a text block (0.0 when the block is empty)."""
    max_size = 0.0
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            if not (span.get("text") or "").strip():
                continue
            max_size = max(max_size, float(span.get("size") or 0.0))
    return max_size


def _page_image_count(page: pymupdf.Page) -> int:
    """Count images referenced by a page (best-effort; failures count as 0)."""
    try:
        return len(page.get_images(full=True))
    except Exception:  # noqa: BLE001 — 单页图片计数失败不阻断转换
        return 0


def _inline_find_tables(page: pymupdf.Page, *, page_number: int) -> List[List[List[str]]]:
    """Minimal ``find_tables`` fallback when ``pdf._extract_page_tables`` is
    unavailable (defensive — the sibling module lives in the same package).
    """
    try:
        table_finder = page.find_tables()
    except Exception:  # noqa: BLE001 — 单页表格识别失败只跳过该页
        logger.warning("PDF table extraction failed on page %d; page skipped", page_number)
        return []
    tables: List[List[List[str]]] = []
    for table in table_finder.tables:
        try:
            extracted = table.extract()
        except Exception:  # noqa: BLE001 — 单个表格提取失败只跳过该表
            continue
        rows = [[cell if cell else "" for cell in row] for row in extracted]
        rows = [row for row in rows if row]
        if rows:
            tables.append(rows)
    return tables


def _extract_tables_for_page(page: pymupdf.Page, *, page_number: int) -> List[List[List[str]]]:
    """Round-2 text-layer table extraction with an inline fallback."""
    try:
        from .pdf import _extract_page_tables
    except ImportError:  # pragma: no cover — 同包模块，防御性兜底
        return _inline_find_tables(page, page_number=page_number)
    return _extract_page_tables(page, page_number=page_number)


def _table_bboxes(page: pymupdf.Page) -> List[Tuple[float, float, float, float]]:
    """Bounding boxes of the tables ``find_tables`` detects on a page.

    Used only to de-duplicate table text (blocks inside a rendered table
    region are skipped from the paragraph stream); detection failures
    degrade to "no skip regions", which can duplicate cell text as
    paragraphs but never loses content.
    """
    try:
        return [tuple(table.bbox) for table in page.find_tables().tables]
    except Exception:  # noqa: BLE001 — 去重失败只是重复，不能阻断转换
        return []


def _block_center_inside(
    block_bbox: Optional[List[float]],
    table_rects: List[Tuple[float, float, float, float]],
) -> bool:
    """Whether a text block's center falls inside any rendered table region."""
    if not block_bbox or not table_rects:
        return False
    x0, y0, x1, y1 = block_bbox
    center_x = (x0 + x1) / 2.0
    center_y = (y0 + y1) / 2.0
    for rx0, ry0, rx1, ry1 in table_rects:
        if rx0 <= center_x <= rx1 and ry0 <= center_y <= ry1:
            return True
    return False


def _build_docx(
    pdf: pymupdf.Document,
    *,
    body_size: float,
) -> Tuple[Document, Dict[str, int]]:
    """Walk every page and rebuild text blocks + tables as a Document.

    Returns the Document plus counters (``paragraphs`` / ``tables`` /
    ``images``). Tables are appended after the page's text blocks — the
    intra-page interleaving of tables and paragraphs is a documented
    approximation (see module docstring). Text blocks whose center falls
    inside a *rendered* table region are skipped so cell text is not
    duplicated as stray paragraphs (blocks are only dropped when the
    corresponding table actually made it into the document).
    """
    doc = Document()
    # 与 word.generate_docx 一致的中西文默认字体（宋体 / Times New Roman），
    # 避免转换产物在中文 Word 里回退到日文 theme 字体。
    set_doc_default_font(doc, "Times New Roman", "宋体")

    counters = {"paragraphs": 0, "tables": 0, "images": 0}
    for page in pdf:
        page_dict = page.get_text("dict")
        page_tables = _extract_tables_for_page(page, page_number=page.number + 1)
        # 只对真正渲染成 docx 表格的区域去重（bbox 与提取结果同序同源；
        # 提取被截断时以较少者为准，宁重复不丢内容）。
        detected_rects = _table_bboxes(page)[: len(page_tables)]
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:  # 0 = text block; image blocks are skipped
                continue
            if _block_center_inside(block.get("bbox"), detected_rects):
                continue  # 表格单元格文本由 docx 表格承载，避免重复段落
            text = _block_text(block)
            if not text.strip():
                continue
            level = _heading_level(_block_max_font_size(block), body_size)
            if level > 0:
                doc.add_heading(text, level=level)
            else:
                doc.add_paragraph(text)
            counters["paragraphs"] += 1
        for table_rows in page_tables:
            col_count = max(len(row) for row in table_rows)
            table = doc.add_table(rows=len(table_rows), cols=col_count)
            table.style = "Table Grid"
            for row_idx, row in enumerate(table_rows):
                for col_idx in range(col_count):
                    table.cell(row_idx, col_idx).text = (
                        row[col_idx] if col_idx < len(row) else ""
                    )
            counters["tables"] += 1
        counters["images"] += _page_image_count(page)
    return doc, counters


def convert_pdf_to_word(source: Path, workspace: Path, out_filename: str) -> PdfToWordResult:
    """Convert a (text-layer) PDF into a managed .docx document.

    Never raises — see module docstring for the contract and the
    documented fidelity approximations (text layer only; block-level
    heading heuristic; page-level table placement).

    Args:
        source: Path to the source PDF (must resolve inside ``workspace``).
        workspace: The managed workspace directory.
        out_filename: Desired output filename; empty/missing extension is
            handled (defaults to ``<pdf-stem>.docx`` and the ``.docx``
            extension is auto-appended when omitted).

    Returns:
        PdfToWordResult — ``ok=True`` with the managed output path and
        content counters, or ``ok=False`` with a generic ``error``.
    """
    try:
        return _convert_inner(source, workspace, out_filename)
    except OfficeError as exc:
        logger.warning("PDF→Word conversion failed: %s", exc)
        return PdfToWordResult(ok=False, error=exc.message)
    except Exception as exc:  # noqa: BLE001 — 契约：绝不向路由层抛异常
        logger.exception("PDF→Word conversion crashed unexpectedly")
        # GENERIC message — never interpolate ``exc`` or internal paths.
        return PdfToWordResult(
            ok=False,
            error=f"PDF conversion failed ({type(exc).__name__}; see logs)",
        )


def _convert_inner(source: Path, workspace: Path, out_filename: str) -> PdfToWordResult:
    # 1) Workspace boundary + source containment (mirrors read_pdf).
    resolved_workspace = validate_workspace(Path(workspace))
    source = Path(source)
    if not source.exists():
        return PdfToWordResult(ok=False, error="Source file not found")
    resolved_source = resolve_within(resolved_workspace, source)
    if not resolved_source.is_file():
        return PdfToWordResult(ok=False, error="Source path is not a regular file")

    # 2) Preflight guards — same constants as pdf.py (single source of truth).
    source_size = resolved_source.stat().st_size
    if source_size > MAX_PDF_SIZE:
        return PdfToWordResult(
            ok=False,
            error=f"Source PDF exceeds the {MAX_PDF_SIZE // (1024 * 1024)} MiB size limit",
        )

    try:
        pdf = pymupdf.open(str(resolved_source))
    except Exception as exc:
        logger.warning("Failed to open source PDF: %s", exc)
        return PdfToWordResult(ok=False, error="Failed to open PDF")
    try:
        page_count = len(pdf)
        if page_count > MAX_PDF_PAGES:
            return PdfToWordResult(
                ok=False,
                error=f"Source PDF exceeds the {MAX_PDF_PAGES}-page limit",
            )

        # 3) Heading baseline + per-page rebuild.
        body_size = _body_font_size(pdf)
        doc, counters = _build_docx(pdf, body_size=body_size)
    finally:
        pdf.close()

    # 4) Managed output: <workspace>/office/word/<uuid>/<out_filename>.
    safe_filename = (out_filename or "").strip() or f"{resolved_source.stem}.docx"
    doc_id = uuid.uuid4().hex
    # generate_document_dir 创建（并返回）managed 目录；路径算术统一走
    # managed_document_path，与存储层共享同一布局实现。
    generate_document_dir(resolved_workspace, OfficeDocType.WORD, doc_id)
    output_path = managed_document_path(
        resolved_workspace, OfficeDocType.WORD, doc_id, safe_filename
    )
    doc.save(str(output_path))

    return PdfToWordResult(
        ok=True,
        output_path=str(output_path),
        filename=output_path.name,
        file_size_bytes=output_path.stat().st_size,
        paragraph_count=counters["paragraphs"],
        table_count=counters["tables"],
        image_count=counters["images"],
        page_count=page_count,
    )
