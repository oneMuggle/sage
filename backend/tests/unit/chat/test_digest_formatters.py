"""3 个 digest 格式化器单元测试 (Task 2).

覆盖 pptx (title + text_blocks), docx (首句), excel (sheet 名 + 前 5 行)
的边界条件: 空 slide/paragraph/sheet, 长文本裁剪, OfficePathError 透传。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.chat import attachment_resolver
from backend.chat.attachment_resolver import (
    _digest_excel,
    _digest_ppt,
    _digest_word,
)
from backend.office.errors import OfficePathError

# ─── _digest_ppt ────────────────────────────────────────────────


def _fake_ppt(slides):
    """Build OfficePptReadResult with given slides list."""
    from backend.office.models import (
        OfficeDocumentMetadata,
        OfficeDocumentSummary,
        OfficePptReadResult,
    )

    summary = OfficeDocumentSummary(
        id="x",
        workspace_path="/w",
        doc_type="ppt",
        original_filename=None,
        generated_filename="x.pptx",
        status="parsed",
        created_at=0,
        updated_at=0,
        metadata=OfficeDocumentMetadata(file_size_bytes=0, page_count=len(slides)),
    )
    return OfficePptReadResult(summary=summary, slides=slides)


def test_digest_ppt_basic() -> None:
    from backend.office.models import PptSlideContent

    slides = [
        PptSlideContent(
            index=0,
            title="Intro",
            text_blocks=["hi", "world"],
            table_count=0,
            image_count=0,
            notes=None,
        ),
        PptSlideContent(
            index=1,
            title=None,
            text_blocks=["no title slide"],
            table_count=0,
            image_count=0,
            notes=None,
        ),
    ]
    with patch.object(attachment_resolver, "read_ppt", return_value=_fake_ppt(slides)):
        out = _digest_ppt("/w/x.pptx", workspace="/w")
    assert "[Intro]" in out
    assert "  - hi" in out
    assert "  - world" in out
    assert "[(untitled)]" in out
    assert "  - no title slide" in out


def test_digest_ppt_empty() -> None:
    with patch.object(attachment_resolver, "read_ppt", return_value=_fake_ppt([])):
        out = _digest_ppt("/w/empty.pptx", workspace="/w")
    assert out == ""


def test_digest_ppt_propagates_path_error() -> None:
    # nested-with is canonical pytest.raises idiom; merging would require
    # Py3.10+ parenthesized with (SIM117 unsafe fix), breaking Win7 Py3.8.
    with patch.object(  # noqa: SIM117
        attachment_resolver,
        "read_ppt",
        side_effect=OfficePathError("traversal blocked", file_path=None),
    ):
        with pytest.raises(OfficePathError):
            _digest_ppt("/etc/passwd.pptx", workspace="/w")


# ─── _digest_word ───────────────────────────────────────────────


def _fake_word(paragraphs):
    from backend.office.models import (
        OfficeDocumentMetadata,
        OfficeDocumentSummary,
        OfficeWordReadResult,
    )

    summary = OfficeDocumentSummary(
        id="y",
        workspace_path="/w",
        doc_type="word",
        original_filename=None,
        generated_filename="y.docx",
        status="parsed",
        created_at=0,
        updated_at=0,
        metadata=OfficeDocumentMetadata(file_size_bytes=0, page_count=0),
    )
    return OfficeWordReadResult(
        summary=summary,
        paragraphs=paragraphs,
        tables=[],
        images=0,
    )


def test_digest_word_first_sentence() -> None:
    from backend.office.models import WordParagraphContent

    paragraphs = [
        WordParagraphContent(style="Normal", text="First sentence here.", level=0),
        WordParagraphContent(
            style="Normal",
            text="Second paragraph spans two sentences. Final one.",
            level=0,
        ),
    ]
    with patch.object(attachment_resolver, "read_docx", return_value=_fake_word(paragraphs)):
        out = _digest_word("/w/y.docx", workspace="/w")
    lines = out.splitlines()
    assert lines[0] == "First sentence here."
    assert lines[1] == "Second paragraph spans two sentences."


def test_digest_word_skips_empty_paragraphs() -> None:
    from backend.office.models import WordParagraphContent

    paragraphs = [
        WordParagraphContent(style="Normal", text="real.", level=0),
        WordParagraphContent(style="Normal", text="   ", level=0),
        WordParagraphContent(style="Normal", text="another.", level=0),
    ]
    with patch.object(attachment_resolver, "read_docx", return_value=_fake_word(paragraphs)):
        out = _digest_word("/w/y.docx", workspace="/w")
    lines = [line for line in out.splitlines() if line.strip()]  # noqa: E741
    assert lines == ["real.", "another."]


def test_digest_word_no_period_falls_back_to_full_text() -> None:
    """段落不含句号 → split('.', 1)[0] 是整段, 但仍加 '.' 后缀"""
    from backend.office.models import WordParagraphContent

    paragraphs = [
        WordParagraphContent(style="Normal", text="no period here", level=0),
    ]
    with patch.object(attachment_resolver, "read_docx", return_value=_fake_word(paragraphs)):
        out = _digest_word("/w/y.docx", workspace="/w")
    assert "no period here." in out


# ─── _digest_excel ──────────────────────────────────────────────


def _fake_excel(sheets):
    from backend.office.models import (
        OfficeDocumentMetadata,
        OfficeDocumentSummary,
        OfficeExcelReadResult,
    )

    summary = OfficeDocumentSummary(
        id="z",
        workspace_path="/w",
        doc_type="excel",
        original_filename=None,
        generated_filename="z.xlsx",
        status="parsed",
        created_at=0,
        updated_at=0,
        metadata=OfficeDocumentMetadata(file_size_bytes=0, page_count=0),
    )
    return OfficeExcelReadResult(summary=summary, sheets=sheets)


def test_digest_excel_sheet_names_plus_first_5_rows() -> None:
    from backend.office.models import ExcelSheetContent

    sheets = [
        ExcelSheetContent(name="A", rows=[["h1", "h2"], ["v1", "v2"]], max_row=2, max_col=2),
        ExcelSheetContent(name="B", rows=[["x"] for _ in range(10)], max_row=10, max_col=1),
    ]
    with patch.object(attachment_resolver, "read_xlsx", return_value=_fake_excel(sheets)):
        out = _digest_excel("/w/z.xlsx", workspace="/w")
    assert "sheets: A, B" in out
    assert "--- A (top 2 rows) ---" in out
    assert "h1\th2" in out
    assert "v1\tv2" in out
    assert "--- B (top 5 rows) ---" in out
    # B 有 10 行但只输出 5 行
    assert "x" in out
    assert out.count("x\n") + out.count("x\t") + (1 if out.endswith("x") else 0) == 5


def test_digest_excel_empty() -> None:
    with patch.object(attachment_resolver, "read_xlsx", return_value=_fake_excel([])):
        out = _digest_excel("/w/empty.xlsx", workspace="/w")
    # 无 sheet 行但仍输出 'sheets: '
    assert out.startswith("sheets: ")


def test_digest_excel_truncates_long_rows() -> None:
    from backend.office.models import ExcelSheetContent

    rows = [[f"cell{i}"] for i in range(100)]
    sheets = [
        ExcelSheetContent(name="Long", rows=rows, max_row=100, max_col=1),
    ]
    with patch.object(attachment_resolver, "read_xlsx", return_value=_fake_excel(sheets)):
        out = _digest_excel("/w/long.xlsx", workspace="/w")
    # 仅前 5 行, cell5 之后不再出现
    assert "cell4" in out
    assert "cell5" not in out
    assert "cell99" not in out
