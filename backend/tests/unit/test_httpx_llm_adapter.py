"""``HttpxLLMAdapter`` 单元测试。

覆盖：

1. 构造器：``**kwargs`` 透传到 ``LLMConfig``，并构造 ``_LLMClient``。
2. ``_from_domain_message`` 四个分支：基本、带 ``tool_calls``、带 ``tool_call_id``、空 ``tool_calls``。
3. ``_to_domain_message`` 三个分支：基本、带 ``tool_calls``（arguments JSON 反序列化）、arguments 非法 JSON 降级。
4. ``chat`` 委派：把 ``domain.Message`` → dict 后传给 ``LLMClient.chat``，并把 ``LLMResponse`` 转回 ``domain.Message``。
5. ``chat`` 委派透传 ``tools``。
6. ``chat`` 委派对 ``dict`` 形式 ``tool_choice`` 安全降级为 ``None``。
7. ``chat_stream`` 委派：底层 async generator 透传。
8. ``aclose`` 委派。
9. Protocol 一致性：``HttpxLLMAdapter`` 满足 ``LLMPort`` 结构性子类型。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.adapters.out.llm.httpx_adapter import HttpxLLMAdapter
from backend.core.llm_client import LLMConfig, LLMResponse, LLMToolCall
from backend.domain.message import Message, Role, ToolCall
from backend.ports.llm import LLMPort

pytestmark = pytest.mark.unit


# ============================================================================
# 构造器
# ============================================================================


def test_constructor_passes_kwargs_to_llmconfig():
    """``**kwargs`` 透传到 ``LLMConfig`` 并构造底层 ``LLMClient``。"""
    with patch("backend.adapters.out.llm.httpx_adapter._LLMClient") as MockClient:
        MockClient.return_value = MagicMock()
        adapter = HttpxLLMAdapter(
            provider="openai",
            api_key="sk-test",
            base_url="https://api.example.com/v1",
            model="gpt-4o-mini",
            temperature=0.2,
        )
    # LLMConfig 正确接收
    MockClient.assert_called_once()
    config_arg = MockClient.call_args.args[0]
    assert isinstance(config_arg, LLMConfig)
    assert config_arg.provider == "openai"
    assert config_arg.api_key == "sk-test"
    assert config_arg.base_url == "https://api.example.com/v1"
    assert config_arg.model == "gpt-4o-mini"
    assert config_arg.temperature == 0.2
    # adapter 持有 _client
    assert adapter._client is MockClient.return_value


def test_constructor_uses_llmconfig_defaults_when_kwargs_minimal():
    """只提供 base_url 时, 其他字段取 ``LLMConfig`` 默认值。"""
    with patch("backend.adapters.out.llm.httpx_adapter._LLMClient") as MockClient:
        MockClient.return_value = MagicMock()
        HttpxLLMAdapter(base_url="https://api.example.com/v1")
    config = MockClient.call_args.args[0]
    assert config.provider == "openai"  # LLMConfig 默认
    assert config.model == "gpt-3.5-turbo"  # LLMConfig 默认
    assert config.api_key == ""


# ============================================================================
# domain → dict 转换
# ============================================================================


def test_from_domain_basic_message():
    """基本消息：只含 role + content → dict 只含 role/content。"""
    msg = Message(role=Role.USER, content="hello")
    result = HttpxLLMAdapter.from_domain(msg)
    assert result == {"role": "user", "content": "hello"}


def test_from_domain_message_with_tool_calls_serializes_args_as_json():
    """带 tool_calls 时, args 序列化为 JSON 字符串并按 OpenAI 格式输出。"""
    msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(name="calculator", args={"x": 1, "y": 2}, id="call-1")],
    )
    result = HttpxLLMAdapter.from_domain(msg)
    assert result["role"] == "assistant"
    assert result["content"] == ""
    assert result["tool_calls"] == [
        {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "calculator",
                "arguments": '{"x": 1, "y": 2}',
            },
        }
    ]


def test_from_domain_message_with_tool_call_id_includes_key():
    """``tool_call_id`` 不为空时, dict 中包含该字段。"""
    msg = Message(role=Role.TOOL, content="42", tool_call_id="call-xyz")
    result = HttpxLLMAdapter.from_domain(msg)
    assert result["role"] == "tool"
    assert result["content"] == "42"
    assert result["tool_call_id"] == "call-xyz"
    # tool_calls 默认空列表, 不应出现该 key（_from_domain_message 内部判断 if msg.tool_calls）
    # 注意：当前实现是只在 tool_calls 非空时才写入；tool_call_id 消息通常也不带 tool_calls。
    assert "tool_calls" not in result


def test_from_domain_empty_tool_calls_omits_key():
    """``tool_calls`` 为空列表时, dict 中不写入该 key。"""
    msg = Message(role=Role.USER, content="hi", tool_calls=[])
    result = HttpxLLMAdapter.from_domain(msg)
    assert "tool_calls" not in result


def test_from_domain_tool_call_with_no_id_defaults_to_empty_string():
    """ToolCall.id 为 None 时, dict 中 id 默认空字符串。"""
    msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(name="noop", args={})],  # id 缺省为 None
    )
    result = HttpxLLMAdapter.from_domain(msg)
    assert result["tool_calls"][0]["id"] == ""
    assert result["tool_calls"][0]["function"]["name"] == "noop"
    assert result["tool_calls"][0]["function"]["arguments"] == "{}"


# ============================================================================
# LLMResponse → domain.Message 转换
# ============================================================================


def test_to_domain_basic_response():
    """基本 LLMResponse → domain.Message(role=ASSISTANT, content=...)。"""
    raw = LLMResponse(content="Hello from mock!", model="test-model")
    msg = HttpxLLMAdapter.to_domain(raw)
    assert msg.role == Role.ASSISTANT
    assert msg.content == "Hello from mock!"
    assert msg.tool_calls == []


def test_to_domain_response_with_tool_calls_parses_arguments_json():
    """``LLMToolCall.arguments``（JSON 字符串）→ ``ToolCall.args``（dict）。"""
    raw = LLMResponse(
        content=None,
        tool_calls=[
            LLMToolCall(
                id="call-1",
                name="search",
                arguments='{"q": "weather"}',
            )
        ],
    )
    msg = HttpxLLMAdapter.to_domain(raw)
    assert msg.role == Role.ASSISTANT
    assert msg.content == ""  # None → ""
    assert len(msg.tool_calls) == 1
    tc = msg.tool_calls[0]
    assert tc.name == "search"
    assert tc.args == {"q": "weather"}
    assert tc.id == "call-1"


def test_to_domain_tool_call_with_invalid_json_arguments_falls_back_to_empty_dict():
    """arguments 不是合法 JSON 时, 降级为 ``{}`` 而不抛错。"""
    raw = LLMResponse(
        content="",
        tool_calls=[LLMToolCall(id="x", name="fn", arguments="not-json-at-all")],
    )
    msg = HttpxLLMAdapter.to_domain(raw)
    assert msg.tool_calls[0].args == {}


def test_to_domain_tool_call_with_empty_arguments_defaults_to_empty_dict():
    """arguments 为空字符串时, 解析结果为 ``{}``。"""
    raw = LLMResponse(
        content="",
        tool_calls=[LLMToolCall(id="x", name="fn", arguments="")],
    )
    msg = HttpxLLMAdapter.to_domain(raw)
    assert msg.tool_calls[0].args == {}


def test_to_domain_tool_call_with_no_id_keeps_id_as_none():
    """LLMToolCall.id 为空字符串时, domain ToolCall.id 设为 None（避免空串泄漏到上层）。"""
    raw = LLMResponse(
        content="",
        tool_calls=[LLMToolCall(id="", name="fn", arguments="{}")],
    )
    msg = HttpxLLMAdapter.to_domain(raw)
    assert msg.tool_calls[0].id is None


# ============================================================================
# chat() 委派
# ============================================================================


def _build_adapter_with_mocked_client() -> tuple[HttpxLLMAdapter, AsyncMock]:
    """构造 adapter + 返回底层 chat AsyncMock, 便于委派断言。"""
    with patch("backend.adapters.out.llm.httpx_adapter._LLMClient") as MockClient:
        MockClient.return_value = MagicMock()
        adapter = HttpxLLMAdapter(
            base_url="https://api.example.com/v1",
            api_key="test",
        )
    chat_mock = AsyncMock(return_value=LLMResponse(content="hi back", model="m"))
    adapter._client.chat = chat_mock  # type: ignore[method-assign]
    return adapter, chat_mock


@pytest.mark.asyncio()
async def test_chat_delegates_to_llmclient_with_dict_messages():
    """``chat`` 把 domain 消息转为 dict 后传给 ``LLMClient.chat``。"""
    adapter, chat_mock = _build_adapter_with_mocked_client()
    msgs = [
        Message(role=Role.SYSTEM, content="You are helpful"),
        Message(role=Role.USER, content="hi"),
    ]
    reply = await adapter.chat(msgs)
    chat_mock.assert_awaited_once()
    # 第一个位置参数是 messages 列表
    sent = chat_mock.call_args.args[0]
    assert sent == [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "hi"},
    ]
    # 返回值转为 domain.Message
    assert reply.role == Role.ASSISTANT
    assert reply.content == "hi back"


@pytest.mark.asyncio()
async def test_chat_passes_tools_through_to_llmclient():
    """``tools`` 参数透传到 LLMClient.chat。"""
    adapter, chat_mock = _build_adapter_with_mocked_client()
    tools = [{"type": "function", "function": {"name": "fn"}}]
    await adapter.chat(
        [Message(role=Role.USER, content="x")],
        tools=tools,
    )
    assert chat_mock.call_args.kwargs["tools"] == tools


@pytest.mark.asyncio()
async def test_chat_passes_string_tool_choice_through_to_llmclient():
    """``tool_choice`` 为 str 时, 透传。"""
    adapter, chat_mock = _build_adapter_with_mocked_client()
    await adapter.chat(
        [Message(role=Role.USER, content="x")],
        tools=[{"type": "function", "function": {"name": "fn"}}],
        tool_choice="required",
    )
    assert chat_mock.call_args.kwargs["tool_choice"] == "required"


@pytest.mark.asyncio()
async def test_chat_dict_tool_choice_safely_falls_back_to_none():
    """``tool_choice`` 为 dict 时, 降级为 ``None``（LLMClient 暂不识 dict 形式）。"""
    adapter, chat_mock = _build_adapter_with_mocked_client()
    await adapter.chat(
        [Message(role=Role.USER, content="x")],
        tools=[{"type": "function", "function": {"name": "fn"}}],
        tool_choice={"name": "fn"},
    )
    # dict → None（避免传 dict 给 LLMClient 触发 type error）
    assert chat_mock.call_args.kwargs["tool_choice"] is None


@pytest.mark.asyncio()
async def test_chat_converts_response_with_tool_calls_to_domain():
    """``chat`` 端到端：LLMResponse 含 tool_calls → domain.Message 含 ToolCall 列表。"""
    adapter, _ = _build_adapter_with_mocked_client()
    adapter._client.chat = AsyncMock(  # type: ignore[method-assign]
        return_value=LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(id="c-1", name="calc", arguments='{"x": 1}'),
            ],
        )
    )
    reply = await adapter.chat([Message(role=Role.USER, content="2+2")])
    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0].name == "calc"
    assert reply.tool_calls[0].args == {"x": 1}


@pytest.mark.asyncio()
async def test_chat_via_real_mock_fixture_returns_domain_message(mock_llm_ok):
    """端到端：使用 P0 的 ``mock_llm_ok`` 走完真实 HTTP mock 路径, 拿到 ``domain.Message``。"""
    adapter = HttpxLLMAdapter(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        model="gpt-3.5-turbo",
    )
    reply = await adapter.chat([Message(role=Role.USER, content="hi")])
    assert reply.role == Role.ASSISTANT
    assert reply.content == "Hello from mock!"
    assert reply.tool_calls == []
    await adapter.aclose()


# ============================================================================
# chat_stream() 委派
# ============================================================================


@pytest.mark.asyncio()
async def test_chat_stream_yields_chunks_from_underlying_client():
    """``chat_stream`` 透传底层 async generator 的 chunk。"""
    adapter = HttpxLLMAdapter(
        base_url="https://api.example.com/v1",
        api_key="test-key",
    )

    async def fake_stream(_messages):
        yield "Hello"
        yield " "
        yield "world"

    adapter._client.chat_stream = fake_stream  # type: ignore[method-assign]

    msgs = [Message(role=Role.USER, content="hi")]
    chunks: list[str] = []
    async for c in adapter.chat_stream(msgs):
        chunks.append(c)
    assert chunks == ["Hello", " ", "world"]


@pytest.mark.asyncio()
async def test_chat_stream_converts_domain_messages_to_dicts():
    """``chat_stream`` 把 domain 消息转为 dict 再传给 LLMClient。"""
    adapter = HttpxLLMAdapter(
        base_url="https://api.example.com/v1",
        api_key="test-key",
    )

    received: list[list[dict]] = []

    async def fake_stream(messages):
        received.append(messages)
        if False:  # pragma: no cover  -- 防止被识别为普通函数
            yield ""

    adapter._client.chat_stream = fake_stream  # type: ignore[method-assign]

    msgs = [
        Message(role=Role.SYSTEM, content="sys"),
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[ToolCall(name="t", args={"k": "v"}, id="id-1")],
        ),
    ]
    async for _ in adapter.chat_stream(msgs):
        pass
    assert received
    assert received[0] == [
        {"role": "system", "content": "sys"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "id-1",
                    "type": "function",
                    "function": {"name": "t", "arguments": '{"k": "v"}'},
                }
            ],
        },
    ]


@pytest.mark.asyncio()
async def test_chat_stream_via_real_mock_fixture_yields_chunks():
    """端到端：用 P0 mock fixture + httpx ``stream`` mock 走完 stream 路径。"""
    adapter = HttpxLLMAdapter(
        base_url="https://api.example.com/v1",
        api_key="test-key",
    )

    async def _async_iter(items):
        for item in items:
            yield item

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

    with patch.object(adapter._client, "_get_client", return_value=mock_http):
        chunks: list[str] = []
        async for c in adapter.chat_stream([Message(role=Role.USER, content="hi")]):
            chunks.append(c)
        assert chunks == ["Hello", " world"]

    await adapter.aclose()


# ============================================================================
# aclose 委派
# ============================================================================


@pytest.mark.asyncio()
async def test_aclose_delegates_to_underlying_llmclient():
    """``aclose`` 调用 ``LLMClient.close``。"""
    adapter = HttpxLLMAdapter(
        base_url="https://api.example.com/v1",
        api_key="test-key",
    )
    adapter._client.close = AsyncMock()  # type: ignore[method-assign]
    await adapter.aclose()
    adapter._client.close.assert_awaited_once()  # type: ignore[attr-defined]


# ============================================================================
# Protocol 一致性
# ============================================================================


def test_adapter_exposes_chat_and_chat_stream_methods():
    """``HttpxLLMAdapter`` 实例暴露 ``chat`` 和 ``chat_stream`` 两个方法。"""
    with patch("backend.adapters.out.llm.httpx_adapter._LLMClient") as MockClient:
        MockClient.return_value = MagicMock()
        adapter = HttpxLLMAdapter(
            base_url="https://api.example.com/v1",
            api_key="test",
        )
    assert hasattr(adapter, "chat")
    assert hasattr(adapter, "chat_stream")
    assert callable(adapter.chat)
    assert callable(adapter.chat_stream)


def test_protocol_is_importable_and_has_expected_methods():
    """``LLMPort`` 暴露 ``chat`` 和 ``chat_stream``（防御性检查）。"""
    assert hasattr(LLMPort, "chat")
    assert hasattr(LLMPort, "chat_stream")
