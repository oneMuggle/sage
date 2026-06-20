"""验证 ``MockLLMAdapter`` 行为。

覆盖：

1. 默认响应（无预置 responses）。
2. 预置 responses 按顺序消费，耗尽后回退默认。
3. 每次调用被记录到 ``calls``。
4. ``chat_stream`` 逐字符 yield。
5. ``assert_called_with`` 通过与失败路径。
6. ``reset`` 清空状态。
7. ``LLMPort`` 协议结构一致性。
"""

from __future__ import annotations

import pytest

from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
from sage_core import Message, Role, ToolCall
from sage_core.repositories import LLMPort

pytestmark = pytest.mark.unit


# ============================================================================
# chat() 行为
# ============================================================================


async def test_default_response():
    """无预置 responses 时返回默认 ASSISTANT 消息。"""
    adapter = MockLLMAdapter()
    result = await adapter.chat([Message(role=Role.USER, content="hi")])
    assert result.role == Role.ASSISTANT
    assert result.content == "[mock default]"


async def test_presed_responses_returned_in_order():
    """预置 responses 按顺序返回；耗尽后回退到默认。"""
    adapter = MockLLMAdapter(
        responses=[
            Message(role=Role.ASSISTANT, content="first"),
            Message(role=Role.ASSISTANT, content="second"),
        ]
    )
    r1 = await adapter.chat([Message(role=Role.USER, content="a")])
    r2 = await adapter.chat([Message(role=Role.USER, content="b")])
    r3 = await adapter.chat([Message(role=Role.USER, content="c")])
    assert r1.content == "first"
    assert r2.content == "second"
    assert r3.content == "[mock default]"  # exhausted


async def test_chat_passes_tools_and_tool_choice_through():
    """``chat`` 把 ``tools`` / ``tool_choice`` 原样写入 ``calls``。"""
    adapter = MockLLMAdapter()
    tools = [{"type": "function", "function": {"name": "ping"}}]
    await adapter.chat(
        [Message(role=Role.USER, content="hi")],
        tools=tools,
        tool_choice="auto",
    )
    assert adapter.calls[0]["tools"] == tools
    assert adapter.calls[0]["tool_choice"] == "auto"


async def test_tool_call_message_returned_verbatim():
    """含 ``tool_calls`` 的预置响应被原样返回。"""
    tc = ToolCall(name="ping", args={"x": 1}, id="call_1")
    canned = Message(role=Role.ASSISTANT, content="", tool_calls=[tc])
    adapter = MockLLMAdapter(responses=[canned])
    result = await adapter.chat([Message(role=Role.USER, content="call it")])
    assert result.tool_calls == [tc]


# ============================================================================
# 调用记录
# ============================================================================


async def test_calls_recorded():
    """每次调用被记录到 ``calls``。"""
    adapter = MockLLMAdapter()
    msg = Message(role=Role.USER, content="test")
    await adapter.chat([msg])
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["messages"] == [msg]


async def test_default_args_recorded_as_none():
    """未传入 ``tools`` / ``tool_choice`` 时记录为 ``None``。"""
    adapter = MockLLMAdapter()
    await adapter.chat([Message(role=Role.USER, content="x")])
    call = adapter.calls[0]
    assert call["tools"] is None
    assert call["tool_choice"] is None
    assert "stream" not in call  # 仅 chat() 不写入 stream 字段


# ============================================================================
# chat_stream() 行为
# ============================================================================


async def test_chat_stream_yields_chars():
    """流式返回 ``default_content`` 的每个字符。"""
    adapter = MockLLMAdapter(default_content="abc")
    chunks: list[str] = []
    async for chunk in adapter.chat_stream([Message(role=Role.USER, content="hi")]):
        chunks.append(chunk)
    assert chunks == ["a", "b", "c"]


async def test_chat_stream_records_call():
    """``chat_stream`` 调用也写入 ``calls``，带 ``stream=True`` 标记。"""
    adapter = MockLLMAdapter(default_content="z")
    async for _ in adapter.chat_stream([Message(role=Role.USER, content="hi")]):
        pass
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["stream"] is True


# ============================================================================
# assert_called_with
# ============================================================================


def test_assert_called_with_passes():
    """``assert_called_with`` 在入参匹配时不抛错。"""
    adapter = MockLLMAdapter()
    msg = Message(role=Role.USER, content="hi")
    # 手动写入一次调用记录
    adapter.calls.append({"messages": [msg]})
    adapter.assert_called_with(messages=[msg])  # should not raise


def test_assert_called_with_raises_when_messages_mismatch():
    """messages 不一致时抛 ``AssertionError``。"""
    adapter = MockLLMAdapter()
    actual = Message(role=Role.USER, content="hi")
    expected = Message(role=Role.USER, content="hello")
    adapter.calls.append({"messages": [actual]})
    with pytest.raises(AssertionError, match="Expected messages"):
        adapter.assert_called_with(messages=[expected])


def test_assert_called_with_raises_when_no_calls():
    """从未调用时抛 ``AssertionError``。"""
    adapter = MockLLMAdapter()
    with pytest.raises(AssertionError, match="was not called"):
        adapter.assert_called_with(messages=[])


def test_assert_called_with_kwargs():
    """``**kwargs`` 字段按 ``==`` 与最后一次调用记录比较。"""
    adapter = MockLLMAdapter()
    tools = [{"name": "ping"}]
    adapter.calls.append({"messages": [], "tools": tools, "tool_choice": "auto"})
    adapter.assert_called_with(tools=tools, tool_choice="auto")  # ok
    with pytest.raises(AssertionError, match="tool_choice"):
        adapter.assert_called_with(tools=tools, tool_choice="none")


# ============================================================================
# reset
# ============================================================================


def test_reset_clears_state():
    """``reset`` 清空 ``calls`` 和 responses 索引。"""
    adapter = MockLLMAdapter(responses=[Message(role=Role.ASSISTANT, content="x")])
    adapter.calls.append({"x": 1})
    adapter.reset()
    assert adapter.calls == []
    assert adapter._index == 0


async def test_reset_allows_reusing_same_responses():
    """``reset`` 后可以重新消费同一组预置 responses。"""
    adapter = MockLLMAdapter(responses=[Message(role=Role.ASSISTANT, content="again")])
    r1 = await adapter.chat([Message(role=Role.USER, content="1")])
    assert r1.content == "again"
    r2 = await adapter.chat([Message(role=Role.USER, content="2")])
    assert r2.content == "[mock default]"  # 已耗尽
    adapter.reset()
    r3 = await adapter.chat([Message(role=Role.USER, content="3")])
    assert r3.content == "again"  # reset 后重新可消费


# ============================================================================
# 协议一致性
# ============================================================================


def test_satisfies_llm_port():
    """``MockLLMAdapter`` 结构上满足 ``LLMPort`` 协议。"""
    adapter: LLMPort = MockLLMAdapter()  # type: ignore[assignment]
    assert hasattr(adapter, "chat")
    assert hasattr(adapter, "chat_stream")
