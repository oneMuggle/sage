"""DOCX reader using python-docx.

Pure functions: no FastAPI, no I/O outside the file argument. Caller (the
FastAPI route handler in office_routes.py) wraps exceptions into HTTP errors.

The reader extracts a structured view of a .docx:
- paragraphs with style + level (heading level 0 means body text)
- tables (rows of cell text, ignoring nested tables / images inside cells)
- image count (inline shapes count as images)

It does NOT extract:
- headers / footers (out of scope per plan §1.3)
- footnotes / endnotes
- text boxes / shapes outside the body
- track changes / comments

These omissions are intentional per plan §1.3 "non-goals".
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List, Optional, Set

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

DEFAULT_ASCII_FONT = "Times New Roman"
DEFAULT_EA_FONT = "宋体"


_STYLES_TO_PATCH = (
    "Normal",
    "Title",
    "Heading 1",
    "Heading 2",
    "Heading 3",
    "List Bullet",
    "List Number",
)


def _patch_style_rfonts(style, ascii_name: str, ea_name: str) -> None:
    """向指定 style 的 rPr.rFonts 写入 ascii/hAnsi/eastAsia/cs，并清掉 theme 引用。

    python-docx 默认模板中 Title/Heading 1-9/Subtitle 等样式携带
    ``w:asciiTheme="majorHAnsi" w:eastAsiaTheme="majorEastAsia"``，这些
    theme 引用优先级高于显式 ``w:eastAsia``——不删的话日语 Word 默认
    theme 会解析为 ＭＳ ゴシック，让标题仍然渲染成日文字体。
    """
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    for theme_attr in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        attr = qn(f"w:{theme_attr}")
        if attr in rFonts.attrib:
            del rFonts.attrib[attr]
    rFonts.set(qn("w:ascii"), ascii_name)
    rFonts.set(qn("w:hAnsi"), ascii_name)
    rFonts.set(qn("w:eastAsia"), ea_name)
    rFonts.set(qn("w:cs"), ascii_name)


def _patch_linked_character_styles(doc: Document, ascii_name: str, ea_name: str) -> None:
    """Patch 所有被 ``<w:link>`` 关联的 character styles（HeadingNChar /
    TitleChar / SubtitleChar 等）。Word 渲染时，paragraph style 通过
    ``<w:link>`` 关联的 character style 的 rFonts 会覆盖 paragraph style
    本身的 rFonts——所以仅 patch paragraph style 不够，必须同步 patch 所有
    linked character style。
    """
    linked_style_ids: Set[str] = set()
    for style in doc.styles:
        link = style.element.find(qn("w:link"))
        if link is not None:
            linked_style_ids.add(link.get(qn("w:val")))
    for style in doc.styles:
        if style.style_id in linked_style_ids:
            _patch_style_rfonts(style, ascii_name, ea_name)


def set_doc_default_font(doc: Document, ascii_name: str, ea_name: str) -> None:
    """改 styles.xml 中所有 generator 用到的样式（Normal / Title / Heading
    1-3 / List Bullet / List Number）的 rPr.rFonts，强制 Word 用指定字体渲染。

    只改 Normal 不够——Title 与 Heading 1-9 默认携带 theme 引用，会让日语
    Word 渲染成 ＭＳ ゴシック；此外它们通过 ``<w:link>`` 关联的 character
    styles（HeadingNChar / TitleChar）也会覆盖 paragraph style 的 rFonts，
    必须同步 patch。
    """
    for style_name in _STYLES_TO_PATCH:
        try:
            style = doc.styles[style_name]
        except KeyError:
            continue
        _patch_style_rfonts(style, ascii_name, ea_name)
    _patch_linked_character_styles(doc, ascii_name, ea_name)

from .errors import OfficeFileNotFoundError, OfficeParseError
from .models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
    OfficeWordReadResult,
    WordParagraphContent,
    WordTableContent,
)

logger = logging.getLogger(__name__)


def _extract_heading_level(style_name: str) -> int:
    """Extract heading level from python-docx style name.

    Returns 1, 2, 3, ... for 'Heading 1', 'Heading 2', etc.
    Returns 0 for 'Normal' or any other body style.
    """
    if not style_name:
        return 0
    if style_name.startswith("Heading "):
        try:
            return int(style_name[len("Heading ") :])
        except (ValueError, IndexError):
            return 0
    if style_name == "Title":
        return 1  # treat Title as h1
    return 0


def _extract_paragraphs(doc: Document) -> List[WordParagraphContent]:
    """Extract body paragraphs (skipping tables, headers, footers)."""
    paragraphs: List[WordParagraphContent] = []
    for para in doc.paragraphs:
        style_name = para.style.name if para.style else "Normal"
        text = para.text.strip()
        # Skip empty paragraphs (would just clutter result)
        if not text:
            continue
        paragraphs.append(
            WordParagraphContent(
                style=style_name,
                text=text,
                level=_extract_heading_level(style_name),
            )
        )
    return paragraphs


def _extract_tables(doc: Document) -> List[WordTableContent]:
    """Extract body tables (skipping nested tables)."""
    tables: List[WordTableContent] = []
    for table in doc.tables:
        rows: List[List[str]] = []
        for row in table.rows:
            cells: List[str] = []
            for cell in row.cells:
                cells.append(cell.text.strip())
            rows.append(cells)
        tables.append(WordTableContent(rows=rows))
    return tables


def _count_images(doc: Document) -> int:
    """Count inline pictures in the document body.

    python-docx exposes doc.inline_shapes as a sequence of InlineShape objects,
    one per picture (image or chart).
    """
    return len(doc.inline_shapes)


def _build_docx_summary(
    file_path: Path,
    *,
    document_id: str,
    workspace_path: str,
    generated_filename: Optional[str],
    original_filename: Optional[str],
    status: OfficeDocStatus,
    paragraph_count: int,
) -> OfficeDocumentSummary:
    """Construct a summary for a DOCX document."""
    now_ms = int(time.time() * 1000)
    return OfficeDocumentSummary(
        id=document_id,
        workspace_path=workspace_path,
        doc_type=OfficeDocType.WORD,
        original_filename=original_filename,
        generated_filename=generated_filename or file_path.name,
        status=status,
        created_at=now_ms,
        updated_at=now_ms,
        metadata=OfficeDocumentMetadata(
            page_count=None,  # DOCX doesn't expose page count without rendering
            table_count=None,
            paragraph_count=paragraph_count,
            file_size_bytes=file_path.stat().st_size,
        ),
    )


def read_docx(
    file_path: Path,
    *,
    document_id: Optional[str] = None,
    workspace_path: str = "",
    generated_filename: Optional[str] = None,
    original_filename: Optional[str] = None,
) -> OfficeWordReadResult:
    """Read a .docx file and return its structured content.

    Args:
        file_path: Absolute path to the .docx file.
        document_id: Optional UUID for the summary record. Defaults to file_path.stem.
        workspace_path: Required by storage layer; pass empty string for read-only tests.
        generated_filename: Filename as stored in workspace/office/<id>/.
        original_filename: User's uploaded filename.

    Returns:
        OfficeWordReadResult with summary + paragraphs + tables + image count.

    Raises:
        OfficeFileNotFoundError: file doesn't exist.
        OfficeParseError: file exists but isn't a valid DOCX.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise OfficeFileNotFoundError(file_path)
    if not file_path.is_file():
        raise OfficeParseError(f"Path is not a regular file: {file_path}", file_path=file_path)

    try:
        doc = Document(str(file_path))
    except Exception as exc:
        # python-docx raises zipfile.BadZipFile, lxml.etree.XMLSyntaxError, etc.
        raise OfficeParseError(f"Failed to parse DOCX: {exc}", file_path=file_path) from exc

    paragraphs = _extract_paragraphs(doc)
    tables = _extract_tables(doc)
    images = _count_images(doc)

    doc_id = document_id or file_path.stem

    summary = _build_docx_summary(
        file_path,
        document_id=doc_id,
        workspace_path=workspace_path,
        generated_filename=generated_filename,
        original_filename=original_filename,
        status=OfficeDocStatus.PARSED,
        paragraph_count=len(paragraphs),
    )

    return OfficeWordReadResult(
        summary=summary,
        paragraphs=paragraphs,
        tables=tables,
        images=images,
    )


