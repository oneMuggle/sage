"""R160 — 被动读取循环检测 NudgeGuard 单元测试。

覆盖：passive_threshold 校验、双条件触发（动作关键词 × 连续全被动）、
streak 重置语义、OpenAI 嵌套与扁平 tool_call 结构、自定义配置。
"""

from __future__ import annotations

import pytest

from backend.application.services.middleware.nudge_guard import (
    DEFAULT_ACTION_KEYWORDS,
    DEFAULT_NUDGE_MESSAGE,
    DEFAULT_PASSIVE_READ_TOOLS,
    NudgeGuard,
)

pytestmark = pytest.mark.unit


def test_threshold_below_one_rejected():
    with pytest.raises(ValueError, match="passive_threshold"):
        NudgeGuard(passive_threshold=0)


def _flat(name):
    return {"name": name}


def test_nudge_when_action_wanted_and_all_passive():
    guard = NudgeGuard(passive_threshold=1)
    out = guard.check("帮我写一个脚本", [_flat("read_file"), _flat("list_dir")])
    assert out is not None
    assert "write_file" in out
    assert guard.passive_streak == 1


def test_no_action_keyword_resets_and_returns_none():
    guard = NudgeGuard(passive_threshold=2)
    guard.check("帮我写脚本", [_flat("read_file")])
    assert guard.passive_streak == 1
    out = guard.check("今天天气如何", [_flat("read_file")])  # 无动作关键词
    assert out is None
    assert guard.passive_streak == 0


def test_active_tool_resets_streak():
    guard = NudgeGuard(passive_threshold=2)
    assert guard.check("写脚本", [_flat("read_file")]) is None  # streak 1
    assert guard.check("写脚本", [_flat("bash")]) is None  # 主动工具 → 重置
    assert guard.passive_streak == 0


def test_empty_tool_calls_treated_non_passive():
    guard = NudgeGuard(passive_threshold=1)
    assert guard.check("写脚本", []) is None
    assert guard.passive_streak == 0


def test_threshold_two_nudges_on_second_passive_round():
    guard = NudgeGuard(passive_threshold=2)
    assert guard.check("写脚本", [_flat("read_file")]) is None  # streak 1
    out = guard.check("写脚本", [_flat("web_search")])  # streak 2 ≥ 2
    assert out == DEFAULT_NUDGE_MESSAGE
    assert guard.passive_streak == 2


def test_openai_nested_tool_call_structure_recognized():
    guard = NudgeGuard(passive_threshold=1)
    calls = [{"function": {"name": "read_file", "arguments": "{}"}}]
    out = guard.check("写脚本", calls)
    assert out is not None


def test_reset_clears_streak():
    guard = NudgeGuard(passive_threshold=5)
    guard.check("写脚本", [_flat("read_file")])
    assert guard.passive_streak == 1
    guard.reset()
    assert guard.passive_streak == 0


def test_custom_passive_tools_and_nudge():
    guard = NudgeGuard(
        passive_tools={"my_lookup"},
        action_keywords={"创建"},
        nudge_message="CUSTOM NUDGE",
        passive_threshold=1,
    )
    out = guard.check("创建一份报告", [_flat("my_lookup")])
    assert out == "CUSTOM NUDGE"


def test_custom_action_keywords_excluded():
    guard = NudgeGuard(action_keywords={"画画"})
    out = guard.check("帮我写个脚本", [_flat("read_file")])
    assert out is None  # "写" 不在自定义词表 → 无动作意图


def test_mixed_passive_and_active_no_nudge():
    guard = NudgeGuard(passive_threshold=1)
    calls = [_flat("read_file"), _flat("bash")]
    assert guard.check("写脚本", calls) is None
    assert guard.passive_streak == 0


def test_default_constants_exported():
    assert isinstance(DEFAULT_PASSIVE_READ_TOOLS, frozenset)
    assert "read_file" in DEFAULT_PASSIVE_READ_TOOLS
    assert isinstance(DEFAULT_ACTION_KEYWORDS, frozenset)
    assert "写" in DEFAULT_ACTION_KEYWORDS
    assert "write_file" in DEFAULT_NUDGE_MESSAGE
