"""
NudgeGuard 测试 (A13 from LLM_Simple)

测试被动读取循环检测与推动消息注入。
"""

import pytest

from backend.application.services.middleware import (
    DEFAULT_NUDGE_MESSAGE,
    NudgeGuard,
)


def _call(name: str) -> dict:
    """构造扁平风格 tool_call"""
    return {"name": name, "arguments": "{}"}


def _oai_call(name: str) -> dict:
    """构造 OpenAI 风格 tool_call"""
    return {"id": "call_1", "function": {"name": name, "arguments": "{}"}}


class TestNudgeGuardTrigger:
    """触发条件测试"""

    def test_all_passive_with_action_keyword_returns_nudge(self):
        """用户要求动作 + 全被动读取 → 注入默认 nudge 消息"""
        # Arrange
        guard = NudgeGuard()

        # Act
        nudge = guard.check(
            "帮我写一个排序脚本",
            [_call("read_file"), _call("list_dir")],
        )

        # Assert
        assert nudge == DEFAULT_NUDGE_MESSAGE

    def test_english_action_keyword_returns_nudge(self):
        """英文动作关键词同样触发"""
        guard = NudgeGuard()

        nudge = guard.check(
            "Please create a config file for me",
            [_call("read_file")],
        )

        assert nudge == DEFAULT_NUDGE_MESSAGE

    def test_no_action_keyword_returns_none(self):
        """用户只问信息（无动作关键词）→ 不注入"""
        # Arrange
        guard = NudgeGuard()

        # Act
        nudge = guard.check(
            "这个项目用了什么技术栈？",
            [_call("read_file"), _call("web_search")],
        )

        # Assert
        assert nudge is None
        assert guard.passive_streak == 0

    def test_mixed_passive_and_active_returns_none(self):
        """本轮包含主动工具（write_file）→ 不注入"""
        guard = NudgeGuard()

        nudge = guard.check(
            "帮我写一个排序脚本",
            [_call("read_file"), _call("write_file")],
        )

        assert nudge is None
        assert guard.passive_streak == 0

    def test_all_active_returns_none(self):
        """本轮全部为主动工具 → 不注入"""
        guard = NudgeGuard()

        nudge = guard.check(
            "帮我修复这个 bug",
            [_call("write_file"), _call("terminal")],
        )

        assert nudge is None

    def test_empty_tool_calls_returns_none(self):
        """空工具调用列表 → 不注入（无循环可言）"""
        guard = NudgeGuard()

        nudge = guard.check("帮我写一个脚本", [])

        assert nudge is None
        assert guard.passive_streak == 0

    def test_sage_passive_tool_set(self):
        """Sage 内置只读工具（web_search/memory_search/office_read 等）均视为被动"""
        guard = NudgeGuard()

        nudge = guard.check(
            "总结这份文档",
            [
                _call("read_file"),
                _call("web_search"),
                _call("web_fetch"),
                _call("memory_search"),
                _call("office_list"),
                _call("office_read"),
                _call("calculator"),
                _call("list_dir"),
            ],
        )

        assert nudge == DEFAULT_NUDGE_MESSAGE


class TestNudgeGuardStreak:
    """连续被动轮数（streak）行为测试"""

    def test_streak_resets_after_active_round(self):
        """被动 → 主动 → 被动：streak 重置，threshold=2 时第二轮被动不触发"""
        # Arrange
        guard = NudgeGuard(passive_threshold=2)

        # Act & Assert
        assert guard.check("写一个工具", [_call("read_file")]) is None
        assert guard.passive_streak == 1

        # 主动工具打断，streak 归零
        assert guard.check("写一个工具", [_call("write_file")]) is None
        assert guard.passive_streak == 0

        # 再次被动只累计到 1，未达阈值 2
        assert guard.check("写一个工具", [_call("read_file")]) is None
        assert guard.passive_streak == 1

    def test_consecutive_passive_rounds_trigger_at_threshold(self):
        """连续全被动轮数达到 threshold → 触发，且之后每轮持续触发"""
        # Arrange
        guard = NudgeGuard(passive_threshold=2)

        # Act & Assert: 第 1 轮未达阈值
        assert guard.check("生成报告", [_call("read_file")]) is None
        # 第 2 轮达到阈值
        assert guard.check("生成报告", [_call("list_dir")]) == DEFAULT_NUDGE_MESSAGE
        # 第 3 轮继续触发（仍处于被动循环）
        assert guard.check("生成报告", [_call("web_search")]) == DEFAULT_NUDGE_MESSAGE
        assert guard.passive_streak == 3

    def test_non_action_message_resets_streak(self):
        """无动作关键词的消息重置 streak"""
        # Arrange
        guard = NudgeGuard(passive_threshold=2)
        guard.check("写代码", [_call("read_file")])
        assert guard.passive_streak == 1

        # Act
        guard.check("这段代码是什么意思？", [_call("read_file")])

        # Assert
        assert guard.passive_streak == 0

    def test_reset_clears_streak(self):
        """reset() 显式清零 streak"""
        # Arrange
        guard = NudgeGuard(passive_threshold=3)
        guard.check("写代码", [_call("read_file")])
        guard.check("写代码", [_call("read_file")])
        assert guard.passive_streak == 2

        # Act
        guard.reset()

        # Assert
        assert guard.passive_streak == 0
        assert guard.check("写代码", [_call("read_file")]) is None


class TestNudgeGuardConfig:
    """配置与兼容性测试"""

    def test_openai_style_tool_calls(self):
        """兼容 OpenAI 风格 {"function": {"name": ...}}"""
        guard = NudgeGuard()

        nudge = guard.check(
            "create a readme",
            [_oai_call("read_file"), _oai_call("list_dir")],
        )

        assert nudge == DEFAULT_NUDGE_MESSAGE

    def test_mixed_call_formats(self):
        """兼容扁平与 OpenAI 混合格式"""
        guard = NudgeGuard()

        nudge = guard.check(
            "create a readme",
            [_call("read_file"), _oai_call("web_search")],
        )

        assert nudge == DEFAULT_NUDGE_MESSAGE

    def test_custom_passive_tools(self):
        """自定义被动工具集合覆盖默认"""
        # Arrange: 只有 my_reader 算被动；read_file 不再视为被动
        guard = NudgeGuard(passive_tools={"my_reader"})

        # Act & Assert
        assert guard.check("写代码", [_call("my_reader")]) == DEFAULT_NUDGE_MESSAGE

        guard.reset()
        assert guard.check("写代码", [_call("read_file")]) is None

    def test_custom_nudge_message(self):
        """自定义 nudge 消息"""
        guard = NudgeGuard(nudge_message="动手！")

        nudge = guard.check("写代码", [_call("read_file")])

        assert nudge == "动手！"

    def test_custom_action_keywords(self):
        """自定义动作关键词覆盖默认"""
        # Arrange
        guard = NudgeGuard(action_keywords={"deploy"})

        # Act & Assert: 默认关键词"写"不再生效
        assert guard.check("帮我写代码", [_call("read_file")]) is None
        # 自定义关键词生效
        assert (
            guard.check("Deploy the service", [_call("read_file")])
            == DEFAULT_NUDGE_MESSAGE
        )

    def test_invalid_threshold_raises(self):
        """passive_threshold < 1 抛 ValueError"""
        with pytest.raises(ValueError, match="passive_threshold"):
            NudgeGuard(passive_threshold=0)

    def test_empty_user_message(self):
        """空用户消息不触发"""
        guard = NudgeGuard()

        assert guard.check("", [_call("read_file")]) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
