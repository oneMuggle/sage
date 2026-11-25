"""Optional extraction backends (M6b): markitdown / docling.

Both are optional imports. They are never added to requirements; if the
package is missing the factory raises at instantiation, which the registry
probe converts to "unavailable".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import ExtractedBlock, StructuredDocument
from .tables import table_markdown

_SUPPORTED = (".docx", ".xlsx", ".pptx", ".pdf", ".csv", ".md", ".html", ".txt")


def _paragraph_blocks(markdown: str) -> List[ExtractedBlock]:
    blocks: List[ExtractedBlock] = []
    for chunk in markdown.split("\n\n"):
        text = chunk.strip()
        if text:
            blocks.append(ExtractedBlock(type="paragraph", text=text))
    return blocks


def _docling_table_rows(table: Any) -> List[List[str]]:
    """Best-effort extraction of one Docling table into rows of strings.

    Docling's table API moved around between releases, so every access is
    guarded: the newer ``table.data.grid`` first, then the pandas export.
    A table that cannot be read is skipped rather than failing the whole
    extraction.
    """
    grid = getattr(getattr(table, "data", None), "grid", None)
    if grid:
        rows: List[List[str]] = []
        for row in grid:
            cells = []
            for cell in row:
                text = getattr(cell, "text", None)
                if text is None:
                    text = str(cell)
                cells.append(text)
            rows.append(cells)
        if rows:
            return rows
    try:
        frame = table.export_to_dataframe()
    except Exception:  # noqa: BLE001 — 单个表格读不出只跳过该表
        return []
    try:
        return [[("" if value is None else str(value)) for value in row] for row in frame.values]
    except Exception:  # noqa: BLE001 — 形状意外时同样只跳过该表
        return []


def _docling_table_page(table: Any) -> Optional[int]:
    """First source page of a Docling table (1-based), if recorded."""
    provenance = getattr(table, "prov", None) or []
    for item in provenance:
        page_no = getattr(item, "page_no", None)
        if isinstance(page_no, int):
            return page_no + 1
    return None


class MarkItDownExtractor:
    """Microsoft MarkItDown adapter (optional)."""

    name = "markitdown"

    def __init__(self) -> None:
        from markitdown import MarkItDown  # noqa: PLC0415 — optional dependency

        self._converter = MarkItDown()

    def supports(self, suffix: str) -> bool:
        return suffix.lower() in _SUPPORTED

    def extract(self, path: Path) -> StructuredDocument:
        result = self._converter.convert(str(path))
        markdown = getattr(result, "text_content", None) or getattr(result, "markdown", "")
        markdown = str(markdown or "")
        return StructuredDocument(
            source_path=path.name,
            format=path.suffix.lower().lstrip("."),
            extractor=self.name,
            markdown=markdown,
            blocks=_paragraph_blocks(markdown),
        )


class DoclingExtractor:
    """IBM Docling adapter (optional, complex PDF/layout oriented).

    M6g：PDF 复杂表格兜底——Docling 的 ``document.tables`` 能识别无边框/跨页
    表格，``light`` 的 PyMuPDF ``find_tables`` 只能识别有框线表格。把 Docling
    结构化表格单独输出为 ``table`` 块，让 RAG/compare 能锚定到具体表格索引。
    """

    name = "docling"

    def __init__(self) -> None:
        from docling.document_converter import DocumentConverter  # noqa: PLC0415

        self._converter = DocumentConverter()

    def supports(self, suffix: str) -> bool:
        return suffix.lower() in _SUPPORTED

    def extract(self, path: Path) -> StructuredDocument:
        result = self._converter.convert(str(path))
        document = result.document
        markdown = str(document.export_to_markdown() or "")
        blocks: List[ExtractedBlock] = _paragraph_blocks(markdown)
        diagnostics: Dict[str, Any] = {
            "table_count": 0,
            "null_cells": 0,
            "total_cells": 0,
            "max_rows": 0,
            "max_cols": 0,
            "truncated": False,
            "failed_pages": 0,
            "borderless_candidate_pages": [],
        }
        # M6b: 结构化表格块 —— docling 能给出真正的表格网格（含合并单元格
        # 的空洞），这正是 light 后端做不到的部分。docling 各版本的表格
        # API 不一致：优先走 data.grid / export_to_dataframe 取真网格，
        # 取不到时退回 docling 自带的 export_to_markdown()；单表失败只跳过
        # 该表，不让整次提取失败。
        for table_index, table in enumerate(getattr(document, "tables", None) or []):
            rows = _docling_table_rows(table)
            table_text = table_markdown(rows) if rows else ""
            page = _docling_table_page(table) if rows else None
            if not table_text:
                try:
                    table_text = str(table.export_to_markdown() or "").strip()
                except Exception:  # noqa: BLE001 — 单表失败不阻断整篇
                    table_text = ""
            if not table_text:
                continue
            anchor: Dict[str, Any] = {"table_index": table_index, "source": "docling"}
            if page is not None:
                anchor["page"] = page
            blocks.append(
                ExtractedBlock(type="table", text=table_text, anchor=anchor)
            )
            diagnostics["table_count"] += 1
            if rows:
                diagnostics["total_cells"] += sum(len(row) for row in rows)
                diagnostics["max_rows"] = max(diagnostics["max_rows"], len(rows))
                diagnostics["max_cols"] = max(
                    diagnostics["max_cols"], *(len(row) for row in rows)
                )
                diagnostics["null_cells"] += sum(
                    1 for row in rows for cell in row if not str(cell).strip()
                )
        return StructuredDocument(
            source_path=path.name,
            format=path.suffix.lower().lstrip("."),
            extractor=self.name,
            markdown=markdown,
            blocks=blocks,
            table_diagnostics=diagnostics,
        )
