"""legacy_routes /chat/stream 失败原因持久化集成测试 (2026-10-22)

验证 agent run_loop 产出 FAILED 事件时：

  1. SSE 的 failed 事件把带上限装饰的错误串原样下发给前端；
  2. sessions.run_status 落为 'failed'；
  3. sessions.last_error 落为**真实原因**（含 ``limit=<数值>``），
     而不是笼统的 "运行失败"。

第 3 点是本次修复的核心：``_consume_run_loop`` 内对 ``_producer_error``
的赋值原先缺 ``nonlocal``，Python 闭包把它当成函数局部变量，外层
``finally`` 读到的仍是 None → last_error 降级为 "运行失败"，用户
既看不到原因、也不知道该把上限调到多少。
"""

from __future__ import annotations

import json
from typing import List
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"


def _parse_ndjson(text: str) -> List[dict]:
    return [json.loads(line) for line in text.split("\n") if line.strip()]


def _ensure_stream_registry():
    from backend.api.chat_stream_registry import StreamRegistry

    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()


async def _run_failing_session(title: str, error: str) -> tuple:
    """跑一轮必然失败的 run，返回 (session_id, SSE 原始响应体)。"""
    _ensure_stream_registry()
    from backend.data.session_repo import SessionRepository

    repo = SessionRepository()
    session = repo.create(title=title)
    session_id = session.id

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(state=AgentState.FAILED, iteration=0, error=error)

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Sage-Local-Authorization": "Bearer test-local-auth-token"},
        ) as ac:
            create_resp = await ac.post(
                CHAT_STREAM_PATH,
                json={"session_id": session_id, "message": "hi"},
            )
            assert create_resp.status_code == 200
            stream_id = create_resp.json()["streamId"]

            attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
            assert attach_resp.status_code == 200
            body = attach_resp.text

    return session_id, body


@pytest.mark.asyncio()
async def test_failed_event_reason_is_persisted_with_limit():
    """迭代超限 → last_error 落真实原因 + 上限值，不是 "运行失败"。"""
    from backend.data.session_repo import SessionRepository

    error = "max_iterations_exceeded (limit=25)"
    session_id, body = await _run_failing_session("迭代超限", error)

    # 1) SSE 下发的 failed 事件携带完整错误串
    events = _parse_ndjson(body)
    failed_events = [
        e for e in events if e.get("state") == "failed" and isinstance(e.get("error"), str)
    ]
    assert failed_events, f"未收到 failed 事件: {events}"
    assert any("limit=25" in e["error"] for e in failed_events), failed_events

    # 2) 3) last_error 落真实原因（含上限），不是笼统文案
    updated = SessionRepository().get(session_id)
    assert updated is not None
    assert updated.run_status == "failed"
    assert updated.last_error == error
    assert "limit=25" in (updated.last_error or "")
    assert "运行失败" not in (updated.last_error or "")


@pytest.mark.asyncio()
async def test_tool_budget_failure_reason_is_persisted_with_limit():
    """工具预算耗尽 → last_error 同样携带上限值。"""
    from backend.data.session_repo import SessionRepository

    error = "tool_budget_exceeded (limit=100)"
    session_id, body = await _run_failing_session("工具预算耗尽", error)

    events = _parse_ndjson(body)
    failed_events = [
        e for e in events if e.get("state") == "failed" and isinstance(e.get("error"), str)
    ]
    assert failed_events, f"未收到 failed 事件: {events}"
    assert any("limit=100" in e["error"] for e in failed_events), failed_events

    updated = SessionRepository().get(session_id)
    assert updated is not None
    assert updated.run_status == "failed"
    assert updated.last_error == error
    assert "limit=100" in (updated.last_error or "")
