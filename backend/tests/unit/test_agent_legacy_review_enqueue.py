"""M1 技能页草稿链路修复: legacy run_loop 的 Background Review 入队 parity。

hex ChatService 在 ``tool_calls_used >= 2`` 时入队 ``complex_turn``,legacy
路径此前缺这段(默认 ``API_MODE=legacy`` 下待审草稿因此恒为空)。
本次补丁把同一阈值搬到 ``SageAgent.run_loop`` DONE 分支,best-effort 降级。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall

pytestmark = pytest.mark.unit


def _tool_response(name: str, expression: str = "1+1") -> LLMResponse:
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


def _text_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[])


def _make_agent(side_effects: list) -> SageAgent:
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(side_effect=side_effects)
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=MagicMock(success=True, content={"result": 2}, error=None)
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)
    return agent


async def _collect(agent: SageAgent, session_id: str = "session-test"):
    messages = [{"role": "user", "content": "hi"}]
    events = []
    async for evt in agent.run_loop(messages, session_id=session_id):
        events.append(evt)
    return events


class TestLegacyReviewEnqueue:
    @pytest.mark.asyncio()
    async def test_enqueues_complex_turn_with_two_non_skill_tool_calls(
        self, monkeypatch
    ):
        """>=2 非技能工具调用 + 正常 DONE → 入队 complex_turn"""
        enqueue_mock = MagicMock()
        monkeypatch.setattr(
            "backend.skills.review_queue.get_review_queue",
            lambda: MagicMock(enqueue=enqueue_mock),
        )

        agent = _make_agent(
            [
                _tool_response("bash", "ls"),
                _tool_response("read_file", "x.py"),
                _text_response("done"),
            ]
        )
        events = await _collect(agent)
        assert any(e.state == AgentState.DONE for e in events)
        assert enqueue_mock.call_count == 1
        kwargs = enqueue_mock.call_args.kwargs
        assert kwargs["trigger_type"] == "complex_turn"
        assert kwargs["session_id"] == "session-test"
        assert kwargs["context"]["tool_call_count"] == 2
        assert kwargs["context"]["api_mode"] == "legacy"
        assert kwargs["context"]["needs_screening"] is True  # 2 < 4

    @pytest.mark.asyncio()
    async def test_skips_when_only_one_tool_call(self, monkeypatch):
        """单工具调用 < 阈值 2 → 不入队"""
        enqueue_mock = MagicMock()
        monkeypatch.setattr(
            "backend.skills.review_queue.get_review_queue",
            lambda: MagicMock(enqueue=enqueue_mock),
        )
        agent = _make_agent(
            [_tool_response("bash", "ls"), _text_response("done")]
        )
        await _collect(agent)
        assert enqueue_mock.call_count == 0

    @pytest.mark.asyncio()
    async def test_skips_when_only_skill_and_learn_tools(self, monkeypatch):
        """整轮只围绕 skill/skill_save/learn → 不入队(类比 hex activation_block)"""
        enqueue_mock = MagicMock()
        monkeypatch.setattr(
            "backend.skills.review_queue.get_review_queue",
            lambda: MagicMock(enqueue=enqueue_mock),
        )
        agent = _make_agent(
            [
                _tool_response("skill", "search"),
                _tool_response("skill_save", "x"),
                _tool_response("learn", "x"),
                _text_response("done"),
            ]
        )
        await _collect(agent)
        assert enqueue_mock.call_count == 0

    @pytest.mark.asyncio()
    async def test_enqueue_failure_does_not_break_run(self, monkeypatch):
        """入队异常 best-effort 静默降级,run 仍正常 DONE"""

        class FailingQueue:
            def enqueue(self, *a, **k):
                raise RuntimeError("simulated db locked")

        monkeypatch.setattr(
            "backend.skills.review_queue.get_review_queue", lambda: FailingQueue()
        )
        agent = _make_agent(
            [
                _tool_response("bash", "ls"),
                _tool_response("read_file", "x.py"),
                _text_response("final answer"),
            ]
        )
        events = await _collect(agent)
        states = [e.state for e in events]
        assert AgentState.DONE in states
        done_event = next(e for e in events if e.state == AgentState.DONE)
        assert done_event.content == "final answer"

    @pytest.mark.asyncio()
    async def test_skips_when_session_id_is_none(self, monkeypatch):
        """session_id 缺失时不入队(无法归因会话)"""
        enqueue_mock = MagicMock()
        monkeypatch.setattr(
            "backend.skills.review_queue.get_review_queue",
            lambda: MagicMock(enqueue=enqueue_mock),
        )
        agent = _make_agent(
            [
                _tool_response("bash", "ls"),
                _tool_response("read_file", "x.py"),
                _text_response("done"),
            ]
        )
        messages = [{"role": "user", "content": "hi"}]
        async for _ in agent.run_loop(messages, session_id=None):
            pass
        assert enqueue_mock.call_count == 0
