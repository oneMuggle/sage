"""
M5 — AgentTool (in-loop sub-agent) unit tests.

- mocked LLM sub-agent → answer returned + lane created SUCCEEDED
- sub-agent tool whitelist is strictly read-only (no terminal/write/agent)
- sub-agent attempting terminal → registry rejects (tool not found), loop recovers
- LLM failure → error ToolResult, caller (primary loop) continues
- output cap (20_000 chars) enforced
- no LLM configured → clean error ToolResult
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.models import LaneStatus
from backend.tools.agent_tool import (
    SUBAGENT_ANSWER_CAP,
    AgentTool,
    build_readonly_tool_registry,
)
from backend.tools.base import ToolResult


def _done_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, finish_reason="stop", tool_calls=[])


def _tool_call_response(name: str, arguments: dict) -> LLMResponse:
    return LLMResponse(
        content="",
        finish_reason="tool_calls",
        tool_calls=[LLMToolCall(id="call_1", name=name, arguments=json.dumps(arguments))],
    )


def _mock_sub_llm(*responses: LLMResponse) -> MagicMock:
    """Mock LLM client: run_loop calls ``client.chat(...)``."""
    client = MagicMock()
    client.chat = AsyncMock(side_effect=list(responses))
    return client


class TestReadonlyWhitelist:
    def test_whitelist_is_read_only(self):
        """Registry exposes exactly the six read-only tools — nothing else."""
        registry = build_readonly_tool_registry()

        names = set(registry.list_names())
        assert names == {
            "read_file",
            "list_dir",
            "web_search",
            "web_fetch",
            "memory_search",
            "calculator",
        }
        # Never granted to sub-agents.
        for dangerous in ("terminal", "write_file", "memory_save", "agent", "office_read"):
            assert registry.get(dangerous) is None


class TestAgentToolExecution:
    def test_success_returns_answer_and_creates_succeeded_lane(self):
        tool = AgentTool(llm_client=_mock_sub_llm(_done_response("sub answer: 42")))

        result = tool.execute(description="Compute answer", prompt="What is 6*7?")

        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.content["answer"] == "sub answer: 42"
        assert result.content["truncated"] is False

        lane = LaneRegistry().get_lane(result.content["lane_id"])
        assert lane is not None
        assert lane.status == LaneStatus.SUCCEEDED
        assert lane.agent_id == "subagent"
        assert lane.metadata.get("source") == "subagent"

    def test_subagent_terminal_call_rejected_and_loop_recovers(self):
        """Sub LLM tries terminal → not registered → error fed back, loop DONEs."""
        sub_llm = _mock_sub_llm(
            _tool_call_response("terminal", {"command": "rm -rf /"}),
            _done_response("recovered answer"),
        )
        tool = AgentTool(llm_client=sub_llm)

        result = tool.execute(description="Naughty", prompt="do something")

        # The loop survived the rejected tool call and still produced an answer.
        assert result.success is True
        assert result.content["answer"] == "recovered answer"
        # Two LLM turns: the tool-call attempt and the recovery.
        assert sub_llm.chat.await_count == 2
        lane = LaneRegistry().get_lane(result.content["lane_id"])
        assert lane.status == LaneStatus.SUCCEEDED

    def test_llm_failure_returns_error_result_and_failed_lane(self):
        sub_llm = MagicMock()
        sub_llm.chat = AsyncMock(side_effect=RuntimeError("llm exploded"))
        tool = AgentTool(llm_client=sub_llm)

        result = tool.execute(description="Failing task", prompt="anything")

        assert result.success is False
        assert "llm exploded" in result.error
        assert "subagent_failed" in result.error
        # Lane recorded as FAILED but exists — board shows the failed run.
        lane = LaneRegistry().get_lane(result.content["lane_id"])
        assert lane.status == LaneStatus.FAILED
        assert lane.error is not None

    def test_missing_params_rejected_without_lane(self):
        tool = AgentTool(llm_client=_mock_sub_llm(_done_response("x")))

        result = tool.execute(description="", prompt="")

        assert result.success is False
        assert "non-empty" in result.error
        # No lane created for a validation failure.
        assert LaneRegistry().list_all_lanes() == []

    def test_no_llm_configured_clean_error(self, monkeypatch):
        monkeypatch.setattr(
            "backend.tools.agent_tool.build_llm_client_from_settings", lambda: None
        )
        tool = AgentTool()  # no injected client, factory yields None

        result = tool.execute(description="No LLM", prompt="task")

        assert result.success is False
        assert "no_llm_configured" in result.error
        assert LaneRegistry().list_all_lanes() == []

    def test_answer_capped_at_limit(self):
        long_answer = "x" * (SUBAGENT_ANSWER_CAP + 10_000)
        tool = AgentTool(llm_client=_mock_sub_llm(_done_response(long_answer)))

        result = tool.execute(description="Verbose", prompt="be verbose")

        assert result.success is True
        assert len(result.content["answer"]) == SUBAGENT_ANSWER_CAP
        assert result.content["truncated"] is True

    def test_subagent_factory_injection_used(self):
        """Custom factory (test seam) receives the restricted registry."""
        captured = {}

        class _FakeSubagent:
            def __init__(self, registry):
                captured["registry"] = registry
                self.llm_client = None

            async def run_loop(self, messages, max_iterations=None):
                from backend.core.legacy.agent_state import AgentEvent, AgentState

                yield AgentEvent(state=AgentState.DONE, content="fake answer")

        tool = AgentTool(
            llm_client=_mock_sub_llm(_done_response("unused")),
            subagent_factory=lambda registry: _FakeSubagent(registry),
        )

        result = tool.execute(description="Factory", prompt="task")

        assert result.success is True
        assert result.content["answer"] == "fake answer"
        assert "terminal" not in captured["registry"].list_names()
