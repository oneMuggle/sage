"""Tests for required-argument validation in SageAgent.run_loop.

Verifies that when the LLM issues a tool call missing required parameters
(as declared in the tool's schema), the agent loop:

1. Returns a friendly ``[参数错误]`` message instead of a raw Python TypeError
2. Does NOT execute the tool (no ACTING event emitted)
3. Feeds the error back as an is_error tool result so the LLM can retry
4. Also catches the case where ``arguments`` parses to a non-dict (list/scalar)
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.permissions import PermissionEnforcer, PermissionMode


# ── Test fixtures ──────────────────────────────────────────────────────────


class _OfficeReadStub(BaseTool):
    """Minimal stub mirroring OfficeReadTool's required-parameter shape.

    ``doc_id`` is required (matches the real schema); the stub's execute()
    never runs in these tests — the validation block must intercept first.
    """

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_read",
            description="Stub office_read for required-arg tests.",
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "section": {"type": "string", "default": "summary"},
                },
                "required": ["doc_id"],
            },
        )

    def execute(self, doc_id: str, section: str = "summary", **kwargs: Any) -> ToolResult:
        # If this runs, the validation failed to intercept.
        return ToolResult(success=True, content={"doc_id": doc_id})


class _NoRequiredTool(BaseTool):
    """Tool with empty required list — should never be blocked."""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_list",
            description="Stub office_list (no required params).",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": [],
            },
        )

    def execute(self, query: Optional[str] = None, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, content={"items": []})


class _MultiRequiredTool(BaseTool):
    """Tool with multiple required parameters."""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_lint",
            description="Stub with two required params.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "format_spec": {"type": "object"},
                },
                "required": ["file_path", "format_spec"],
            },
        )

    def execute(self, file_path: str, format_spec: Dict, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, content={"ok": True})


def _make_agent_with_llm(side_effect_responses):
    """Build a SageAgent with a mocked LLM client returning queued responses.

    The default SageAgent uses ``permission_enforcer=None`` and constructs one
    from settings in ``_build_permission_enforcer``. In the test environment
    no settings are loaded, so we inject an explicit ``FULL_ACCESS`` enforcer
    with no rules — all tool calls in these tests are stub-only (no real I/O)
    and the validation logic does not depend on permission semantics.
    """
    agent = SageAgent()
    agent.permission_enforcer = PermissionEnforcer(
        mode=PermissionMode.FULL_ACCESS, rules=[]
    )
    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=side_effect_responses)
    agent.llm_client = llm
    return agent


def _final_stop_turn(content: str = "done") -> LLMResponse:
    return LLMResponse(content=content, finish_reason="stop")


def _tool_call_turn(
    call_id: str, name: str, arguments: Any
) -> LLMResponse:
    """Build an LLMResponse that issues a single tool call.

    ``arguments`` is JSON-serialized (mirrors real LLM behavior).
    """
    return LLMResponse(
        content="",
        finish_reason="tool_calls",
        tool_calls=[
            LLMToolCall(
                id=call_id,
                name=name,
                arguments=json.dumps(arguments) if not isinstance(arguments, str) else arguments,
            )
        ],
    )


# ── Tests ──────────────────────────────────────────────────────────────────


class TestRequiredArgsValidation:
    @pytest.mark.asyncio()
    async def test_missing_required_arg_returns_friendly_error(self):
        """LLM calls office_read without doc_id → [参数错误] with missing list."""
        agent = _make_agent_with_llm([
            _tool_call_turn("call_1", "office_read", {"section": "all"}),
            _final_stop_turn(),
        ])
        agent.tool_registry.register(_OfficeReadStub())

        events = []
        async for event in agent.run_loop(
            messages=[{"role": "user", "content": "read doc"}],
            session_id="test-session",
        ):
            events.append(event)

        # Find the OBSERVING event with the error
        error_events = [
            e for e in events
            if e.state == AgentState.OBSERVING
            and getattr(e, "tool_result", None) is not None
            and e.tool_result.is_error
        ]
        assert len(error_events) == 1, (
            f"Expected exactly 1 error OBSERVING event, got {len(error_events)}"
        )
        error_content = error_events[0].tool_result.content
        assert "[参数错误]" in error_content
        assert "office_read" in error_content
        assert "doc_id" in error_content

        # Tool must NOT have been executed (no ACTING event for this call)
        acting_events = [
            e for e in events
            if e.state == AgentState.ACTING
            and getattr(e, "tool_call", None) is not None
            and e.tool_call.name == "office_read"
        ]
        assert len(acting_events) == 0, (
            "Tool should NOT have been executed when required arg is missing"
        )

    @pytest.mark.asyncio()
    async def test_all_required_args_present_tool_executes(self):
        """LLM provides all required args → tool executes normally."""
        agent = _make_agent_with_llm([
            _tool_call_turn("call_1", "office_read", {"doc_id": "abc-123"}),
            _final_stop_turn(),
        ])
        agent.tool_registry.register(_OfficeReadStub())

        events = []
        async for event in agent.run_loop(
            messages=[{"role": "user", "content": "read doc"}],
            session_id="test-session",
        ):
            events.append(event)

        # Tool should have been executed → ACTING event present
        acting_events = [
            e for e in events
            if e.state == AgentState.ACTING
            and getattr(e, "tool_call", None) is not None
            and e.tool_call.name == "office_read"
        ]
        assert len(acting_events) == 1, "Tool should have been executed"

        # No [参数错误] error
        error_events = [
            e for e in events
            if e.state == AgentState.OBSERVING
            and getattr(e, "tool_result", None) is not None
            and e.tool_result.is_error
            and "[参数错误]" in (e.tool_result.content or "")
        ]
        assert len(error_events) == 0, "Should not have parameter error when all args present"

    @pytest.mark.asyncio()
    async def test_no_required_schema_never_blocked(self):
        """Tool with required=[] is never blocked by validation."""
        agent = _make_agent_with_llm([
            _tool_call_turn("call_1", "office_list", {}),
            _final_stop_turn(),
        ])
        agent.tool_registry.register(_NoRequiredTool())

        events = []
        async for event in agent.run_loop(
            messages=[{"role": "user", "content": "list docs"}],
            session_id="test-session",
        ):
            events.append(event)

        acting_events = [
            e for e in events
            if e.state == AgentState.ACTING
            and getattr(e, "tool_call", None) is not None
            and e.tool_call.name == "office_list"
        ]
        assert len(acting_events) == 1, "Tool with no required params should execute"

    @pytest.mark.asyncio()
    async def test_multiple_required_partial_missing(self):
        """Tool with 2 required params, only 1 provided → error lists missing."""
        agent = _make_agent_with_llm([
            _tool_call_turn("call_1", "office_lint", {"file_path": "/tmp/test.docx"}),
            _final_stop_turn(),
        ])
        agent.tool_registry.register(_MultiRequiredTool())

        events = []
        async for event in agent.run_loop(
            messages=[{"role": "user", "content": "lint doc"}],
            session_id="test-session",
        ):
            events.append(event)

        error_events = [
            e for e in events
            if e.state == AgentState.OBSERVING
            and getattr(e, "tool_result", None) is not None
            and e.tool_result.is_error
        ]
        assert len(error_events) == 1
        error_content = error_events[0].tool_result.content
        assert "format_spec" in error_content, (
            f"Missing 'format_spec' should be in error: {error_content}"
        )

    @pytest.mark.asyncio()
    async def test_non_dict_arguments_returns_type_error(self):
        """LLM sends arguments as JSON array → friendly type error, not Python crash."""
        agent = _make_agent_with_llm([
            # LLM accidentally sends a list instead of an object
            _tool_call_turn("call_1", "office_read", "[1, 2, 3]"),
            _final_stop_turn(),
        ])
        agent.tool_registry.register(_OfficeReadStub())

        events = []
        async for event in agent.run_loop(
            messages=[{"role": "user", "content": "read doc"}],
            session_id="test-session",
        ):
            events.append(event)

        error_events = [
            e for e in events
            if e.state == AgentState.OBSERVING
            and getattr(e, "tool_result", None) is not None
            and e.tool_result.is_error
        ]
        assert len(error_events) == 1
        error_content = error_events[0].tool_result.content
        assert "[参数错误]" in error_content
        assert "object" in error_content or "list" in error_content

    @pytest.mark.asyncio()
    async def test_unknown_tool_not_blocked(self):
        """Unknown tool name → validation does not crash (schema_tool is None)."""
        agent = _make_agent_with_llm([
            _tool_call_turn("call_1", "nonexistent_tool", {"arg": "val"}),
            _final_stop_turn(),
        ])
        # Do NOT register any tool

        events = []
        async for event in agent.run_loop(
            messages=[{"role": "user", "content": "do something"}],
            session_id="test-session",
        ):
            events.append(event)

        # Should reach the "tool does not exist" error path, not the validation path
        error_events = [
            e for e in events
            if e.state == AgentState.OBSERVING
            and getattr(e, "tool_result", None) is not None
            and e.tool_result.is_error
        ]
        assert len(error_events) >= 1
        # The error should be "tool does not exist", not a parameter error
        all_error_contents = [e.tool_result.content for e in error_events]
        assert any("不存在" in c or "nonexistent" in c.lower() for c in all_error_contents), (
            f"Expected 'tool not found' error, got: {all_error_contents}"
        )
