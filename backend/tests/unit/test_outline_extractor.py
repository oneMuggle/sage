"""Tests for backend.design.outline_extractor (M5a)."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.design.outline_extractor import (
    _MAX_BULLETS_PER_SLIDE,
    _MAX_SLIDES,
    OutlineExtractor,
    OutlineResult,
)


def _paragraphs(*items):
    return list(items)


class TestFromParagraphs:
    def test_groups_body_under_heading(self):
        result = OutlineExtractor().from_paragraphs(
            _paragraphs(
                (1, "市场概览"),
                (0, "规模持续增长"),
                (0, "竞争格局分散"),
                (1, "产品策略"),
                (0, "聚焦中端客户"),
            ),
            source_name="pitch",
        )
        assert isinstance(result, OutlineResult)
        assert result.title == "市场概览"
        assert result.slide_count == 2
        assert "## 1. 市场概览" in result.outline_md
        assert "- 规模持续增长" in result.outline_md
        assert "## 2. 产品策略" in result.outline_md

    def test_body_before_first_heading_becomes_slide_named_after_source(self):
        result = OutlineExtractor().from_paragraphs(
            _paragraphs(
                (0, "前言正文"),
                (1, "第一章"),
                (0, "内容"),
            ),
            source_name="年度报告",
        )
        assert result.slide_count == 2
        assert result.title == "年度报告"
        assert "- 前言正文" in result.outline_md

    def test_consecutive_duplicate_bullets_are_dropped(self):
        result = OutlineExtractor().from_paragraphs(
            _paragraphs(
                (1, "标题"),
                (0, "重复"),
                (0, "重复"),
                (0, "不同"),
            ),
        )
        assert result.outline_md.count("- 重复") == 1
        assert "- 不同" in result.outline_md

    def test_blank_paragraphs_are_ignored(self):
        result = OutlineExtractor().from_paragraphs(
            _paragraphs((1, "标题"), (0, "   "), (0, "")),
        )
        assert result.slide_count == 1
        assert "- （无正文内容" in result.outline_md

    def test_long_bullets_are_truncated(self):
        result = OutlineExtractor().from_paragraphs(
            _paragraphs((1, "标题"), (0, "字" * 400)),
        )
        bullet = next(
            line for line in result.outline_md.splitlines()
            if line.startswith("- 字")
        )
        assert bullet.endswith("…")
        assert len(bullet) <= 142  # "- " + 140

    def test_bullets_capped_per_slide(self):
        items = [(1, "标题")] + [(0, f"条目 {i}") for i in range(20)]
        result = OutlineExtractor().from_paragraphs(_paragraphs(*items))
        bullets = [
            line for line in result.outline_md.splitlines()
            if line.startswith("- ")
        ]
        assert len(bullets) == _MAX_BULLETS_PER_SLIDE

    def test_headings_capped(self):
        items = [(1, f"标题 {i}") for i in range(_MAX_SLIDES + 10)]
        result = OutlineExtractor().from_paragraphs(_paragraphs(*items))
        assert result.slide_count == _MAX_SLIDES

    def test_tables_rendered_as_bullets(self):
        result = OutlineExtractor().from_paragraphs(
            _paragraphs((1, "数据")),
            tables=[(3, 4)],
        )
        assert "- 表格：3 行 × 4 列" in result.outline_md

    def test_empty_document_yields_placeholder_slide(self):
        result = OutlineExtractor().from_paragraphs(
            _paragraphs(), source_name="空文档",
        )
        assert result.slide_count == 1
        assert result.title == "空文档"


class TestExtractFromDocx:
    def test_extract_reads_headings_and_body(self, tmp_path: Path):
        from docx import Document

        doc = Document()
        doc.add_heading("季度回顾", level=1)
        doc.add_paragraph("收入增长 12%")
        doc.add_heading("下一步", level=1)
        doc.add_paragraph("扩大渠道")
        path = tmp_path / "deck.docx"
        doc.save(str(path))

        result = OutlineExtractor().extract(path)

        assert result.title == "季度回顾"
        assert result.slide_count == 2
        assert result.source_path == str(path)
        assert "- 收入增长 12%" in result.outline_md
        assert "- 扩大渠道" in result.outline_md

    def test_missing_file_raises(self, tmp_path: Path):
        from backend.office.errors import OfficeFileNotFoundError

        with pytest.raises(OfficeFileNotFoundError):
            OutlineExtractor().extract(tmp_path / "nope.docx")
