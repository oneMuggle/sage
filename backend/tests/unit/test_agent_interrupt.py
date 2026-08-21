"""P0-1 — run_loop 中断检查：标志在每轮迭代顶部被消费（one-shot）。

旧行为: interrupt() 只置 _interrupted, is_interrupted() 全仓零调用者,
run_loop 从不读标志 → 中断请求完全无效。
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


@pytest.mark.asyncio()
async def test_pre_set_interrupt_flag_yields_failed_without_llm_call():
    """进循环前已置位 → 首个事件即 FAILED，LLM 一次都不调。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(content="不可能到达"))
    agent.interrupt()

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "hi"}]):
        events.append(evt)

    assert [e.state for e in events] == [AgentState.FAILED]
    assert events[0].error == "interrupted by user"
    agent.llm_client.chat.assert_not_called()
    # one-shot：标志被消费后复位，同一实例下一轮 run 不受影响
    assert agent.is_interrupted() is False


@pytest.mark.asyncio()
async def test_interrupt_between_iterations_stops_before_next_llm_call():
    """第 0 轮 LLM 返回 tool_calls（调用期间置位）→ 第 1 轮顶部 FAILED。"""
    tool_call = LLMToolCall(
        id="call_1", name="calculator", arguments='{"expression": "1+1"}'
    )
    agent = SageAgent()
    agent.llm_client = MagicMock()

    def _chat_and_set_flag(*args, **kwargs):
        agent.interrupt()  # 模拟：用户在本轮工具执行期间点了 interrupt
        return _make_response(tool_calls=[tool_call])

    agent.llm_client.chat = AsyncMock(side_effect=_chat_and_set_flag)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "hi"}]):
        events.append(evt)

    assert events[-1].state == AgentState.FAILED
    assert events[-1].error == "interrupted by user"
    # 只发生了第 0 轮的 LLM 调用；第 1 轮在 THINKING 之前就被拦截
    assert agent.llm_client.chat.await_count == 1
