"""Round 58: sources_extractor 单元测试

覆盖 backend/chat/sources_extractor.py：
- web_search / web_fetch / wiki_search / wiki_answer / MCP 各自的提取形状
- 畸形 JSON / 缺字段 / 未知工具 → 空列表（fail-safe，绝不抛错）
- snippet/preview 截断
- merge_sources 去重（url / path）与总量上限
"""

from __future__ import annotations

import json

import pytest

from backend.chat.sources_extractor import (
    MAX_PREVIEW_CHARS,
    MAX_SOURCES_PER_TOOL,
    SOURCES_CAP,
    extract_sources_from_tool,
    merge_sources,
)

pytestmark = pytest.mark.unit


def _dumps(payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


# ── web_search ────────────────────────────────────────────────────────


def test_web_search_extracts_results():
    content = _dumps(
        {
            "query": "sage electron",
            "engine": "bing",
            "results": [
                {"title": "Sage 官网", "url": "https://sage.example.com/", "snippet": "一个 AI 助手"},
                {"title": "文档", "url": "https://docs.example.com/guide", "snippet": "使用指南"},
            ],
        }
    )
    sources = extract_sources_from_tool("web_search", content)
    assert len(sources) == 2
    first = sources[0]
    assert first["kind"] == "web"
    assert first["title"] == "Sage 官网"
    assert first["url"] == "https://sage.example.com/"
    assert first["snippet"] == "一个 AI 助手"
    assert first["query"] == "sage electron"


def test_web_search_skips_entries_without_url():
    content = _dumps({"results": [{"title": "无 url"}, {"url": "https://a.com", "title": "A"}]})
    sources = extract_sources_from_tool("web_search", content)
    assert len(sources) == 1
    assert sources[0]["url"] == "https://a.com"


def test_web_search_missing_title_falls_back_to_host():
    content = _dumps({"results": [{"url": "https://docs.example.com/x", "snippet": "s"}]})
    (source,) = extract_sources_from_tool("web_search", content)
    assert source["title"] == "docs.example.com"


def test_web_search_caps_per_tool():
    results = [{"title": f"t{i}", "url": f"https://e.com/{i}"} for i in range(MAX_SOURCES_PER_TOOL + 5)]
    sources = extract_sources_from_tool("web_search", _dumps({"results": results}))
    assert len(sources) == MAX_SOURCES_PER_TOOL


# ── web_fetch ─────────────────────────────────────────────────────────


def test_web_fetch_extracts_single_source():
    content = _dumps({"url": "https://example.com/a", "title": "页面标题", "content": "正文" * 200})
    (source,) = extract_sources_from_tool("web_fetch", content)
    assert source["kind"] == "web"
    assert source["title"] == "页面标题"
    assert source["url"] == "https://example.com/a"
    assert len(source["snippet"]) <= MAX_PREVIEW_CHARS or len(source["snippet"]) <= 161
    assert source["snippet"].endswith("…") or len(source["snippet"]) < 160


def test_web_fetch_without_url_returns_empty():
    assert extract_sources_from_tool("web_fetch", _dumps({"content": "x"})) == []


# ── wiki_search / wiki_answer ─────────────────────────────────────────


def test_wiki_search_extracts_results_with_score():
    content = _dumps(
        {
            "results": [
                {"title": "架构笔记", "path": "wiki/arch.md", "snippet": "分层设计", "score": 0.8731},
            ],
            "total": 1,
        }
    )
    (source,) = extract_sources_from_tool("wiki_search", content)
    assert source == {
        "kind": "wiki",
        "title": "架构笔记",
        "path": "wiki/arch.md",
        "snippet": "分层设计",
        "score": 0.87,
    }


def test_wiki_answer_uses_citations():
    content = _dumps(
        {
            "messages": [],
            "citations": [
                {"id": "S1", "path": "wiki/rust.md", "title": "Rust", "excerpt": "所有权系统"},
            ],
        }
    )
    (source,) = extract_sources_from_tool("wiki_answer", content)
    assert source["kind"] == "wiki"
    assert source["path"] == "wiki/rust.md"
    assert source["snippet"] == "所有权系统"


# ── browser_navigate ──────────────────────────────────────────────────


def test_browser_navigate_extracts_source():
    content = _dumps({"url": "https://example.com/page", "title": "示例页"})
    (source,) = extract_sources_from_tool("browser_navigate", content)
    assert source["kind"] == "web"
    assert source["url"] == "https://example.com/page"
    assert source["title"] == "示例页"


def test_browser_navigate_missing_title_falls_back_to_host():
    content = _dumps({"url": "https://docs.example.com/deep/path"})
    (source,) = extract_sources_from_tool("browser_navigate", content)
    assert source["title"] == "docs.example.com"


def test_browser_navigate_without_url_returns_empty():
    assert extract_sources_from_tool("browser_navigate", _dumps({"title": "无 url"})) == []


# ── MCP ───────────────────────────────────────────────────────────────


def test_mcp_tool_extracts_preview_from_text_payload():
    sources = extract_sources_from_tool("mcp__github__search_issues", _dumps("找到 3 个 issue"))
    (source,) = sources
    assert source == {
        "kind": "tool",
        "server": "github",
        "tool": "search_issues",
        "preview": "找到 3 个 issue",
    }


def test_mcp_tool_extracts_from_text_key_payload():
    content = _dumps({"text": "结果内容", "metadata": {"x": 1}})
    (source,) = extract_sources_from_tool("mcp__docs__list", content)
    assert source["kind"] == "tool"
    assert source["preview"] == "结果内容"


def test_mcp_tool_name_with_double_underscore_tool_part():
    sources = extract_sources_from_tool("mcp__srv__ns__deep", _dumps("ok"))
    assert sources[0]["tool"] == "ns__deep"


def test_mcp_tool_empty_preview_returns_empty():
    assert extract_sources_from_tool("mcp__srv__noop", _dumps("")) == []


# ── fail-safe ─────────────────────────────────────────────────────────


def test_malformed_json_returns_empty():
    assert extract_sources_from_tool("web_search", "{not json") == []


def test_non_dict_payload_returns_empty():
    assert extract_sources_from_tool("web_search", _dumps([1, 2, 3])) == []


def test_unknown_tool_returns_empty():
    assert extract_sources_from_tool("bash", _dumps({"output": "ls"})) == []


def test_empty_name_returns_empty():
    assert extract_sources_from_tool("", _dumps({"results": []})) == []


# ── merge_sources ─────────────────────────────────────────────────────


def test_merge_dedups_by_url_and_path():
    acc = [{"kind": "web", "title": "A", "url": "https://a.com"}]
    incoming = [
        {"kind": "web", "title": "A 变体", "url": "https://a.com"},
        {"kind": "web", "title": "B", "url": "https://b.com"},
    ]
    merged = merge_sources(acc, incoming)
    assert [s["url"] for s in merged] == ["https://a.com", "https://b.com"]


def test_merge_wiki_dedups_by_path():
    acc = [{"kind": "wiki", "path": "wiki/x.md"}]
    merged = merge_sources(acc, [{"kind": "wiki", "path": "wiki/x.md", "snippet": "new"}])
    assert len(merged) == 1


def test_merge_caps_total():
    acc = [{"kind": "web", "url": f"https://{i}.com"} for i in range(SOURCES_CAP)]
    merged = merge_sources(acc, [{"kind": "web", "url": "https://new.com"}])
    assert len(merged) == SOURCES_CAP


def test_merge_empty_incoming_returns_copy():
    acc = [{"kind": "web", "url": "https://a.com"}]
    merged = merge_sources(acc, [])
    assert merged == acc
    assert merged is not acc
