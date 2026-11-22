"""M2: 后台子代理完成通知 —— 系统通知队列与迭代边界注入。

覆盖：
- 注入窗口关闭时拒绝
- 注入后以系统通知形态进入队列
- run_loop 迭代边界注入为 user 消息（带【后台子代理完成】/【后台子代理失败】前缀）
  且不产生 STEER_CONSUMED 事件、不落库为 steering 消息
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall

pytestmark = pytest.mark.unit


def _make_response(content: str = "", tool_calls: list = None) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=tool_calls or [])


def test_inject_system_note_rejected_when_window_closed():
    agent = SageAgent()
    assert agent.inject_system_note("后台子代理完成") is False
    assert len(agent._pending_system_notes) == 0


def test_inject_system_note_blank_rejected():
    agent = SageAgent()
    agent.begin_accept_steer()
    assert agent.inject_system_note("   ") is False


def test_inject_system_note_queued_when_window_open():
    agent = SageAgent()
    agent.begin_accept_steer()
    assert agent.inject_system_note("【后台子代理完成】调研结论") is True
    assert list(agent._pending_system_notes) == ["【后台子代理完成】调研结论"]


@pytest.mark.asyncio()
async def test_system_note_injected_at_iteration_boundary():
    agent = SageAgent()
    agent.begin_accept_steer()
    agent.llm_client = MagicMock()
    tool_call = LLMToolCall(id="c1", name="list_dir", arguments="{}")
    calls = {"n": 0}

    async def _chat(messages, tools=None, tool_choice=None, retry_callback=None):
        calls["n"] += 1
        if calls["n"] == 1:
            agent.inject_system_note("【后台子代理完成】找齐 3 篇资料")
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
        m
        for m in messages
        if m.get("role") == "user" and "找齐 3 篇资料" in str(m.get("content"))
    ]
    assert len(injected) == 1
    # 系统通知不进 steering 消费回执（避免前端暂存区误处理）
    assert not [e for e in events if e.state == AgentState.STEER_CONSUMED]
    # 队列被排空
    assert len(list(agent._pending_system_notes)) == 0
    # 未落库为 steering 用户消息（通知仅存在于本轮 LLM 上下文）
    agent._persist_consumed_steers = MagicMock()
    assert agent._persist_consumed_steers.call_count == 0
