"""
LLMClient.chat_stream 错误分类测试（关闭 Task 11）

验证流式路径与 ``chat()`` 一致：抛出分类的 ``LLMError(LLMErrorType.*)``
而非裸 ``RuntimeError``。通过 mock httpx 客户端模拟超时 / 连接失败 /
HTTP 状态码错误，并断言正常流的 yield 契约不受影响。
"""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from backend.core.errors import LLMError, LLMErrorType
from backend.core.legacy.llm_client import LLMClient, LLMConfig

pytestmark = pytest.mark.unit


class _StreamContext:
    """模拟 ``httpx.AsyncClient.stream()`` 返回的异步上下文管理器。

    ``enter_error`` 非 None 时在 ``__aenter__`` 抛出（模拟连接/握手阶段失败）；
    否则返回 ``response``。
    """

    def __init__(self, response=None, enter_error=None):
        self._response = response
        self._enter_error = enter_error

    async def __aenter__(self):
        if self._enter_error is not None:
            raise self._enter_error
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _status_response(status_code, headers=None):
    """构造 raise_for_status 抛 HTTPStatusError 的 mock 流响应。"""
    response = AsyncMock()
    response.status_code = status_code
    response.text = f"HTTP {status_code}"
    response.headers = headers or {}
    # raise_for_status 是同步方法，必须用普通 Mock 才能正确触发 side_effect
    response.raise_for_status = Mock(
        side_effect=httpx.HTTPStatusError(
            str(status_code), request=AsyncMock(), response=response
        )
    )
    return response


def _ok_response(lines):
    """构造正常 SSE 流响应（aiter_lines 产出给定行）。"""
    response = AsyncMock()
    response.status_code = 200
    response.raise_for_status = Mock()

    async def aiter_lines():
        for line in lines:
            yield line

    response.aiter_lines = aiter_lines
    return response


def _patch_stream(client, response=None, enter_error=None):
    """把 client._get_client 替换为返回 mock httpx 客户端的 patcher。"""
    patcher = patch.object(client, "_get_client")
    mock_get_client = patcher.start()
    mock_http = AsyncMock()
    mock_http.stream = Mock(
        return_value=_StreamContext(response=response, enter_error=enter_error)
    )
    mock_get_client.return_value = mock_http
    return patcher


@pytest.fixture()
def client():
    return LLMClient(
        LLMConfig(
            provider="openai",
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="gpt-3.5-turbo",
            use_proxy=False,
        )
    )


_MESSAGES = [{"role": "user", "content": "hi"}]


async def _consume(stream):
    """消费流并收集全部 chunk（单语句形式，满足 PT012 约束）。"""
    return [chunk async for chunk in stream]


@pytest.mark.asyncio()
async def test_stream_timeout_raises_timeout_error(client):
    """连接/读取超时应映射为 TIMEOUT。"""
    # Arrange
    patcher = _patch_stream(client, enter_error=httpx.TimeoutException("timeout"))

    try:
        # Act / Assert
        with pytest.raises(LLMError) as exc_info:
            await _consume(client.chat_stream(_MESSAGES))
        assert exc_info.value.type == LLMErrorType.TIMEOUT
    finally:
        patcher.stop()


@pytest.mark.asyncio()
async def test_stream_connect_error_raises_network_error(client):
    """httpx.ConnectError 应映射为 NETWORK。"""
    # Arrange
    patcher = _patch_stream(client, enter_error=httpx.ConnectError("connection refused"))

    try:
        # Act / Assert
        with pytest.raises(LLMError) as exc_info:
            await _consume(client.chat_stream(_MESSAGES))
        assert exc_info.value.type == LLMErrorType.NETWORK
    finally:
        patcher.stop()


@pytest.mark.asyncio()
async def test_stream_401_raises_auth_failed(client):
    """HTTP 401 应映射为 AUTH_FAILED。"""
    # Arrange
    patcher = _patch_stream(client, response=_status_response(401))

    try:
        # Act / Assert
        with pytest.raises(LLMError) as exc_info:
            await _consume(client.chat_stream(_MESSAGES))
        assert exc_info.value.type == LLMErrorType.AUTH_FAILED
        assert exc_info.value.status_code == 401
    finally:
        patcher.stop()


@pytest.mark.asyncio()
async def test_stream_429_raises_rate_limited(client):
    """HTTP 429 应映射为 RATE_LIMITED 并携带 retry_after。"""
    # Arrange
    patcher = _patch_stream(
        client, response=_status_response(429, headers={"retry-after": "30"})
    )

    try:
        # Act / Assert
        with pytest.raises(LLMError) as exc_info:
            await _consume(client.chat_stream(_MESSAGES))
        assert exc_info.value.type == LLMErrorType.RATE_LIMITED
        assert exc_info.value.retry_after == 30
    finally:
        patcher.stop()


@pytest.mark.asyncio()
async def test_stream_500_raises_server_error(client):
    """HTTP 5xx 应映射为 SERVER_ERROR。"""
    # Arrange
    patcher = _patch_stream(client, response=_status_response(500))

    try:
        # Act / Assert
        with pytest.raises(LLMError) as exc_info:
            await _consume(client.chat_stream(_MESSAGES))
        assert exc_info.value.type == LLMErrorType.SERVER_ERROR
        assert exc_info.value.status_code == 500
    finally:
        patcher.stop()


@pytest.mark.asyncio()
async def test_stream_unknown_status_raises_unknown(client):
    """其余 HTTP 状态码（如 404）应映射为 UNKNOWN，与非流式路径一致。"""
    # Arrange
    patcher = _patch_stream(client, response=_status_response(404))

    try:
        # Act / Assert
        with pytest.raises(LLMError) as exc_info:
            await _consume(client.chat_stream(_MESSAGES))
        assert exc_info.value.type == LLMErrorType.UNKNOWN
        assert exc_info.value.status_code == 404
    finally:
        patcher.stop()


@pytest.mark.asyncio()
async def test_stream_decoding_failure_raises_parsing(client):
    """流体解码抛出 ValueError 时应映射为 PARSING。"""

    # Arrange
    response = AsyncMock()
    response.status_code = 200
    response.raise_for_status = Mock()

    async def aiter_lines():
        yield 'data: {"choices": [{"delta": {"content": "ok"}}]}'
        raise ValueError("stream body decode failed")

    response.aiter_lines = aiter_lines
    patcher = _patch_stream(client, response=response)

    try:
        # Act / Assert
        with pytest.raises(LLMError) as exc_info:
            await _consume(client.chat_stream(_MESSAGES))
        assert exc_info.value.type == LLMErrorType.PARSING
    finally:
        patcher.stop()


@pytest.mark.asyncio()
async def test_stream_success_yields_content_chunks(client):
    """正常流应逐 chunk yield 内容（yield 契约不受错误分类重构影响）。"""
    # Arrange
    lines = [
        'data: {"choices": [{"delta": {"content": "Hello"}}]}',
        "not-a-data-line",  # 非 data: 前缀行应被跳过
        "data: {malformed json",  # 坏 JSON 行应被容忍跳过
        'data: {"choices": [{"delta": {"content": " world"}}]}',
        "data: [DONE]",
    ]
    patcher = _patch_stream(client, response=_ok_response(lines))

    try:
        # Act
        chunks = await _consume(client.chat_stream(_MESSAGES))

        # Assert
        assert chunks == ["Hello", " world"]
    finally:
        patcher.stop()
