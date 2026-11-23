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
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
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
from .progress import report_current
from .storage import validate_workspace

logger = logging.getLogger(__name__)


# Phase 3.5：pymupdf(~300ms) 只在实际读写 PDF 时才用得上；启动路径（会话列表
# / 聊天）不碰 PDF → 改为按需惰性导入。
def __getattr__(name: str) -> Any:
    from backend.core.lazy import load_module

    if name == "pymupdf":
        return load_module("pymupdf", "pymupdf", globals())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# PDF preflight limits — analogous to ``MAX_DOCX_*`` in ``word_template.py``.
MAX_PDF_SIZE = 50 * 1024 * 1024  # 50 MiB
MAX_PDF_PAGES = 10_000
MAX_PDF_OUTPUT_SIZE = 200 * 1024 * 1024  # 200 MiB

# ── M6c: 内嵌图片提取（预检 + 有界预览）────────────────────────────
# 图片相关的常量与实现全部在 ``pdf_images`` 模块 —— 那里才是「不可信
# PDF」的边界所在（过滤器白名单、解码预算、alpha 合成）。
from .pdf_images import (  # noqa: E402 — 放在常量区，保持阅读顺序
    MAX_EMBEDDED_IMAGE_BYTES,
    MAX_IMAGES_PER_PAGE,
    MAX_TOTAL_EMBEDDED_IMAGE_BYTES,
    ImageExtractionState,
    extract_page_images,
    list_page_images,
)

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
        from backend.core.lazy import load_module

        pymupdf = load_module("pymupdf", "pymupdf", globals())
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
    include_images: bool = False,
    max_images_per_page: int = 3,
    embed_image_data: bool = False,
    max_image_bytes: int = MAX_EMBEDDED_IMAGE_BYTES,
    max_total_image_bytes: int = MAX_TOTAL_EMBEDDED_IMAGE_BYTES,
) -> PdfReadResult:
    """Read a PDF file and extract text, tables, images, and metadata.

    Round 2 R2a: ``tables`` per page now comes from PyMuPDF ``find_tables``
    (text-layer ruled tables); scanned/image-only PDFs still report no tables.

    M6c: ``include_images`` 时按页提取内嵌图的**有界预览**。预算与上限在
    本函数内部强制执行（不依赖调用方自觉）：

    - ``include_images=False`` 时**完全不枚举**图片 —— 病理 PDF 的
      ``get_images()`` 单页可达 0.1s，而这条路径会被聊天附件 / LaTeX /
      Zotero / remote MCP 全部命中；
    - ``max_images_per_page`` 被 clamp 到 ``0..MAX_IMAGES_PER_PAGE``；
    - 单图在**解码前**按过滤器白名单 + 像素/字节预检（解压炸弹在这一步
      被挡住）；
    - 全文档的 base64 总量不超过 ``max_total_image_bytes``。

    ``embed_image_data=False`` 时只返回图片元数据，不带 ``data_url``。

    ``image_count`` 只在 ``include_images=True`` 时统计（没枚举就没有
    总数可言）；``images_omitted`` 是本页检测到但**未返回**的图片数
    （超出每页上限 / 预检拒绝 / 预算放不下）。
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

    # Clamp the per-page image count — callers are untrusted.
    try:
        per_page_limit = int(max_images_per_page)
    except (TypeError, ValueError):
        per_page_limit = 0
    per_page_limit = max(0, min(per_page_limit, MAX_IMAGES_PER_PAGE))

    # Re-open for content extraction (preflight closed its own handle).
    from backend.core.lazy import load_module

    pymupdf = load_module("pymupdf", "pymupdf", globals())

    try:
        doc = pymupdf.open(str(file_path))
    except Exception as exc:
        raise OfficePdfParseError("Failed to open PDF", file_path=file_path) from exc

    pages: List[PdfPageContent] = []
    # 跨页共享的图片提取状态（输出预算 + xref 缓存 + 跳过集合 + 计数）。
    image_state = ImageExtractionState(max(0, int(max_total_image_bytes)))
    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            # P4-A (office-p4a): 扫描/纯图页 OCR 兜底 —— 仅 SAGE_OCR=1 且
            # pytesseract+tesseract 可用时触发；否则保持原（空）文本。
            ocr_used = False
            from .ocr import ocr_page_if_needed

            ocr_text = ocr_page_if_needed(page, text)
            if ocr_text is not None:
                text = ocr_text
                ocr_used = True
            image_count = 0
            page_images: List[Dict[str, Any]] = []
            if include_images:
                image_infos = list_page_images(pymupdf, page, image_state)
                image_count = len(image_infos)
                page_images = extract_page_images(
                    pymupdf,
                    doc,
                    image_infos,
                    per_page_limit,
                    image_state,
                    embed_image_data=embed_image_data,
                    max_image_bytes=max(0, int(max_image_bytes)),
                )
            pages.append(
                PdfPageContent(
                    page_number=page_num + 1,
                    text=text,
                    tables=_extract_page_tables(page, page_number=page_num + 1),
                    images=page_images,
                    image_count=image_count,
                    images_omitted=max(0, image_count - len(page_images)),
                    ocr=ocr_used,
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

    # P2-A: soffice 可用时优先 HTML 路线（自动换行 + 真表格排版）；
    # soffice 缺失/失败静默回落 reportlab 直绘 —— 能力降级对用户不可见。
    from .pdf_html import generate_pdf_via_soffice

    if generate_pdf_via_soffice(req, output_path):
        return _finalize_pdf_result(output_path, filename, len(req.pages))

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

        total_pages = len(req.pages)
        for i, page_spec in enumerate(req.pages):
            # P12: 逐页进度上报（40→85 区间）
            report_current(
                f"生成页面 {i + 1}/{total_pages}",
                40 + int(45 * (i + 1) / total_pages),
            )
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

    return _finalize_pdf_result(output_path, filename, len(req.pages))


def _finalize_pdf_result(output_path: Path, filename: str, page_count: int) -> PdfGenerateResult:
    """产物校验（存在/大小上限）并组装结果；异常路径清理半成品。"""
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
        page_count=page_count,
    )
