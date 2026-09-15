# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""L2 真流式 tool-calling（backend/core/legacy/llm_client.py + agent.py）单元测试。

覆盖：
1. ``StreamToolCallAggregator``：跨 chunk 聚合 / index 排序 / 残缺调用丢弃；
2. ``LLMClient.chat_stream_events``：事件序列（content/reasoning/response）、
   tool_calls 聚合、<think> 清理、[DONE] 终止；
3. ``run_loop`` 流式路径：CONTENT_DELTA 事件实时下发、DONE 带全量、
   首块前失败自动回退非流式并标记 client、首块后失败向上抛。

SSE mock 复用 test_agent_streaming.py 的 ``_sse_response`` 模式。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.errors import LLMError, LLMErrorType
from backend.core.legacy.agent import SageAgent
from backend.core.legacy.llm_client import (
    LLMClient,
    LLMConfig,
    LLMResponse,
    StreamToolCallAggregator,
)

pytestmark = pytest.mark.unit


# =============================================================================
# 工具:构造 SSE 风格 mock 流式响应(与 test_agent_streaming.py 同模式)
# =============================================================================


def _sse_response(chunks: list, status_code: int = 200):
    """构造一个 mock SSE 响应对象,支持 ``aiter_lines()``。"""
    lines = []
    for c in chunks:
        if isinstance(c, dict):
            lines.append(f"data: {json.dumps(c)}")
        else:
            lines.append(c)
    body = "\n\n".join(lines) + "\n\n"

    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock()

    async def aiter_lines():
        for ln in body.split("\n"):
            if ln == "":
                continue
            yield ln

    response.aiter_lines = aiter_lines

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _make_client() -> LLMClient:
    return LLMClient(
        LLMConfig(
            provider="openai",
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="gpt-3.5-turbo",
        )
    )


def _wire_stream(client: LLMClient, chunks: list) -> None:
    """把 mock SSE 流接到 client 上。"""
    ctx = _sse_response(chunks)
    mock_http = MagicMock()
    mock_http.stream = MagicMock(return_value=ctx)
    client._get_client = lambda: mock_http  # type: ignore[method-assign]


# =============================================================================
# StreamToolCallAggregator
# =============================================================================


def test_aggregator_assembles_split_arguments():
    agg = StreamToolCallAggregator()
    agg.feed([{"index": 0, "id": "call_1", "function": {"name": "read_file", "arguments": '{"path": "a"'}}])
    agg.feed([{"index": 0, "function": {"arguments": ', "b"'}}])
    agg.feed([{"index": 0, "function": {"arguments": "}"}}])
    calls = agg.build()
    assert len(calls) == 1
    assert calls[0].id == "call_1"
    assert calls[0].name == "read_file"
    assert calls[0].arguments == '{"path": "a", "b"}'


def test_aggregator_orders_by_index_and_skips_nameless():
    agg = StreamToolCallAggregator()
    agg.feed([
        {"index": 1, "id": "call_2", "function": {"name": "tool_b", "arguments": "{}"}},
        {"index": 0, "id": "call_1", "function": {"name": "tool_a", "arguments": "{}"}},
        {"index": 2, "function": {"arguments": "{}"}},  # 无 name → 丢弃
    ])
    calls = agg.build()
    assert [c.name for c in calls] == ["tool_a", "tool_b"]
    assert [c.id for c in calls] == ["call_1", "call_2"]


def test_aggregator_missing_index_defaults_to_zero():
    agg = StreamToolCallAggregator()
    agg.feed([{"id": "call_x", "function": {"name": "t", "arguments": '{"a"'}}])
    agg.feed([{"function": {"arguments": ":1}"}}])  # 无 index → 同一调用
    calls = agg.build()
    assert len(calls) == 1
    assert calls[0].arguments == '{"a":1}'


def test_aggregator_ignores_non_list_and_synthesizes_id():
    agg = StreamToolCallAggregator()
    agg.feed(None)
    agg.feed("garbage")
    agg.feed([{"index": 0, "function": {"name": "t"}}])
    calls = agg.build()
    assert calls[0].id == "call_0"  # id 缺失 → 按 index 合成
    assert calls[0].arguments == "{}"


# =============================================================================
# LLMClient.chat_stream_events
# =============================================================================


@pytest.mark.asyncio()
async def test_chat_stream_events_yields_deltas_then_response():
    client = _make_client()
    _wire_stream(
        client,
        [
            {"choices": [{"delta": {"content": "你"}}]},
            {"choices": [{"delta": {"reasoning_content": "想"}}]},
            {"choices": [{"delta": {"content": "好"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            "data: [DONE]",
        ],
    )

    events = []
    async for kind, payload in client.chat_stream_events([{"role": "user", "content": "hi"}]):
        events.append((kind, payload))

    kinds = [k for k, _ in events]
    assert kinds == ["content_delta", "reasoning_delta", "content_delta", "response"]
    final = events[-1][1]
    assert isinstance(final, LLMResponse)
    assert final.content == "你好"
    assert final.reasoning_content == "想"
    assert final.finish_reason == "stop"
    assert final.tool_calls == []


@pytest.mark.asyncio()
async def test_chat_stream_events_aggregates_tool_calls():
    client = _make_client()
    _wire_stream(
        client,
        [
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_9", "function": {"name": "git_status", "arguments": "{}"}},
            ]}}]},
            {"choices": [{"delta": {"content": "让我先看状态。"}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 1, "function": {"name": "git_diff", "arguments": '{"staged":'}},
            ]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 1, "function": {"arguments": "false}"}},
            ]}}]},
            "data: [DONE]",
        ],
    )

    events = []
    async for kind, payload in client.chat_stream_events(
        [{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {"name": "x"}}]
    ):
        events.append((kind, payload))

    final = events[-1][1]
    assert [(tc.name, tc.arguments) for tc in final.tool_calls] == [
        ("git_status", "{}"),
        ("git_diff", '{"staged":false}'),
    ]
    assert final.tool_calls[0].id == "call_9"
    # content_delta 与 tool_calls 可共存
    assert "让我先看状态。" in [p for k, p in events if k == "content_delta"]


