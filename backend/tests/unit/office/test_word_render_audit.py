"""Unit tests for rendered Word audit (M5a)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.office.errors import OfficeParseError
from backend.office.export_pdf import ExportPdfResult
from backend.office.word_render_audit import audit_rendered_pdf, audit_word_render


def _make_pdf(path: Path, pages: list[dict]) -> Path:
    import fitz

    document = fitz.open()
    try:
        for spec in pages:
            page = document.new_page(
                width=float(spec.get("width", 595.28)),
                height=float(spec.get("height", 841.89)),
            )
            for text_spec in spec.get("texts", []):
                page.insert_text(
                    (float(text_spec[0]), float(text_spec[1])),
                    str(text_spec[2]),
                    fontname="helv",
                    fontsize=float(text_spec[3]),
                )
        document.save(str(path))
    finally:
        document.close()
    return path


def _fake_export(pdf_path: Path):
    def exporter(source: Path, workspace: Path, *, timeout_seconds: int = 120):
        return ExportPdfResult(ok=True, method="libreoffice", output_path=str(pdf_path))

    return exporter


def test_rendered_pdf_checks_size_margins_fonts_and_page_number(tmp_path: Path) -> None:
    pdf = _make_pdf(
        tmp_path / "doc.pdf",
        [
            {
                "width": 595.28,
                "height": 841.89,
                "texts": [(100, 100, "Hello world", 12), (5, 300, "left overflow", 12)],
            },
            {"width": 612, "height": 792, "texts": [(100, 100, "Letter page", 12)]},
        ],
    )

    issues, warnings, count = audit_rendered_pdf(
        pdf,
        expected_size="A4",
        margins_cm={"left": 2.0, "right": 2.0, "top": 2.0, "bottom": 2.0},
        allowed_fonts=["Helvetica"],
        require_page_number=True,
    )

    assert count == 2
    assert warnings == []
    categories = {(issue.page_index, issue.category) for issue in issues}
    assert (1, "page") in categories
    assert (0, "margin") in categories
    assert (0, "page_number") in categories
    assert all(issue.category != "font" for issue in issues)


def test_rendered_pdf_flags_disallowed_fonts(tmp_path: Path) -> None:
    pdf = _make_pdf(
        tmp_path / "fonts.pdf",
        [{"texts": [(100, 100, "Hello", 12)]}],
    )

    issues, _warnings, _count = audit_rendered_pdf(pdf, allowed_fonts=["SimSun"])

    assert len(issues) == 1
    assert issues[0].category == "font"
    assert "Helvetica" in issues[0].message


def test_audit_word_render_degrades_without_converter(tmp_path: Path) -> None:
    source = tmp_path / "doc.docx"
    source.write_bytes(b"not really docx")

    def failing_export(source: Path, workspace: Path, *, timeout_seconds: int = 120):
        return ExportPdfResult(ok=False, error="no soffice")

    result = audit_word_render(
        source, workspace_path=str(tmp_path), export_fn=failing_export
    )

    assert result.rendered is False
    assert result.ok is True
    assert any(warning["code"] == "render_unavailable" for warning in result.warnings)


def test_audit_word_render_uses_rendered_pdf(tmp_path: Path) -> None:
    import fitz

    source = tmp_path / "doc.docx"
    source.write_bytes(b"not really docx")
    pdf = tmp_path / "doc.pdf"
    document = fitz.open()
    page = document.new_page(width=595.28, height=841.89)
    page.insert_text((100, 100), "Hello", fontname="helv", fontsize=12)
    document.save(str(pdf))
    document.close()

    result = audit_word_render(
        source,
        workspace_path=str(tmp_path),
        options={"expected_size": "A4", "allowed_fonts": ["Helvetica"]},
        export_fn=_fake_export(pdf),
    )

    assert result.rendered is True
    assert result.method == "libreoffice"
    assert result.page_count == 1
    assert result.source_path == "doc.docx"
    assert result.issues == []


def test_audit_word_render_rejects_non_docx(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("text", encoding="utf-8")

    with pytest.raises(OfficeParseError):
        audit_word_render(source, workspace_path=str(tmp_path))
