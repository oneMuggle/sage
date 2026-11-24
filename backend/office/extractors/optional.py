"""Optional extraction backends (M6b): markitdown / docling.

Both are optional imports. They are never added to requirements; if the
package is missing the factory raises at instantiation, which the registry
probe converts to "unavailable".
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from .base import ExtractedBlock, StructuredDocument

_SUPPORTED = (".docx", ".xlsx", ".pptx", ".pdf", ".csv", ".md", ".html", ".txt")


def _paragraph_blocks(markdown: str) -> List[ExtractedBlock]:
    blocks: List[ExtractedBlock] = []
    for chunk in markdown.split("\n\n"):
        text = chunk.strip()
        if text:
            blocks.append(ExtractedBlock(type="paragraph", text=text))
    return blocks


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
        tables = getattr(document, "tables", None) or []
        for table_index, table in enumerate(tables):
            try:
                table_md = str(table.export_to_markdown() or "")
            except Exception:  # noqa: BLE001 — 单表失败不阻断整篇
                table_md = ""
            if table_md.strip():
                blocks.append(
                    ExtractedBlock(
                        type="table",
                        text=table_md.strip(),
                        anchor={"table_index": table_index, "source": "docling"},
                    )
                )
        return StructuredDocument(
            source_path=path.name,
            format=path.suffix.lower().lstrip("."),
            extractor=self.name,
            markdown=markdown,
            blocks=blocks,
        )
