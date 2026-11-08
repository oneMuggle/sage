from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ruff: noqa: UP006, UP007, UP035


def read_docx_text(path: Path) -> str:
    """Extract all paragraph text from a .docx file, joined by double newlines.

    Used by generate workspace for reference texts and iterate mode.
    Raises FileNotFoundError if path does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"docx file not found: {path}")
    from docx import Document

    doc = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)
