"""AcademicSearchSkill 单元测试。

覆盖:
1. schema 必填字段(name / description / triggers / parameters.query)
2. happy path —— 传入 query + web_fetch + ask_user_question mock,返回结构化 prompt
3. 缺 web_fetch 工具 → 返回 SkillResult(success=False, error=...)
4. query 缺省/空字符串 → 返回 SkillResult(success=False, error=...)
5. 未知 site → 返回 SkillResult(success=False, error=含可用站点列表)
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import Mock

import pytest

from backend.skills.builtin.academic_adapters import register_site_adapter
from backend.skills.builtin.academic_search import AcademicSearchSkill

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _mock_tool(name: str, *, success: bool = True, content: Any = None, error: Optional[str] = None) -> Mock:
    """构造一个返回 ToolResult 形状的 tool mock。"""
    tool = Mock()
    tool.name = name
    result = Mock()
    result.success = success
    result.content = content
    result.error = error
    tool.execute = Mock(return_value=result)
    return tool


# ============================================================================
# 1. schema
# ============================================================================


def test_schema_declares_required_fields():
    skill = AcademicSearchSkill()
    schema = skill.schema
    assert schema.name == "academic-search"
    assert "文献" in schema.description or "检索" in schema.description
    assert "找文献" in schema.triggers
    assert schema.parameters["required"] == ["query"]
    assert schema.parameters["properties"]["query"]["type"] == "string"
    assert schema.parameters["properties"]["site"]["default"] == "cnki"


# ============================================================================
# 2. happy path —— web_fetch + ask_user_question 都可用
# ============================================================================


class TestHappyPath:
    def test_execute_returns_structured_prompt_for_llm(self):
        skill = AcademicSearchSkill()
        web_fetch = _mock_tool(
            "web_fetch",
            success=True,
            content="<html><body>假装这是 CNKI 检索结果页</body></html>",
        )
        ask_user = _mock_tool(
            "ask_user_question",
            success=True,
            content={"answer": "按相关度"},
        )

        result = skill.execute(
            params={"query": "大语言模型综述", "limit": 5},
            context={"tools": {"web_fetch": web_fetch, "ask_user_question": ask_user}},
        )

        assert result.success is True, f"unexpected error: {result.error}"
        # web_fetch 真的被调用,且参数正确(query 在 URL 里,经 urlencode 编码)
        web_fetch.execute.assert_called_once()
        call_kwargs = web_fetch.execute.call_args.kwargs
        assert "cnki.net" in call_kwargs["url"]
        # URL 是 percent-encoded;解码后包含 query 原文
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(call_kwargs["url"]).query)
        assert qs["Txt"] == ["大语言模型综述"]
        assert qs["t"] == ["5"]

        # ask_user 也被调用
        ask_user.execute.assert_called_once()

        # 返回内容是给 LLM 的结构化 prompt
        assert isinstance(result.content, str)
        assert "大语言模型综述" in result.content
        assert "cnki" in result.content
        assert "按相关度" in result.content  # 用户选择的排序
        assert "5" in result.content  # limit
        # metadata 携带元数据供 LLM 决策
        assert result.metadata["query"] == "大语言模型综述"
        assert result.metadata["site"] == "cnki"
        assert result.metadata["limit"] == 5
        assert result.metadata["sort_pref"] == "按相关度"
        assert result.metadata["asked_user"] is True

    def test_execute_works_without_ask_user_question(self):
        """ask_user_question 缺失时,skill 仍能用,默认 sort_pref=relevance。"""
        skill = AcademicSearchSkill()
        web_fetch = _mock_tool(
            "web_fetch",
            success=True,
            content="result page content",
        )

        result = skill.execute(
            params={"query": "transformer"},
            context={"tools": {"web_fetch": web_fetch}},
        )

        assert result.success is True
        assert result.metadata["sort_pref"] == "relevance"
        assert result.metadata["asked_user"] is False


# ============================================================================
# 3. 失败模式
# ============================================================================


class TestFailureModes:
    def test_missing_web_fetch_tool_returns_error(self):
        skill = AcademicSearchSkill()
        result = skill.execute(
            params={"query": "deep learning"},
            context={"tools": {}},
        )
        assert result.success is False
        assert "web_fetch" in result.error

    def test_empty_query_returns_error(self):
        skill = AcademicSearchSkill()
        web_fetch = _mock_tool("web_fetch", success=True, content="ignored")
        result = skill.execute(
            params={"query": ""},
            context={"tools": {"web_fetch": web_fetch}},
        )
        assert result.success is False
        assert "query" in result.error
        web_fetch.execute.assert_not_called()  # 校验失败不应调工具

    def test_unknown_site_returns_error_with_available_list(self):
        skill = AcademicSearchSkill()
        web_fetch = _mock_tool("web_fetch", success=True, content="ignored")
        result = skill.execute(
            params={"query": "x", "site": "pubmed"},
            context={"tools": {"web_fetch": web_fetch}},
        )
        assert result.success is False
        assert "pubmed" in result.error
        assert "cnki" in result.error  # 列出可用项
        web_fetch.execute.assert_not_called()

    def test_web_fetch_failure_propagates_error(self):
        """web_fetch 工具返回 success=False 时,skill 不应继续往下走。"""
        skill = AcademicSearchSkill()
        web_fetch = _mock_tool(
            "web_fetch", success=False, error="network timeout"
        )
        result = skill.execute(
            params={"query": "x"},
            context={"tools": {"web_fetch": web_fetch}},
        )
        assert result.success is False
        assert "network timeout" in result.error or "抓取" in result.error


# ============================================================================
# 4. 自定义 site 扩展点
# ============================================================================


def test_custom_site_adapter_can_be_used_via_register():
    """register_site_adapter 注入新站点后,AcademicSearchSkill 能用。"""

    class _StubAdapter:
        name = "stub-site"

        def build_search_url(self, query: str, **kwargs: Any) -> str:
            return f"https://stub.example/search?q={query}"

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            return None

    try:
        register_site_adapter(_StubAdapter())  # type: ignore[arg-type]
        skill = AcademicSearchSkill()
        web_fetch = _mock_tool(
            "web_fetch", success=True, content="page"
        )
        result = skill.execute(
            params={"query": "x", "site": "stub-site"},
            context={"tools": {"web_fetch": web_fetch}},
        )
        assert result.success is True
        assert result.metadata["site"] == "stub-site"
        assert "stub.example" in result.metadata["search_url"]
    finally:
        from backend.skills.builtin import academic_adapters

        academic_adapters._DEFAULT_ADAPTERS.pop("stub-site", None)
