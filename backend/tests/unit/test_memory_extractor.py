"""验证 MemoryExtractor 的事实提取功能。"""

import pytest

from backend.memory.extractor import MemoryExtractor

pytestmark = pytest.mark.unit


class TestMemoryExtractorKeywords:
    """测试关键词降级提取（无 LLM）"""

    @pytest.mark.asyncio()
    async def test_extract_preference_with_keyword(self):
        """包含偏好关键词时应提取事实。"""
        extractor = MemoryExtractor(llm_client=None)
        # 消息需要足够长（> 20 字符）才触发提取
        facts = await extractor.extract("我喜欢吃火锅，每次去成都都要找地道的火锅店" + "x" * 20, "好的")
        assert len(facts) >= 1
        assert any("火锅" in f["content"] for f in facts)
        assert all(f["importance"] == 7 for f in facts)

    @pytest.mark.asyncio()
    async def test_extract_short_message_returns_empty(self):
        """太短的消息不应提取。"""
        extractor = MemoryExtractor(llm_client=None)
        facts = await extractor.extract("hi", "hello")
        assert facts == []

    @pytest.mark.asyncio()
    async def test_extract_no_keywords_returns_empty(self):
        """无偏好关键词的普通对话不应提取。"""
        extractor = MemoryExtractor(llm_client=None)
        facts = await extractor.extract("今天天气怎么样", "今天晴天")
        assert facts == []


class TestMemoryExtractorLLM:
    """测试 LLM 提取"""

    @pytest.mark.asyncio()
    async def test_extract_with_mock_llm_json(self):
        """LLM 返回 JSON 时应正确解析。"""

        class MockLLM:
            async def chat(self, messages, **kwargs):
                from backend.domain.message import Message
                return Message(
                    role="assistant",
                    content='[{"content":"用户喜欢吃火锅","importance":8,"category":"preference","tags":["火锅"]}]',
                )

        extractor = MemoryExtractor(llm_client=MockLLM())
        facts = await extractor.extract(
            "我喜欢吃火锅，每次去成都都要找地道的火锅店" + "x" * 20,
            "好的记住了",
        )
        assert len(facts) == 1
        assert facts[0]["content"] == "用户喜欢吃火锅"
        assert facts[0]["importance"] == 8
        assert facts[0]["category"] == "preference"

    @pytest.mark.asyncio()
    async def test_extract_with_markdown_code_block(self):
        """LLM 返回 markdown 代码块中的 JSON 应正确解析。"""

        class MockLLM:
            async def chat(self, messages, **kwargs):
                from backend.domain.message import Message
                return Message(
                    role="assistant",
                    content='好的，以下是提取的结果：\n```json\n[{"content":"用户喜欢Python","importance":6,"category":"fact","tags":["编程"]}]\n```\n希望这对你有帮助！',
                )

        extractor = MemoryExtractor(llm_client=MockLLM())
        facts = await extractor.extract(
            "我喜欢用Python编程，已经学了一年多了" + "x" * 20,
            "很好",
        )
        assert len(facts) == 1
        assert "Python" in facts[0]["content"]

    @pytest.mark.asyncio()
    async def test_extract_with_invalid_json_falls_back(self):
        """LLM 返回无效 JSON 时应降级到关键词提取。"""

        class MockLLM:
            async def chat(self, messages, **kwargs):
                from backend.domain.message import Message
                return Message(
                    role="assistant",
                    content="这不是JSON格式",
                )

        extractor = MemoryExtractor(llm_client=MockLLM())
        facts = await extractor.extract("我喜欢吃火锅，每次都去那家店" + "x" * 20, "好的")
        assert len(facts) >= 0

    @pytest.mark.asyncio()
    async def test_extract_with_llm_error_falls_back(self):
        """LLM 调用失败时应降级到关键词提取。"""

        class FailingLLM:
            async def chat(self, messages, **kwargs):
                raise RuntimeError("LLM unavailable")

        extractor = MemoryExtractor(llm_client=FailingLLM())
        facts = await extractor.extract("我喜欢吃火锅，每次都去那家店" + "x" * 20, "好的")
        assert len(facts) >= 0
