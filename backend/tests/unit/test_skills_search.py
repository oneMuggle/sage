"""
SearchSkill 单元测试

覆盖：
- schema 元数据
- execute 正常路径：调用 web_search.execute 拿结果 → 格式化
- execute 无 web_search 工具 → 失败
- execute web_search 失败 → 失败包装
- execute 搜索结果为空 → "没有找到相关结果。"
- _format_results 内部方法：多条结果 / 单条 / 空 / 缺 url
- match() 触发词匹配
"""

from unittest.mock import Mock

import pytest

from backend.skills.builtin.search import SearchSkill
from backend.tools.base import ToolResult

pytestmark = pytest.mark.unit


# ============================================================================
# Schema
# ============================================================================


def test_schema_metadata():
    skill = SearchSkill()
    assert skill.name == "search"
    assert "搜索" in skill.triggers or "search" in skill.triggers
    params = skill.schema.parameters
    assert params["required"] == ["query"]
    assert "query" in params["properties"]
    assert "limit" in params["properties"]


def test_schema_examples_non_empty():
    skill = SearchSkill()
    assert len(skill.schema.examples) >= 1


# ============================================================================
# execute 路径
# ============================================================================


def test_execute_without_web_search_tool_returns_failure():
    """context 中没提供 tools['web_search'] → success=False, error='搜索工具不可用'."""
    skill = SearchSkill()
    result = skill.execute({"query": "python"}, {"tools": {}})
    assert result.success is False
    assert "搜索工具不可用" in (result.error or "")


def test_execute_without_tools_key_returns_failure():
    skill = SearchSkill()
    result = skill.execute({"query": "python"}, {})
    assert result.success is False
    assert "搜索工具不可用" in (result.error or "")


def test_execute_with_empty_query_passes_through_to_tool():
    """query 为空时仍调用工具（不做业务校验, 这是 skill 的契约）."""
    web_search = Mock()
    web_search.execute.return_value = ToolResult(
        success=True, content={"results": []}
    )
    skill = SearchSkill()
    result = skill.execute({"query": ""}, {"tools": {"web_search": web_search}})
    assert result.success is True
    assert "没有找到相关结果" in (result.content or "")
    web_search.execute.assert_called_once_with(query="", limit=5)


def test_execute_with_results_formats_them():
    """正常路径: web_search 返回 results, skill 格式化并附加 metadata."""
    web_search = Mock()
    web_search.execute.return_value = ToolResult(
        success=True,
        content={
            "results": [
                {
                    "title": "Python 异步编程",
                    "snippet": "asyncio 教程",
                    "url": "https://example.com/async",
                },
                {
                    "title": "FastAPI 文档",
                    "snippet": "现代 web 框架",
                    "url": "https://fastapi.tiangolo.com",
                },
            ]
        },
    )
    skill = SearchSkill()
    result = skill.execute({"query": "python 异步", "limit": 2}, {"tools": {"web_search": web_search}})
    assert result.success is True
    assert "Python 异步编程" in result.content
    assert "FastAPI" in result.content
    assert "https://example.com/async" in result.content
    assert result.metadata["query"] == "python 异步"
    assert result.metadata["count"] == 2


def test_execute_with_empty_results_returns_no_match_message():
    web_search = Mock()
    web_search.execute.return_value = ToolResult(success=True, content={"results": []})
    skill = SearchSkill()
    result = skill.execute({"query": "nothing"}, {"tools": {"web_search": web_search}})
    assert result.success is True
    assert result.content == "没有找到相关结果。"
    assert result.metadata["count"] == 0


def test_execute_when_tool_returns_failure_wraps_error():
    """web_search.execute 返回 success=False → skill 返回 failure + 错误信息."""
    web_search = Mock()
    web_search.execute.return_value = ToolResult(
        success=False, content=None, error="network timeout"
    )
    skill = SearchSkill()
    result = skill.execute({"query": "x"}, {"tools": {"web_search": web_search}})
    assert result.success is False
    assert "network timeout" in (result.error or "")


def test_execute_when_tool_returns_failure_no_error_uses_fallback():
    """tool 失败且无 error 字段 → skill 用 '搜索失败' fallback."""
    web_search = Mock()
    web_search.execute.return_value = ToolResult(success=False, content=None)
    skill = SearchSkill()
    result = skill.execute({"query": "x"}, {"tools": {"web_search": web_search}})
    assert result.success is False
    assert result.error == "搜索失败"


def test_execute_passes_limit_to_tool():
    """limit 参数透传给 web_search.execute."""
    web_search = Mock()
    web_search.execute.return_value = ToolResult(success=True, content={"results": []})
    skill = SearchSkill()
    skill.execute({"query": "x", "limit": 20}, {"tools": {"web_search": web_search}})
    _, kwargs = web_search.execute.call_args
    assert kwargs["limit"] == 20


def test_execute_default_limit_is_5():
    web_search = Mock()
    web_search.execute.return_value = ToolResult(success=True, content={"results": []})
    skill = SearchSkill()
    skill.execute({"query": "x"}, {"tools": {"web_search": web_search}})
    _, kwargs = web_search.execute.call_args
    assert kwargs["limit"] == 5


# ============================================================================
# _format_results 内部
# ============================================================================


def test_format_results_with_missing_fields_uses_defaults():
    """结果缺 url 或 snippet 也能格式化（不抛错）."""
    skill = SearchSkill()
    out = skill._format_results(
        [
            {"title": "Only title"},
            {"title": "With snippet", "snippet": "abc"},
        ]
    )
    assert "Only title" in out
    assert "无标题" not in out  # title 存在, 不出现"无标题"
    assert "abc" in out


def test_format_results_empty_list_returns_no_match():
    skill = SearchSkill()
    assert skill._format_results([]) == "没有找到相关结果。"


def test_format_results_missing_title_uses_fallback():
    skill = SearchSkill()
    out = skill._format_results([{"snippet": "无标题的条目", "url": "https://x"}])
    assert "无标题" in out
    assert "无标题的条目" in out


# ============================================================================
# match
# ============================================================================


def test_match_returns_true_for_chinese_and_english_triggers():
    skill = SearchSkill()
    assert skill.match("帮我搜索一下 Python 教程") is True
    assert skill.match("please search for me") is True
    assert skill.match("查一下 ChatGPT") is True
    assert skill.match("不相关的内容") is False
