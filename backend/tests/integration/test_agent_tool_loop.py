"""
M5 — integration: primary agent loop spawns a sub-agent via the `agent` tool.

run_loop with a mocked primary LLM issuing an ``agent`` tool call:
- a lane appears in the LaneRegistry (source=subagent) and ends SUCCEEDED
- the tool result fed back into the loop carries the sub-agent's answer
- the primary loop reaches DONE (both LLM clients mocked, distinguished via
  side_effect queues)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.models import LaneStatus
from backend.tools.agent_tool import AgentTool


def _primary_first_turn() -> LLMResponse:
    """Primary LLM decides to delegate via the agent tool."""
    return LLMResponse(
        content="",
        finish_reason="tool_calls",
        tool_calls=[
            LLMToolCall(
                id="call_primary_1",
                name="agent",
                arguments=json.dumps(
                    {
                        "description": "Compute the answer",
                        "prompt": "Figure out 6*7 and report the number.",
                    }
                ),
            )
        ],
    )


def _primary_final_turn() -> LLMResponse:
    """Primary LLM wraps up with the final answer."""
    return LLMResponse(content="The sub-agent computed 42.", finish_reason="stop")


def _sub_done_turn() -> LLMResponse:
    return LLMResponse(content="sub answer: 42", finish_reason="stop")


class TestAgentToolInRunLoop:
    @pytest.mark.asyncio()
    async def test_run_loop_spawns_subagent_lane_and_reaches_done(self):
        # Arrange — primary agent with mocked LLM (side_effect queue).
        agent = SageAgent()  # no llm_config; injected below
        primary_llm = MagicMock()
        primary_llm.chat = AsyncMock(
            side_effect=[_primary_first_turn(), _primary_final_turn()]
        )
        agent.llm_client = primary_llm

        # Register the agent tool with its OWN mocked sub LLM client.
        sub_llm = MagicMock()
        sub_llm.chat = AsyncMock(side_effect=[_sub_done_turn()])
        agent.tool_registry.register(AgentTool(llm_client=sub_llm))

        messages = [
            {"role": "system", "content": "You are Sage."},
            {"role": "user", "content": "What is 6*7? Delegate if needed."},
        ]

        # Act — drive the loop.
        events = [event async for event in agent.run_loop(messages, max_iterations=5)]

        # Assert — loop reached DONE with the final answer.
        terminal = [e for e in events if e.state == AgentState.DONE]
        assert len(terminal) == 1
        assert terminal[0].content == "The sub-agent computed 42."

        # The agent tool executed (ACTING + OBSERVING pair).
        acting = [
            e
            for e in events
            if e.state == AgentState.ACTING and e.tool_call and e.tool_call.name == "agent"
        ]
        observing = [
            e
            for e in events
            if e.state == AgentState.OBSERVING and e.tool_call and e.tool_call.name == "agent"
        ]
        assert len(acting) == 1
        assert len(observing) == 1

        # Tool result carries the sub-agent's answer + lane id.
        tool_result = observing[0].tool_result
        assert tool_result is not None
        assert tool_result.is_error is False
        payload = json.loads(tool_result.content)
        assert payload["answer"] == "sub answer: 42"
        lane_id = payload["lane_id"]

        # Lane appeared in the real LaneRegistry and succeeded.
        lane = LaneRegistry().get_lane(lane_id)
        assert lane is not None
        assert lane.status == LaneStatus.SUCCEEDED
        assert lane.metadata.get("source") == "subagent"
        assert lane.agent_id == "subagent"

        # Both LLMs used exactly their queued turns.
        assert primary_llm.chat.await_count == 2
        assert sub_llm.chat.await_count == 1

        # The sub-answer was fed back into the primary conversation.
        tool_messages = [m for m in messages if m["role"] == "tool"]
        assert len(tool_messages) == 1
        assert "sub answer: 42" in tool_messages[0]["content"]

    @pytest.mark.asyncio()
    async def test_run_loop_survives_subagent_failure(self):
        """Sub-agent LLM failure → error tool result, primary loop continues."""
        agent = SageAgent()
        primary_llm = MagicMock()
        primary_llm.chat = AsyncMock(
            side_effect=[_primary_first_turn(), _primary_final_turn()]
        )
        agent.llm_client = primary_llm

        failing_sub_llm = MagicMock()
        failing_sub_llm.chat = AsyncMock(side_effect=RuntimeError("sub llm down"))
        agent.tool_registry.register(AgentTool(llm_client=failing_sub_llm))

        messages = [
            {"role": "system", "content": "You are Sage."},
            {"role": "user", "content": "delegate something"},
        ]

        events = [event async for event in agent.run_loop(messages, max_iterations=5)]

        # Loop still DONEs — primary LLM saw the error and continued.
        assert any(e.state == AgentState.DONE for e in events)
        observing = [e for e in events if e.state == AgentState.OBSERVING]
        assert observing[0].tool_result.is_error is True
        assert "subagent_failed" in observing[0].tool_result.content

        # Failed lane recorded for board visibility.
        lanes = LaneRegistry().list_all_lanes()
        assert len(lanes) == 1
        assert lanes[0].status == LaneStatus.FAILED
