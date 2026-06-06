"""
WriterSkill 单元测试

覆盖：
- schema 元数据（type/topic/length/style）
- execute 各 type 分支：article / email / report / social
- execute 未知 type → 默认走 article 模板
- 无 LLM → mock 内容
- 有 LLM → 调用 llm.complete
- LLM 抛异常 → SkillResult(success=False)
- 默认值: length=medium, style=professional
- _build_prompt 内部映射
- match() 触发词
"""

from unittest.mock import Mock

import pytest

from backend.skills.builtin.writer import WriterSkill

pytestmark = pytest.mark.unit


# ============================================================================
# Schema
# ============================================================================


def test_schema_metadata():
    skill = WriterSkill()
    assert skill.name == "writer"
    assert "写" in skill.triggers or "write" in skill.triggers
    params = skill.schema.parameters
    assert "type" in params["properties"]
    assert "topic" in params["properties"]
    assert params["required"] == ["type", "topic"]


def test_schema_examples_non_empty():
    skill = WriterSkill()
    assert len(skill.schema.examples) >= 1


# ============================================================================
# execute 路径
# ============================================================================


def test_execute_article_without_llm_uses_mock_template():
    skill = WriterSkill()
    result = skill.execute(
        {"type": "article", "topic": "AI 发展", "style": "casual", "length": "long"},
        {},
    )
    assert result.success is True
    assert "AI 发展" in result.content
    assert result.metadata["type"] == "article"
    assert result.metadata["topic"] == "AI 发展"
    assert result.metadata["style"] == "casual"
    assert result.metadata["length"] == "long"
    assert result.metadata["mock"] is True


def test_execute_email_without_llm_uses_mock_template():
    skill = WriterSkill()
    result = skill.execute({"type": "email", "topic": "合作"}, {})
    assert result.success is True
    assert "合作" in result.content
    assert "主题" in result.content  # 邮件模板含"主题："
    assert result.metadata["type"] == "email"


def test_execute_report_without_llm_uses_mock_template():
    skill = WriterSkill()
    result = skill.execute({"type": "report", "topic": "Q3 业绩"}, {})
    assert result.success is True
    assert "Q3 业绩" in result.content
    assert "分析报告" in result.content
    assert result.metadata["type"] == "report"


def test_execute_social_without_llm_uses_mock_template():
    skill = WriterSkill()
    result = skill.execute({"type": "social", "topic": "新品发布"}, {})
    assert result.success is True
    assert "新品发布" in result.content
    assert result.metadata["type"] == "social"


def test_execute_unknown_type_falls_back_to_article_template():
    """type='other' 或未知值 → 回退到 article 模板（不抛错）."""
    skill = WriterSkill()
    result = skill.execute({"type": "weird-unknown", "topic": "X"}, {})
    assert result.success is True
    assert "X" in result.content
    assert result.metadata["type"] == "weird-unknown"


def test_execute_default_length_is_medium():
    skill = WriterSkill()
    result = skill.execute({"type": "article", "topic": "x"}, {})
    assert result.metadata["length"] == "medium"


def test_execute_default_style_is_professional():
    skill = WriterSkill()
    result = skill.execute({"type": "article", "topic": "x"}, {})
    assert result.metadata["style"] == "professional"


def test_execute_with_llm_calls_complete_and_returns_result():
    llm = Mock()
    llm.complete.return_value = "## AI 发展史\n\n2020 年..."
    skill = WriterSkill()
    result = skill.execute(
        {"type": "article", "topic": "AI 发展", "length": "long", "style": "academic"},
        {"llm": llm},
    )
    assert result.success is True
    assert result.content == "## AI 发展史\n\n2020 年..."
    assert result.metadata.get("mock") is not True
    llm.complete.assert_called_once()
    prompt = llm.complete.call_args[0][0]
    assert "AI 发展" in prompt
    assert "1500-2000" in prompt  # long → 1500-2000 字
    assert "academic" in prompt


def test_execute_with_llm_raises_returns_failure_result():
    llm = Mock()
    llm.complete.side_effect = RuntimeError("upstream error")
    skill = WriterSkill()
    result = skill.execute({"type": "article", "topic": "x"}, {"llm": llm})
    assert result.success is False
    assert "upstream error" in (result.error or "")
    assert result.content is None


# ============================================================================
# _build_prompt 内部
# ============================================================================


def test_build_prompt_article_length_map():
    skill = WriterSkill()
    p_short = skill._build_prompt("article", "X", "short", "casual")
    p_medium = skill._build_prompt("article", "X", "medium", "casual")
    p_long = skill._build_prompt("article", "X", "long", "casual")
    assert "100-200" in p_short
    assert "500-800" in p_medium
    assert "1500-2000" in p_long


def test_build_prompt_email_includes_topic_and_style():
    skill = WriterSkill()
    prompt = skill._build_prompt("email", "项目延期", "medium", "formal")
    assert "项目延期" in prompt
    assert "formal" in prompt
    assert "商务邮件" in prompt


def test_build_prompt_social_uses_fixed_length():
    """social 类型有固定 100 字, 不应受 length 参数影响."""
    skill = WriterSkill()
    prompt_short = skill._build_prompt("social", "X", "short", "casual")
    prompt_long = skill._build_prompt("social", "X", "long", "casual")
    assert "100字" in prompt_short
    assert "100字" in prompt_long


def test_build_prompt_unknown_type_falls_back_to_article():
    skill = WriterSkill()
    prompt = skill._build_prompt("unknown", "X", "medium", "casual")
    # 回退到 article 模板
    assert "文章" in prompt


# ============================================================================
# match
# ============================================================================


def test_match_returns_true_for_writing_triggers():
    skill = WriterSkill()
    assert skill.match("帮我写一篇文章") is True
    assert skill.match("创作一首诗") is True
    assert skill.match("write an email") is True
    assert skill.match("不相关的内容") is False


# ============================================================================
# 边界
# ============================================================================


def test_execute_with_empty_topic_still_returns_mock():
    skill = WriterSkill()
    result = skill.execute({"type": "article", "topic": ""}, {})
    assert result.success is True
    assert result.metadata["topic"] == ""


def test_execute_with_very_long_topic():
    skill = WriterSkill()
    long_topic = "超级长话题" * 200
    result = skill.execute({"type": "article", "topic": long_topic}, {})
    assert result.success is True
    assert long_topic in result.content
