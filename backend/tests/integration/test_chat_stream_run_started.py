"""2026-11-19 实时排序：/api/v1/chat/stream 在 run 开始时推送 run_started 事件。

此前侧栏会话列表只在流结束时全量刷新 —— 运行中的会话要等流结束才会
按运行态重排。producer 在 running 落库后推送 session_updated/run_started，
前端据此即时置顶。
"""

from __future__ import annotations

import json
from typing import Any, List
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from backend.data.session_repo import SessionRepository
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"


def _parse_ndjson(text: str) -> List[dict]:
    return [json.loads(line) for line in text.split("\n") if line.strip()]


@pytest.mark.asyncio()
async def test_legacy_stream_emits_run_started_event(client: AsyncClient):
    # conftest 的 client fixture 负责初始化/清空 app.state.streams
    assert hasattr(app.state, "streams")

    sid = SessionRepository().create().id

    async def mock_run_loop(messages: Any, max_iterations: int = 5, **kwargs: Any) -> Any:
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        create_resp = await client.post(
            CHAT_STREAM_PATH,
            json={"session_id": sid, "message": "ping"},
        )
        assert create_resp.status_code == 200
        stream_id = create_resp.json()["streamId"]

        attach_resp = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
        assert attach_resp.status_code == 200

    events = _parse_ndjson(attach_resp.text)
    started = [
        e
        for e in events
        if e.get("type") == "session_updated" and e.get("subtype") == "run_started"
    ]
    event_summary = [
        (e.get("type"), e.get("subtype"), e.get("state")) for e in events
    ]
    assert started, f"未找到 run_started 事件，events={event_summary}"
    assert started[0]["session_id"] == sid
