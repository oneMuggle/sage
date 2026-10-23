"""R138 — 消息领域模型单元测试。

覆盖：Role 四枚举 str 比较、ToolCall 字段、Message 缺省值与
ASSISTANT/TOOL 场景构造。
"""

from __future__ import annotations

import pytest

from backend.domain.message import Message, Role, ToolCall

pytestmark = pytest.mark.unit


def test_role_four_values_str_comparable():
    assert Role.SYSTEM == "system"
    assert Role.USER == "user"
    assert Role.ASSISTANT == "assistant"
    assert Role.TOOL == "tool"


def test_tool_call_fields():
    call = ToolCall(name="web_search", args={"query": "x"}, id="call_1")
    assert call.name == "web_search"
    assert call.args == {"query": "x"}
    assert call.id == "call_1"


def test_tool_call_id_optional():
    call = ToolCall(name="t", args={})
    assert call.id is None


def test_message_defaults():
    msg = Message(role=Role.USER, content="你好")
    assert msg.role == Role.USER
    assert msg.content == "你好"
    assert msg.tool_calls == []
    assert msg.tool_call_id is None


def test_assistant_message_with_tool_calls():
    calls = [ToolCall(name="t", args={"a": 1})]
    msg = Message(role=Role.ASSISTANT, content="", tool_calls=calls)
    assert msg.tool_calls == calls


def test_tool_message_with_call_id():
    msg = Message(role=Role.TOOL, content="result", tool_call_id="call_1")
    assert msg.tool_call_id == "call_1"


def test_role_comparison_with_plain_string():
    msg = Message(role=Role.ASSISTANT, content="hi")
    assert msg.role == "assistant"  # str 枚举可直接与裸字符串比较
