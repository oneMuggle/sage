# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""重试退避期间 heartbeat 事件发射单元测试。

2026-10-26: 后端在 LLM 重试退避等待期间每 5s 发一次 heartbeat 事件,
喂前端 watchdog 防止长退避(如 30s)期间 watchdog 误杀流。

覆盖:
- delay=0 → 不发 heartbeat (与原有 retry 行为一致)
- delay=12s → 发 3 次 heartbeat (5s, 10s, 12s 尾部)
- delay=3s → 发 1 次 heartbeat (尾部 sleep 3s 后 yield)
- AgentState.HEARTBEAT 枚举值存在
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.core.legacy.llm_client import LLMClient, LLMConfig

pytestmark = pytest.mark.unit


def _make_client() -> LLMClient:
    return LLMClient(
        LLMConfig(
            provider="openai",
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="gpt-3.5-turbo",
        )
    )


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        "http error",
        request=MagicMock(),
        response=MagicMock(status_code=status, headers={}, text=""),
    )


def _sse_ctx(chunks: list):
    lines = [f"data: {json.dumps(c)}" if isinstance(c, dict) else c for c in chunks]
    body = "\n\n".join(lines) + "\n\n"
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()

    async def aiter_lines():
        for ln in body.split("\n"):
            if ln != "":
                yield ln

    response.aiter_lines = aiter_lines
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _wire_stream(client: LLMClient, ctx_list: list) -> MagicMock:
    mock_http = MagicMock()
    calls = {"n": 0}

    def stream(*args, **kwargs):
        ctx = ctx_list[min(calls["n"], len(ctx_list) - 1)]
        calls["n"] += 1
        return ctx

    mock_http.stream = MagicMock(side_effect=stream)
    client._get_client = lambda: mock_http  # type: ignore[method-assign]
    return mock_http


@pytest.mark.asyncio()
async def test_retry_with_zero_delay_emits_no_heartbeat(monkeypatch):
    """delay=0 → 退避循环不进入 → 不发 heartbeat(与原有行为一致)"""
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "0")
    client = _make_client()

    fail_ctx = _sse_ctx([])
    fail_response = fail_ctx.__aenter__.return_value

    def raise_500():
        raise _http_status_error(500)

    fail_response.raise_for_status = MagicMock(side_effect=raise_500)

    ok_ctx = _sse_ctx(
        [
            {"choices": [{"delta": {"content": "ok"}}]},
            "data: [DONE]",
        ]
    )
    _wire_stream(client, [fail_ctx, ok_ctx])

    events = []
    async for kind, _payload in client.chat_stream_events(
        [{"role": "user", "content": "x"}]
    ):
        events.append(kind)

    # delay=0 → 无 heartbeat, 与原有 test_stream_retries_before_first_delta 一致
    assert events == ["retry", "content_delta", "response"]


@pytest.mark.asyncio()
async def test_retry_with_12s_delay_emits_3_heartbeats(monkeypatch):
    """delay=12s → heartbeat interval=5s → 3 次 heartbeat (5s, 10s, 12s 尾部)

    while elapsed < delay:
      0 < 12 → sleep(min(5, 12))=5  → elapsed=5  → yield hb
      5 < 12 → sleep(min(5, 7))=5   → elapsed=10 → yield hb
      10 < 12 → sleep(min(5, 2))=2  → elapsed=12 → yield hb
      12 < 12 False → 退出
    """
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "12")
    client = _make_client()

    fail_ctx = _sse_ctx([])
    fail_response = fail_ctx.__aenter__.return_value

    def raise_500():
        raise _http_status_error(500)

    fail_response.raise_for_status = MagicMock(side_effect=raise_500)

    ok_ctx = _sse_ctx(
        [
            {"choices": [{"delta": {"content": "ok"}}]},
            "data: [DONE]",
        ]
    )
    _wire_stream(client, [fail_ctx, ok_ctx])

    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr("backend.core.legacy.llm_client.asyncio.sleep", fake_sleep)

    events = []
    async for kind, _payload in client.chat_stream_events(
        [{"role": "user", "content": "x"}]
    ):
        events.append(kind)

    heartbeat_count = events.count("heartbeat")
    assert heartbeat_count == 3
    assert slept == [5.0, 5.0, 2.0]
    assert events == [
        "retry",
        "heartbeat",
        "heartbeat",
        "heartbeat",
        "content_delta",
        "response",
    ]


@pytest.mark.asyncio()
async def test_retry_with_3s_delay_emits_1_heartbeat(monkeypatch):
    """delay=3s → while 0<3 → sleep(min(5,3))=3 → elapsed=3 → yield hb; 3<3 退出"""
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "3")
    client = _make_client()

    fail_ctx = _sse_ctx([])
    fail_response = fail_ctx.__aenter__.return_value

    def raise_500():
        raise _http_status_error(500)

    fail_response.raise_for_status = MagicMock(side_effect=raise_500)

    ok_ctx = _sse_ctx(
        [
            {"choices": [{"delta": {"content": "ok"}}]},
            "data: [DONE]",
        ]
    )
    _wire_stream(client, [fail_ctx, ok_ctx])

    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr("backend.core.legacy.llm_client.asyncio.sleep", fake_sleep)

    events = []
    async for kind, _payload in client.chat_stream_events(
        [{"role": "user", "content": "x"}]
    ):
        events.append(kind)

    assert events == ["retry", "heartbeat", "content_delta", "response"]
    assert slept == [3.0]


def test_agent_state_heartbeat_enum():
    """AgentState.HEARTBEAT 枚举值存在且为 'heartbeat'"""
    assert AgentState.HEARTBEAT.value == "heartbeat"


def test_agent_event_heartbeat_creation():
    """AgentEvent with HEARTBEAT state should carry minimal fields"""
    evt = AgentEvent(state=AgentState.HEARTBEAT, iteration=1, agent_id="test-agent")
    assert evt.state == AgentState.HEARTBEAT
    assert evt.iteration == 1
    assert evt.agent_id == "test-agent"
    # heartbeat 不携带内容/工具/错误
    assert evt.content is None
    assert evt.tool_call is None
    assert evt.error is None
