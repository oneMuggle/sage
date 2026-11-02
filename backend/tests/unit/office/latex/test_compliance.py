"""Tests for LaTeX source + PDF compliance checks."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import pymupdf

from backend.office.latex.compliance import check_latex_compliance

A4 = (595.28, 841.89)

_GOOD_TEX = r"""
\documentclass{article}
\title{Paper}
\author{Alice}
\keywords{latex, journals}
\begin{document}
\begin{abstract}Abstract text.\end{abstract}
\section{Introduction}
Text.
\section{Conclusion}
Done.
\end{document}
"""


def _write_tex(tmp_path: Path, text: str = _GOOD_TEX) -> Path:
    path = tmp_path / "paper.tex"
    path.write_text(text, encoding="utf-8")
    return path


def _write_pdf(
    tmp_path: Path,
    *,
    pages: int = 1,
    size: Tuple[float, float] = A4,
    text: str = "Hello",
    image: bool = False,
) -> Path:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=size[0], height=size[1])
        if text:
            page.insert_text((72, 100), text)
        if image:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10))
            pix.clear_with(200)
            page.insert_image(
                pymupdf.Rect(72, 200, 372, 500),
                stream=pix.tobytes("png"),
            )
    path = tmp_path / "paper.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _checks(result) -> dict:
    return {item["id"]: item for item in result["checks"]}


def test_source_only_passes_and_pdf_checks_skipped(tmp_path: Path) -> None:
    tex = _write_tex(tmp_path)

    result = check_latex_compliance(
        tex,
        root=tmp_path,
        profile={
            "required_sections": ["Introduction", "Conclusion"],
            "required_metadata": ["title", "author", "abstract", "keywords"],
            "forbidden_commands": ["write18"],
        },
    )

    checks = _checks(result)
    assert result["ok"] is True
    assert result["pdf_path"] is None
    assert checks["tex.sections"]["status"] == "pass"
    assert checks["tex.metadata"]["status"] == "pass"
    assert checks["tex.commands"]["status"] == "pass"
    assert all(
        checks[key]["status"] == "skipped"
        for key in ("pdf.page_count", "pdf.page_size", "pdf.fonts", "pdf.images")
    )


def test_missing_required_metadata_and_section(tmp_path: Path) -> None:
    tex = _write_tex(
        tmp_path,
        _GOOD_TEX.replace(r"\keywords{latex, journals}", "").replace(
            r"\section{Conclusion}", ""
        ),
    )

    result = check_latex_compliance(
        tex,
        root=tmp_path,
        profile={
            "required_sections": ["Conclusion"],
            "required_metadata": ["keywords"],
        },
    )

    rules = {issue["rule_id"] for issue in result["issues"]}
    assert "LATEX-META-REQUIRED" in rules
    assert "LATEX-SECTION-REQUIRED" in rules
    checks = _checks(result)
    assert checks["tex.metadata"]["status"] == "fail"
    assert checks["tex.sections"]["status"] == "fail"
    assert result["ok"] is False


def test_forbidden_command(tmp_path: Path) -> None:
    tex = _write_tex(
        tmp_path,
        _GOOD_TEX.replace("Done.", "Done.\\todo{fix me}"),
    )

    result = check_latex_compliance(
        tex,
        root=tmp_path,
        profile={"forbidden_commands": ["todo"]},
    )

    issues = [
        issue
        for issue in result["issues"]
        if issue["rule_id"] == "LATEX-COMMAND-FORBIDDEN"
    ]
    assert issues
    assert issues[0]["source"] == "tex"
    assert issues[0]["anchor"]["line"] >= 1
    assert _checks(result)["tex.commands"]["status"] == "fail"


def test_pdf_checks_page_count_size_and_fonts(tmp_path: Path) -> None:
    tex = _write_tex(tmp_path)
    pdf = _write_pdf(tmp_path, pages=1)

    result = check_latex_compliance(
        tex,
        root=tmp_path,
        pdf_path=pdf,
        profile={
            "required_min_pages": 2,
            "required_max_pages": 3,
            "allowed_page_sizes": ["Letter"],
            "require_embedded_fonts": True,
        },
    )

    rules = {issue["rule_id"] for issue in result["issues"]}
    assert "PDF-PAGE-COUNT" in rules
    assert "PDF-PAGE-SIZE-NOT-ALLOWED" in rules
    assert "PDF-FONT-NOT-EMBEDDED" in rules
    checks = _checks(result)
    assert checks["pdf.page_count"]["status"] == "fail"
    assert checks["pdf.page_size"]["status"] == "fail"
    assert checks["pdf.fonts"]["status"] == "fail"
    assert result["pdf_path"] == "paper.pdf"


def test_require_embedded_fonts_false_skips_font_check(tmp_path: Path) -> None:
    tex = _write_tex(tmp_path)
    pdf = _write_pdf(tmp_path)

    result = check_latex_compliance(
        tex,
        root=tmp_path,
        pdf_path=pdf,
        profile={"require_embedded_fonts": False},
    )

    rules = {issue["rule_id"] for issue in result["issues"]}
    assert "PDF-FONT-NOT-EMBEDDED" not in rules
    assert _checks(result)["pdf.fonts"]["status"] == "skipped"
    assert result["ok"] is True


def test_low_dpi_image_warning(tmp_path: Path) -> None:
    tex = _write_tex(tmp_path)
    pdf = _write_pdf(tmp_path, text="", image=True)

    result = check_latex_compliance(
        tex,
        root=tmp_path,
        pdf_path=pdf,
        profile={"min_image_dpi": 150},
    )

    issues = [
        issue
        for issue in result["issues"]
        if issue["rule_id"] == "PDF-IMAGE-LOW-DPI"
    ]
    assert issues
    assert issues[0]["source"] == "pdf"
    assert _checks(result)["pdf.images"]["status"] == "warn"
    assert result["ok"] is True


def test_unknown_metadata_key_warns(tmp_path: Path) -> None:
    tex = _write_tex(tmp_path)

    result = check_latex_compliance(
        tex,
        root=tmp_path,
        profile={"required_metadata": ["unknown_key"]},
    )

    profile_issues = [
        issue
        for issue in result["issues"]
        if issue["rule_id"] == "LATEX-COMPLIANCE-PROFILE"
    ]
    assert profile_issues
    assert profile_issues[0]["source"] == "profile"
    assert result["ok"] is True
