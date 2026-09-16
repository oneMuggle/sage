"""
agent.run_loop() STEP_DONE 事件验证 (2026-09 step-by-step)

验证 SageAgent.run_loop() 在每个工具调用迭代结束后产出 STEP_DONE 事件:

1. 单工具调用 + 最终文本:1 个 STEP_DONE(step_index=0)
2. 多工具调用(连续 2 次):2 个 STEP_DONE(step_index=0, 1)
3. STEP_DONE 在 OBSERVING 之后、下一个迭代的 THINKING 之前
4. 单步纯文本(无工具调用):无 STEP_DONE
5. STEP_DONE.step_index 与 iteration 对齐
6. to_dict() 序列化包含 step_index 字段
"""

from __future__ import annotations

from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.tools.base import ToolResult

pytestmark = pytest.mark.unit


def _make_response(content: str = "", tool_calls: list = None) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
    )


def _make_tool_call(call_id: str, name: str = "calculator", args: str = '{"expression": "1+1"}') -> LLMToolCall:
    return LLMToolCall(id=call_id, name=name, arguments=args)


def _patch_tool_registry(agent: SageAgent, success: bool = True, content=None, error: str | None = None):
    """给 agent.tool_registry.get 装一个总是返回成功 ToolResult 的 mock。"""
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=ToolResult(
            success=success,
            content=content if content is not None else {"result": 42},
            error=error,
        )
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)
    return mock_tool


async def _collect_events(agent: SageAgent, messages, **run_kwargs) -> List[AgentEvent]:
    events = []
    async for evt in agent.run_loop(messages, **run_kwargs):
        events.append(evt)
    return events


def _step_done_events(events: List[AgentEvent]) -> List[AgentEvent]:
    return [e for e in events if e.state == AgentState.STEP_DONE]


# =============================================================================
# 1. 单工具调用 + 最终文本
# =============================================================================


@pytest.mark.asyncio()
async def test_run_loop_yields_one_step_done_after_single_tool_iteration():
    """LLM 调用 1 次(带 tool_calls)→ ACTING/OBSERVING → STEP_DONE。
    然后 LLM 调用 2 次(纯文本)→ DONE。不再 yield STEP_DONE。
    """
    tool_call = _make_tool_call("call_1")
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[tool_call]),
            _make_response(content="最终回答"),
        ]
    )
    _patch_tool_registry(agent)

    events = await _collect_events(agent, [{"role": "user", "content": "hi"}])

    step_dones = _step_done_events(events)
    assert len(step_dones) == 1, f"expected exactly 1 STEP_DONE, got {len(step_dones)}: {[e.state for e in events]}"
    # step_index 与 iteration 对齐
    assert step_dones[0].step_index == 0
    assert step_dones[0].iteration == 0


# =============================================================================
# 2. 多步(2 轮工具调用 + 最终文本)
# =============================================================================


@pytest.mark.asyncio()
async def test_run_loop_yields_step_done_per_iteration_in_multi_step_run():
    """LLM 调用 3 次:iter0 tool, iter1 tool, iter2 文本 → 2 个 STEP_DONE。"""
    tc_a = _make_tool_call("call_a")
    tc_b = _make_tool_call("call_b")
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[tc_a]),
            _make_response(content="", tool_calls=[tc_b]),
            _make_response(content="最终"),
        ]
    )
    _patch_tool_registry(agent)

    events = await _collect_events(agent, [{"role": "user", "content": "x"}])

    step_dones = _step_done_events(events)
    assert len(step_dones) == 2, f"expected 2 STEP_DONE, got {len(step_dones)}: {[e.state for e in events]}"
    # step_index 严格按 0, 1 递增
    assert [e.step_index for e in step_dones] == [0, 1]
    assert [e.iteration for e in step_dones] == [0, 1]


# =============================================================================
# 3. STEP_DONE 出现在 OBSERVING 之后、下一个 THINKING 之前
# =============================================================================


