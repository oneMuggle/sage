"""R134 — MockLLMAdapter（LLMPort 内存实现）单元测试。

覆盖：chat 顺序消费与 default 回退、调用记录、chat_stream 逐字符流、
assert_called_with 的成功/未调用/不匹配路径、reset 重放语义。
"""

from __future__ import annotations

import pytest
from sage_core import Message, Role

from backend.adapters.out.llm.mock_adapter import MockLLMAdapter

pytestmark = pytest.mark.unit


def _msg(role, content):
    return Message(role=role, content=content)


@pytest.mark.asyncio()
async def test_chat_consumes_responses_in_order():
    adapter = MockLLMAdapter(responses=[_msg(Role.ASSISTANT, "one"), _msg(Role.ASSISTANT, "two")])
    first = await adapter.chat([_msg(Role.USER, "q1")])
    second = await adapter.chat([_msg(Role.USER, "q2")])
    assert first.content == "one"
    assert second.content == "two"


@pytest.mark.asyncio()
async def test_chat_exhausted_falls_back_to_default():
    adapter = MockLLMAdapter(responses=[_msg(Role.ASSISTANT, "only")], default_content="[d]")
    await adapter.chat([])
    third = await adapter.chat([])
    assert third.content == "[d]"
    assert third.role == Role.ASSISTANT


@pytest.mark.asyncio()
async def test_chat_records_calls():
    tools = [{"name": "t"}]
    adapter = MockLLMAdapter()
    messages = [_msg(Role.USER, "hi")]
    await adapter.chat(messages, tools=tools, tool_choice="auto")
    assert adapter.calls == [{"messages": messages, "tools": tools, "tool_choice": "auto"}]


@pytest.mark.asyncio()
async def test_chat_stream_yields_chars_and_records():
    adapter = MockLLMAdapter(default_content="abc")
    chunks = [c async for c in adapter.chat_stream([_msg(Role.USER, "q")])]
    assert chunks == ["a", "b", "c"]
    assert adapter.calls[-1]["stream"] is True


def test_assert_called_with_no_calls_raises():
    adapter = MockLLMAdapter()
    with pytest.raises(AssertionError, match="was not called"):
        adapter.assert_called_with()


@pytest.mark.asyncio()
async def test_assert_called_with_messages_match():
    adapter = MockLLMAdapter()
    messages = [_msg(Role.USER, "hi")]
    await adapter.chat(messages)
    adapter.assert_called_with(messages=messages)  # 不抛即通过


@pytest.mark.asyncio()
async def test_assert_called_with_mismatch_raises():
    adapter = MockLLMAdapter()
    await adapter.chat([_msg(Role.USER, "actual")])
    with pytest.raises(AssertionError, match="Expected messages"):
        adapter.assert_called_with(messages=[_msg(Role.USER, "expected")])


@pytest.mark.asyncio()
async def test_assert_called_with_kwargs_field():
    adapter = MockLLMAdapter()
    await adapter.chat([], tools=["t"], tool_choice="auto")
    adapter.assert_called_with(tools=["t"], tool_choice="auto")
    with pytest.raises(AssertionError, match="Expected tool_choice"):
        adapter.assert_called_with(tool_choice="none")


@pytest.mark.asyncio()
async def test_reset_clears_calls_and_index():
    adapter = MockLLMAdapter(responses=[_msg(Role.ASSISTANT, "only")])
    await adapter.chat([])
    await adapter.chat([])
    adapter.reset()
    assert adapter.calls == []
    again = await adapter.chat([])  # 索引归零 → responses 可重放
    assert again.content == "only"
