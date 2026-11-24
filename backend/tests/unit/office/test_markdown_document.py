# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""parse_markdown_document 测试：内联标记 / 引用 / 表格 / 图片。"""
from __future__ import annotations

from backend.office.markdown_to_paragraphs import (
    parse_markdown_document,
    parse_markdown_to_paragraphs,
)


class TestPlainParagraphs:
    def test_basic_document_shape(self) -> None:
        out = parse_markdown_document("# Title\n\n正文")
        assert out["tables"] == []
        assert out["images"] == []
        assert out["paragraphs"] == [
            {"text": "Title", "heading": "h1", "style": None},
            {"text": "正文", "heading": None, "style": None},
        ]

    def test_no_runs_key_without_markup(self) -> None:
        out = parse_markdown_document("plain sentence")
        assert "runs" not in out["paragraphs"][0]

    def test_empty_input(self) -> None:
        out = parse_markdown_document("")
        assert out == {
            "paragraphs": [{"text": "", "heading": None, "style": None}],
            "tables": [],
            "images": [],
        }

    def test_legacy_wrapper_matches_paragraphs(self) -> None:
        md = "# 标题\n\n段落\n\n- 项目"
        legacy = parse_markdown_to_paragraphs(md)
        assert legacy == parse_markdown_document(md)["paragraphs"]


class TestInlineMarkup:
    def test_bold_becomes_run(self) -> None:
        out = parse_markdown_document("这是 **加粗** 文字")
        para = out["paragraphs"][0]
        assert para["text"] == "这是 加粗 文字"
        assert para["runs"] == [
            {"text": "这是 "},
            {"text": "加粗", "bold": True},
            {"text": " 文字"},
        ]

    def test_italic_becomes_run(self) -> None:
        out = parse_markdown_document("*强调*内容")
        assert out["paragraphs"][0]["runs"] == [
            {"text": "强调", "italic": True},
            {"text": "内容"},
        ]

    def test_bold_italic_becomes_run(self) -> None:
        out = parse_markdown_document("***重点***")
        assert out["paragraphs"][0]["runs"] == [
            {"text": "重点", "bold": True, "italic": True},
        ]

    def test_link_becomes_run(self) -> None:
        out = parse_markdown_document("见 [文档](https://example.com/doc)")
        assert out["paragraphs"][0]["runs"] == [
            {"text": "见 "},
            {"text": "文档", "link": "https://example.com/doc"},
        ]

    def test_bold_inside_bullet(self) -> None:
        out = parse_markdown_document("- **重点**内容")
        para = out["paragraphs"][0]
        assert para["style"] == "bullet"
        assert para["text"] == "重点内容"
        assert para["runs"] == [
            {"text": "重点", "bold": True},
            {"text": "内容"},
        ]

    def test_heading_markup_is_flattened(self) -> None:
        out = parse_markdown_document("# **标题**")
        para = out["paragraphs"][0]
        assert para == {"text": "标题", "heading": "h1", "style": None}

    def test_mixed_runs_in_one_paragraph(self) -> None:
        out = parse_markdown_document("**粗**、*斜*、[链](http://a.b)")
        runs = out["paragraphs"][0]["runs"]
        assert {"text": "粗", "bold": True} in runs
        assert {"text": "斜", "italic": True} in runs
        assert {"text": "链", "link": "http://a.b"} in runs


class TestQuote:
    def test_quote_block(self) -> None:
        out = parse_markdown_document("> 引用第一行\n> 引用第二行")
        assert out["paragraphs"] == [
            {"text": "引用第一行", "heading": None, "style": "quote"},
            {"text": "引用第二行", "heading": None, "style": "quote"},
        ]

    def test_quote_with_inline_markup(self) -> None:
        out = parse_markdown_document("> **注意**事项")
        para = out["paragraphs"][0]
        assert para["style"] == "quote"
        assert para["runs"] == [
            {"text": "注意", "bold": True},
            {"text": "事项"},
        ]


class TestTable:
    def test_pipe_table(self) -> None:
        md = "| 列A | 列B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
        out = parse_markdown_document(md)
        assert out["paragraphs"] == []
        assert out["tables"] == [
            {"headers": ["列A", "列B"], "rows": [["1", "2"], ["3", "4"]]},
        ]

    def test_table_alongside_paragraphs(self) -> None:
        md = "前文\n\n| H1 | H2 |\n| --- | --- |\n| a | b |\n\n后文"
        out = parse_markdown_document(md)
        assert [p["text"] for p in out["paragraphs"]] == ["前文", "后文"]
        assert out["tables"][0]["headers"] == ["H1", "H2"]

    def test_table_cells_flatten_inline_markup(self) -> None:
        md = "| 名称 |\n| --- |\n| **粗**文字 |"
        out = parse_markdown_document(md)
        assert out["tables"][0]["rows"] == [["粗文字"]]


class TestImage:
    def test_standalone_image(self) -> None:
        out = parse_markdown_document("![图注](images/a.png)")
        assert out["paragraphs"] == []
        assert out["images"] == [
            {"source": "images/a.png", "caption": "图注", "after_paragraph": -1},
        ]

    def test_image_after_paragraph(self) -> None:
        md = "前文\n\n![架构图](img/arch.png)"
        out = parse_markdown_document(md)
        assert out["images"] == [
            {"source": "img/arch.png", "caption": "架构图", "after_paragraph": 0},
        ]

    def test_image_without_alt(self) -> None:
        out = parse_markdown_document("![](images/b.png)")
        assert out["images"][0]["source"] == "images/b.png"
        assert out["images"][0]["caption"] is None