@pytest.mark.asyncio()
async def test_step_done_emitted_after_observing_before_next_thinking():
    """验证事件顺序:OBSERVING → STEP_DONE → (下一个迭代的)THINKING。"""
    tc_a = _make_tool_call("call_a")
    tc_b = _make_tool_call("call_b")
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[tc_a]),
            _make_response(content="", tool_calls=[tc_b]),
            _make_response(content="done"),
        ]
    )
    _patch_tool_registry(agent)

    events = await _collect_events(agent, [{"role": "user", "content": "x"}])

    states = [e.state for e in events]

    first_observing_idx = states.index(AgentState.OBSERVING)
    first_step_done_idx = states.index(AgentState.STEP_DONE)
    assert first_observing_idx < first_step_done_idx

    second_step_done_idx = states.index(AgentState.STEP_DONE, first_step_done_idx + 1)
    assert second_step_done_idx > first_step_done_idx

    done_idx = states.index(AgentState.DONE)
    assert done_idx > second_step_done_idx


# =============================================================================
# 4. 单步纯文本:不 yield STEP_DONE
# =============================================================================


@pytest.mark.asyncio()
async def test_no_step_done_when_run_has_no_tool_calls():
    """纯文本回答(无 tool_calls)直接到 DONE,不应有 STEP_DONE 插在中间。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(content="纯文本"))

    events = await _collect_events(agent, [{"role": "user", "content": "hi"}])

    step_dones = _step_done_events(events)
    assert step_dones == []
    assert any(e.state == AgentState.DONE for e in events)


# =============================================================================
# 5. STEP_DONE.step_index == iteration(对齐)
# =============================================================================


@pytest.mark.asyncio()
async def test_step_done_step_index_aligns_with_iteration():
    """STEP_DONE 的 step_index 与同一迭代的 iteration 字段对齐。"""
    tc1 = _make_tool_call("call_1")
    tc2 = _make_tool_call("call_2")
    tc3 = _make_tool_call("call_3")
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[tc1]),
            _make_response(content="", tool_calls=[tc2]),
            _make_response(content="", tool_calls=[tc3]),
            _make_response(content="final"),
        ]
    )
    _patch_tool_registry(agent)

    events = await _collect_events(agent, [{"role": "user", "content": "x"}], max_iterations=10)

    step_dones = _step_done_events(events)
    assert len(step_dones) == 3
    for evt in step_dones:
        assert evt.step_index == evt.iteration
    assert [e.step_index for e in step_dones] == [0, 1, 2]


# =============================================================================
# 6. STEP_DONE 事件 to_dict() 包含 step_index
# =============================================================================


def test_step_done_event_to_dict_includes_step_index():
    """AgentEvent.to_dict() 在 state=step_done 时携带 step_index。"""
    evt = AgentEvent(
        state=AgentState.STEP_DONE,
        iteration=2,
        step_index=2,
        agent_id="agent-1",
    )
    d = evt.to_dict()
    assert d["state"] == "step_done"
    assert d["step_index"] == 2
    assert d["iteration"] == 2


# =============================================================================
# 7. STEP_DONE 的 agent_id 透传(多 agent 场景)
# =============================================================================


@pytest.mark.asyncio()
async def test_step_done_carries_agent_id():
    """STEP_DONE 携带 agent_id,与 DONE/FAILED 一致,用于前端区分多 agent run。"""
    tc = _make_tool_call("call_1")
    agent = SageAgent()
    # SageAgent 仅在 DB profile 命中时才设 self.agent_id;测试里手动注入
    # agent_id 不依赖 DB fixture
    agent.agent_id = "planner-1"
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=[
            _make_response(content="", tool_calls=[tc]),
            _make_response(content="done"),
        ]
    )
    _patch_tool_registry(agent)

    events = await _collect_events(agent, [{"role": "user", "content": "x"}])

    step_dones = _step_done_events(events)
    assert len(step_dones) == 1
    assert step_dones[0].agent_id == "planner-1"