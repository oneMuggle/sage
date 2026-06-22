"""
测试 AgentState 状态机的取值、字符串继承与枚举成员。

注:`AgentState` 当前为简单 `str, Enum`,未提供 `initial()` / `can_transition_to()`。
该测试聚焦于:
- 枚举值与字符串互转(用于 NDJSON 流式响应)
- 完整状态机覆盖(确保新增状态不会漏测)
- AgentEvent / ToolCallRequest / ToolCallResult 的序列化路径
"""

import pytest

from backend.core.legacy.agent_state import (
    AgentEvent,
    AgentState,
    ToolCallRequest,
    ToolCallResult,
)

pytestmark = pytest.mark.unit


# ---------------------- 枚举值 & 字符串继承 ----------------------


def test_agent_state_enum_has_ten_states():
    """状态机应有 10 个状态:IDLE/THINKING/REASONING/REASONING_DELTA/REASONING_DONE/
    ACTING/OBSERVING/CONTENT_DELTA/DONE/FAILED。

    CONTENT_DELTA 由 I4 引入,用于流式 LLM 响应 — 每个 token chunk 推一个
    CONTENT_DELTA 事件,前端 appendContent 累积实现逐字渲染。
    REASONING 用于携带 LLM 思考/推理过程内容（reasoning_content）。
    REASONING_DELTA/REASONING_DONE 用于 reasoning 的 fake streaming。
    """
    assert len(AgentState) == 10


def test_agent_state_enum_string_inheritance():
    """继承自 str,可与字符串直接比较(用于 HTTP 协议层)。"""
    assert AgentState.DONE == "done"
    assert AgentState.FAILED == "failed"
    assert AgentState.THINKING == "thinking"
    # str() 转换
    assert str(AgentState.DONE) == "AgentState.DONE"
    # 在集合中可用作字符串
    assert AgentState.DONE in {"done", "failed"}


@pytest.mark.parametrize(
    ("state", "raw"),
    [
        (AgentState.IDLE, "idle"),
        (AgentState.THINKING, "thinking"),
        (AgentState.REASONING, "reasoning"),
        (AgentState.REASONING_DELTA, "reasoning_delta"),
        (AgentState.REASONING_DONE, "reasoning_done"),
        (AgentState.ACTING, "acting"),
        (AgentState.OBSERVING, "observing"),
        (AgentState.CONTENT_DELTA, "content_delta"),
        (AgentState.DONE, "done"),
        (AgentState.FAILED, "failed"),
    ],
)
def test_agent_state_value_matches_string(state, raw):
    assert state.value == raw


def test_agent_state_iteration_order():
    """枚举迭代顺序稳定(避免序列化时顺序漂移)。"""
    expected = [
        "idle",
        "thinking",
        "reasoning",
        "reasoning_delta",
        "reasoning_done",
        "acting",
        "observing",
        "content_delta",
        "done",
        "failed",
    ]
    actual = [s.value for s in AgentState]
    assert actual == expected


# ---------------------- AgentEvent 序列化 ----------------------


def test_agent_event_to_dict_minimal():
    """AgentEvent 最小字段(state + iteration) 序列化。"""
    evt = AgentEvent(state=AgentState.THINKING, iteration=2)
    d = evt.to_dict()
    assert d == {"state": "thinking", "iteration": 2}


def test_agent_event_to_dict_with_error():
    """FAILED 事件应包含 error 字段。"""
    evt = AgentEvent(
        state=AgentState.FAILED,
        iteration=5,
        error="max_iterations_exceeded",
    )
    d = evt.to_dict()
    assert d["state"] == "failed"
    assert d["error"] == "max_iterations_exceeded"


def test_agent_event_to_dict_with_tool_call_and_result():
    """OBSERVING 事件同时包含 tool_call 和 tool_result。"""
    tc = ToolCallRequest(id="c1", name="calculator", arguments={"x": 1})
    tr = ToolCallResult(tool_call_id="c1", content="1", is_error=False)
    evt = AgentEvent(
        state=AgentState.OBSERVING,
        iteration=0,
        tool_call=tc,
        tool_result=tr,
    )
    d = evt.to_dict()
    assert d["state"] == "observing"
    assert d["tool_call"]["function"]["name"] == "calculator"
    assert d["tool_result"]["content"] == "1"
    assert d["tool_result"]["role"] == "tool"


def test_agent_event_omits_none_fields():
    """to_dict() 不会写出 None 字段(节省 NDJSON 流量)。"""
    evt = AgentEvent(state=AgentState.IDLE, iteration=0)
    d = evt.to_dict()
    assert "content" not in d
    assert "tool_call" not in d
    assert "tool_result" not in d
    assert "error" not in d


# ---------------------- ToolCallRequest/Result 边界 ----------------------


def test_tool_call_request_unicode_arguments_serialized():
    """中文/Unicode 参数应原样保留(确保中文工具参数不丢)。"""
    tc = ToolCallRequest(
        id="c_unicode",
        name="search",
        arguments={"query": "你好世界", "tag": "中文"},
    )
    d = tc.to_dict()
    args_str = d["function"]["arguments"]
    # ensure_ascii=False:Unicode 字符不被转义
    assert "你好世界" in args_str
    assert "中文" in args_str


def test_tool_call_result_serialization_minimal():
    """ToolCallResult 不必传 is_error,默认为 False。"""
    tr = ToolCallResult(tool_call_id="c1", content="ok")
    d = tr.to_dict()
    assert d == {"tool_call_id": "c1", "role": "tool", "content": "ok"}


def test_tool_call_result_error_case():
    """ToolCallResult 错误结果序列化时 is_error=True 不进入 dict(前端通过 content 判断)。"""
    tr = ToolCallResult(tool_call_id="c1", content="工具不存在", is_error=True)
    d = tr.to_dict()
    assert d["content"] == "工具不存在"
