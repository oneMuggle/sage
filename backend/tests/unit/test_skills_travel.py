"""
TravelSkill 单元测试

覆盖：
- schema 元数据
- execute 无 LLM → mock 计划（1/2/3 天）
- execute 有 LLM → 调用 llm.complete
- execute LLM 抛异常 → SkillResult(success=False)
- 默认值: days=3, budget=medium, style=sightseeing
- _build_prompt 风格/预算映射
- match() 触发词
"""

from unittest.mock import Mock

import pytest

from backend.skills.builtin.travel import TravelSkill

pytestmark = pytest.mark.unit


# ============================================================================
# Schema
# ============================================================================


def test_schema_metadata():
    skill = TravelSkill()
    assert skill.name == "travel"
    assert "旅行" in skill.triggers or "travel" in skill.triggers
    params = skill.schema.parameters
    assert "destination" in params["properties"]
    assert params["required"] == ["destination"]


def test_schema_examples_non_empty():
    skill = TravelSkill()
    assert len(skill.schema.examples) >= 1


# ============================================================================
# execute 路径
# ============================================================================


def test_execute_three_days_without_llm_returns_three_day_plan():
    skill = TravelSkill()
    result = skill.execute(
        {"destination": "北京", "days": 3, "budget": "medium", "style": "sightseeing"},
        {},
    )
    assert result.success is True
    assert "北京" in result.content
    assert "Day 1" in result.content
    assert "Day 3" in result.content
    assert result.metadata["destination"] == "北京"
    assert result.metadata["days"] == 3
    assert result.metadata["mock"] is True


def test_execute_one_day_without_llm_returns_one_day_plan():
    skill = TravelSkill()
    result = skill.execute({"destination": "上海", "days": 1}, {})
    assert result.success is True
    assert "上海" in result.content
    assert "一日游" in result.content


def test_execute_two_days_without_llm_returns_two_day_plan():
    skill = TravelSkill()
    result = skill.execute({"destination": "杭州", "days": 2}, {})
    assert result.success is True
    assert "杭州" in result.content
    assert "Day 2" in result.content


def test_execute_five_days_falls_back_to_three_day_plan_template():
    """days=5 不在预设模板 (1/2/3) 中, 应回退到三日游模板."""
    skill = TravelSkill()
    result = skill.execute({"destination": "成都", "days": 5}, {})
    assert result.success is True
    assert "成都" in result.content
    # 三日游模板有 "Day 3: 休闲返程"
    assert "Day 3" in result.content


def test_execute_default_days_is_3():
    skill = TravelSkill()
    result = skill.execute({"destination": "厦门"}, {})
    assert result.metadata["days"] == 3
    assert "Day 3" in result.content


def test_execute_default_budget_and_style_are_medium_sightseeing():
    skill = TravelSkill()
    result = skill.execute({"destination": "西安"}, {})
    assert result.metadata["budget"] == "medium"
    assert result.metadata["style"] == "sightseeing"


def test_execute_with_llm_calls_complete_and_returns_result():
    llm = Mock()
    llm.complete.return_value = "Day 1: 抵达西安..."
    skill = TravelSkill()
    result = skill.execute(
        {"destination": "西安", "days": 2, "budget": "high", "style": "foodie"},
        {"llm": llm},
    )
    assert result.success is True
    assert result.content == "Day 1: 抵达西安..."
    assert result.metadata["budget"] == "high"
    assert result.metadata["style"] == "foodie"
    # mock=True 不应出现
    assert result.metadata.get("mock") is not True
    llm.complete.assert_called_once()
    prompt = llm.complete.call_args[0][0]
    assert "西安" in prompt
    assert "美食" in prompt  # foodie → 美食探索
    assert "高端奢华" in prompt  # high → 高端奢华


def test_execute_with_llm_raises_returns_failure_result():
    llm = Mock()
    llm.complete.side_effect = RuntimeError("rate limit")
    skill = TravelSkill()
    result = skill.execute(
        {"destination": "广州"}, {"llm": llm}
    )
    assert result.success is False
    assert "rate limit" in (result.error or "")
    assert result.content is None


# ============================================================================
# _build_prompt 内部
# ============================================================================


def test_build_prompt_known_budget_and_style_mapped_to_chinese():
    skill = TravelSkill()
    prompt = skill._build_prompt("北京", 3, "low", "adventure")
    assert "北京" in prompt
    assert "经济实惠" in prompt  # low → 经济实惠
    assert "冒险体验" in prompt  # adventure → 冒险体验
    assert "3天" in prompt


def test_build_prompt_unknown_budget_falls_back_to_medium():
    skill = TravelSkill()
    prompt = skill._build_prompt("x", 2, "ultra-mega", "sightseeing")
    assert "中等消费" in prompt


def test_build_prompt_unknown_style_falls_back_to_sightseeing():
    skill = TravelSkill()
    prompt = skill._build_prompt("x", 1, "medium", "unknown-style")
    assert "观光游览" in prompt


# ============================================================================
# match
# ============================================================================


def test_match_returns_true_for_travel_triggers():
    skill = TravelSkill()
    assert skill.match("帮我规划北京旅行") is True
    assert skill.match("旅游攻略") is True
    assert skill.match("行程安排") is True
    assert skill.match("travel plan please") is True
    assert skill.match("完全不相关") is False


# ============================================================================
# 边界
# ============================================================================


def test_execute_with_empty_destination_uses_empty_in_template():
    """destination 为空时 mock 模板仍能 format（虽然不美观, 但不应抛错）."""
    skill = TravelSkill()
    result = skill.execute({"destination": ""}, {})
    assert result.success is True
    assert result.metadata["destination"] == ""


def test_execute_with_very_long_destination():
    skill = TravelSkill()
    long_dest = "非常" * 500 + "长的地方"
    result = skill.execute({"destination": long_dest}, {})
    assert result.success is True
    assert long_dest in result.content
