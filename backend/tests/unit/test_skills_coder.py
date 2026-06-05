"""
CoderSkill 单元测试

覆盖：
- schema 元数据（name / triggers / examples）
- execute 各 action 分支：write / explain / debug / review / refactor
- 未知 action 返回 SkillResult(success=False, error=...)
- 无 LLM → 走 mock 模板
- LLM 存在 → 调用 llm.complete 并返回 result
- LLM 抛异常 → SkillResult(success=False, error=...)
- 边界: 空 requirement / 空 code / 长输入
"""

from unittest.mock import Mock

import pytest

from backend.skills.builtin.coder import CoderSkill

pytestmark = pytest.mark.unit


# ============================================================================
# Schema
# ============================================================================


def test_schema_name_description_triggers():
    skill = CoderSkill()
    assert skill.name == "coder"
    assert "代码" in skill.description or "code" in skill.description.lower()
    assert "写代码" in skill.triggers
    assert "code" in skill.triggers


def test_schema_examples_non_empty():
    skill = CoderSkill()
    assert len(skill.schema.examples) >= 1


def test_schema_parameters_require_action():
    skill = CoderSkill()
    params = skill.schema.parameters
    assert params.get("required") == ["action"]
    assert "action" in params["properties"]
    assert "language" in params["properties"]


# ============================================================================
# execute 路径
# ============================================================================


def test_execute_unknown_action_returns_failure():
    """action 不在已知枚举内 → success=False, error 提示未知操作."""
    skill = CoderSkill()
    result = skill.execute({"action": "summarize"}, {})
    assert result.success is False
    assert "未知操作" in (result.error or "")
    assert result.content is None


def test_execute_write_without_llm_uses_mock_template():
    """action=write 且 llm=None → 走 mock 模板, 元数据中 mock=True."""
    skill = CoderSkill()
    result = skill.execute(
        {"action": "write", "language": "python", "requirement": "实现快速排序"},
        {},
    )
    assert result.success is True
    assert "python" in (result.content or "")
    assert "快速排序" in (result.content or "")
    assert result.metadata["action"] == "write"
    assert result.metadata["language"] == "python"
    assert result.metadata["mock"] is True


def test_execute_explain_without_llm_uses_mock_template():
    skill = CoderSkill()
    result = skill.execute(
        {"action": "explain", "language": "python", "code": "def f(): pass"},
        {},
    )
    assert result.success is True
    assert "python" in (result.content or "")
    assert result.metadata["action"] == "explain"


def test_execute_debug_without_llm_uses_mock_template():
    skill = CoderSkill()
    result = skill.execute(
        {"action": "debug", "language": "javascript", "code": "var x = ;"},
        {},
    )
    assert result.success is True
    assert result.content is not None
    # debug 模板是固定中文（不嵌入 language）, 校验 action 走通即可
    assert "代码检查结果" in result.content
    assert result.metadata["action"] == "debug"
    assert result.metadata["language"] == "javascript"


def test_execute_review_without_llm_uses_mock_template():
    skill = CoderSkill()
    result = skill.execute(
        {"action": "review", "language": "go", "code": "package main"},
        {},
    )
    assert result.success is True
    assert "go" in (result.content or "")
    assert result.metadata["action"] == "review"


def test_execute_refactor_without_llm_uses_mock_template():
    skill = CoderSkill()
    result = skill.execute(
        {"action": "refactor", "language": "rust", "code": "fn main() {}"},
        {},
    )
    assert result.success is True
    assert "rust" in (result.content or "")
    assert result.metadata["action"] == "refactor"


def test_execute_with_llm_calls_complete_and_returns_result():
    """提供 llm 时, execute 把构造的 prompt 传给 llm.complete 并返回 result."""
    llm = Mock()
    llm.complete.return_value = "```python\ndef example(): pass\n```"
    skill = CoderSkill()
    result = skill.execute(
        {"action": "write", "language": "python", "requirement": "demo"},
        {"llm": llm},
    )
    assert result.success is True
    assert "def example" in result.content
    assert result.metadata["action"] == "write"
    assert result.metadata["language"] == "python"
    # mock=True 不应出现
    assert result.metadata.get("mock") is not True
    llm.complete.assert_called_once()
    prompt_arg = llm.complete.call_args[0][0]
    assert "demo" in prompt_arg
    assert "python" in prompt_arg


def test_execute_with_llm_raises_returns_failure_result():
    """llm.complete 抛异常 → SkillResult(success=False, error=...) 包装错误信息."""
    llm = Mock()
    llm.complete.side_effect = RuntimeError("api down")
    skill = CoderSkill()
    result = skill.execute({"action": "write", "requirement": "x"}, {"llm": llm})
    assert result.success is False
    assert "api down" in (result.error or "")
    assert result.content is None


# ============================================================================
# 边界
# ============================================================================


def test_execute_default_language_is_python():
    """未传 language 时, 默认使用 python."""
    skill = CoderSkill()
    result = skill.execute({"action": "write", "requirement": "demo"}, {})
    assert result.metadata["language"] == "python"
    assert "python" in (result.content or "")


def test_execute_with_empty_requirement_still_returns_mock():
    skill = CoderSkill()
    result = skill.execute({"action": "write"}, {})
    assert result.success is True
    assert result.metadata["action"] == "write"


def test_execute_with_very_long_code_input():
    """超长 code 不会导致 mock/explain 路径崩溃."""
    skill = CoderSkill()
    long_code = "x = 1\n" * 10_000
    result = skill.execute(
        {"action": "explain", "language": "python", "code": long_code}, {}
    )
    assert result.success is True
    assert result.metadata["action"] == "explain"


def test_execute_match_returns_true_for_trigger_words():
    skill = CoderSkill()
    assert skill.match("帮我写代码") is True
    assert skill.match("please code this") is True
    assert skill.match("完全无关的输入") is False
