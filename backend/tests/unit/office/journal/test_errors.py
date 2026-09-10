"""JournalError 层级 HTTP 映射测试。

错误基类 JournalError 必须继承 OfficeError；
6 个细分错误码分别映射到不同的 HTTP 状态码，
通过 backend.office.errors.office_error_to_http_status 复用映射。
"""
from backend.office.errors import (
    OfficeError,
    OfficeParseError,
    office_error_to_http_status,
)
from backend.office.journal.errors import (
    JournalContentShapeError,
    JournalError,
    JournalGenerationError,
    JournalPandocError,
    JournalParseError,
    JournalSpecNotFoundError,
)


def test_journal_error_inherits_office_error():
    err = JournalError("boom")
    assert isinstance(err, OfficeError)
    assert str(err) == "boom"


def test_journal_parse_error_maps_to_office_parse_error_http():
    err = JournalParseError("bad xml")
    assert isinstance(err, OfficeParseError)
    assert office_error_to_http_status(err) == 422


def test_journal_spec_not_found_maps_to_404():
    err = JournalSpecNotFoundError("spec_id=abc")
    assert office_error_to_http_status(err) == 404


def test_journal_content_shape_error_maps_to_422():
    err = JournalContentShapeError("missing 'abstract'")
    assert office_error_to_http_status(err) == 422


def test_journal_pandoc_error_maps_to_500():
    err = JournalPandocError("exit 1")
    assert office_error_to_http_status(err) == 500


def test_journal_generation_error_maps_to_500():
    err = JournalGenerationError("llm timeout")
    assert office_error_to_http_status(err) == 500
