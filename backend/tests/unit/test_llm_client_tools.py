"""
LLMClient tools 透传测试

验证 LLMClient.chat() 在传入 tools 时把 OpenAI 兼容的 tools / tool_choice
字段写入请求体；未传 tools 时请求体不包含这两个字段。
"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.core.legacy.llm_client import LLMClient, LLMConfig

pytestmark = pytest.mark.unit


@pytest.fixture  # noqa: PT001 — 兼容 CI ruff 0.15.x (偏好无括号)
def client():
    return LLMClient(
        LLMConfig(
            provider="openai",
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="gpt-3.5-turbo",
        )
    )


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_sends_tools_when_provided(client):
    """tools 参数应传递到请求体。"""
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {},
    }
    mock_response.raise_for_status = lambda: None

    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "数学计算",
                    "parameters": {
                        "type": "object",
                        "properties": {"expression": {"type": "string"}},
                    },
                },
            }
        ]
        await client.chat([{"role": "user", "content": "hi"}], tools=tools)

        call_args = mock_http.post.call_args
        body = call_args.kwargs["json"]
        assert "tools" in body
        assert body["tools"] == tools
        assert body["tool_choice"] == "auto"


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_omits_tools_when_none(client):
    """tools=None 时请求体不应包含 tools 字段。"""
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {},
    }
    mock_response.raise_for_status = lambda: None

    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http

        await client.chat([{"role": "user", "content": "hi"}])
        call_args = mock_http.post.call_args
        body = call_args.kwargs["json"]
        assert "tools" not in body
        assert "tool_choice" not in body
