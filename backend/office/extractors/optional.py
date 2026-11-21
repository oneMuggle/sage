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
    """IBM Docling adapter (optional, complex PDF/layout oriented)."""

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
        return StructuredDocument(
            source_path=path.name,
            format=path.suffix.lower().lstrip("."),
            extractor=self.name,
            markdown=markdown,
            blocks=_paragraph_blocks(markdown),
        )
