"""Markdown → WordParagraphSpec 测试。"""
from __future__ import annotations

from backend.office.markdown_to_paragraphs import parse_markdown_to_paragraphs


def test_parses_h1() -> None:
    out = parse_markdown_to_paragraphs("# Title")
    assert out == [{"text": "Title", "heading": "h1", "style": None}]


def test_parses_h2_h3() -> None:
    md = "## Sub\n### Sub-sub"
    out = parse_markdown_to_paragraphs(md)
    assert out == [
        {"text": "Sub", "heading": "h2", "style": None},
        {"text": "Sub-sub", "heading": "h3", "style": None},
    ]


def test_parses_bullet_with_dash() -> None:
    md = "- item one\n- item two"
    out = parse_markdown_to_paragraphs(md)
    assert out == [
        {"text": "item one", "heading": None, "style": "bullet"},
        {"text": "item two", "heading": None, "style": "bullet"},
    ]


def test_parses_bullet_with_asterisk() -> None:
    md = "* star one\n* star two"
    out = parse_markdown_to_paragraphs(md)
    assert out[0]["style"] == "bullet"
    assert out[0]["text"] == "star one"


def test_parses_numbered_list() -> None:
    md = "1. 第一步\n2. 第二步"
    out = parse_markdown_to_paragraphs(md)
    assert out == [
        {"text": "第一步", "heading": None, "style": "numbered"},
        {"text": "第二步", "heading": None, "style": "numbered"},
    ]


def test_parses_plain_paragraph() -> None:
    out = parse_markdown_to_paragraphs("just a sentence.")
    assert out == [{"text": "just a sentence.", "heading": None, "style": None}]


def test_preserves_emoji() -> None:
    md = "🎯 功能特点\n✅ 多模型槽位"
    out = parse_markdown_to_paragraphs(md)
    assert out[0]["text"] == "🎯 功能特点"
    assert out[1]["text"] == "✅ 多模型槽位"


def test_mixed_markdown() -> None:
    md = "# 标题\n\n段落正文\n\n## 二级标题\n\n- bullet 1\n- bullet 2"
    out = parse_markdown_to_paragraphs(md)
    assert out[0] == {"text": "标题", "heading": "h1", "style": None}
    assert out[1] == {"text": "段落正文", "heading": None, "style": None}
    assert out[2] == {"text": "二级标题", "heading": "h2", "style": None}
    assert out[3]["style"] == "bullet"
    assert out[3]["text"] == "bullet 1"
    assert out[4]["style"] == "bullet"
    assert out[4]["text"] == "bullet 2"


def test_empty_lines_split_paragraphs() -> None:
    md = "first paragraph\n\nsecond paragraph"
    out = parse_markdown_to_paragraphs(md)
    assert len(out) == 2
    assert out[0]["text"] == "first paragraph"
    assert out[1]["text"] == "second paragraph"