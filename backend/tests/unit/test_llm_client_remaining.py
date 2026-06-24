"""
LLMClient 未覆盖路径（使用 P0 共享 fixture + 直接 patch 补全）。

PG1.3 目标：把 core/llm_client.py 覆盖率从 67% 推到 ≥ 90%。
本文件覆盖：
    - P0 共享 fixture 的 happy path / rate_limit / server_error / timeout
    - _get_client 初始化（Authorization header、extra_headers、复用）
    - close() 生命周期
    - _convert_messages 透传 tool_calls / tool_call_id
    - _parse_tool_calls 各种 default 字段
    - provider=claude 分支
    - 429 时 retry-after 解析失败分支
    - 4xx（除 401/429）→ UNKNOWN 映射
    - chat 响应含 tool_calls 的解析路径
    - chat_stream 主路径（普通 chunk + [DONE]）+ HTTPStatusError / 通用异常
    - complete() 简单补全
    - to_dict() 配置导出
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from backend.core.errors import LLMError, LLMErrorType
from backend.core.legacy.llm_client import LLMClient, LLMConfig

pytestmark = pytest.mark.unit


def _make_config(**overrides) -> LLMConfig:
    """构造测试用 LLMConfig（与 P0 mock fixture 的 base_url 对齐）。

    v2: 默认 ``use_proxy=False``,让 LLMClient 直连上游,respx 直接拦截上游调用。
    这样 fixture 不需要知道 proxy URL 是什么,保持简洁。proxy 行为有单独测试覆盖。

    base_url 不带 ``/v1`` 是因为 v2 改造后 LLMClient 路径已变为
    ``/v1/chat/completions``(因为它现在默认走 proxy,在 proxy URL 上拼这个路径;
    use_proxy=False 模式下路径仍是 ``/v1/chat/completions``)。
    """
    defaults = {
        "provider": "openai",
        "api_key": "test-key",
        "base_url": "https://api.example.com",
        "model": "gpt-3.5-turbo",
        "use_proxy": False,
    }
    defaults.update(overrides)
    return LLMConfig(**defaults)


# ============================================================================
# P0 共享 fixture 路径
# ============================================================================


@pytest.mark.asyncio()
async def test_chat_normal_response_via_fixture(mock_llm_ok):
    """mock_llm_ok → 正常 chat 返回 LLMResponse, content='Hello from mock!'."""
    client = LLMClient(_make_config())
    response = await client.chat([{"role": "user", "content": "hi"}])
    assert response.content == "Hello from mock!"
    assert response.model == "test-model"
    assert response.finish_reason == "stop"
    assert response.input_tokens == 10
    assert response.output_tokens == 5
    assert response.total_tokens == 15


@pytest.mark.asyncio()
async def test_chat_rate_limit_via_fixture(mock_llm_rate_limit):
    """mock_llm_rate_limit → LLMError(RATE_LIMITED), 无 retry-after header → retry_after=None."""
    client = LLMClient(_make_config())
    with pytest.raises(LLMError) as exc_info:
        await client.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.type == LLMErrorType.RATE_LIMITED
    assert exc_info.value.retry_after is None


@pytest.mark.asyncio()
async def test_chat_server_error_via_fixture(mock_llm_server_error):
    """mock_llm_server_error → LLMError(SERVER_ERROR, status_code=500)."""
    client = LLMClient(_make_config())
    with pytest.raises(LLMError) as exc_info:
        await client.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.type == LLMErrorType.SERVER_ERROR
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio()
async def test_chat_timeout_fixture_maps_to_timeout(mock_llm_timeout):
    """mock_llm_timeout 抛 httpx.TimeoutException，命中 LLMClient 中
    ``except httpx.TimeoutException`` 分支，映射为 LLMErrorType.TIMEOUT。

    本测试同时是 mock_llm_timeout fixture 的回归门禁：
    若有人把 fixture 的 side_effect 改回 builtin TimeoutError，
    此断言会立刻失败（实际类型会 fallback 到 UNKNOWN）。
    """
    client = LLMClient(_make_config())
    with pytest.raises(LLMError) as exc_info:
        await client.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.type == LLMErrorType.TIMEOUT


# ============================================================================
# _get_client 初始化
# ============================================================================


def test_get_client_initializes_with_authorization_header():
    """首次调用 _get_client 创建 httpx.AsyncClient, 含 Authorization Bearer header."""
    client = LLMClient(_make_config(api_key="sk-abc"))
    http = client._get_client()
    assert isinstance(http, httpx.AsyncClient)
    assert http.headers["Authorization"] == "Bearer sk-abc"
    assert http.headers["Content-Type"] == "application/json"


def test_get_client_omits_authorization_when_no_api_key():
    """api_key 为空时, 不设置 Authorization header."""
    client = LLMClient(_make_config(api_key=""))
    http = client._get_client()
    assert "Authorization" not in http.headers


def test_get_client_merges_extra_headers():
    """LLMConfig.extra_headers 被合并到请求 header 中."""
    client = LLMClient(_make_config(extra_headers={"X-Custom": "value", "X-Trace": "abc"}))
    http = client._get_client()
    assert http.headers["X-Custom"] == "value"
    assert http.headers["X-Trace"] == "abc"


def test_get_client_reuses_existing_instance():
    """第二次调用 _get_client 复用之前的 client, 不重建."""
    client = LLMClient(_make_config())
    first = client._get_client()
    second = client._get_client()
    assert first is second


def test_get_client_recreates_after_close():
    """client 已关闭后, 重新调用 _get_client 会创建新 client."""
    client = LLMClient(_make_config())
    first = client._get_client()
    # httpx.AsyncClient.is_closed 是只读 property, 用 patch.object 替换
    with patch.object(type(first), "is_closed", new_callable=Mock, return_value=True):
        second = client._get_client()
    assert first is not second


# ============================================================================
# close() 生命周期
# ============================================================================


@pytest.mark.asyncio()
async def test_close_when_client_never_initialized_is_noop():
    """未调用过 _get_client 时, close() 是 no-op, 不抛错."""
    client = LLMClient(_make_config())
    assert client._client is None
    await client.close()
    assert client._client is None


@pytest.mark.asyncio()
async def test_close_calls_aclose_on_initialized_client():
    """初始化过的 client, close() 触发 _client.aclose()."""
    client = LLMClient(_make_config())
    http = client._get_client()
    aclose_mock = AsyncMock()
    http.aclose = aclose_mock  # type: ignore[attr-defined]
    await client.close()
    aclose_mock.assert_awaited_once()


@pytest.mark.asyncio()
async def test_close_skips_already_closed_client():
    """client 已关闭时, close() 不会重复调用 aclose()."""
    client = LLMClient(_make_config())
    http = client._get_client()
    aclose_mock = AsyncMock()
    http.aclose = aclose_mock  # type: ignore[attr-defined]
    # is_closed 是 httpx 只读 property, 通过 patch 替换为 True
    with patch.object(type(http), "is_closed", new_callable=Mock, return_value=True):
        await client.close()
    aclose_mock.assert_not_called()


# ============================================================================
# _convert_messages 静态方法
# ============================================================================


def test_convert_messages_basic_passthrough():
    """普通消息只保留 role 和 content."""
    out = LLMClient._convert_messages(
        [
            {"role": "system", "content": "you are helpful"},
            {"role": "user", "content": "hi"},
        ]
    )
    assert out == [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "hi"},
    ]


def test_convert_messages_preserves_tool_calls():
    """包含 tool_calls 字段的消息应透传 tool_calls 列表."""
    raw = [{"role": "assistant", "content": "", "tool_calls": [{"id": "1", "type": "function"}]}]
    out = LLMClient._convert_messages(raw)
    assert out[0]["tool_calls"] == [{"id": "1", "type": "function"}]
    assert out[0]["content"] == ""


def test_convert_messages_preserves_tool_call_id():
    """tool 角色的消息应透传 tool_call_id."""
    raw = [{"role": "tool", "content": "42", "tool_call_id": "call-xyz"}]
    out = LLMClient._convert_messages(raw)
    assert out[0]["tool_call_id"] == "call-xyz"
    assert out[0]["role"] == "tool"


# ============================================================================
# _parse_tool_calls 静态方法
# ============================================================================


def test_parse_tool_calls_full_fields():
    """完整字段的工具调用 → 正确构造 LLMToolCall."""
    raw = [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "calculator", "arguments": '{"x": 1}'},
        }
    ]
    out = LLMClient._parse_tool_calls(raw)
    assert len(out) == 1
    assert out[0].id == "call-1"
    assert out[0].name == "calculator"
    assert out[0].arguments == '{"x": 1}'


def test_parse_tool_calls_missing_arguments_defaults_to_empty_object():
    """arguments 缺省时默认 '{}'."""
    raw = [{"id": "x", "function": {"name": "fn"}}]
    out = LLMClient._parse_tool_calls(raw)
    assert out[0].arguments == "{}"
    assert out[0].name == "fn"


def test_parse_tool_calls_missing_id_defaults_to_empty_string():
    """id 缺省时默认空字符串."""
    raw = [{"function": {"name": "fn", "arguments": "{}"}}]
    out = LLMClient._parse_tool_calls(raw)
    assert out[0].id == ""
    assert out[0].name == "fn"


def test_parse_tool_calls_empty_input_returns_empty_list():
    """空输入返回空列表."""
    assert LLMClient._parse_tool_calls([]) == []


# ============================================================================
# provider=claude 分支
# ============================================================================


@pytest.mark.asyncio()
async def test_chat_with_claude_provider_keeps_max_tokens(mock_llm_ok):
    """provider=claude 时, 请求仍能成功（line 166 走 max_tokens 保持分支）."""
    client = LLMClient(_make_config(provider="claude"))
    response = await client.chat([{"role": "user", "content": "hi"}])
    assert response.content == "Hello from mock!"


# ============================================================================
# 错误分类边界分支
# ============================================================================


@pytest.mark.asyncio()
async def test_rate_limit_with_invalid_retry_after_header_falls_back_to_none():
    """429 且 retry-after header 不是合法整数 → retry_after=None（不抛错）."""
    client = LLMClient(_make_config())
    mock_response = AsyncMock()
    mock_response.status_code = 429
    mock_response.text = "Too Many Requests"
    mock_response.headers = {"retry-after": "not-a-number"}
    mock_response.raise_for_status = Mock(
        side_effect=httpx.HTTPStatusError("429", request=AsyncMock(), response=mock_response)
    )
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http
        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.type == LLMErrorType.RATE_LIMITED
    assert exc_info.value.retry_after is None


@pytest.mark.asyncio()
async def test_unknown_http_error_status_maps_to_unknown():
    """4xx 中除 401/429 之外的状态码（如 418）→ LLMError(UNKNOWN, status_code=418)."""
    client = LLMClient(_make_config())
    mock_response = AsyncMock()
    mock_response.status_code = 418
    mock_response.text = "I'm a teapot"
    mock_response.raise_for_status = Mock(
        side_effect=httpx.HTTPStatusError("418", request=AsyncMock(), response=mock_response)
    )
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http
        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.type == LLMErrorType.UNKNOWN
    assert exc_info.value.status_code == 418


@pytest.mark.asyncio()
async def test_unexpected_exception_maps_to_unknown():
    """非 httpx / ValueError / KeyError 的异常 → LLMError(UNKNOWN)."""
    client = LLMClient(_make_config())
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        # 抛一个 httpx 未识别的异常
        mock_http.post = AsyncMock(side_effect=RuntimeError("boom"))
        mock_get_client.return_value = mock_http
        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.type == LLMErrorType.UNKNOWN


# ============================================================================
# chat 响应含 tool_calls 解析
# ============================================================================


@pytest.mark.asyncio()
async def test_chat_response_with_tool_calls_parses_them():
    """响应 message 含 tool_calls 时, LLMResponse.tool_calls 正确填充."""
    client = LLMClient(_make_config())
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = lambda: None
    mock_response.json = lambda: {
        "id": "x",
        "model": "gpt-4",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "search", "arguments": '{"q":"weather"}'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http
        response = await client.chat([{"role": "user", "content": "weather?"}])
    assert response.content is None
    assert response.finish_reason == "tool_calls"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "search"
    assert response.tool_calls[0].arguments == '{"q":"weather"}'


# ============================================================================
# chat_stream
# ============================================================================


async def _async_iter(items):
    """把列表转为 async iterator, 供 mock.aiter_lines 使用."""
    for item in items:
        yield item


async def _drain_stream(agen):
    """完整消费 async generator, 触发内部 yield 与异常路径."""
    async for _ in agen:
        pass


@pytest.mark.asyncio()
async def test_chat_stream_yields_content_chunks():
    """chat_stream 正常路径: 解析 SSE chunk, 拼接 content 字段, 遇 [DONE] 终止."""
    client = LLMClient(_make_config())
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = lambda: None
    mock_response.aiter_lines = lambda: _async_iter(
        [
            'data: {"choices": [{"delta": {"content": "Hello"}}]}',
            'data: {"choices": [{"delta": {"content": " world"}}]}',
            "data: [DONE]",
        ]
    )

    mock_http = AsyncMock()

    @asynccontextmanager
    async def _stream_ctx(*_args, **_kwargs):
        yield mock_response

    mock_http.stream = _stream_ctx

    with patch.object(client, "_get_client", return_value=mock_http):
        chunks = []
        async for c in client.chat_stream([{"role": "user", "content": "hi"}]):
            chunks.append(c)
        assert chunks == ["Hello", " world"]


@pytest.mark.asyncio()
async def test_chat_stream_skips_non_data_lines():
    """chat_stream 忽略不以 'data: ' 开头的行（如 SSE 注释、空行）."""
    client = LLMClient(_make_config())
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = lambda: None
    mock_response.aiter_lines = lambda: _async_iter(
        [
            ": keep-alive",
            "",
            'data: {"choices": [{"delta": {"content": "ok"}}]}',
            "data: [DONE]",
        ]
    )

    mock_http = AsyncMock()

    @asynccontextmanager
    async def _stream_ctx(*_args, **_kwargs):
        yield mock_response

    mock_http.stream = _stream_ctx

    with patch.object(client, "_get_client", return_value=mock_http):
        chunks = []
        async for c in client.chat_stream([{"role": "user", "content": "hi"}]):
            chunks.append(c)
        assert chunks == ["ok"]


@pytest.mark.asyncio()
async def test_chat_stream_skips_invalid_json_lines():
    """chat_stream 跳过 JSON 解析失败的 data 行, 继续读后续 chunk."""
    client = LLMClient(_make_config())
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = lambda: None
    mock_response.aiter_lines = lambda: _async_iter(
        [
            "data: not-json-at-all",
            'data: {"choices": [{"delta": {"content": "valid"}}]}',
            "data: [DONE]",
        ]
    )

    mock_http = AsyncMock()

    @asynccontextmanager
    async def _stream_ctx(*_args, **_kwargs):
        yield mock_response

    mock_http.stream = _stream_ctx

    with patch.object(client, "_get_client", return_value=mock_http):
        chunks = []
        async for c in client.chat_stream([{"role": "user", "content": "hi"}]):
            chunks.append(c)
        assert chunks == ["valid"]


@pytest.mark.asyncio()
async def test_chat_stream_http_error_raises_runtime_error():
    """chat_stream HTTP 错误时抛 RuntimeError（保留旧行为, Task 11 将统一为 LLMError）."""
    client = LLMClient(_make_config())
    mock_http = AsyncMock()

    @asynccontextmanager
    async def _stream_ctx(*_args, **_kwargs):
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "500", request=AsyncMock(), response=AsyncMock(status_code=500)
            )
        )
        yield mock_response

    mock_http.stream = _stream_ctx

    with (
        patch.object(client, "_get_client", return_value=mock_http),
        pytest.raises(RuntimeError) as exc_info,
    ):
        await _drain_stream(client.chat_stream([{"role": "user", "content": "hi"}]))
    assert "500" in str(exc_info.value)


@pytest.mark.asyncio()
async def test_chat_stream_other_exception_raises_runtime_error():
    """chat_stream 其他异常时也抛 RuntimeError."""
    client = LLMClient(_make_config())
    mock_http = AsyncMock()

    @asynccontextmanager
    async def _stream_ctx(*_args, **_kwargs):
        raise RuntimeError("stream failed")
        yield  # pragma: no cover  # unreachable, just for type checker

    mock_http.stream = _stream_ctx

    with (
        patch.object(client, "_get_client", return_value=mock_http),
        pytest.raises(RuntimeError),
    ):
        await _drain_stream(client.chat_stream([{"role": "user", "content": "hi"}]))


# ============================================================================
# complete() 简单补全
# ============================================================================


@pytest.mark.asyncio()
async def test_complete_returns_response_content(mock_llm_ok):
    """complete() 把 prompt 包装为单条 user 消息, 返回 chat 响应 content."""
    client = LLMClient(_make_config())
    content = await client.complete("hello")
    assert content == "Hello from mock!"


# ============================================================================
# to_dict() 配置导出
# ============================================================================


def test_to_dict_exports_config_subset():
    """to_dict 只导出关键配置项, 不含 api_key 等敏感字段."""
    config = _make_config(
        provider="openai",
        model="gpt-4o-mini",
        temperature=0.3,
        max_tokens=2048,
        base_url="https://api.example.com/v1",
    )
    client = LLMClient(config)
    d = client.to_dict()
    assert d == {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "base_url": "https://api.example.com/v1",
        "temperature": 0.3,
        "max_tokens": 2048,
    }


# ============================================================================
# v2: LLM proxy 行为
# ============================================================================


@pytest.mark.asyncio()
async def test_proxy_default_routes_through_backend():
    """v2: 默认 ``use_proxy=True`` 时,_get_client 把请求发到本机 backend proxy,
    并把 base_url(用户填的真实上游)放在 ``X-LLM-Provider-Url`` header。
    """
    config = LLMConfig(
        base_url="https://api.minimaxi.com/",
        api_key="sk-test",
        model="minimax-m3",
        # 不传 use_proxy → 默认 True
    )
    captured: dict = {}

    def fake_init(self, *args, **kwargs):
        """拦截 httpx.AsyncClient.__init__ 抓取 base_url 和 headers。"""
        captured["base_url"] = kwargs.get("base_url") or (
            args[0] if args else None
        )
        captured["init_headers"] = dict(kwargs.get("headers", {}))

        # 阻止真实网络:抛错让测试快速失败(下面还会再 patch post)
        raise RuntimeError("STOP_AT_INIT")

    from unittest.mock import patch

    with patch.object(httpx.AsyncClient, "__init__", new=fake_init):
        client = LLMClient(config)
        with pytest.raises(RuntimeError, match="STOP_AT_INIT"):
            await client.chat([{"role": "user", "content": "hi"}])

    # httpx base_url 指向本机 proxy
    assert captured["base_url"] == "http://127.0.0.1:8765/api/v1/llm"
    # 真实上游 URL 应在 X-LLM-Provider-Url header
    assert captured["init_headers"]["X-LLM-Provider-Url"] == "https://api.minimaxi.com/"
    # 鉴权仍透传
    assert captured["init_headers"]["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio()
async def test_use_proxy_false_bypasses_proxy():
    """v2: ``use_proxy=False`` 时,LLMClient 直连 base_url(单测场景),不走 proxy,
    也不发 X-LLM-Provider-Url header。"""
    import os

    os.environ.pop("BACKEND_URL", None)
    config = LLMConfig(
        base_url="https://api.example.com/",
        api_key="test-key",
        use_proxy=False,
    )
    captured: dict = {}

    def fake_init(self, *args, **kwargs):
        captured["base_url"] = kwargs.get("base_url") or (
            args[0] if args else None
        )
        captured["init_headers"] = dict(kwargs.get("headers", {}))
        raise RuntimeError("STOP_AT_INIT")

    from unittest.mock import patch

    with patch.object(httpx.AsyncClient, "__init__", new=fake_init):
        client = LLMClient(config)
        with pytest.raises(RuntimeError, match="STOP_AT_INIT"):
            await client.chat([{"role": "user", "content": "hi"}])

    # 直连上游,base_url 应该是用户填的真实 URL
    assert captured["base_url"] == "https://api.example.com/"
    # 不应发 X-LLM-Provider-Url(因为没走 proxy)
    assert "X-LLM-Provider-Url" not in captured["init_headers"]
    # 鉴权仍透传
    assert captured["init_headers"]["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio()
async def test_backend_url_from_env():
    """v2: backend_url 默认从 ``BACKEND_URL`` 环境变量读取。"""
    import os

    os.environ["BACKEND_URL"] = "http://192.168.1.10:9999"
    try:
        config = LLMConfig(base_url="https://api.example.com/")
        assert config.backend_url == "http://192.168.1.10:9999"
    finally:
        del os.environ["BACKEND_URL"]


def test_use_proxy_default_true():
    """v2: use_proxy 默认 True(LLMClient 走 proxy 是默认行为)。"""
    config = LLMConfig()
    assert config.use_proxy is True
