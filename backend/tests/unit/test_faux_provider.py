"""
FauxProvider 测试 (A25 from pi)

测试模拟 LLM Provider。
"""

import pytest
from sage_core import Message, Role

from backend.adapters.out.llm.faux_provider import (
    CompletionRequest,
    FauxProvider,
    create_faux_provider,
)


class TestFauxProvider:
    """FauxProvider 测试套件"""

    @pytest.mark.asyncio()
    async def test_complete_returns_preset_response(self):
        """complete 返回预设响应"""
        faux = FauxProvider(responses=["Hello, world!"])
        req = CompletionRequest(messages=[Message(role=Role.USER, content="Hi")])

        result = await faux.complete(req)

        assert result.content == "Hello, world!"
        assert faux.call_count == 1

    @pytest.mark.asyncio()
    async def test_complete_cycles_through_responses(self):
        """complete 循环使用响应列表"""
        faux = FauxProvider(responses=["First", "Second", "Third"])
        req = CompletionRequest(messages=[])

        r1 = await faux.complete(req)
        r2 = await faux.complete(req)
        r3 = await faux.complete(req)
        r4 = await faux.complete(req)  # 循环回第一个

        assert r1.content == "First"
        assert r2.content == "Second"
        assert r3.content == "Third"
        assert r4.content == "First"
        assert faux.call_count == 4

    @pytest.mark.asyncio()
    async def test_complete_includes_token_usage(self):
        """complete 包含 token 统计"""
        faux = FauxProvider(responses=["Hello world"])
        req = CompletionRequest(messages=[Message(role=Role.USER, content="Hi there")])

        result = await faux.complete(req)

        assert "input" in result.usage
        assert "output" in result.usage
        assert "total" in result.usage
        assert result.usage["total"] == result.usage["input"] + result.usage["output"]

    @pytest.mark.asyncio()
    async def test_stream_yields_characters(self):
        """stream 逐字符 yield"""
        faux = FauxProvider(responses=["Hi"])
        req = CompletionRequest(messages=[])

        chunks = []
        async for chunk in faux.stream(req):
            chunks.append(chunk.content)

        assert chunks == ["H", "i"]
        assert faux.call_count == 1

    @pytest.mark.asyncio()
    async def test_stream_marks_last_chunk(self):
        """stream 标记最后一个 chunk"""
        faux = FauxProvider(responses=["AB"])
        req = CompletionRequest(messages=[])

        chunks = []
        async for chunk in faux.stream(req):
            chunks.append(chunk)

        assert chunks[0].is_done is False
        assert chunks[1].is_done is True

    @pytest.mark.asyncio()
    async def test_chat_compatibility(self):
        """chat 兼容接口"""
        faux = FauxProvider(responses=["Response"])
        messages = [Message(role=Role.USER, content="Hello")]

        result = await faux.chat(messages)

        assert isinstance(result, Message)
        assert result.role == Role.ASSISTANT
        assert result.content == "Response"

    @pytest.mark.asyncio()
    async def test_chat_stream_compatibility(self):
        """chat_stream 兼容接口"""
        faux = FauxProvider(responses=["Hi"])
        messages = [Message(role=Role.USER, content="Hello")]

        content = ""
        async for chunk in faux.chat_stream(messages):
            content += chunk

        assert content == "Hi"

    def test_create_faux_provider_helper(self):
        """create_faux_provider 便捷函数"""
        faux = create_faux_provider(responses=["Test"])

        assert isinstance(faux, FauxProvider)
        assert faux.responses == ["Test"]

    @pytest.mark.asyncio()
    async def test_default_response(self):
        """默认响应"""
        faux = FauxProvider()
        req = CompletionRequest(messages=[])

        result = await faux.complete(req)

        assert result.content == "This is a faux response."


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
