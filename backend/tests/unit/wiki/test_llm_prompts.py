"""R161 — wiki LLM Prompt 模板单元测试。

覆盖：四个 format 函数的参数注入、双花括号 JSON 样例 format 后保留
字面花括号、RAG 防注入规则文案在模板中、注入值含花括号时的安全透传。
"""

from __future__ import annotations

import pytest

from backend.wiki.llm_prompts import (
    RAG_SYSTEM,
    STEP1_ANALYZE,
    STEP2_WRITE,
    format_rag_system,
    format_rag_user_message,
    format_step1_prompt,
    format_step2_prompt,
)

pytestmark = pytest.mark.unit


def test_format_step1_injects_source_and_keeps_json_sample():
    out = format_step1_prompt("源文档正文")
    assert "源文档正文" in out
    assert '"entities"' in out  # 双花括号被还原为字面花括号
    assert "tags" in out
    assert "{" in out
    assert "}" in out


def test_format_step1_source_with_braces_safe():
    out = format_step1_prompt("代码片段 {key: value} 出现")
    assert "{key: value} 出现" in out  # 注入值原样透传


def test_format_step2_injects_all_params():
    out = format_step2_prompt(
        filename="src/my-note.md",
        content="正文内容",
        analysis="分析结果",
        tags_csv="tag1, tag2",
        related_links="[[Topic1]] [[Topic2]]",
        today="2026-09-26",
    )
    assert "src/my-note.md" in out
    assert "正文内容" in out
    assert "分析结果" in out
    assert "tag1, tag2" in out
    assert "[[Topic1]] [[Topic2]]" in out
    assert "2026-09-26" in out
    assert "---" in out  # frontmatter 样例保留
    assert "[[X]]" in out  # related 格式示例保留


def test_format_rag_system_contains_context_and_rules():
    context = "【S1】片段一\n【S2】片段二"
    out = format_rag_system(context)
    assert context in out
    assert "知识库助手" in out
    assert "[S1]" in out  # 引用格式规则
    assert "不得编造" in out  # 防注入规则保留


def test_format_rag_user_contains_query():
    out = format_rag_user_message("什么是记忆系统？")
    assert "什么是记忆系统？" in out


def test_templates_constants_present():
    from backend.wiki.llm_prompts import RAG_USER_TEMPLATE

    assert "分析以下源文档" in STEP1_ANALYZE
    assert "写入完整的 Wiki 页面" in STEP2_WRITE
    assert "知识库助手" in RAG_SYSTEM
    assert "{query}" in RAG_USER_TEMPLATE


@pytest.mark.parametrize(
    ("fn", "kwargs", "needle"),
    [
        (format_step1_prompt, {"source_content": "x{}y"}, "x{}y"),
        (format_rag_user_message, {"query": "q{}q"}, "q{}q"),
    ],
)
def test_format_values_with_braces_are_verbatim(fn, kwargs, needle):
    out = fn(**kwargs)
    assert needle in out  # 注入值含花括号时原样透传
