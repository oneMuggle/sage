"""Word template analysis and fill using docxtpl.

docxtpl extends python-docx with Jinja2-like template syntax:
- {{variable}} for text placeholders
- {% if condition %} ... {% endif %} for control flow
- {%tr for row in rows %} ... {%tr endfor %} for table loops
"""

from __future__ import annotations

import re
import time
import zipfile
from pathlib import Path
from typing import List, Optional

from docx import Document

from .errors import (
    OfficeFileNotFoundError,
    OfficeSizeLimitError,
    OfficeTemplateParseError,
)
from .models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
    PlaceholderLocation,
    TemplatePlaceholder,
    TemplatePlaceholderType,
    WordTemplateAnalysis,
)
from .path_safety import resolve_within
from .storage import validate_workspace

PLACEHOLDER_RE = re.compile(r"\{\{([^}]+)\}\}")
JINJA_CONTROL_RE = re.compile(r"\{%[^%]+%\}")
MAX_DOCX_COMPRESSED_SIZE = 50 * 1024 * 1024
MAX_DOCX_MEMBERS = 10_000
MAX_DOCX_UNCOMPRESSED_SIZE = 250 * 1024 * 1024


def _validate_docx_zip(file_path: Path) -> None:
    """Reject oversized or malformed DOCX ZIP containers before parsing."""
    try:
        compressed_size = file_path.stat().st_size
        if compressed_size > MAX_DOCX_COMPRESSED_SIZE:
            raise OfficeSizeLimitError(
                compressed_size,
                MAX_DOCX_COMPRESSED_SIZE,
                file_path=file_path,
            )
        with zipfile.ZipFile(str(file_path)) as archive:
            members = archive.infolist()
            if len(members) > MAX_DOCX_MEMBERS:
                raise OfficeSizeLimitError(
                    len(members),
                    MAX_DOCX_MEMBERS,
                    file_path=file_path,
                )
            uncompressed_size = sum(member.file_size for member in members)
            if uncompressed_size > MAX_DOCX_UNCOMPRESSED_SIZE:
                raise OfficeSizeLimitError(
                    uncompressed_size,
                    MAX_DOCX_UNCOMPRESSED_SIZE,
                    file_path=file_path,
                )
    except OfficeSizeLimitError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise OfficeTemplateParseError(
            f"Failed to inspect DOCX ZIP: {exc}", file_path=file_path
        ) from exc


def _extract_placeholders_from_text(
    text: str,
    location: PlaceholderLocation,
    *,
    paragraph_index: Optional[int] = None,
    table_index: Optional[int] = None,
    row_index: Optional[int] = None,
    col_index: Optional[int] = None,
) -> List[TemplatePlaceholder]:
    """Extract {{}} placeholders from a text string."""
    placeholders = []
    for match in PLACEHOLDER_RE.finditer(text):
        raw_tag = match.group(0)
        name = match.group(1).strip()

        if "日期" in name or "date" in name.lower():
            ph_type = TemplatePlaceholderType.DATE
        elif "图片" in name or "image" in name.lower():
            ph_type = TemplatePlaceholderType.IMAGE
        else:
            ph_type = TemplatePlaceholderType.TEXT

        placeholders.append(
            TemplatePlaceholder(
                name=name,
                raw_tag=raw_tag,
                type=ph_type,
                location=location,
                paragraph_index=paragraph_index,
                table_index=table_index,
                row_index=row_index,
                col_index=col_index,
            )
        )
    return placeholders


def _scan_paragraphs(doc: Document) -> List[TemplatePlaceholder]:
    """Scan all body paragraphs for placeholders."""
    placeholders = []
    for idx, para in enumerate(doc.paragraphs):
        text = para.text
        if PLACEHOLDER_RE.search(text):
            placeholders.extend(
                _extract_placeholders_from_text(
                    text, PlaceholderLocation.BODY, paragraph_index=idx
                )
            )
    return placeholders


def _cell_direct_text(cell) -> str:
    """Return paragraph text directly in a cell, excluding nested tables."""
    return "\n".join(paragraph.text for paragraph in cell.paragraphs)


def _scan_table(table, location: PlaceholderLocation, table_index: int) -> List[TemplatePlaceholder]:
    """Scan a table and nested tables using the outer table index."""
    placeholders = []
    for row_idx, row in enumerate(table.rows):
        for col_idx, cell in enumerate(row.cells):
            text = _cell_direct_text(cell)
            if PLACEHOLDER_RE.search(text):
                placeholders.extend(
                    _extract_placeholders_from_text(
                        text,
                        location,
                        table_index=table_index,
                        row_index=row_idx,
                        col_index=col_idx,
                    )
                )
            for nested_table in cell.tables:
                placeholders.extend(_scan_table(nested_table, location, table_index))
    return placeholders


