"""OOXML → JournalSpec 解析测试。

TDD: 先写失败测试，再实现 parser.py。
"""
from pathlib import Path

import pytest

from backend.office.journal.errors import JournalParseError
from backend.office.journal.models import CitationStyle
from backend.office.journal.parser import parse_journal_spec


FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "fixtures" / "journal"
)


def test_parse_simple_chinese_template_extracts_spec():
    spec = parse_journal_spec(FIXTURE_DIR / "simple_chinese_template.docx")
    assert spec.template_filename == "simple_chinese_template.docx"
    assert spec.body_pt == 12.0
    assert spec.heading_pt == 16.0
    assert abs(spec.line_spacing - 1.5) < 0.01
    assert abs(spec.margins_cm - 2.54) < 0.1
    assert spec.font_body.eastasia is not None  # 宋体或宋体归一化
    assert spec.citation_style == CitationStyle.UNKNOWN or isinstance(
        spec.citation_style, CitationStyle
    )
    assert any(h.keyword == "摘要" for h in spec.headings)


def test_parse_bad_template_corrupt_raises_parse_error():
    with pytest.raises(JournalParseError):
        parse_journal_spec(FIXTURE_DIR / "bad_template_corrupt.docx")


def test_parse_docx_missing_raises_parse_error(tmp_path: Path):
    with pytest.raises(JournalParseError):
        parse_journal_spec(tmp_path / "ghost.docx")


def test_parse_doc_without_pandoc_raises(tmp_path: Path, monkeypatch):
    """当 pandoc 不可用时，.doc 输入应抛 JournalParseError（包装自 JournalPandocError）。"""
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    src = tmp_path / "in.doc"
    src.write_bytes(b"\xd0\xcf\x11\xe0\xa1\x1a\xe1" + b"x" * 256)
    with pytest.raises(JournalParseError) as exc:
        parse_journal_spec(src)
    assert "pandoc" in str(exc.value).lower()