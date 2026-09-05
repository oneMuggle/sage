"""Unit tests for Word template analysis."""

from pathlib import Path

import pytest
from docx import Document
from docx.shared import Inches

from backend.office.errors import OfficeFileNotFoundError, OfficeTemplateParseError
from backend.office.models import PlaceholderLocation, TemplatePlaceholderType
from backend.office.word_template import analyze_word_template


@pytest.fixture()
def simple_template(tmp_path: Path) -> Path:
    """Create a simple Word template with placeholders."""
    doc = Document()
    doc.add_heading("合同模板", level=0)
    doc.add_paragraph("甲方：{{甲方姓名}}")
    doc.add_paragraph("乙方：{{乙方姓名}}")
    doc.add_paragraph("合同金额：{{合同金额}}")

    template_path = tmp_path / "template.docx"
    doc.save(str(template_path))
    return template_path


def test_analyze_simple_template(simple_template: Path):
    result = analyze_word_template(
        simple_template,
        workspace_path=str(simple_template.parent),
    )
    assert len(result.placeholders) == 3
    names = [p.name for p in result.placeholders]
    assert "甲方姓名" in names
    assert "乙方姓名" in names
    assert "合同金额" in names


def test_analyze_template_placeholder_details(simple_template: Path):
    result = analyze_word_template(
        simple_template,
        workspace_path=str(simple_template.parent),
    )
    for ph in result.placeholders:
        assert ph.location == PlaceholderLocation.BODY
        assert ph.type == TemplatePlaceholderType.TEXT
        assert ph.paragraph_index is not None
        assert ph.raw_tag.startswith("{{")
        assert ph.raw_tag.endswith("}}")


def test_analyze_nonexistent_file():
    with pytest.raises(OfficeFileNotFoundError):
        analyze_word_template(
            Path("/nonexistent/template.docx"),
            workspace_path="/tmp",
        )


def test_analyze_invalid_docx(tmp_path: Path):
    invalid_file = tmp_path / "invalid.docx"
    invalid_file.write_text("not a docx file")

    with pytest.raises(OfficeTemplateParseError):
        analyze_word_template(
            invalid_file,
            workspace_path=str(tmp_path),
        )


def test_analyze_non_body_placeholders_and_indices(tmp_path: Path):
    doc = Document()
    doc.add_paragraph("正文")
    body_table = doc.add_table(rows=1, cols=2)
    body_table.cell(0, 0).text = "日期：{{合同日期}}"
    body_table.cell(0, 1).text = "图片：{{签名图片}}"

    section = doc.sections[0]
    section.header.paragraphs[0].text = "页眉：{{页眉文本}}"
    header_table = section.header.add_table(rows=1, cols=1, width=Inches(1))
    header_table.cell(0, 0).text = "页眉表格：{{header_image}}"
    section.footer.paragraphs[0].text = "页脚：{{页脚文本}}"
    footer_table = section.footer.add_table(rows=1, cols=1, width=Inches(1))
    footer_table.cell(0, 0).text = "页脚表格：{{footer_date}}"

    path = tmp_path / "locations.docx"
    doc.save(str(path))

    result = analyze_word_template(path, workspace_path=str(tmp_path))
    placeholders = {placeholder.name: placeholder for placeholder in result.placeholders}

    assert placeholders["合同日期"].type == TemplatePlaceholderType.DATE
    assert placeholders["合同日期"].location == PlaceholderLocation.TABLE
    assert (placeholders["合同日期"].table_index, placeholders["合同日期"].row_index,
            placeholders["合同日期"].col_index) == (0, 0, 0)
    assert placeholders["签名图片"].type == TemplatePlaceholderType.IMAGE
    assert placeholders["页眉文本"].location == PlaceholderLocation.HEADER
    assert placeholders["页脚文本"].location == PlaceholderLocation.FOOTER
    assert placeholders["header_image"].location == PlaceholderLocation.HEADER
    assert (placeholders["header_image"].table_index, placeholders["header_image"].row_index,
            placeholders["header_image"].col_index) == (0, 0, 0)
    assert placeholders["footer_date"].location == PlaceholderLocation.FOOTER
    assert (placeholders["footer_date"].table_index, placeholders["footer_date"].row_index,
            placeholders["footer_date"].col_index) == (0, 0, 0)
    assert placeholders["footer_date"].type == TemplatePlaceholderType.DATE


@pytest.mark.parametrize("control_location", ["body_table", "header", "footer"])
def test_analyze_jinja_control_in_all_stories(tmp_path: Path, control_location: str):
    doc = Document()
    if control_location == "body_table":
        doc.add_table(rows=1, cols=1).cell(0, 0).text = "{%tr for row in rows %}"
    elif control_location == "header":
        doc.sections[0].header.paragraphs[0].text = "{% if show_header %}"
    else:
        doc.sections[0].footer.paragraphs[0].text = "{% if show_footer %}"

    path = tmp_path / (control_location + ".docx")
    doc.save(str(path))

    result = analyze_word_template(path, workspace_path=str(tmp_path))

    assert result.has_jinja_control is True
