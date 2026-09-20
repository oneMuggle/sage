"""R81/R83 集成回归: /chat/stream 参考来源端到端

锁定整条链路: OBSERVING 事件里的 web_search 命中 → producer 聚合 →
sources_used 流事件（STEP_DONE 边界增量 + DONE 前全量）→ 终稿 assistant
行 sources 列落盘 → get_by_session 回读。

mock run_loop 直接产出 agent 事件（同 test_chat_stream_persist 的思路，
但会话用 SessionRepository 直建,绕开 SessionService DI —— 那是旧文件
被 skipif(True) 整体跳过的原因）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from unittest.mock import patch

import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState, ToolCallRequest, ToolCallResult
from backend.data.session_repo import MessageRepository, SessionRepository
from backend.main import app

pytestmark = [pytest.mark.integration]

CHAT_STREAM_PATH = "/api/v1/chat/stream"

WEB_RESULT_CONTENT = json.dumps(
    {
        "query": "sage electron",
        "engine": "bing",
        "results": [
            {"title": "Sage 官网", "url": "https://sage.example.com/", "snippet": "AI 助手"},
        ],
        "total": 1,
    },
    ensure_ascii=False,
)


async def _drain_stream(client, stream_id: str) -> list:
    """attach NDJSON 流并逐行收集事件,直到 producer 收尾。"""
    events = []
    async with client.stream("GET", f"{CHAT_STREAM_PATH}/{stream_id}") as resp:
        async for raw_line in resp.aiter_lines():
            line = raw_line.strip()
            if not line:
                continue
            with contextlib.suppress(ValueError):
                events.append(json.loads(line))
    entry = app.state.streams.get(stream_id)
    if entry and entry.task:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await entry.task
    return events


@pytest.mark.asyncio()
async def test_web_search_sources_flow_event_and_persistence(client):
    """web_search 命中 → sources_used 事件 + 终稿行 sources 落库回读。"""
    session = SessionRepository().create(title="r84-sources")
    events_seen: list = []

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.ACTING,
            iteration=0,
            tool_call=ToolCallRequest(id="tc-1", name="web_search", arguments={"query": "sage"}),
        )
        yield AgentEvent(
            state=AgentState.OBSERVING,
            iteration=0,
            tool_call=ToolCallRequest(id="tc-1", name="web_search", arguments={"query": "sage"}),
            tool_result=ToolCallResult(tool_call_id="tc-1", content=WEB_RESULT_CONTENT, is_error=False),
        )
        yield AgentEvent(state=AgentState.STEP_DONE, iteration=0, step_index=0)
        yield AgentEvent(state=AgentState.THINKING, iteration=1)
        yield AgentEvent(state=AgentState.DONE, iteration=1, content="根据搜索结果回答")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop
        MockAgent.return_value.memory_manager = None

        create_stream = await client.post(
            CHAT_STREAM_PATH,
            json={"session_id": session.id, "message": "搜一下 sage"},
        )
        assert create_stream.status_code == 200, create_stream.text
        stream_id = create_stream.json()["streamId"]
        events_seen = await _drain_stream(client, stream_id)

    # 1) 流事件: 至少一次 sources_used（STEP_DONE 边界增量推送）
    sources_events = [e for e in events_seen if e.get("state") == "sources_used"]
    assert sources_events, f"expected sources_used event, got states={[e.get('state') for e in events_seen]}"
    first = sources_events[0]["sources"][0]
    assert first["kind"] == "web"
    assert first["url"] == "https://sage.example.com/"

    # 2) 落库: 终稿 assistant 行 sources 列可回读为结构化列表
    rows = MessageRepository().get_by_session(session.id)
    final_rows = [r for r in rows if r.role == "assistant" and r.to_dict().get("sources")]
    assert final_rows, f"no assistant row with sources persisted, rows={[(r.role, r.to_dict().get('sources')) for r in rows]}"
    persisted = final_rows[0].to_dict()["sources"]
    assert persisted[0]["title"] == "Sage 官网"
    assert persisted[0]["kind"] == "web"
    # 落库内容与事件载荷同源
    assert persisted == sources_events[-1]["sources"]


@pytest.mark.asyncio()
async def test_no_tool_calls_no_sources_event(client):
    """纯文本回答（无检索类工具）不应产 sources_used,也不落 sources 列。"""
    session = SessionRepository().create(title="r84-no-sources")

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="不需要来源的回答")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop
        MockAgent.return_value.memory_manager = None

        create_stream = await client.post(
            CHAT_STREAM_PATH,
            json={"session_id": session.id, "message": "你好"},
        )
        assert create_stream.status_code == 200
        stream_id = create_stream.json()["streamId"]
        events_seen = await _drain_stream(client, stream_id)

    assert not [e for e in events_seen if e.get("state") == "sources_used"]
    rows = MessageRepository().get_by_session(session.id)
    assert all(r.to_dict().get("sources") is None for r in rows)


@pytest.mark.asyncio()
async def test_browser_navigate_sources_flow(client):
    """R87: agent 经受控浏览器主动访问的页面同样进来源（snippet 留空）。"""
    session = SessionRepository().create(title="r90-navigate")

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.ACTING,
            iteration=0,
            tool_call=ToolCallRequest(id="tc-1", name="browser_navigate", arguments={"url": "https://b.example.com"}),
        )
        yield AgentEvent(
            state=AgentState.OBSERVING,
            iteration=0,
            tool_call=ToolCallRequest(id="tc-1", name="browser_navigate", arguments={"url": "https://b.example.com"}),
            tool_result=ToolCallResult(
                tool_call_id="tc-1",
                content=json.dumps({"url": "https://b.example.com", "title": "示例站"}),
                is_error=False,
            ),
        )
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="已浏览该页面")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop
        MockAgent.return_value.memory_manager = None

        create_stream = await client.post(
            CHAT_STREAM_PATH,
            json={"session_id": session.id, "message": "看看这个页面"},
        )
        assert create_stream.status_code == 200
        stream_id = create_stream.json()["streamId"]
        await _drain_stream(client, stream_id)

    rows = MessageRepository().get_by_session(session.id)
    final_rows = [r for r in rows if r.role == "assistant" and r.to_dict().get("sources")]
    assert final_rows
    persisted = final_rows[0].to_dict()["sources"]
    assert persisted[0]["kind"] == "web"
    assert persisted[0]["url"] == "https://b.example.com"
    assert persisted[0]["title"] == "示例站"
