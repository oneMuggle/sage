"""Unit tests for applying a style profile to an existing Word document."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from backend.api.office_word_style_routes import (
    WordStyleApplyRequest,
    apply_style_endpoint,
)
from backend.office.word_style_apply import apply_style_to_document
from backend.office.word_style_presets import resolve_effective_format_spec


def _make_doc(tmp_path: Path, *, with_direct: bool = False) -> Path:
    doc = Document()
    doc.add_heading("第一章", level=1)
    paragraph = doc.add_paragraph()
    run = paragraph.add_run("正文")
    if with_direct:
        run.bold = True
        run.font.size = Pt(20)
        run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
    path = tmp_path / "doc.docx"
    doc.save(str(path))
    return path


def _style_rfonts(doc: Document, style_name: str):
    rPr = doc.styles[style_name].element.get_or_add_rPr()
    return rPr.find(qn("w:rFonts"))


def _spec(preset: str):
    spec = resolve_effective_format_spec(preset, None)
    assert spec is not None
    return spec


def test_apply_report_preset_restyles_existing_document(tmp_path: Path) -> None:
    source = _make_doc(tmp_path)
    result = apply_style_to_document(source, _spec("report"))
    assert result["ok"] is True
    assert result["dry_run"] is False
    output = Path(result["output_path"])
    assert output.name == "doc-styled.docx"
    assert output.exists()

    # 源文件不变
    original = Document(str(source))
    assert original.styles["Normal"].font.size is None

    styled = Document(str(output))
    assert styled.styles["Normal"].font.size.pt == pytest.approx(12)
    fonts = _style_rfonts(styled, "Normal")
    assert fonts is not None
    assert fonts.get(qn("w:eastAsia")) == "宋体"
    h1_fonts = _style_rfonts(styled, "Heading 1")
    assert h1_fonts is not None
    assert h1_fonts.get(qn("w:eastAsia")) == "黑体"
    assert styled.styles["Heading 1"].font.size.pt == pytest.approx(16)
    assert any(item["style"] == "Normal" for item in result["styles_changed"])


def test_clear_direct_formatting_keeps_bold(tmp_path: Path) -> None:
    source = _make_doc(tmp_path, with_direct=True)
    result = apply_style_to_document(
        source, _spec("report"), clear_direct_formatting=True
    )
    assert result["direct_runs_cleared"] >= 1
    styled = Document(result["output_path"])
    run = styled.paragraphs[1].runs[0]
    rPr = run._r.find(qn("w:rPr"))
    assert rPr is not None
    assert rPr.find(qn("w:sz")) is None
    assert rPr.find(qn("w:color")) is None
    # 语义强调（加粗）保留
    assert rPr.find(qn("w:b")) is not None
    assert run.font.bold is True


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    source = _make_doc(tmp_path)
    result = apply_style_to_document(source, _spec("report"), dry_run=True)
    assert result["dry_run"] is True
    assert result["saved"] is False
    assert result["output_path"] is None
    assert result["styles_changed"]
    assert not (tmp_path / "doc-styled.docx").exists()


def test_overwrite_replaces_source_atomically(tmp_path: Path) -> None:
    source = _make_doc(tmp_path)
    result = apply_style_to_document(source, _spec("report"), overwrite=True)
    assert result["output_path"] == str(source)
    styled = Document(str(source))
    assert styled.styles["Normal"].font.size.pt == pytest.approx(12)


def test_second_apply_is_idempotent(tmp_path: Path) -> None:
    source = _make_doc(tmp_path)
    first = apply_style_to_document(source, _spec("report"))
    second = apply_style_to_document(
        Path(first["output_path"]), _spec("report"), overwrite=True
    )
    assert second["styles_changed"] == []


def test_apply_requires_spec_or_preset(tmp_path: Path) -> None:
    source = _make_doc(tmp_path)
    with pytest.raises(Exception):
        apply_style_endpoint(WordStyleApplyRequest(file_path=str(source)))


def test_apply_endpoint_with_preset(tmp_path: Path) -> None:
    source = _make_doc(tmp_path)
    result = apply_style_endpoint(
        WordStyleApplyRequest(file_path=str(source), format_spec_preset="report")
    )
    assert result["ok"] is True
    assert Path(result["output_path"]).exists()


def test_apply_rejects_non_docx(tmp_path: Path) -> None:
    bogus = tmp_path / "notes.txt"
    bogus.write_text("not a docx", encoding="utf-8")
    with pytest.raises(Exception):
        apply_style_to_document(bogus, _spec("report"))
