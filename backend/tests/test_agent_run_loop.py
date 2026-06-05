"""
agent.run_loop() 状态机测试

验证 SageAgent.run_loop():
1. LLM 返回纯文本时，状态机经过 THINKING → DONE
2. LLM 返回工具调用时，状态机经过 THINKING → ACTING → OBSERVING → THINKING → DONE
3. max_iterations 限制：超过时发出 FAILED 事件
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.agent import SageAgent
from backend.core.agent_state import AgentState
from backend.core.llm_client import LLMResponse, LLMToolCall


def _make_response(content: str = "", tool_calls: list = None) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
    )


@pytest.mark.asyncio()
async def test_run_loop_returns_done_when_no_tool_call():
    """LLM 返回纯文本时，状态机经过 THINKING → DONE。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(content="你好"))

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "hi"}]):
        events.append(evt)

    states = [e.state for e in events]
    assert AgentState.THINKING in states
    assert AgentState.DONE in states
    done_evt = next(e for e in events if e.state == AgentState.DONE)
    assert done_evt.content == "你好"


@pytest.mark.asyncio()
async def test_run_loop_executes_tool_and_observes():
    """LLM 返回工具调用时，状态机经过 THINKING → ACTING → OBSERVING → THINKING → DONE。"""
    tool_call = LLMToolCall(
        id="call_1",
        name="calculator",
        arguments='{"expression": "1+1"}',
    )
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(side_effect=[
        _make_response(content="", tool_calls=[tool_call]),
        _make_response(content="答案是 2"),
    ])

    # 替换 tool_registry.get
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(return_value=MagicMock(
        success=True,
        content={"result": 2},
        error=None,
    ))
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "1+1 等于几"}]):
        events.append(evt)

    states = [e.state for e in events]
    assert AgentState.ACTING in states
    assert AgentState.OBSERVING in states
    assert AgentState.DONE in states


@pytest.mark.asyncio()
async def test_run_loop_respects_max_iterations():
    """max_iterations=2 时，应发出 FAILED。"""
    tool_call = LLMToolCall(id="c", name="calculator", arguments="{}")
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(tool_calls=[tool_call]))

    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(return_value=MagicMock(success=True, content={}, error=None))
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}], max_iterations=2):
        events.append(evt)

    failed = [e for e in events if e.state == AgentState.FAILED]
    assert len(failed) == 1
    assert failed[0].error == "max_iterations_exceeded"
