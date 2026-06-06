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
