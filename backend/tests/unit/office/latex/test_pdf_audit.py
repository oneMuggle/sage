"""Tests for read-only PDF layout/font audit."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import pymupdf
import pytest

from backend.office.errors import OfficeParseError
from backend.office.latex import pdf_audit
from backend.office.latex.pdf_audit import audit_pdf

A4 = (595.28, 841.89)
LETTER = (612.0, 792.0)


def _pdf(
    path: Path,
    *,
    pages: int = 1,
    size: Tuple[float, float] = A4,
    text: str = "Hello",
    image: bool = False,
    sizes: Optional[List[Tuple[float, float]]] = None,
    encrypted: bool = False,
) -> Path:
    doc = pymupdf.open()
    page_sizes = sizes if sizes is not None else [size] * pages
    for width, height in page_sizes:
        page = doc.new_page(width=width, height=height)
        if text:
            page.insert_text((72, 100), text)
        if image:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10))
            pix.clear_with(200)
            page.insert_image(
                pymupdf.Rect(72, 200, 372, 500),
                stream=pix.tobytes("png"),
            )
    if encrypted:
        doc.save(
            str(path),
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="user",
        )
    else:
        doc.save(str(path))
    doc.close()
    return path


def test_audit_a4_reports_unembedded_font(tmp_path: Path) -> None:
    path = _pdf(tmp_path / "main.pdf")

    result = audit_pdf(path)

    assert result["summary"]["pages"] == 1
    assert result["summary"]["page_size"]["label"] == "A4"
    assert result["ok"] is False
    font_issues = [
        issue for issue in result["issues"] if issue["rule_id"] == "PDF-FONT-NOT-EMBEDDED"
    ]
    assert font_issues
    assert font_issues[0]["anchor"]["page"] == 1
    assert result["summary"]["fonts"][0]["embedded"] is False


def test_audit_page_count_limits(tmp_path: Path) -> None:
    path = _pdf(tmp_path / "two.pdf", pages=2)

    too_few = audit_pdf(path, required_min_pages=5)
    too_many = audit_pdf(path, required_max_pages=1)

    assert any(i["rule_id"] == "PDF-PAGE-COUNT" for i in too_few["issues"])
    assert any(i["rule_id"] == "PDF-PAGE-COUNT" for i in too_many["issues"])
    assert all(
        i["severity"] == "error"
        for i in too_few["issues"]
        if i["rule_id"] == "PDF-PAGE-COUNT"
    )


def test_audit_mixed_page_sizes(tmp_path: Path) -> None:
    path = _pdf(tmp_path / "mixed.pdf", sizes=[A4, LETTER])

    result = audit_pdf(path)

    assert any(i["rule_id"] == "PDF-PAGE-SIZE-MIXED" for i in result["issues"])
    assert len(result["summary"]["page_sizes"]) == 2


def test_audit_unusual_page_size(tmp_path: Path) -> None:
    path = _pdf(tmp_path / "square.pdf", size=(400.0, 400.0))

    result = audit_pdf(path)

    assert result["summary"]["page_size"]["label"] == "Custom"
    assert any(i["rule_id"] == "PDF-PAGE-SIZE-UNUSUAL" for i in result["issues"])


def test_audit_low_dpi_image(tmp_path: Path) -> None:
    path = _pdf(tmp_path / "image.pdf", image=True)

    result = audit_pdf(path)

    assert result["summary"]["images_count"] == 1
    assert result["summary"]["min_image_dpi"] < 10
    assert any(i["rule_id"] == "PDF-IMAGE-LOW-DPI" for i in result["issues"])


def test_audit_rejects_encrypted_pdf(tmp_path: Path) -> None:
    path = _pdf(tmp_path / "locked.pdf", encrypted=True)

    with pytest.raises(OfficeParseError):
        audit_pdf(path)


def test_audit_rejects_non_pdf(tmp_path: Path) -> None:
    path = tmp_path / "main.txt"
    path.write_text("not a pdf", encoding="utf-8")

    with pytest.raises(OfficeParseError):
        audit_pdf(path)


def test_audit_page_limit_reports_info(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _pdf(tmp_path / "many.pdf", pages=2)
    monkeypatch.setattr(pdf_audit, "MAX_ANALYZED_PAGES", 1)

    result = audit_pdf(path)

    assert result["summary"]["pages"] == 2
    assert any(i["rule_id"] == "PDF-PAGE-LIMIT" for i in result["issues"])


def test_audit_uses_workspace_relative_source_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = _pdf(workspace / "main.pdf")

    result = audit_pdf(path, root=workspace)

    assert result["source_path"] == "main.pdf"
