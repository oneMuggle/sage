"""LLMClient 线协议一致性测试 (M6 生态扩展)。

把真实 LLMClient 指向脚本化 mock 服务器 (base_url 覆盖, use_proxy=False),
端到端验证普通 / tool_call 往返 / SSE 流式三种响应的解析 — 客户端的
线协议处理在无网络环境下被真实执行。

模式来源: claw-code ``crates/mock-anthropic-service``。
"""

from __future__ import annotations

import json

import pytest

from backend.core.legacy.llm_client import LLMClient, LLMConfig
from backend.services.usage_tracker import usage_tracker
from backend.tests.parity.mock_server import SCENARIOS, MockLLMServer

pytestmark = pytest.mark.integration

CALCULATOR_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "计算数学表达式",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
}


@pytest.fixture()
def mock_server():
    with MockLLMServer(SCENARIOS) as server:
        yield server


@pytest.fixture(autouse=True)
def _reset_tracker():
    usage_tracker.reset()
    yield
    usage_tracker.reset()


def _make_client(base_url: str) -> LLMClient:
    return LLMClient(
        LLMConfig(
            provider="openai",
            api_key="parity-key",
            base_url=base_url,
            model="mock-model",
            timeout=10,
            use_proxy=False,
        )
    )


@pytest.mark.asyncio()
async def test_parity_plain_chat_reply(mock_server):
    """(a) 普通回复: content / finish_reason / usage 全链路解析。"""
    client = _make_client(mock_server.base_url)
    response = await client.chat(
        [{"role": "user", "content": "PARITY_SCENARIO:plain\nSay hello"}]
    )

    assert response.content == "Hello from the mock."
    assert response.finish_reason == "stop"
    assert response.tool_calls == []
    assert response.usage == {
        "prompt_tokens": 11,
        "completion_tokens": 5,
        "total_tokens": 16,
    }
    assert response.input_tokens == 11
    assert response.output_tokens == 5

    # usage 联动进了全局 tracker
    summary = usage_tracker.summary()
    assert summary["totals"]["requests"] == 1
    assert summary["totals"]["prompt_tokens"] == 11
    # 线协议: Authorization header 与请求体透传
    captured = mock_server.requests[-1]
    assert captured["headers"].get("Authorization") == "Bearer parity-key"
    assert captured["body"]["model"] == "mock-model"
    await client.close()


@pytest.mark.asyncio()
async def test_parity_tool_call_round_trip(mock_server):
    """(b) tool_call 往返: 首轮解析 tool_calls, 喂回工具结果后拿到终答。"""
    client = _make_client(mock_server.base_url)
    messages = [
        {"role": "user", "content": "PARITY_SCENARIO:tool_round_trip\nwhat is 6*7?"}
    ]

    first = await client.chat(messages, tools=[CALCULATOR_TOOL_SCHEMA])
    assert first.content == ""
    assert len(first.tool_calls) == 1
    tool_call = first.tool_calls[0]
    assert tool_call.id == "call_parity_1"
    assert tool_call.name == "calculator"
    assert json.loads(tool_call.arguments) == {"expression": "6*7"}

    # 模拟 agent 循环: 回填 assistant + tool 消息, 第二轮请求
    messages.append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {"name": tool_call.name, "arguments": tool_call.arguments},
                }
            ],
        }
    )
    messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": "42"})

    second = await client.chat(messages, tools=[CALCULATOR_TOOL_SCHEMA])
    assert second.content == "The answer is 42."
    assert second.tool_calls == []
    assert mock_server.call_count("tool_round_trip") == 2

    # 第二轮请求确实携带了 tool 消息 (线协议双向验证)
    second_body = mock_server.requests[-1]["body"]
    roles = [m["role"] for m in second_body["messages"]]
    assert roles == ["user", "assistant", "tool"]
    assert second_body["messages"][2]["tool_call_id"] == "call_parity_1"
    await client.close()


@pytest.mark.asyncio()
async def test_parity_streaming_reply(mock_server):
    """(c) SSE 流式: chunk 文本拼接 + 末尾 usage 进 tracker。"""
    client = _make_client(mock_server.base_url)
    chunks = [
        chunk
        async for chunk in client.chat_stream(
            [{"role": "user", "content": "PARITY_SCENARIO:stream\nhi"}]
        )
    ]

    assert "".join(chunks) == "Hello from stream"
    summary = usage_tracker.summary()
    assert summary["totals"]["requests"] == 1
    assert summary["totals"]["prompt_tokens"] == 7
    assert summary["totals"]["completion_tokens"] == 3
    await client.close()


@pytest.mark.asyncio()
async def test_parity_missing_scenario_marker_yields_llm_error(mock_server):
    """无场景标记 → mock 返回 400 → 客户端映射为 LLMError (不透传原始异常)。"""
    from backend.core.errors import LLMError

    client = _make_client(mock_server.base_url)
    with pytest.raises(LLMError):
        await client.chat([{"role": "user", "content": "no scenario marker"}])
    assert usage_tracker.summary()["totals"]["requests"] == 0
    await client.close()
