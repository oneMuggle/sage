"""Unit tests for Word template analysis."""

import pytest
from pathlib import Path
from docx import Document

from backend.office.word_template import analyze_word_template
from backend.office.errors import OfficeFileNotFoundError, OfficeTemplateParseError
from backend.office.models import PlaceholderLocation, TemplatePlaceholderType


@pytest.fixture
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


def test_analyze_template_with_jinja_control(tmp_path: Path):
    doc = Document()
    doc.add_paragraph("{% if show_section %}")
    doc.add_paragraph("条件内容")
    doc.add_paragraph("{% endif %}")
    doc.add_paragraph("姓名：{{姓名}}")

    path = tmp_path / "with_control.docx"
    doc.save(str(path))

    result = analyze_word_template(path, workspace_path=str(tmp_path))
    assert result.has_jinja_control is True
    assert len(result.placeholders) == 1
    assert result.placeholders[0].name == "姓名"
