# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""L7 run_loop 守卫（每-run 工具调用数上限 + 参数 JSON 解析错误回传）单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall

pytestmark = pytest.mark.unit


def _mock_llm_with_tool_calls(responses: list) -> MagicMock:
    """按序返回预置响应的 LLM mock（非流式路径,MagicMock 使 _should_stream 为 False）。"""
    mock_client = MagicMock()
    mock_client.chat = AsyncMock(side_effect=responses)
    return mock_client


@pytest.mark.asyncio()
async def test_run_loop_aborts_when_tool_budget_exceeded(monkeypatch):
    """工具调用数超过上限 → FAILED("tool_budget_exceeded")，不再执行后续工具。"""
    monkeypatch.setenv("SAGE_MAX_TOOL_CALLS_PER_RUN", "2")

    # 第 1 轮 2 个工具调用（正好用完预算）,第 2 轮再发 1 个（超限）,
    # 第 3 轮本应给 DONE——但守卫应在第 2 轮的第 3 个调用处终止。
    round1 = LLMResponse(content="", tool_calls=[
        LLMToolCall(id="c1", name="calculator", arguments='{"expression": "1+1"}'),
        LLMToolCall(id="c2", name="calculator", arguments='{"expression": "2+2"}'),
    ])
    round2 = LLMResponse(content="", tool_calls=[
        LLMToolCall(id="c3", name="calculator", arguments='{"expression": "3+3"}'),
    ])
    final = LLMResponse(content="done")
    llm = _mock_llm_with_tool_calls([round1, round2, final])

    agent = SageAgent()
    agent.llm_client = llm

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    assert events[-1].state.value == "failed"
    assert events[-1].error == "tool_budget_exceeded"
    # LLM 只被调用 2 次（第 2 轮工具执行超限即终止,不再进第 3 轮）
    assert llm.chat.await_count == 2


@pytest.mark.asyncio()
async def test_run_loop_within_budget_completes(monkeypatch):
    """未超预算的正常多工具会话不受影响。"""
    monkeypatch.setenv("SAGE_MAX_TOOL_CALLS_PER_RUN", "25")
    round1 = LLMResponse(content="", tool_calls=[
        LLMToolCall(id="c1", name="calculator", arguments='{"expression": "1+1"}'),
    ])
    final = LLMResponse(content="done")
    llm = _mock_llm_with_tool_calls([round1, final])

    agent = SageAgent()
    agent.llm_client = llm

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    assert events[-1].state.value == "done"
    assert events[-1].content == "done"


@pytest.mark.asyncio()
async def test_invalid_json_args_returned_as_error_result():
    """arguments 非法 JSON → is_error 工具结果回传 LLM + tool 消息,循环继续。"""
    bad_call = LLMResponse(content="", tool_calls=[
        LLMToolCall(id="c1", name="calculator", arguments='{"expression": 1+1}'),  # 非法 JSON
    ])
    final = LLMResponse(content="recovered")
    llm = _mock_llm_with_tool_calls([bad_call, final])

    agent = SageAgent()
    agent.llm_client = llm

    events = []
    messages = [{"role": "user", "content": "x"}]
    async for evt in agent.run_loop(messages):
        events.append(evt)

    # 出现过 is_error 的 OBSERVING 事件,最终仍然 DONE
    observing = [e for e in events if e.state.value == "observing" and e.tool_result]
    assert any(r.is_error for e in observing for r in [e.tool_result])
    assert "不是合法 JSON" in observing[0].tool_result.content
    assert events[-1].state.value == "done"
    assert events[-1].content == "recovered"
    # tool 消息进了上下文（LLM 能看到错误并修正）
    tool_messages = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert "不是合法 JSON" in tool_messages[0]["content"]


def test_effective_budget_env_override(monkeypatch):
    monkeypatch.setenv("SAGE_MAX_TOOL_CALLS_PER_RUN", "7")
    agent = SageAgent()
    assert agent._effective_max_tool_calls_per_run() == 7

    monkeypatch.setenv("SAGE_MAX_TOOL_CALLS_PER_RUN", "garbage")
    assert agent._effective_max_tool_calls_per_run() >= 1
