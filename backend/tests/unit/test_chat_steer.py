"""RT5 (round7) — 单 agent steering 测试。

覆盖两层：
- agent 层：inject_user_message 的运行窗口语义 + run_loop 迭代边界消费
- 端点层：POST /api/v1/chat/steer 的 200/404/409/400 面
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import ASGITransport

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall

pytestmark = pytest.mark.unit


def _make_response(content: str = "", tool_calls: list = None) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=tool_calls or [])


# ---- agent 层 -----------------------------------------------------------------


def test_inject_rejected_when_run_not_active():
    agent = SageAgent()
    assert agent.inject_user_message("补充指示") is False
    assert len(agent._pending_user_messages) == 0


def test_inject_rejects_blank_content():
    agent = SageAgent()
    agent._run_loop_active = True
    assert agent.inject_user_message("   ") is False


@pytest.mark.asyncio()
async def test_steering_consumed_at_iteration_boundary():
    """run 中注入的消息在下一迭代边界以【用户补充】前缀进入 LLM 上下文。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    tool_call = LLMToolCall(id="c1", name="calculator", arguments="{}")
    calls = {"n": 0}

    async def _chat(messages, tools=None):
        calls["n"] += 1
        if calls["n"] == 1:
            # run 活跃窗口内注入 → 下一迭代边界（LLM 调用 2 之前）被消费
            agent.inject_user_message("改用方法 B")
            return _make_response(content="", tool_calls=[tool_call])
        return _make_response(content="done")

    agent.llm_client.chat = AsyncMock(side_effect=_chat)

    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(return_value=MagicMock(success=True, content={}, error=None))
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    messages = [{"role": "user", "content": "开始"}]
    events = []
    async for evt in agent.run_loop(messages, max_iterations=3):
        events.append(evt)

    assert AgentState.DONE in [e.state for e in events]
    injected = [
        m for m in messages if m.get("role") == "user" and "改用方法 B" in str(m.get("content"))
    ]
    assert len(injected) == 1
    assert injected[0]["content"].startswith("【用户补充】")


@pytest.mark.asyncio()
async def test_steer_window_narrows_after_run():
    """run 结束后 inject 拒绝；run 启动时清空残留（不跨 run 泄漏）。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(content="ok"))

    agent._pending_user_messages.append("上一 run 的遗留")
    messages = [{"role": "user", "content": "hi"}]
    async for _ in agent.run_loop(messages):
        pass

    assert agent._run_loop_active is False
    assert len(agent._pending_user_messages) == 0
    assert agent.inject_user_message("晚了") is False
    assert not any("遗留" in str(m.get("content")) for m in messages)


# ---- 端点层 --------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_steer_endpoint_injects_into_registered_stream(monkeypatch):
    from backend.api import legacy_routes as lr
    from backend.main import app

    agent = SageAgent()
    agent._run_loop_active = True
    monkeypatch.setitem(lr._ACTIVE_STREAMS, "s1", {"agent": agent, "run_id": None})

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/chat/steer", json={"stream_id": "s1", "content": "用方法 B"}
        )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert list(agent._pending_user_messages) == ["用方法 B"]
    assert agent.inject_user_message("校验入队") is True  # 窗口仍开着
    assert len(agent._pending_user_messages) == 2


@pytest.mark.asyncio()
async def test_steer_endpoint_404_for_unknown_stream():
    from backend.main import app

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/chat/steer", json={"stream_id": "missing", "content": "hi"}
        )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "stream_not_found"


@pytest.mark.asyncio()
async def test_steer_endpoint_409_when_not_running(monkeypatch):
    from backend.api import legacy_routes as lr
    from backend.main import app

    agent = SageAgent()  # 未在 run 窗口
    monkeypatch.setitem(lr._ACTIVE_STREAMS, "s2", {"agent": agent, "run_id": None})

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/chat/steer", json={"stream_id": "s2", "content": "hi"}
        )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "not_running"


@pytest.mark.asyncio()
async def test_steer_endpoint_400_for_blank_and_oversize(monkeypatch):
    from backend.api import legacy_routes as lr
    from backend.main import app

    agent = SageAgent()
    agent._run_loop_active = True
    monkeypatch.setitem(lr._ACTIVE_STREAMS, "s3", {"agent": agent, "run_id": None})

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        blank = await client.post(
            "/api/v1/chat/steer", json={"stream_id": "s3", "content": "   "}
        )
        oversize = await client.post(
            "/api/v1/chat/steer", json={"stream_id": "s3", "content": "x" * 8193}
        )
    assert blank.status_code == 400
    assert blank.json()["detail"]["code"] == "empty_content"
    assert oversize.status_code == 400
    assert oversize.json()["detail"]["code"] == "msg_too_long"
