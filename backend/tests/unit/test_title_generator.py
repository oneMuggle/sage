"""Title Generator — 单元测试

测试 TitleGenerator 的 LLM 调用、输出清洗、启发式兜底行为。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.chat.title_generator import (
    DEFAULT_TITLE,
    MAX_TITLE_ATTEMPTS,
    TitleGenerator,
    fallback_title,
    needs_title,
)

# ---------------------------------------------------------------------------
# _clean_title 静态方法测试
# ---------------------------------------------------------------------------


class TestCleanTitle:
    def test_basic_clean(self):
        assert TitleGenerator._clean_title("Python 编程") == "Python 编程"

    def test_strip_quotes(self):
        assert TitleGenerator._clean_title('"Python 编程"') == "Python 编程"
        assert TitleGenerator._clean_title("'Python 编程'") == "Python 编程"
        assert TitleGenerator._clean_title("「Python 编程」") == "Python 编程"

    def test_strip_prefix(self):
        assert TitleGenerator._clean_title("title: Python 编程") == "Python 编程"
        assert TitleGenerator._clean_title("标题: Python 编程") == "Python 编程"
        assert TitleGenerator._clean_title("Title：Python 编程") == "Python 编程"

    def test_multiline_takes_first(self):
        assert TitleGenerator._clean_title("Python 编程\n更多解释") == "Python 编程"

    def test_too_short_returns_none(self):
        assert TitleGenerator._clean_title("a") is None

    def test_too_long_returns_none(self):
        assert TitleGenerator._clean_title("a" * 31) is None

    def test_empty_returns_none(self):
        assert TitleGenerator._clean_title("") is None
        assert TitleGenerator._clean_title("   ") is None

    def test_placeholder_title_rejected(self):
        """LLM 原样吐回占位标题 → 视为无效，触发下一轮重试。"""
        assert TitleGenerator._clean_title(DEFAULT_TITLE) is None


# ---------------------------------------------------------------------------
# fallback_title 测试
# ---------------------------------------------------------------------------


class TestFallbackTitle:
    def test_uses_user_first_line(self):
        assert fallback_title("帮我写一个排序算法\n顺便解释", "好的") == "帮我写一个排序算法"

    def test_truncates_long_message(self):
        result = fallback_title("一" * 50, "")
        assert result.endswith("…")
        assert len(result) == 21  # 20 字 + 省略号

    def test_falls_back_to_assistant_when_user_empty(self):
        assert fallback_title("", "这是助手的回复内容") == "这是助手的回复内容"

    def test_returns_default_when_both_unusable(self):
        assert fallback_title("", "") == DEFAULT_TITLE
        assert fallback_title("a", "b") == DEFAULT_TITLE


# ---------------------------------------------------------------------------
# needs_title 测试
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self, title, attempts=0):
        self.title = title
        self.title_attempts = attempts


class TestNeedsTitle:
    def test_placeholder_title_needs_generation(self):
        assert needs_title(_FakeSession(DEFAULT_TITLE)) is True

    def test_none_title_needs_generation(self):
        assert needs_title(_FakeSession(None)) is True

    def test_real_title_does_not_need(self):
        assert needs_title(_FakeSession("排序算法")) is False

    def test_exhausted_attempts_stop_retrying(self):
        assert needs_title(_FakeSession(DEFAULT_TITLE, MAX_TITLE_ATTEMPTS)) is False

    def test_dict_form_supported(self):
        assert needs_title({"title": DEFAULT_TITLE, "title_attempts": 0}) is True
        assert needs_title({"title": "已有标题", "title_attempts": 0}) is False


# ---------------------------------------------------------------------------
# generate 方法测试
# ---------------------------------------------------------------------------


class TestGenerate:
    @pytest.mark.asyncio()
    async def test_none_llm_uses_fallback(self):
        gen = TitleGenerator(None)
        result = await gen.generate("hello world", "world response")
        assert result == "hello world"

    @pytest.mark.asyncio()
    async def test_short_messages_skip_llm(self):
        mock_llm = AsyncMock()
        gen = TitleGenerator(mock_llm)
        result = await gen.generate("hi", "ok")
        assert result == "hi"
        mock_llm.chat.assert_not_called()

    @pytest.mark.asyncio()
    async def test_llm_success(self):
        """LLM 返回正常标题"""

        class FakeResponse:
            content = "Python 入门指南"

        mock_llm = AsyncMock()
        # 兼容 dict 接口
        mock_llm.chat = AsyncMock(return_value=FakeResponse())

        gen = TitleGenerator(mock_llm)
        result = await gen.generate(
            "我想学 Python", "好的，我来帮你介绍 Python 编程的基础知识..."
        )
        assert result == "Python 入门指南"

    @pytest.mark.asyncio()
    async def test_llm_failure_uses_fallback(self):
        """LLM 抛异常 → 降级到启发式标题，而不是 None"""
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        gen = TitleGenerator(mock_llm)
        result = await gen.generate("hello world", "This is a response about programming")
        assert result == "hello world"

    @pytest.mark.asyncio()
    async def test_llm_unusable_output_uses_fallback(self):
        """LLM 输出不可清洗（过短）→ 降级到启发式"""
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value={"content": "a"})

        gen = TitleGenerator(mock_llm)
        result = await gen.generate(
            "帮我分析数据", "好的，我来帮你做数据分析..."
        )
        assert result == "帮我分析数据"

    @pytest.mark.asyncio()
    async def test_llm_dict_response(self):
        """LLM 返回 dict 格式（降级接口）"""
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value={"content": "数据分析"})

        gen = TitleGenerator(mock_llm)
        result = await gen.generate(
            "帮我分析数据", "好的，我来帮你做数据分析..."
        )
        assert result == "数据分析"