# ──────────────────────────────────────────────────────────────────────
# Generator (Phase 1.4 step 19, plan §4.1.4)
# ──────────────────────────────────────────────────────────────────────


def generate_docx(req, output_dir: Optional[str] = None) -> Path:
    """Generate a .docx file from structured Pydantic input.

    ``output_dir`` 提供时写入该任意目录（信任的用户指定目录，经
    :func:`resolve_output_path` 校验文件名）；``None`` 时保持现状写
    workspace 沙箱（``<workspace>/office/word/<id>/<name>``）。
    """
    import uuid

    from docx import Document as _Doc

    from .errors import OfficeGenerateError
    from .models import OfficeDocType
    from .path_safety import managed_document_path, resolve_output_path
    from .storage import validate_workspace

    if output_dir is not None:
        output_path = resolve_output_path(output_dir, OfficeDocType.WORD, req.filename)
    else:
        workspace = validate_workspace(Path(req.workspace_path))
        doc_id = uuid.uuid4().hex
        output_path = managed_document_path(workspace, OfficeDocType.WORD, doc_id, req.filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        doc = _Doc()
        # ★ 新增：显式设置字体（修"字体奇怪"bug）
        ascii_font = getattr(req, "ascii_font", None) or DEFAULT_ASCII_FONT
        ea_font = getattr(req, "font_family", None) or DEFAULT_EA_FONT
        set_doc_default_font(doc, ascii_font, ea_font)

        # Title
        doc.add_heading(req.title, level=0)
        # Body paragraphs
        for para in req.paragraphs:
            if para.heading == "h1":
                doc.add_heading(para.text, level=1)
            elif para.heading == "h2":
                doc.add_heading(para.text, level=2)
            elif para.heading == "h3":
                doc.add_heading(para.text, level=3)
            elif para.style == "bullet":
                # ★ 新增：bullet 列表
                doc.add_paragraph(para.text, style="List Bullet")
            elif para.style == "numbered":
                # ★ 新增：numbered 列表
                doc.add_paragraph(para.text, style="List Number")
            else:
                doc.add_paragraph(para.text)
        # Tables
        for table_spec in req.tables:
            table = doc.add_table(rows=1 + len(table_spec.rows), cols=len(table_spec.headers))
            # Header row
            for ci, header in enumerate(table_spec.headers):
                table.cell(0, ci).text = header
            # Data rows
            for ri, row in enumerate(table_spec.rows):
                for ci, cell in enumerate(row):
                    if ci < len(table_spec.headers):
                        table.cell(ri + 1, ci).text = cell
        doc.save(str(output_path))
    except Exception as exc:
        raise OfficeGenerateError(f"Failed to generate DOCX: {exc}", file_path=output_path) from exc

    return output_path
