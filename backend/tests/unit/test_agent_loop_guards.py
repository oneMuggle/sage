"""run_loop 循环守卫测试（对标 hermes: empty_response / repetition_guard）

覆盖:
- B1 空响应守卫: 空响应后注入提示重试 / 重试耗尽兜底 DONE / 关闭开关
- B2 复读守卫: 软限注入 system 提醒 / 硬限拦截执行（合成错误 tool result）
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall

pytestmark = pytest.mark.unit


def _text_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[])


def _tool_response(name: str = "calculator", expression: str = "1+1") -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            LLMToolCall(
                id="call_1",
                name=name,
                arguments=json.dumps({"expression": expression}),
            )
        ],
    )


def _make_agent(side_effects) -> SageAgent:
    """构造 llm_client 按序返回 side_effects 的 agent（工具恒成功）"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(side_effect=side_effects)
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=MagicMock(success=True, content={"result": 2}, error=None)
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)
    return agent


async def _collect(agent, **kwargs):
    messages = [{"role": "user", "content": "hi"}]
    events = []
    async for evt in agent.run_loop(messages, **kwargs):
        events.append(evt)
    return events, messages


class TestEmptyResponseGuard:
    @pytest.mark.asyncio()
    async def test_empty_then_valid_retries_and_completes(self, monkeypatch):
        """空响应 → 注入提示重试 → 正常内容 DONE"""
        monkeypatch.setenv("SAGE_EMPTY_RESPONSE_MAX_RETRIES", "2")
        agent = _make_agent(
            [_text_response(""), _text_response("  "), _text_response("你好")]
        )
        events, messages = await _collect(agent)

        states = [e.state for e in events]
        assert AgentState.DONE in states
        done = next(e for e in events if e.state == AgentState.DONE)
        assert done.content == "你好"
        assert agent.llm_client.chat.call_count == 3
        # 注入了 system 提示
        assert any(
            m.get("role") == "system" and "响应内容为空" in m.get("content", "")
            for m in messages
        )

    @pytest.mark.asyncio()
    async def test_exhausted_retries_yields_fallback_done(self, monkeypatch):
        """重试耗尽 → DONE + 兜底文案（非 FAILED）"""
        monkeypatch.setenv("SAGE_EMPTY_RESPONSE_MAX_RETRIES", "1")
        agent = _make_agent([_text_response(""), _text_response("")])
        events, _ = await _collect(agent)

        states = [e.state for e in events]
        assert AgentState.FAILED not in states
        done = next(e for e in events if e.state == AgentState.DONE)
        assert "空响应" in done.content
        # 1 次初始 + 1 次重试
        assert agent.llm_client.chat.call_count == 2

    @pytest.mark.asyncio()
    async def test_guard_disabled_keeps_legacy_behavior(self, monkeypatch):
        """SAGE_EMPTY_RESPONSE_MAX_RETRIES=0 → 保持旧行为（空响应即 DONE）"""
        monkeypatch.setenv("SAGE_EMPTY_RESPONSE_MAX_RETRIES", "0")
        agent = _make_agent([_text_response("")])
        events, _ = await _collect(agent)

        assert agent.llm_client.chat.call_count == 1
        done = next(e for e in events if e.state == AgentState.DONE)
        assert done.content == ""


class TestRepetitionGuard:
    @pytest.mark.asyncio()
    async def test_soft_limit_injects_nudge(self, monkeypatch):
        """相同工具调用达软限 → messages 注入 system 提醒, 执行不中断"""
        monkeypatch.setenv("SAGE_TOOL_REPEAT_SOFT_LIMIT", "2")
        monkeypatch.setenv("SAGE_TOOL_REPEAT_HARD_LIMIT", "0")
        # 连续 3 次相同工具调用, 最后一次正常收尾
        agent = _make_agent(
            [
                _tool_response(),
                _tool_response(),
                _tool_response(),
                _text_response("完成"),
            ]
        )
        events, messages = await _collect(agent, max_iterations=8)

        assert AgentState.DONE in states_of(events)
        assert any(
            m.get("role") == "system" and "重复调用" in m.get("content", "")
            for m in messages
        )
        assert agent.tool_registry.get.return_value.execute.call_count == 3

    @pytest.mark.asyncio()
    async def test_hard_limit_intercepts_execution(self, monkeypatch):
        """相同工具调用达硬限 → 不执行, 返回合成错误 tool result"""
        monkeypatch.setenv("SAGE_TOOL_REPEAT_SOFT_LIMIT", "0")
        monkeypatch.setenv("SAGE_TOOL_REPEAT_HARD_LIMIT", "3")
        agent = _make_agent(
            [
                _tool_response(),
                _tool_response(),
                _tool_response(),
                _tool_response(),
                _tool_response(),
                _text_response("改为直接回答"),
            ]
        )
        events, messages = await _collect(agent, max_iterations=10)

        # 第 3 次起被拦截: 4 次调用中前 2 次执行, 后 2 次拦截
        assert agent.tool_registry.get.return_value.execute.call_count == 2
        intercepted = [
            e
            for e in events
            if e.state == AgentState.OBSERVING
            and e.tool_result
            and "拦截" in (e.tool_result.content or "")
        ]
        assert len(intercepted) >= 2
        assert all(e.tool_result.is_error for e in intercepted)
        assert any(
            m.get("role") == "tool" and "拦截" in m.get("content", "")
            for m in messages
        )
        assert AgentState.DONE in states_of(events)


def states_of(events):
    return [e.state for e in events]
