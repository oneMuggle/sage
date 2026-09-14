"""content_sniff 单元测试：魔数 / HTML 判定 / 期望类型 / 伪装文件 mismatch。"""

import pytest

from backend.tools import content_sniff as cs

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize(
    ("head", "kind"),
    [
        (b"%PDF-1.7\n%\xe2\xe3", "pdf"),
        (b"PK\x03\x04\x14\x00", "zip"),
        (b"\x1f\x8b\x08\x00", "gzip"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"\xff\xd8\xff\xe0", "jpeg"),
        (b"Rar!\x1a\x07\x01\x00", "rar"),
        (b"MZ\x90\x00", "exe"),
        (b"<!DOCTYPE html><html>", "html"),
        (b"\xef\xbb\xbf  \n<html lang=zh>", "html"),
        (b"<!-- banner -->\n<HTML>", "html"),
        (b"<div id=app></div>", "html"),
        (b"plain text here\nline2", "text"),
        (b'{"json": true}', "text"),
        (b"", "empty"),
        (b"abc\x00def", "binary"),
    ],
)
def test_detect_kind(head, kind):
    assert cs.detect_kind(head) == kind


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("paper.pdf", "pdf"),
        ("Paper.PDF", "pdf"),
        ("data.tar.gz", "gzip"),
        ("report.docx", "zip"),
        ("old.doc", "ole"),
        ("readme.txt", None),
        ("noext", None),
        (None, None),
    ],
)
def test_expected_kind_from_name(name, kind):
    assert cs.expected_kind_from_name(name) == kind


@pytest.mark.parametrize(
    ("ct", "kind"),
    [
        ("application/pdf", "pdf"),
        ("application/pdf; charset=binary", "pdf"),
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "zip"),
        ("application/msword", "ole"),
        ("application/octet-stream", None),
        ("text/html; charset=utf-8", None),
        ("", None),
        (None, None),
    ],
)
def test_expected_kind_from_content_type(ct, kind):
    assert cs.expected_kind_from_content_type(ct) == kind


def test_sniff_html_instead_of_pdf_is_mismatch():
    result = cs.sniff(b"<html><body>login</body></html>", "text/html", "paper.pdf")
    assert result.detected == "html"
    assert result.expected == "pdf"
    assert result.mismatch is True


def test_sniff_content_type_lies_but_magic_wins():
    result = cs.sniff(b"<!doctype html>", "application/pdf", "dl")
    assert result.mismatch is True


def test_sniff_genuine_pdf_no_mismatch():
    result = cs.sniff(b"%PDF-1.4", "application/pdf", "paper.pdf")
    assert result.detected == "pdf"
    assert result.mismatch is False


def test_sniff_html_without_expectation_is_fine():
    result = cs.sniff(b"<html>", "text/html", "page.html")
    assert result.expected is None
    assert result.mismatch is False


def test_sniff_binary_kind_differs_is_not_mismatch():
    """.zip 实为 gzip：都是二进制，不算伪装。"""
    result = cs.sniff(b"\x1f\x8b\x08", "application/zip", "a.zip")
    assert result.detected == "gzip"
    assert result.mismatch is False


@pytest.mark.parametrize(
    ("ct", "expected"),
    [
        ("application/pdf", True),
        ("image/png", True),
        ("application/octet-stream", True),
        ("application/vnd.ms-excel", True),
        ("text/html", False),
        ("application/json", False),
        ("image/svg+xml", False),
        ("", False),
    ],
)
def test_is_binary_content_type(ct, expected):
    assert cs.is_binary_content_type(ct) is expected


def test_is_binary_payload_prefers_textual_content_type():
    # UTF-16 文本带 NUL，但 Content-Type 明示文本 → 不按二进制
    assert cs.is_binary_payload(b"h\x00i\x00", "text/plain; charset=utf-16") is False


def test_is_binary_payload_falls_back_to_magic():
    assert cs.is_binary_payload(b"%PDF-1.5", "") is True
    assert cs.is_binary_payload(b"hello", "") is False
    assert cs.is_binary_payload(b"<html>", "application/unknown") is False


def test_html_excerpt_strips_tags_and_collapses_whitespace():
    head = b"<html><head><title>Sign in</title></head><body>\n\n  Please   <b>log in</b>\n</body></html>"
    assert cs.html_excerpt(head) == "Sign in Please log in"


def test_html_excerpt_respects_limit():
    assert len(cs.html_excerpt(b"<p>" + b"x" * 1000 + b"</p>", limit=50)) == 50
