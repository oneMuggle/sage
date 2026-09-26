# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""C1 (对话阅读体验第二轮): 生成速度统计的采集、透传与落库。

覆盖:
- LLMClient 流式请求: 首字延迟 / 总耗时计时, 写入 usage_tracker 预留列
- LLMClient 非流式请求: 只有总耗时
- AgentEvent.generation_stats: 提取 / 序列化 / 非法值归一
- run_loop: 终稿 DONE 事件带出 generation_stats
- 仓储: generation_stats 往返与分叉复制
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

import backend.core.legacy.llm_client as llm_client_module
from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.core.legacy.llm_client import LLMClient, LLMConfig, LLMResponse

pytestmark = pytest.mark.unit


def _make_client() -> LLMClient:
    return LLMClient(
        LLMConfig(
            provider="openai",
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="gpt-test",
        )
    )


def _wire_stream(client: LLMClient, chunks: list) -> None:
    lines = [c if isinstance(c, str) else f"data: {json.dumps(c)}" for c in chunks]

    response = MagicMock()
    response.raise_for_status = MagicMock()

    async def aiter_lines():
        for line in lines:
            yield line

    response.aiter_lines = aiter_lines
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=None)
    http = MagicMock()
    http.stream = MagicMock(return_value=ctx)
    client._get_client = lambda: http  # type: ignore[method-assign]


def _fake_clock(monkeypatch, *ticks: float) -> None:
    """只替换 llm_client 模块内的 time 引用, 不影响 asyncio 事件循环的时钟。"""
    values = list(ticks)

    def monotonic() -> float:
        return values.pop(0) if len(values) > 1 else values[0]

    monkeypatch.setattr(
        llm_client_module, "time", SimpleNamespace(monotonic=monotonic, time=time.time)
    )


async def _final_response(client: LLMClient) -> LLMResponse:
    final = None
    async for kind, payload in client.chat_stream_events([{"role": "user", "content": "hi"}]):
        if kind == "response":
            final = payload
    assert isinstance(final, LLMResponse)
    return final


@pytest.mark.asyncio()
async def test_stream_measures_first_token_and_latency(monkeypatch):
    # 开始 100.0s → 首个增量 100.25s → 结束 101.5s
    _fake_clock(monkeypatch, 100.0, 100.25, 101.5)
    record = MagicMock()
    from backend.services import usage_tracker as usage_tracker_module

    monkeypatch.setattr(usage_tracker_module.usage_tracker, "record", record)
    client = _make_client()
    _wire_stream(
        client,
        [
            {"choices": [{"delta": {"content": "你"}}]},
            {"choices": [{"delta": {"content": "好"}, "finish_reason": "stop"}]},
            {
                "choices": [],
                "usage": {"prompt_tokens": 12, "completion_tokens": 30, "total_tokens": 42},
            },
            "data: [DONE]",
        ],
    )

    final = await _final_response(client)

    assert final.first_token_ms == 250
    assert final.latency_ms == 1500
    assert final.output_tokens == 30
    kwargs = record.call_args.kwargs
    assert kwargs["first_token_ms"] == 250
    assert kwargs["latency_ms"] == 1500


@pytest.mark.asyncio()
async def test_reasoning_delta_counts_as_first_token(monkeypatch):
    _fake_clock(monkeypatch, 10.0, 10.5, 12.0)
    client = _make_client()
    _wire_stream(
        client,
        [
            {"choices": [{"delta": {"reasoning_content": "想"}}]},
            {"choices": [{"delta": {"content": "答"}}]},
            "data: [DONE]",
        ],
    )

    final = await _final_response(client)

    assert final.first_token_ms == 500
    assert final.latency_ms == 2000


@pytest.mark.asyncio()
async def test_stream_without_text_has_no_first_token():
    client = _make_client()
    _wire_stream(
        client,
        [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "id": "c1", "function": {"name": "t", "arguments": "{}"}}
                            ]
                        }
                    }
                ]
            },
            "data: [DONE]",
        ],
    )

    final = await _final_response(client)

    assert final.first_token_ms is None
    assert isinstance(final.latency_ms, int)
    assert final.latency_ms >= 0


