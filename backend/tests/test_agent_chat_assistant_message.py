"""
agent.chat() 行为测试

验证 SageAgent.chat()：
1. LLMError 透传：不再被吞为字符串，而是结构化 error 字典
2. 成功路径：返回带 assistant message 字典的标准响应
3. _call_llm 返回 LLMResponse：保留 tool_calls 透传通道（Task 9 依赖）

这些测试覆盖 Task 6 修复：移除 _call_llm 的字符串回退 + 移除 chat() 的 dir() hack。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.core.agent import SageAgent
from backend.core.errors import LLMError, LLMErrorType
from backend.core.llm_client import LLMResponse


@pytest.mark.asyncio
async def test_chat_returns_error_dict_on_llm_error():
    """LLM 抛错时 chat() 返回结构化 error 字典，message 为 None。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=LLMError(LLMErrorType.AUTH_FAILED, "API Key 无效", status_code=401)
    )

    result = await agent.chat(
        session_id="00000000-0000-0000-0000-000000000000",
        message="hi",
    )
    assert "error" in result
    assert result["error"]["type"] == "auth_failed"
    assert result["message"] is None
    assert result["session"] is None


@pytest.mark.asyncio
async def test_chat_returns_assistant_message_on_success():
    """LLM 成功时 chat() 返回 message 字典。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=LLMResponse(
        content="你好！",
        model="gpt-3.5-turbo",
    ))

    result = await agent.chat(
        session_id="00000000-0000-0000-0000-000000000000",
        message="hi",
    )
    assert "message" in result
    assert result["message"]["content"] == "你好！"
    assert result["message"]["role"] == "assistant"
    assert "error" not in result
