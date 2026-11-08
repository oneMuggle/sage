from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from backend.office.docx_text import read_docx_text


def test_read_docx_text_extracts_paragraphs(tmp_path: Path) -> None:
    doc = Document()
    doc.add_paragraph("第一段")
    doc.add_paragraph("第二段")
    doc.add_paragraph("第三段")
    path = tmp_path / "test.docx"
    doc.save(str(path))

    result = read_docx_text(path)

    assert result == "第一段\n\n第二段\n\n第三段"


def test_read_docx_text_empty_doc(tmp_path: Path) -> None:
    doc = Document()
    path = tmp_path / "empty.docx"
    doc.save(str(path))

    result = read_docx_text(path)

    assert result == ""


def test_read_docx_text_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_docx_text(tmp_path / "missing.docx")