@pytest.mark.asyncio()
async def test_non_stream_chat_reports_latency_only():
    client = _make_client()
    resp = AsyncMock()
    resp.raise_for_status = Mock()
    resp.json = Mock(
        return_value={
            "model": "gpt-test",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
        }
    )
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=resp)
        mock_get_client.return_value = mock_http

        response = await client.chat([{"role": "user", "content": "hi"}])

    assert response.first_token_ms is None
    assert isinstance(response.latency_ms, int)
    assert response.latency_ms >= 0


def test_generation_stats_from_response_keeps_known_values():
    response = LLMResponse(
        content="x", input_tokens=12, output_tokens=30, first_token_ms=250, latency_ms=1500
    )
    assert AgentEvent.generation_stats_from(response) == {
        "input_tokens": 12,
        "output_tokens": 30,
        "first_token_ms": 250,
        "latency_ms": 1500,
    }


def test_generation_stats_from_response_drops_unknown_values():
    # 上游没返回用量时 tokens 为 0; 测试替身的属性是 MagicMock
    assert AgentEvent.generation_stats_from(LLMResponse(content="x", latency_ms=800)) == {
        "latency_ms": 800
    }
    assert AgentEvent.generation_stats_from(LLMResponse(content="x")) is None
    assert AgentEvent.generation_stats_from(MagicMock()) is None


def test_agent_event_serializes_generation_stats():
    evt = AgentEvent(
        state=AgentState.DONE, content="x", generation_stats={"output_tokens": 30}
    )
    assert evt.to_dict()["generation_stats"] == {"output_tokens": 30}
    assert json.loads(evt.generation_stats_json) == {"output_tokens": 30}


def test_agent_event_omits_or_drops_invalid_generation_stats():
    plain = AgentEvent(state=AgentState.DONE, content="x")
    assert "generation_stats" not in plain.to_dict()
    assert plain.generation_stats_json is None
    for bad in (MagicMock(), {"latency_ms": "slow"}, {"output_tokens": True}, [1, 2]):
        evt = AgentEvent(state=AgentState.DONE, content="x", generation_stats=bad)
        assert evt.generation_stats is None


@pytest.mark.asyncio()
async def test_run_loop_done_carries_generation_stats():
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        return_value=LLMResponse(content="答", tool_calls=[], output_tokens=20, latency_ms=900)
    )
    events = [evt async for evt in agent.run_loop([{"role": "user", "content": "hi"}])]

    done = next(e for e in events if e.state == AgentState.DONE)
    assert done.generation_stats == {"output_tokens": 20, "latency_ms": 900}
    assert done.to_dict()["generation_stats"] == {"output_tokens": 20, "latency_ms": 900}


def test_message_generation_stats_roundtrip(setup_test_db):
    from backend.data.session_repo import Message, MessageRepository, SessionRepository

    session = SessionRepository().create(title="c1")
    repo = MessageRepository()
    repo.save(Message(id="u-1", session_id=session.id, role="user", content="hi", created_at=1))
    repo.save(
        Message(
            id="a-1",
            session_id=session.id,
            role="assistant",
            content="答",
            created_at=2,
            generation_stats=json.dumps({"output_tokens": 30, "latency_ms": 1500}),
        )
    )

    rows = {m.id: m.to_dict() for m in repo.get_by_session(session.id)}
    assert rows["a-1"]["generation_stats"] == {"output_tokens": 30, "latency_ms": 1500}
    assert rows["u-1"]["generation_stats"] is None


def test_fork_copies_generation_stats(setup_test_db):
    from backend.data.session_repo import (
        Message,
        MessageRepository,
        SessionRepository,
        fork_session,
    )

    session_repo = SessionRepository()
    message_repo = MessageRepository()
    source = session_repo.create(title="c1-fork")
    message_repo.save(
        Message(id="u-2", session_id=source.id, role="user", content="q", created_at=1)
    )
    message_repo.save(
        Message(
            id="a-2",
            session_id=source.id,
            role="assistant",
            content="答",
            created_at=2,
            generation_stats=json.dumps({"output_tokens": 7}),
        )
    )

    forked = fork_session(session_repo, message_repo, source.id)

    copied = [m for m in message_repo.get_by_session(forked.id) if m.role == "assistant"]
    assert [m.to_dict()["generation_stats"] for m in copied] == [{"output_tokens": 7}]
