import pytest

from backend.core.legacy.agent_state import (
    AgentEvent,
    AgentState,
    ToolCallRequest,
    ToolCallResult,
)

pytestmark = pytest.mark.unit


def test_agent_state_enum_values():
    assert AgentState.IDLE.value == "idle"
    assert AgentState.THINKING.value == "thinking"
    assert AgentState.REASONING.value == "reasoning"  # 新增：reasoning 状态
    assert AgentState.ACTING.value == "acting"
    assert AgentState.OBSERVING.value == "observing"
    assert AgentState.DONE.value == "done"
    assert AgentState.FAILED.value == "failed"


def test_agent_event_thinking_creation():
    evt = AgentEvent(state=AgentState.THINKING, iteration=0)
    assert evt.state == AgentState.THINKING
    assert evt.iteration == 0
    assert evt.content is None
    assert evt.tool_call is None
    assert evt.error is None


def test_agent_event_done_has_content():
    evt = AgentEvent(state=AgentState.DONE, content="最终回答")
    assert evt.content == "最终回答"


def test_tool_call_request_serialization():
    tc = ToolCallRequest(id="call_1", name="calculator", arguments={"expression": "1+1"})
    d = tc.to_dict()
    assert d["id"] == "call_1"
    assert d["type"] == "function"
    assert d["function"]["name"] == "calculator"
    assert d["function"]["arguments"] == '{"expression": "1+1"}'


def test_tool_call_result_serialization():
    tr = ToolCallResult(tool_call_id="call_1", content="2", is_error=False)
    d = tr.to_dict()
    assert d == {
        "tool_call_id": "call_1",
        "role": "tool",
        "content": "2",
    }


def test_agent_event_reasoning_creation():
    """AgentEvent with REASONING state should carry reasoning content."""
    evt = AgentEvent(
        state=AgentState.REASONING,
        iteration=0,
        reasoning="Let me think about this step by step...",
    )
    assert evt.state == AgentState.REASONING
    assert evt.iteration == 0
    assert evt.reasoning == "Let me think about this step by step..."
    assert evt.content is None


def test_agent_event_reasoning_defaults_to_none():
    """AgentEvent.reasoning should default to None."""
    evt = AgentEvent(state=AgentState.THINKING, iteration=0)
    assert evt.reasoning is None


def test_agent_event_to_dict_includes_reasoning():
    """AgentEvent.to_dict() should include reasoning field when set."""
    evt = AgentEvent(
        state=AgentState.REASONING,
        iteration=1,
        reasoning="Analyzing the problem...",
    )
    d = evt.to_dict()
    assert d["state"] == "reasoning"
    assert d["iteration"] == 1
    assert d["reasoning"] == "Analyzing the problem..."


def test_agent_event_to_dict_excludes_reasoning_when_none():
    """AgentEvent.to_dict() should exclude reasoning field when None."""
    evt = AgentEvent(state=AgentState.DONE, iteration=0, content="Answer")
    d = evt.to_dict()
    assert "reasoning" not in d
    assert d["content"] == "Answer"
