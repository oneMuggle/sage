"""todo 变更监听器单测 —— SSE todo_snapshot 推送的底层机制。

注意：不用 ``with set_tool_context(...)`` —— ``contextvars.Token`` 的
上下文管理器协议是 Python 3.11+ 才有的，本环境（py3.10 / win7 py3.8）
不支持；与仓内既有测试一致走 token + ``reset_tool_context`` 模式。
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from backend.tools import todo_state
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.todo_state import (
    add_todo_listener,
    get_todo_store,
    remove_todo_listener,
)
from backend.tools.todo_tool import TodoWriteTool

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean():
    get_todo_store().clear()
    yield
    get_todo_store().clear()
    # 跨用例隔离：清掉用例注册的监听器（boom / 匿名 lambda 会留存到后续用例）
    todo_state._listeners.clear()


@contextmanager
def _tool_ctx(session_id: str):
    """绑定 ToolExecutionContext 并保证退出时复位（py<3.11 兼容写法）。"""
    token = set_tool_context(
        ToolExecutionContext(
            session_id=session_id,
            stream_id="s1",
            binding_generation=1,
            office_doc_scope=frozenset(),
        )
    )
    try:
        yield
    finally:
        reset_tool_context(token)


def test_replace_notifies_listeners_with_full_snapshot():
    seen: list = []
    add_todo_listener(lambda sid, todos: seen.append((sid, todos)))
    tool = TodoWriteTool()
    with _tool_ctx("sess-a"):
        result = tool.execute(todos=[{"content": "任务1", "status": "pending"}])
    assert result.success is True
    assert len(seen) == 1
    sid, todos = seen[0]
    assert sid == "sess-a"
    assert todos == [{"content": "任务1", "status": "pending"}]


def test_remove_listener_stops_notification():
    seen: list = []

    def listener(sid, todos):
        seen.append(sid)

    add_todo_listener(listener)
    remove_todo_listener(listener)
    tool = TodoWriteTool()
    with _tool_ctx("s"):
        tool.execute(todos=[{"content": "x", "status": "pending"}])
    assert seen == []


def test_listener_exception_does_not_break_tool():
    def boom(sid, todos):
        raise RuntimeError("listener boom")

    add_todo_listener(boom)
    tool = TodoWriteTool()
    with _tool_ctx("s"):
        result = tool.execute(todos=[{"content": "x", "status": "pending"}])
    assert result.success is True


def test_anonymous_bucket_also_notifies():
    seen: list = []
    add_todo_listener(lambda sid, todos: seen.append(sid))
    tool = TodoWriteTool()  # 无上下文 → 匿名桶
    tool.execute(todos=[{"content": "x", "status": "pending"}])
    assert seen == ["__anonymous__"]


def test_route_side_session_filter_pattern():
    """模拟 legacy_routes 监听器：session 不匹配不推送。"""
    pushed: list = []

    def route_listener(session_id, todos):
        if session_id != "target":
            return
        pushed.append(todos)

    add_todo_listener(route_listener)
    tool = TodoWriteTool()
    with _tool_ctx("other"):
        tool.execute(todos=[{"content": "a", "status": "pending"}])
    with _tool_ctx("target"):
        tool.execute(todos=[{"content": "b", "status": "pending"}])
    assert len(pushed) == 1
    assert pushed[0][0]["content"] == "b"
