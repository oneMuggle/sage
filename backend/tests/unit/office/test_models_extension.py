"""Unit tests for extended office data models (template + PDF)."""

from backend.office.models import (
    OfficeDocType,
    OfficeWordGenerateRequest,
    PdfFormField,
    PdfGenerateRequest,
    PdfPageSpec,
    PlaceholderLocation,
    TemplatePlaceholder,
    TemplatePlaceholderType,
    WordParagraphSpec,
    WordTemplateFillRequest,
)


def test_office_doc_type_includes_pdf():
    assert OfficeDocType.PDF == "pdf"


def test_word_paragraph_spec_style_field_accepts_bullet():
    """WordParagraphSpec.style 接受 'bullet' / 'numbered'。"""
    para = WordParagraphSpec(text="item", style="bullet")
    assert para.style == "bullet"


def test_word_generate_request_accepts_font_family():
    """OfficeWordGenerateRequest.font_family 字段存在并可空。"""
    req = OfficeWordGenerateRequest(
        workspace_path="/tmp",
        filename="test",
        title="T",
        font_family="微软雅黑",
    )
    assert req.font_family == "微软雅黑"


def test_word_generate_request_font_family_optional():
    """不传 font_family 不报错，默认为 None。"""
    req = OfficeWordGenerateRequest(
        workspace_path="/tmp", filename="test", title="T"
    )
    assert req.font_family is None


def test_template_placeholder_model():
    ph = TemplatePlaceholder(
        name="客户姓名",
        raw_tag="{{客户姓名}}",
        type=TemplatePlaceholderType.TEXT,
        location=PlaceholderLocation.BODY,
        paragraph_index=5,
    )
    assert ph.name == "客户姓名"
    assert ph.paragraph_index == 5


def test_word_template_fill_request_validation():
    req = WordTemplateFillRequest(
        workspace_path="/tmp/ws",
        template_path="/tmp/ws/template.docx",
        output_filename="output.docx",
        data={"name": "张三"},
    )
    assert req.data["name"] == "张三"


def test_pdf_generate_request_defaults():
    req = PdfGenerateRequest(
        workspace_path="/tmp/ws",
        filename="output.pdf",
        pages=[PdfPageSpec(paragraphs=["Hello"])],
    )
    assert req.page_size == "A4"
    assert req.orientation == "portrait"


def test_pdf_form_field_model():
    field = PdfFormField(name="name", type="text", value="张三")
    assert field.name == "name"
    assert field.required is False
    assert field.read_only is False
