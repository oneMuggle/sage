"""Unit tests for extended office error types (template + PDF)."""

from pathlib import Path

from backend.office.errors import (
    OfficePdfError,
    OfficePdfFormError,
    OfficePdfGenerateError,
    OfficePdfParseError,
    OfficeTemplateError,
    OfficeTemplateFillError,
    OfficeTemplateParseError,
    office_error_to_http_status,
)


def test_template_parse_error_inherits_from_template_error():
    err = OfficeTemplateParseError("bad template", file_path=Path("/tmp/bad.docx"))
    assert isinstance(err, OfficeTemplateError)
    assert err.message == "bad template"
    assert err.file_path == Path("/tmp/bad.docx")


def test_pdf_parse_error_inherits_from_pdf_error():
    err = OfficePdfParseError("corrupt pdf", file_path=Path("/tmp/bad.pdf"))
    assert isinstance(err, OfficePdfError)


def test_error_to_http_status_mapping():
    assert office_error_to_http_status(OfficeTemplateParseError("x")) == 400
    assert office_error_to_http_status(OfficeTemplateFillError("x")) == 422
    assert office_error_to_http_status(OfficePdfParseError("x")) == 400
    assert office_error_to_http_status(OfficePdfGenerateError("x")) == 500
    assert office_error_to_http_status(OfficePdfFormError("x")) == 422
