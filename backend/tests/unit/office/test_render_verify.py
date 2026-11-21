"""Unit tests for Render & Verify (M1).

Covers the PDF-level checks directly (synthetic PDFs, no converter needed)
and the orchestration layer with an injected exporter, matching the
``word_render_audit`` test pattern.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.office.errors import OfficeParseError, OfficePathError
from backend.office.export_pdf import ExportPdfResult
from backend.office.render_verify import (
    RenderVerifyIssue,
    RenderVerifyRequest,
    verify_document,
    verify_rendered_pdf,
)


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


def _request(tmp_path: Path, **overrides) -> RenderVerifyRequest:
    source = tmp_path / "doc.docx"
    if not source.exists():
        source.write_bytes(b"not really docx")
    payload = {"workspace_path": str(tmp_path), "file_path": str(source)}
    payload.update(overrides)
    return RenderVerifyRequest(**payload)


def test_verify_pdf_flags_blank_page_and_reports_summary(tmp_path: Path) -> None:
    pdf = _make_pdf(
        tmp_path / "blank.pdf",
        [
            {"texts": [(100, 100, "Hello world", 12)]},
            {},
        ],
    )

    issues, warnings, summary, thumbnails = verify_rendered_pdf(pdf)

    assert warnings == []
    assert thumbnails == []
    assert summary.pages == 2
    assert summary.inspected_pages == 2
    assert summary.text_pages == 1
    assert summary.blank_pages == 1
    assert any(issue.category == "blank_page" and issue.page_index == 1 for issue in issues)


def test_verify_pdf_flags_page_size_mismatch(tmp_path: Path) -> None:
    pdf = _make_pdf(
        tmp_path / "size.pdf",
        [
            {"width": 595.28, "height": 841.89, "texts": [(100, 100, "A4", 12)]},
            {"width": 612, "height": 792, "texts": [(100, 100, "Letter", 12)]},
        ],
    )

    issues, _warnings, _summary, _thumbs = verify_rendered_pdf(pdf, expected_size="A4")

    assert any(
        issue.category == "page_size" and issue.severity == "error" and issue.page_index == 1
        for issue in issues
    )


def test_verify_pdf_flags_margin_violation_and_missing_page_number(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "margin.pdf", [{"texts": [(5, 300, "left overflow", 12)]}])

    issues, _warnings, _summary, _thumbs = verify_rendered_pdf(
        pdf,
        margins_cm={"left": 2.0, "right": 2.0, "top": 2.0, "bottom": 2.0},
        require_page_number=True,
    )

    categories = {issue.category for issue in issues}
    assert "margin" in categories
    assert "page_number" in categories


def test_verify_pdf_flags_content_overflow(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "overflow.pdf", [{"texts": [(-40, 100, "overflow left", 12)]}])

    issues, _warnings, _summary, _thumbs = verify_rendered_pdf(pdf)

    assert any(issue.category == "content_overflow" for issue in issues)


def test_verify_pdf_returns_jpeg_thumbnails(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "thumb.pdf", [{"texts": [(100, 100, "Hello", 12)]}])

    _issues, _warnings, _summary, thumbnails = verify_rendered_pdf(
        pdf, thumbnail_pages=1, thumbnail_dpi=72
    )

    assert len(thumbnails) == 1
    assert thumbnails[0].startswith("data:image/jpeg;base64,")
    assert len(thumbnails[0]) > len("data:image/jpeg;base64,")


def test_verify_pdf_runs_visual_checker(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "visual.pdf", [{"texts": [(100, 100, "Hello", 12)]}])
    seen: dict = {}

    def checker(images: list[str]) -> list[RenderVerifyIssue]:
        seen["count"] = len(images)
        return [
            RenderVerifyIssue(
                category="visual",
                severity="warning",
                message="检测到疑似重叠",
            )
        ]

    issues, warnings, _summary, thumbnails = verify_rendered_pdf(
        pdf, visual_pages=1, visual_checker=checker
    )

    assert seen["count"] == 1
    assert warnings == []
    assert thumbnails == []
    assert any(issue.category == "visual" for issue in issues)


def test_verify_pdf_visual_checker_failure_degrades(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "visual-fail.pdf", [{"texts": [(100, 100, "Hello", 12)]}])

    def checker(images: list[str]) -> list[RenderVerifyIssue]:
        raise RuntimeError("vision unavailable")

    issues, warnings, _summary, _thumbnails = verify_rendered_pdf(
        pdf, visual_pages=1, visual_checker=checker
    )

    assert not any(issue.category == "visual" for issue in issues)
    assert any(warning["code"] == "visual_check_failed" for warning in warnings)


def test_verify_pdf_truncates_at_max_pages(tmp_path: Path) -> None:
    pdf = _make_pdf(
        tmp_path / "many.pdf",
        [
            {"texts": [(100, 100, "one", 12)]},
            {"texts": [(100, 100, "two", 12)]},
            {"texts": [(100, 100, "three", 12)]},
        ],
    )

    _issues, warnings, summary, _thumbs = verify_rendered_pdf(pdf, max_pages=2)

    assert summary.pages == 3
    assert summary.inspected_pages == 2
    assert any(warning["code"] == "page_limit_truncated" for warning in warnings)


def test_verify_pdf_rejects_unknown_expected_size(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "doc.pdf", [{"texts": [(100, 100, "Hello", 12)]}])

    with pytest.raises(OfficeParseError):
        verify_rendered_pdf(pdf, expected_size="A5")


def test_verify_document_degrades_without_converter(tmp_path: Path) -> None:
    def failing_export(source: Path, workspace: Path, *, timeout_seconds: int = 120):
        return ExportPdfResult(ok=False, error="no soffice")

    result = verify_document(_request(tmp_path), export_fn=failing_export)

    assert result.rendered is False
    assert result.status == "degraded"
    assert result.ok is True
    assert any(warning["code"] == "render_unavailable" for warning in result.warnings)


def test_verify_document_uses_rendered_pdf(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "doc.pdf", [{"texts": [(100, 100, "Hello", 12)]}])

    result = verify_document(
        _request(tmp_path, expected_size="A4"),
        export_fn=_fake_export(pdf),
    )

    assert result.rendered is True
    assert result.status == "passed"
    assert result.ok is True
    assert result.method == "libreoffice"
    assert result.page_count == 1
    assert result.source_path == "doc.docx"
    assert result.issues == []


def test_verify_document_fails_on_error_issues(tmp_path: Path) -> None:
    pdf = _make_pdf(
        tmp_path / "letter.pdf",
        [{"width": 612, "height": 792, "texts": [(100, 100, "Letter", 12)]}],
    )

    result = verify_document(
        _request(tmp_path, expected_size="A4"),
        export_fn=_fake_export(pdf),
    )

    assert result.rendered is True
    assert result.status == "failed"
    assert result.ok is False
    assert any(issue.severity == "error" for issue in result.issues)


def test_verify_document_rejects_unsupported_suffix(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("text", encoding="utf-8")

    with pytest.raises(OfficeParseError):
        verify_document(
            RenderVerifyRequest(workspace_path=str(tmp_path), file_path=str(source))
        )


def test_verify_document_rejects_path_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside.docx"
    outside.write_bytes(b"not really docx")

    with pytest.raises(OfficePathError):
        verify_document(
            RenderVerifyRequest(workspace_path=str(workspace), file_path=str(outside))
        )


def test_verify_document_rejects_oversize_file(tmp_path: Path) -> None:
    source = tmp_path / "huge.docx"
    with source.open("wb") as handle:
        handle.truncate(50 * 1024 * 1024 + 1)

    with pytest.raises(OfficeParseError):
        verify_document(
            RenderVerifyRequest(workspace_path=str(tmp_path), file_path=str(source))
        )


def _letter_docx(path: Path) -> Path:
    from docx import Document
    from docx.shared import Inches

    document = Document()
    section = document.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    document.add_paragraph("Hello")
    document.save(str(path))
    return path


def _size_reflecting_export(tmp_path: Path):
    """Render a PDF whose page size mirrors the current docx section."""

    def exporter(source: Path, workspace: Path, *, timeout_seconds: int = 120):
        import fitz
        from docx import Document

        document = Document(str(source))
        section = document.sections[0]
        width = float(section.page_width.pt)
        height = float(section.page_height.pt)
        pdf = tmp_path / f"render-{int(width)}x{int(height)}.pdf"
        pdf_doc = fitz.open()
        try:
            page = pdf_doc.new_page(width=width, height=height)
            page.insert_text((100, 100), "Hello", fontname="helv", fontsize=12)
            pdf_doc.save(str(pdf))
        finally:
            pdf_doc.close()
        return ExportPdfResult(ok=True, method="libreoffice", output_path=str(pdf))

    return exporter


def test_verify_document_repairs_word_page_size(tmp_path: Path) -> None:
    source = _letter_docx(tmp_path / "letter.docx")

    result = verify_document(
        RenderVerifyRequest(
            workspace_path=str(tmp_path),
            file_path=str(source),
            expected_size="A4",
            repair=True,
        ),
        export_fn=_size_reflecting_export(tmp_path),
    )

    assert result.status == "passed"
    assert result.repairs
    assert result.repairs[0]["fixed_count"] >= 1


def test_verify_document_repair_unsupported_format(tmp_path: Path) -> None:
    from openpyxl import Workbook

    source = tmp_path / "book.xlsx"
    workbook = Workbook()
    workbook.save(str(source))
    pdf = _make_pdf(
        tmp_path / "letter.pdf",
        [{"width": 612, "height": 792, "texts": [(100, 100, "Letter", 12)]}],
    )

    result = verify_document(
        RenderVerifyRequest(
            workspace_path=str(tmp_path),
            file_path=str(source),
            expected_size="A4",
            repair=True,
        ),
        export_fn=_fake_export(pdf),
    )

    assert result.status == "failed"
    assert any(warning["code"] == "repair_unsupported" for warning in result.warnings)
