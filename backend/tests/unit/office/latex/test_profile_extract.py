"""Tests for heuristic compliance-profile extraction."""

from __future__ import annotations

from pathlib import Path

import docx
import pymupdf
import pytest

from backend.office.errors import OfficeParseError, OfficePathError
from backend.office.latex.profile_extract import extract_latex_profile

_GUIDE = """Author Guidelines
Maximum length: 20 pages.
Manuscripts must include the following sections:
Introduction
Methods
Conclusion
Papers must use A4 paper.
Embed all fonts in the PDF.
Figures must be at least 300 dpi.
The manuscript must include an abstract and keywords.
"""


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _txt(workspace: Path, text: str = _GUIDE) -> Path:
    path = workspace / "guidelines.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _docx(path: Path, lines) -> Path:
    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    document.save(str(path))
    return path


def _pdf(path: Path, lines) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=595.28, height=841.89)
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 18
    document.save(str(path))
    document.close()
    return path


def test_extract_from_text_guidelines(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = _txt(workspace)

    result = extract_latex_profile(source, workspace=workspace)

    profile = result["profile"]
    assert result["ok"] is True
    assert result["needs_review"] is True
    assert profile["required_max_pages"] == 20
    assert profile["allowed_page_sizes"] == ["A4"]
    assert profile["require_embedded_fonts"] is True
    assert profile["min_image_dpi"] == 300
    assert profile["required_sections"] == ["Introduction", "Methods", "Conclusion"]
    assert "abstract" in profile["required_metadata"]
    assert "keywords" in profile["required_metadata"]
    fields = {item["field"] for item in result["evidence"]}
    assert {"required_max_pages", "allowed_page_sizes", "required_sections"} <= fields


def test_extract_page_range(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = _txt(workspace, "The paper should be 8-12 pages long.\n")

    result = extract_latex_profile(source, workspace=workspace)

    assert result["profile"]["required_min_pages"] == 8
    assert result["profile"]["required_max_pages"] == 12


def test_extract_from_docx(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = _docx(workspace / "guide.docx", _GUIDE.splitlines())

    result = extract_latex_profile(source, workspace=workspace)

    assert result["profile"]["required_max_pages"] == 20
    assert result["profile"]["allowed_page_sizes"] == ["A4"]


def test_extract_from_pdf(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = _pdf(
        workspace / "guide.pdf",
        [
            "Maximum length: 20 pages.",
            "Introduction",
            "Conclusion",
            "Embed all fonts in the PDF.",
            "Figures must be at least 300 dpi.",
        ],
    )

    result = extract_latex_profile(source, workspace=workspace)

    assert result["profile"]["required_max_pages"] == 20
    assert result["profile"]["require_embedded_fonts"] is True
    assert result["profile"]["min_image_dpi"] == 300
    assert "Introduction" in result["profile"]["required_sections"]


def test_rejects_unsupported_source(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = workspace / "guide.html"
    source.write_text("<html></html>", encoding="utf-8")

    with pytest.raises(OfficeParseError):
        extract_latex_profile(source, workspace=workspace)


def test_rejects_source_outside_workspace(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    outside = tmp_path / "guide.txt"
    outside.write_text(_GUIDE, encoding="utf-8")

    with pytest.raises(OfficePathError):
        extract_latex_profile(outside, workspace=workspace)