def _scan_tables(doc: Document) -> List[TemplatePlaceholder]:
    """Scan all tables, including nested tables."""
    placeholders = []
    for table_idx, table in enumerate(doc.tables):
        placeholders.extend(_scan_table(table, PlaceholderLocation.TABLE, table_idx))
    return placeholders


def _scan_story_tables(story, location: PlaceholderLocation) -> List[TemplatePlaceholder]:
    """Scan tables in a document story, including nested tables."""
    placeholders = []
    for table_idx, table in enumerate(story.tables):
        placeholders.extend(_scan_table(table, location, table_idx))
    return placeholders


def _scan_headers_footers(doc: Document) -> List[TemplatePlaceholder]:
    """Scan paragraphs and tables in headers and footers."""
    placeholders = []
    for section in doc.sections:
        for story, location in (
            (section.header, PlaceholderLocation.HEADER),
            (section.footer, PlaceholderLocation.FOOTER),
        ):
            for para in story.paragraphs:
                if PLACEHOLDER_RE.search(para.text):
                    placeholders.extend(
                        _extract_placeholders_from_text(para.text, location)
                    )
            placeholders.extend(_scan_story_tables(story, location))
    return placeholders


def _table_has_jinja_control(table) -> bool:
    """Check direct cell text and nested tables for Jinja controls."""
    for row in table.rows:
        for cell in row.cells:
            if JINJA_CONTROL_RE.search(_cell_direct_text(cell)):
                return True
            if any(_table_has_jinja_control(nested) for nested in cell.tables):
                return True
    return False


def _story_has_jinja_control(story) -> bool:
    """Check paragraphs and nested table cells in one document story."""
    if any(JINJA_CONTROL_RE.search(para.text) for para in story.paragraphs):
        return True
    return any(_table_has_jinja_control(table) for table in story.tables)


def _has_jinja_control(doc: Document) -> bool:
    """Check body, tables, headers, and footers for Jinja2 controls."""
    if _story_has_jinja_control(doc):
        return True
    return any(
        _story_has_jinja_control(story)
        for section in doc.sections
        for story in (section.header, section.footer)
    )


def _build_template_summary(
    file_path: Path,
    *,
    document_id: str,
    workspace_path: str,
) -> OfficeDocumentSummary:
    """Build a summary for the template analysis result."""
    now_ms = int(time.time() * 1000)
    return OfficeDocumentSummary(
        id=document_id,
        workspace_path=workspace_path,
        doc_type=OfficeDocType.WORD,
        original_filename=file_path.name,
        generated_filename=file_path.name,
        status=OfficeDocStatus.PARSED,
        created_at=now_ms,
        updated_at=now_ms,
        metadata=OfficeDocumentMetadata(file_size_bytes=file_path.stat().st_size),
    )


def analyze_word_template(
    file_path: Path,
    *,
    workspace_path: str,
    document_id: Optional[str] = None,
) -> WordTemplateAnalysis:
    """Analyze a Word template and extract all {{}} placeholders."""
    file_path = Path(file_path)
    workspace = validate_workspace(Path(workspace_path))
    if not file_path.exists():
        raise OfficeFileNotFoundError(file_path)
    file_path = resolve_within(workspace, file_path)

    if not file_path.exists():
        raise OfficeFileNotFoundError(file_path)
    if not file_path.is_file():
        raise OfficeTemplateParseError(
            f"Path is not a file: {file_path}", file_path=file_path
        )

    _validate_docx_zip(file_path)
    try:
        doc = Document(str(file_path))
    except Exception as exc:
        raise OfficeTemplateParseError(
            f"Failed to parse DOCX: {exc}", file_path=file_path
        ) from exc

    placeholders: List[TemplatePlaceholder] = []
    placeholders.extend(_scan_paragraphs(doc))
    placeholders.extend(_scan_tables(doc))
    placeholders.extend(_scan_headers_footers(doc))

    doc_id = document_id or file_path.stem
    summary = _build_template_summary(
        file_path, document_id=doc_id, workspace_path=workspace_path
    )

    return WordTemplateAnalysis(
        file_path=str(file_path),
        placeholders=placeholders,
        summary=summary,
        has_jinja_control=_has_jinja_control(doc),
    )
