"""
/chat/stream create + attach 端点集成测试 (I2)

拆分原 /chat/stream POST 流式响应为:
  - POST /chat/stream        → 立即返回 {"streamId": ...},后台启动 agent.run_loop
  - GET  /chat/stream/{id}   → NDJSON 流式输出已产生的事件

主要验证点:
  1. create 返回 streamId,无 NDJSON
  2. attach 返回 NDJSON 事件
  3. **两个 attach 共享同一 streamId,只触发一次 LLM**(回归 I2 关键不变性)
  4. 未知 streamId → 404
  5. producer 抛异常时,attach 仍能拿到 failed 事件 + 正常关闭

注意:路由通过 app.include_router(legacy_router, prefix="/api/v1") 注册,
所以实际挂载路径是 /api/v1/chat/stream 和 /api/v1/chat/stream/{id}。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.core.legacy.agent_state import (
    AgentEvent,
    AgentState,
    ToolCallRequest,
    ToolCallResult,
)
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"


def _parse_ndjson(text: str) -> list[dict]:
    return [json.loads(line) for line in text.split("\n") if line.strip()]


@pytest.mark.asyncio()
async def test_chat_stream_create_returns_stream_id_immediately():
    """POST /chat/stream 返回 {"streamId": "..."},无 NDJSON 流式输出。"""
    from backend.api.chat_stream_registry import StreamRegistry

    # 兜底:某些测试路径可能不经过 client fixture
    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            CHAT_STREAM_PATH,
            json={
                "session_id": "00000000-0000-0000-0000-000000000000",
                "message": "hi",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "streamId" in body
    assert isinstance(body["streamId"], str)
    assert len(body["streamId"]) >= 16  # uuid4 长度

    # 清理 task
    entry = app.state.streams.get(body["streamId"])
    if entry and entry.task and not entry.task.done():
        entry.task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await entry.task


@pytest.mark.asyncio()
async def test_chat_stream_attach_streams_ndjson_events():
    """create + attach: NDJSON 事件按序到达。"""
    from backend.api.chat_stream_registry import StreamRegistry

    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.ACTING,
            iteration=0,
            tool_call=ToolCallRequest(
                id="c1",
                name="calculator",
                arguments={"expression": "1+1"},
            ),
        )
        yield AgentEvent(
            state=AgentState.OBSERVING,
            iteration=0,
            tool_result=ToolCallResult(tool_call_id="c1", content="2"),
        )
        yield AgentEvent(
            state=AgentState.DONE,
            iteration=1,
            content="答案是 2",
        )

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # 1. create
            create_resp = await ac.post(
                CHAT_STREAM_PATH,
                json={
                    "session_id": "00000000-0000-0000-0000-000000000000",
                    "message": "1+1 等于几",
                },
            )
            assert create_resp.status_code == 200
            stream_id = create_resp.json()["streamId"]

            # 2. attach
            attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
            assert attach_resp.status_code == 200
            assert attach_resp.headers["content-type"].startswith("application/x-ndjson")

            events = _parse_ndjson(attach_resp.text)
            # I5: DONE 事件的 content 现在会被 producer 拆成 content_delta chunks
            # 逐个入队 (逐字流式效果)。所以 events 是 [thinking, acting, observing,
            # content_delta*, done]。
            delta_events = [e for e in events if e["state"] == "content_delta"]
            done_events = [e for e in events if e["state"] == "done"]
            assert events[0]["state"] == "thinking"
            assert events[1]["state"] == "acting"
            assert events[1]["tool_call"]["function"]["name"] == "calculator"
            assert events[2]["state"] == "observing"
            # content_delta 累积 = 完整 content
            accumulated = "".join(e["content"] for e in delta_events)
            assert accumulated == "答案是 2", f"accumulated {accumulated!r} != '答案是 2'"
            assert len(done_events) == 1
            assert done_events[0]["content"] == "答案是 2"


@pytest.mark.asyncio()
async def test_two_attaches_share_queue_without_invoking_llm_twice():
    """关键不变性:同一 streamId 多次 attach,LLM 只被调一次。

    回归 I2 的核心目的 — 修复前 invoke+relay 各发一次 POST,LLM 调两次。

    注:多 attach 共享一个 asyncio.Queue,事件会被两个 consumer 竞争消费
    (类似 work-stealing)。所以两个 attach 各自只拿部分事件,但合计覆盖全部。
    """
    from backend.api.chat_stream_registry import StreamRegistry

    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()

    run_loop_call_count = 0
    lock = asyncio.Lock()

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        nonlocal run_loop_call_count
        async with lock:
            run_loop_call_count += 1
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            create_resp = await ac.post(
                CHAT_STREAM_PATH,
                json={"session_id": "s", "message": "hi"},
            )
            stream_id = create_resp.json()["streamId"]

            # 并发两个 attach
            resp_a, resp_b = await asyncio.gather(
                ac.get(f"{CHAT_STREAM_PATH}/{stream_id}"),
                ac.get(f"{CHAT_STREAM_PATH}/{stream_id}"),
            )

            # 两个响应都成功
            assert resp_a.status_code == 200
            assert resp_b.status_code == 200

            # 关键断言:LLM 只跑了一次(回归 I2 核心)
            assert run_loop_call_count == 1, f"LLM 应该只调一次,实际 {run_loop_call_count} 次"

            # 共享 queue 下事件被两个 consumer 竞争,合计应包含全部事件
            events_a = _parse_ndjson(resp_a.text)
            events_b = _parse_ndjson(resp_b.text)
            all_states = {e["state"] for e in events_a} | {e["state"] for e in events_b}
            assert "thinking" in all_states
            assert "done" in all_states


@pytest.mark.asyncio()
async def test_attach_unknown_stream_id_returns_404():
    """attach 一个不存在的 streamId → 404。"""
    from backend.api.chat_stream_registry import StreamRegistry

    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(f"{CHAT_STREAM_PATH}/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio()
async def test_producer_exception_emits_failed_event_and_closes_stream():
    """producer 抛异常 → attach 收到 failed 事件 + 流正常关闭。"""

    async def broken_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        raise RuntimeError("LLM exploded")
        yield  # pragma: no cover — unreachable, makes this an async generator

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = broken_run_loop

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            create_resp = await ac.post(
                CHAT_STREAM_PATH,
                json={"session_id": "s", "message": "hi"},
            )
            stream_id = create_resp.json()["streamId"]
            attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")

        assert attach_resp.status_code == 200
        events = _parse_ndjson(attach_resp.text)
        # 至少包含 thinking + failed(异常后无 done)
        states = [e["state"] for e in events]
        assert "thinking" in states
        assert "failed" in states
        # failed 事件应含 error 字段
        failed = next(e for e in events if e["state"] == "failed")
        assert "error" in failed


# =============================================================================
# I3: 回归保护 — producer 必须把 request body 里的 llm_config 透传给 agent.run_loop
# =============================================================================


@pytest.mark.asyncio()
async def test_producer_passes_llm_config_to_run_loop_when_api_key_and_url_provided():
    """回归保护:当请求体含 api_key + api_url 时,producer 必须把 llm_config
    传给 agent.run_loop,而不是用实例化时为 None 的默认 LLM。

    之前 PR #28 + PR #27 让 IPC 能调通,但 /chat/stream 一直报 "LLM 未配置"
    因为 producer 构造了 llm_config 却没传给 run_loop(签名根本不接受)。
    本测试锁定 producer 的透传行为。
    """
    from backend.api.chat_stream_registry import StreamRegistry

    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()

    captured_kwargs: dict = {}

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        captured_kwargs.update(kwargs)
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            create_resp = await ac.post(
                CHAT_STREAM_PATH,
                json={
                    "session_id": "s",
                    "message": "hi",
                    "api_key": "sk-test-123",
                    "api_url": "https://example.com/v1",
                    "model": "test-model",
                    "temperature": 0.3,
                },
            )
            assert create_resp.status_code == 200
            stream_id = create_resp.json()["streamId"]

            # 拉一次 attach 让 producer 跑完
            attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
            assert attach_resp.status_code == 200

    # 关键断言: llm_config 真的被传过去了
    assert (
        "llm_config" in captured_kwargs
    ), f"producer 没把 llm_config 透传给 run_loop,kwargs={captured_kwargs}"
    llm_config = captured_kwargs["llm_config"]
    assert llm_config is not None
    assert llm_config["api_key"] == "sk-test-123"
    assert llm_config["base_url"] == "https://example.com/v1"
    assert llm_config["model"] == "test-model"
    assert llm_config["provider"] == "custom"
    assert llm_config["temperature"] == 0.3


@pytest.mark.asyncio()
async def test_producer_passes_no_llm_config_when_request_omits_api_key():
    """请求不带 api_key/api_url → producer 不传 llm_config(走默认 agent client)。"""
    from backend.api.chat_stream_registry import StreamRegistry

    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()

    captured_kwargs: dict = {}

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        captured_kwargs.update(kwargs)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            create_resp = await ac.post(
                CHAT_STREAM_PATH,
                json={"session_id": "s", "message": "hi"},
            )
            stream_id = create_resp.json()["streamId"]
            attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
            assert attach_resp.status_code == 200

    # 没 api_key/api_url → llm_config 应该是 None
    assert captured_kwargs.get("llm_config") is None


# =============================================================================
# PR-7a: provider 透传 + 推理参数 (reasoning_effort / thinking_budget)
# =============================================================================


@pytest.mark.asyncio()
async def test_producer_passes_provider_from_request_body():
    """请求体显式带 provider → llm_config["provider"] 跟着变,不再硬写 'custom'。"""
    from backend.api.chat_stream_registry import StreamRegistry

    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()

    captured_kwargs: dict = {}

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        captured_kwargs.update(kwargs)
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                CHAT_STREAM_PATH,
                json={
                    "session_id": "s",
                    "message": "hi",
                    "api_key": "sk-test",
                    "api_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                    "model": "gemini-2.5-flash",
                    "provider": "gemini",
                },
            )
            assert resp.status_code == 200
            stream_id = resp.json()["streamId"]
            await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")

    llm_config = captured_kwargs["llm_config"]
    assert (
        llm_config["provider"] == "gemini"
    ), f"provider 应该透传,实际 {llm_config.get('provider')!r}"


@pytest.mark.asyncio()
async def test_producer_passes_reasoning_params_when_provided():
    """请求体带 reasoning_effort / thinking_budget → 出现在 llm_config 里。"""
    from backend.api.chat_stream_registry import StreamRegistry

    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()

    captured_kwargs: dict = {}

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        captured_kwargs.update(kwargs)
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                CHAT_STREAM_PATH,
                json={
                    "session_id": "s",
                    "message": "hi",
                    "api_key": "sk-test",
                    "api_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                    "model": "gemini-2.5-flash",
                    "reasoning_effort": "high",
                    "thinking_budget": 4096,
                },
            )
            assert resp.status_code == 200
            stream_id = resp.json()["streamId"]
            await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")

    llm_config = captured_kwargs["llm_config"]
    assert llm_config["reasoning_effort"] == "high"
    assert llm_config["thinking_budget"] == 4096


@pytest.mark.asyncio()
async def test_producer_omits_reasoning_params_when_not_provided():
    """请求体不带推理参数 → llm_config 里也不带(避免污染老 LLM)。"""
    from backend.api.chat_stream_registry import StreamRegistry

    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()

    captured_kwargs: dict = {}

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        captured_kwargs.update(kwargs)
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                CHAT_STREAM_PATH,
                json={
                    "session_id": "s",
                    "message": "hi",
                    "api_key": "sk-test",
                    "api_url": "https://example.com/v1",
                    "model": "gpt-4",
                    # 没传 reasoning_effort / thinking_budget
                },
            )
            assert resp.status_code == 200
            stream_id = resp.json()["streamId"]
            await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")

    llm_config = captured_kwargs["llm_config"]
    # 向后兼容: 老请求不带新字段时,llm_config 也不该有这些 key
    assert "reasoning_effort" not in llm_config
    assert "thinking_budget" not in llm_config
