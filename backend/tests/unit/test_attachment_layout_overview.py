"""Unit tests for the word-digest layout overview (Round 16).

`_render_layout_overview` surfaces header/footer/page-number-field/TOC
info (Round 15 read fields) in the @attachment digest — same independent
dimension semantics as the comments overview (never truncated away).
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.chat.attachment_resolver import _render_layout_overview


def _result(headers_footers=None, toc_fields=None):
    return SimpleNamespace(headers_footers=headers_footers or [], toc_fields=toc_fields or [])


def test_empty_result_renders_nothing() -> None:
    assert _render_layout_overview(_result()) == []


def test_missing_fields_renders_nothing() -> None:
    # 旧序列化产物（无 Round 15 字段）不报错
    assert _render_layout_overview(SimpleNamespace()) == []


def test_header_and_page_field_rendered() -> None:
    result = _result(
        headers_footers=[SimpleNamespace(section=1, header_text="内部资料", footer_text="", has_page_number_field=True)],
    )
    lines = _render_layout_overview(result)
    assert lines == ["页眉(第1节): 内部资料", "页脚(第1节): 含页码域"]


def test_footer_text_and_toc_rendered() -> None:
    result = _result(
        headers_footers=[SimpleNamespace(section=2, header_text="", footer_text="机密", has_page_number_field=False)],
        toc_fields=['TOC \\o "1-3" \\h \\z \\u'],
    )
    lines = _render_layout_overview(result)
    assert lines == ["页脚(第2节): 机密", '目录域: TOC \\o "1-3" \\h \\z \\u']
