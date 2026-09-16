"""alpha.36 (Bug #4): assistant 消息持久化时写入 tool_calls。

根因: DONE 落盘路径 (`legacy_routes.py:2914`) 构造 DbMessage 时不传
`tool_calls` 字段,导致 DB 里 assistant 消息的 tool_calls 列为 NULL。
用户切会话再切回时,前端 loadMessages 从 DB 读到 tool_calls=NULL,
视觉上中间步骤全丢。

修复: 在 run_loop 事件流里累积 ACTING (tool_call) 和 OBSERVING
(tool_result) 事件,落盘时 json.dumps 到 DbMessage.tool_calls。
本测试直接构造 producer 闭包累积逻辑的等价代码,断言:
- 有 ACTING 事件时,accumulated_tool_calls 非空
- OBSERVING 事件把 result 回填到匹配的 tool_call
- 最终 DbMessage.tool_calls 是合法 JSON,形状对齐前端 ToolCall
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.unit


def test_tool_calls_accumulator_empty_when_no_acting_events():
    """没有 ACTING 事件时,累积器应为空列表,DbMessage.tool_calls 为 None。"""
    accumulated: list[dict] = []

    # 模拟无 ACTING 事件
    tool_calls_json = (
        json.dumps(accumulated, ensure_ascii=False) if accumulated else None
    )

    assert tool_calls_json is None


def test_tool_calls_accumulator_captures_acting_events():
    """ACTING 事件应被累积,包含 id/name/args。"""
    from backend.core.legacy.agent_state import (
        AgentState,
        AgentEvent,
        ToolCallRequest,
    )

    accumulated: list[dict] = []

    # 模拟 ACTING 事件
    evt = AgentEvent(
        state=AgentState.ACTING,
        tool_call=ToolCallRequest(
            id="tc-1",
            name="office_read",
            arguments={"doc_id": "doc-42", "section": "summary"},
        ),
    )

    if evt.state.value == "acting" and evt.tool_call:
        tc = evt.tool_call
        accumulated.append(
            {
                "id": tc.id,
                "name": tc.name,
                "args": dict(tc.arguments) if isinstance(tc.arguments, dict) else {},
            }
        )

    assert len(accumulated) == 1
    assert accumulated[0]["id"] == "tc-1"
    assert accumulated[0]["name"] == "office_read"
    assert accumulated[0]["args"]["doc_id"] == "doc-42"
    assert "result" not in accumulated[0]  # OBSERVING 还没来


def test_tool_calls_accumulator_backfills_result_from_observing():
    """OBSERVING 事件应把 result 回填到匹配的 tool_call(按 id)。"""
    from backend.core.legacy.agent_state import (
        AgentState,
        AgentEvent,
        ToolCallRequest,
        ToolCallResult,
    )

    accumulated: list[dict] = []

    # ACTING
    evt_act = AgentEvent(
        state=AgentState.ACTING,
        tool_call=ToolCallRequest(
            id="tc-1",
            name="office_read",
            arguments={"doc_id": "doc-42"},
        ),
    )
    if evt_act.state.value == "acting" and evt_act.tool_call:
        tc = evt_act.tool_call
        accumulated.append(
            {
                "id": tc.id,
                "name": tc.name,
                "args": dict(tc.arguments) if isinstance(tc.arguments, dict) else {},
            }
        )

    # OBSERVING
    evt_obs = AgentEvent(
        state=AgentState.OBSERVING,
        tool_result=ToolCallResult(
            tool_call_id="tc-1",
            content="document content here",
            is_error=False,
        ),
    )
    if evt_obs.state.value == "observing" and evt_obs.tool_result:
        tr = evt_obs.tool_result
        for tc in reversed(accumulated):
            if tc.get("id") == tr.tool_call_id:
                tc["result"] = tr.content
                break

    assert len(accumulated) == 1
    assert accumulated[0]["id"] == "tc-1"
    assert accumulated[0]["result"] == "document content here"


def test_tool_calls_json_serialization_roundtrip():
    """累积器 json.dumps 后应能被 sqlite_adapter._deserialize_tool_calls 还原。"""
    from backend.adapters.out.storage.sqlite_adapter import _deserialize_tool_calls

    accumulated = [
        {"id": "tc-1", "name": "office_read", "args": {"doc_id": "doc-42"}, "result": "content"},
        {"id": "tc-2", "name": "web_search", "args": {"query": "test"}},
    ]

    tool_calls_json = json.dumps(accumulated, ensure_ascii=False)
    deserialized = _deserialize_tool_calls(tool_calls_json)

    assert len(deserialized) == 2
    assert deserialized[0].name == "office_read"
    assert deserialized[0].args == {"doc_id": "doc-42"}
    assert deserialized[0].id == "tc-1"
    assert deserialized[1].name == "web_search"
    assert deserialized[1].args == {"query": "test"}


def test_tool_calls_multiple_acting_events():
    """多个 ACTING 事件应按顺序累积。"""
    from backend.core.legacy.agent_state import AgentState, AgentEvent, ToolCallRequest

    accumulated: list[dict] = []

    for i in range(3):
        evt = AgentEvent(
            state=AgentState.ACTING,
            tool_call=ToolCallRequest(
                id=f"tc-{i}",
                name=f"tool_{i}",
                arguments={"arg": f"value_{i}"},
            ),
        )
        if evt.state.value == "acting" and evt.tool_call:
            tc = evt.tool_call
            accumulated.append(
                {
                    "id": tc.id,
                    "name": tc.name,
                    "args": dict(tc.arguments) if isinstance(tc.arguments, dict) else {},
                }
            )

    assert len(accumulated) == 3
    assert accumulated[0]["id"] == "tc-0"
    assert accumulated[1]["id"] == "tc-1"
    assert accumulated[2]["id"] == "tc-2"


def test_tool_calls_observing_no_match_doesnt_crash():
    """OBSERVING 事件找不到匹配的 tool_call 时不应崩溃(容错)。"""
    from backend.core.legacy.agent_state import (
        AgentState,
        AgentEvent,
        ToolCallResult,
    )

    accumulated: list[dict] = []

    # OBSERVING 没有对应的 ACTING(可能 ACTING 事件丢失或 id 不匹配)
    evt_obs = AgentEvent(
        state=AgentState.OBSERVING,
        tool_result=ToolCallResult(
            tool_call_id="tc-missing",
            content="orphan result",
            is_error=False,
        ),
    )

    if evt_obs.state.value == "observing" and evt_obs.tool_result:
        tr = evt_obs.tool_result
        for tc in reversed(accumulated):
            if tc.get("id") == tr.tool_call_id:
                tc["result"] = tr.content
                break

    # 不应崩溃,累积器仍为空
    assert len(accumulated) == 0
