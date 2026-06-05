"""
LLMClient 错误分类测试

验证 LLMClient.chat() 在不同错误情形下抛出 LLMError(LLMErrorType.*)
而非原先的 RuntimeError。
"""
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from backend.core.errors import LLMError, LLMErrorType
from backend.core.llm_client import LLMClient, LLMConfig


@pytest.fixture()
def client():
    return LLMClient(LLMConfig(
        provider="openai",
        api_key="test-key",
        base_url="https://api.example.com/v1",
        model="gpt-3.5-turbo",
    ))


@pytest.mark.asyncio()
async def test_401_raises_auth_failed(client):
    """HTTP 401 应映射为 AUTH_FAILED。"""
    mock_response = AsyncMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"
    # httpx.Response.raise_for_status 是同步方法；AsyncMock 会让调用返回
    # 未被 await 的协程，因此必须用普通 Mock 替换才能正确触发 side_effect。
    mock_response.raise_for_status = Mock(side_effect=httpx.HTTPStatusError(
        "401", request=AsyncMock(), response=mock_response
    ))

    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http

        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
        assert exc_info.value.type == LLMErrorType.AUTH_FAILED
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio()
async def test_429_raises_rate_limited(client):
    """HTTP 429 应映射为 RATE_LIMITED。"""
    mock_response = AsyncMock()
    mock_response.status_code = 429
    mock_response.text = "Too Many Requests"
    mock_response.headers = {"retry-after": "60"}
    mock_response.raise_for_status = Mock(side_effect=httpx.HTTPStatusError(
        "429", request=AsyncMock(), response=mock_response
    ))

    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http

        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
        assert exc_info.value.type == LLMErrorType.RATE_LIMITED
        assert exc_info.value.retry_after == 60


@pytest.mark.asyncio()
async def test_500_raises_server_error(client):
    """HTTP 5xx 应映射为 SERVER_ERROR。"""
    mock_response = AsyncMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_response.raise_for_status = Mock(side_effect=httpx.HTTPStatusError(
        "500", request=AsyncMock(), response=mock_response
    ))

    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http

        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
        assert exc_info.value.type == LLMErrorType.SERVER_ERROR
        assert exc_info.value.status_code == 500


@pytest.mark.asyncio()
async def test_timeout_raises_timeout_error(client):
    """httpx.TimeoutException 应映射为 TIMEOUT。"""
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_get_client.return_value = mock_http

        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
        assert exc_info.value.type == LLMErrorType.TIMEOUT


@pytest.mark.asyncio()
async def test_connect_error_raises_network_error(client):
    """httpx.ConnectError 应映射为 NETWORK。"""
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_get_client.return_value = mock_http

        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
        assert exc_info.value.type == LLMErrorType.NETWORK


@pytest.mark.asyncio()
async def test_parsing_error_raises_parsing_error_type(client):
    """响应 JSON 解析失败时映射为 PARSING。"""
    import json
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = lambda: None
    mock_response.json = lambda: (_ for _ in ()).throw(json.JSONDecodeError("Expecting value", "", 0))

    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http

        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
        assert exc_info.value.type == LLMErrorType.PARSING


@pytest.mark.asyncio()
async def test_empty_choices_raises_parsing_error(client):
    """choices 为空时应映射为 PARSING。"""
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = lambda: None
    mock_response.json = lambda: {"choices": [], "model": "gpt-3.5-turbo"}

    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http

        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
        assert exc_info.value.type == LLMErrorType.PARSING
