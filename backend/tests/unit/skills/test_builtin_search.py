"""R132 — 内置搜索技能单元测试。

覆盖：schema 契约、context 工具缺失失败、成功路径格式化（序号/缩进/
链接行）与 metadata、空结果、错误透传、limit 透传与缺省。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.skills.builtin.search import SearchSkill

pytestmark = pytest.mark.unit


def _skill_result(success=True, content=None, error=None):
    return SimpleNamespace(success=success, content=content, error=error)


def _fake_tool(result):
    def execute(**kwargs):
        result.kwargs = kwargs
        return result

    return SimpleNamespace(execute=execute)


def _search_results():
    return {
        "results": [
            {"title": "标题一", "snippet": "摘要一", "url": "https://a.example"},
            {"title": "标题二", "snippet": "摘要二", "url": ""},
        ]
    }


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------


def test_schema_contract():
    schema = SearchSkill().schema
    assert schema.name == "search"
    assert "搜索" in schema.triggers
    assert "search" in schema.triggers
    assert schema.parameters["required"] == ["query"]


# ---------------------------------------------------------------------------
# execute 分派
# ---------------------------------------------------------------------------


def test_missing_web_search_tool_fails():
    out = SearchSkill().execute({"query": "q"}, {"tools": {}})
    assert out.success is False
    assert "搜索工具不可用" in out.error


def test_success_formats_results_with_metadata():
    result = _skill_result(success=True, content=_search_results())
    tool = _fake_tool(result)
    out = SearchSkill().execute({"query": "火锅"}, {"tools": {"web_search": tool}})
    assert out.success is True
    assert out.metadata == {"query": "火锅", "count": 2}
    assert "1. **标题一**" in out.content
    assert "   摘要一" in out.content
    assert "   🔗 https://a.example" in out.content


def test_tool_receives_query_and_limit():
    result = _skill_result(success=True, content={"results": []})
    tool = _fake_tool(result)
    SearchSkill().execute({"query": "q", "limit": 9}, {"tools": {"web_search": tool}})
    assert result.kwargs == {"query": "q", "limit": 9}


def test_tool_limit_defaults_to_five():
    result = _skill_result(success=True, content={"results": []})
    tool = _fake_tool(result)
    SearchSkill().execute({"query": "q"}, {"tools": {"web_search": tool}})
    assert result.kwargs["limit"] == 5


def test_empty_results_message():
    result = _skill_result(success=True, content={"results": []})
    tool = _fake_tool(result)
    out = SearchSkill().execute({"query": "q"}, {"tools": {"web_search": tool}})
    assert out.success is True
    assert out.content == "没有找到相关结果。"


def test_tool_error_propagates():
    result = _skill_result(success=False, error="rate limited")
    tool = _fake_tool(result)
    out = SearchSkill().execute({"query": "q"}, {"tools": {"web_search": tool}})
    assert out.success is False
    assert out.error == "rate limited"


def test_format_results_defaults_missing_fields():
    skill = SearchSkill()
    formatted = skill._format_results([{}])
    assert "无标题" in formatted
    assert "🔗" not in formatted  # 无 url 不输出链接行
