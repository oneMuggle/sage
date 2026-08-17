"""Title Generator — 单元测试

测试 TitleGenerator 的 LLM 调用、输出清洗、降级行为。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.chat.title_generator import TitleGenerator

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


# ---------------------------------------------------------------------------
# generate 方法测试
# ---------------------------------------------------------------------------


class TestGenerate:
    @pytest.mark.asyncio()
    async def test_none_llm_returns_none(self):
        gen = TitleGenerator(None)
        result = await gen.generate("hello", "world response")
        assert result is None

    @pytest.mark.asyncio()
    async def test_short_messages_returns_none(self):
        mock_llm = AsyncMock()
        gen = TitleGenerator(mock_llm)
        result = await gen.generate("hi", "ok")
        assert result is None
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
    async def test_llm_failure_returns_none(self):
        """LLM 抛异常 → 降级返回 None"""
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        gen = TitleGenerator(mock_llm)
        result = await gen.generate("hello world", "This is a response about programming")
        assert result is None

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