@pytest.mark.asyncio()
async def test_chat_stream_events_extracts_think_tags_from_content():
    client = _make_client()
    _wire_stream(
        client,
        [
            {"choices": [{"delta": {"content": "<think>推理"}}]},
            {"choices": [{"delta": {"content": "中</think>答案"}}]},
            "data: [DONE]",
        ],
    )

    final = None
    async for kind, payload in client.chat_stream_events([{"role": "user", "content": "hi"}]):
        if kind == "response":
            final = payload

    assert final is not None
    assert final.content == "答案"
    assert final.reasoning_content == "推理中"


@pytest.mark.asyncio()
async def test_chat_stream_events_http_error_raises_llm_error():
    import httpx

    client = _make_client()
    ctx = _sse_response([])
    response = ctx.__aenter__.return_value

    def raise_500():
        raise httpx.HTTPStatusError(
            "server error",
            request=MagicMock(),
            response=MagicMock(status_code=500, headers={}, text=""),
        )

    response.raise_for_status = MagicMock(side_effect=raise_500)

    async def drain():
        async for _ in client.chat_stream_events([{"role": "user", "content": "hi"}]):
            pass

    with pytest.raises(LLMError):
        await drain()


# =============================================================================
# run_loop 流式路径
# =============================================================================


class _FakeStreamClient:
    """带 chat_stream_events 的假 client（模拟支持流式 tool-calling 的 provider）。"""

    def __init__(self, events=None, content="final", error_before_first=False):
        self.events = events if events is not None else [("content_delta", "final")]
        self.content = content
        self.error_before_first = error_before_first
        self.stream_unsupported = False
        self.chat = AsyncMock(return_value=LLMResponse(content="from-non-stream", tool_calls=[]))
        self.chat_stream_events_calls = 0

    async def chat_stream_events(self, messages, tools=None, tool_choice=None):
        self.chat_stream_events_calls += 1
        if self.error_before_first:
            raise LLMError(LLMErrorType.SERVER_ERROR, "stream 4xx")
        for kind, payload in self.events:
            yield (kind, payload)


def _make_agent(client):
    agent = SageAgent()
    agent.llm_client = client
    return agent


@pytest.mark.asyncio()
async def test_run_loop_streams_content_deltas_then_done():
    client = _FakeStreamClient(
        events=[("content_delta", "你好"), ("content_delta", "！"), ("response", LLMResponse(content="你好！"))],
        content="你好！",
    )
    agent = _make_agent(client)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    deltas = [e.content for e in events if e.state.value == "content_delta"]
    assert deltas == ["你好", "！"]
    assert events[-1].state.value == "done"
    assert events[-1].content == "你好！"
    # 非流式路径不应被调用
    client.chat.assert_not_awaited()


@pytest.mark.asyncio()
async def test_run_loop_falls_back_when_stream_fails_before_first_delta():
    client = _FakeStreamClient(error_before_first=True)
    agent = _make_agent(client)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    # 回退后拿到非流式结果
    assert events[-1].state.value == "done"
    assert events[-1].content == "from-non-stream"
    client.chat.assert_awaited_once()
    # client 被标记,后续迭代不再尝试流式
    assert client.stream_unsupported is True


@pytest.mark.asyncio()
async def test_run_loop_raises_when_stream_fails_after_first_delta():
    client = _FakeStreamClient(
        events=[
            ("content_delta", "部分内容"),
            ("response", LLMResponse(content="部分内容")),
        ]
    )
    # 模拟"已产出增量后"流中断
    async def broken_events(messages, tools=None, tool_choice=None):
        yield ("content_delta", "部分内容")
        raise LLMError(LLMErrorType.SERVER_ERROR, "mid-stream drop")

    client.chat_stream_events = broken_events
    agent = _make_agent(client)

    async def drain_loop():
        async for _ in agent.run_loop([{"role": "user", "content": "x"}]):
            pass

    with pytest.raises(LLMError):
        await drain_loop()


@pytest.mark.asyncio()
async def test_run_loop_env_off_disables_streaming(monkeypatch):
    monkeypatch.setenv("SAGE_LLM_STREAMING", "0")
    client = _FakeStreamClient()
    agent = _make_agent(client)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    assert events[-1].state.value == "done"
    assert events[-1].content == "from-non-stream"
    assert client.chat_stream_events_calls == 0
