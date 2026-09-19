"""right-panel R5: workspace_changed 事件链路单元测试。

覆盖 data/workspace_events 监听器注册/注销/异常隔离/无会话静默，以及
三个写文件工具（write_file / edit_file / apply_patch）成功落盘后的
广播钩子（失败路径不广播）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.data import workspace_events
from backend.domain.tool_policy import ToolPolicy
from backend.tools.context import ToolExecutionContext, reset_tool_context, set_tool_context
from backend.tools.edit_tool import EditTool
from backend.tools.file_tool import WriteFileTool
from backend.tools.patch_tool import ApplyPatchTool

pytestmark = pytest.mark.unit


@pytest.fixture()
def listener():
    """注册一个事件收集器，测试结束自动注销。"""
    events: list[dict] = []
    fn = workspace_events.add_workspace_listener(events.append)
    yield events
    workspace_events.remove_workspace_listener(fn)


@pytest.fixture()
def _tool_ctx():
    """绑定带 session_id 的工具上下文，测试结束复位。"""
    token = set_tool_context(
        ToolExecutionContext(
            session_id="sess-events",
            stream_id="stream-1",
            binding_generation=1,
            office_doc_scope=frozenset(),
        )
    )
    yield
    reset_tool_context(token)


# ---------------------------------------------------------------------------
# workspace_events 模块契约
# ---------------------------------------------------------------------------


def test_notify_broadcasts_to_registered_listener(listener):
    workspace_events.notify_workspace_changed("sess-1", "a.py", "write")
    assert listener == [
        {
            "state": "workspace_changed",
            "session_id": "sess-1",
            "change": {"path": "a.py", "kind": "write"},
        }
    ]


def test_notify_without_session_is_silent(listener):
    workspace_events.notify_workspace_changed("", "a.py", "write")
    assert listener == []


def test_listener_exception_is_swallowed():
    def boom(_event: dict) -> None:
        raise RuntimeError("listener exploded")

    events: list[dict] = []
    fn_bad = workspace_events.add_workspace_listener(boom)
    fn_good = workspace_events.add_workspace_listener(events.append)
    try:
        workspace_events.notify_workspace_changed("sess-1", "a.py", "edit")
    finally:
        workspace_events.remove_workspace_listener(fn_bad)
        workspace_events.remove_workspace_listener(fn_good)
    assert len(events) == 1


def test_remove_listener_stops_broadcast(listener):
    workspace_events.remove_workspace_listener(listener.append)
    workspace_events.notify_workspace_changed("sess-1", "a.py", "write")
    assert listener == []


# ---------------------------------------------------------------------------
# 写文件工具钩子
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_tool_ctx")
def test_write_file_success_broadcasts_event(tmp_path, listener):
    tool = WriteFileTool(policy=ToolPolicy(workspace_root=str(tmp_path)))
    result = tool.execute(path=str(tmp_path / "new.py"), content="print('x')\n")

    assert result.success is True
    assert len(listener) == 1
    event = listener[0]
    assert event["state"] == "workspace_changed"
    assert event["session_id"] == "sess-events"
    assert event["change"]["kind"] == "write"


@pytest.mark.usefixtures("_tool_ctx")
def test_write_file_failure_does_not_broadcast(tmp_path, listener):
    tool = WriteFileTool(policy=ToolPolicy(workspace_root=str(tmp_path)))
    result = tool.execute(path=str(tmp_path / "x.png"), content="hello")

    assert result.success is False
    assert listener == []


@pytest.mark.usefixtures("_tool_ctx")
def test_edit_file_success_broadcasts_event(tmp_path, listener):
    target = tmp_path / "code.py"
    target.write_text("value = 1\n", encoding="utf-8")
    tool = EditTool(policy=ToolPolicy(workspace_root=str(tmp_path)))

    result = tool.execute(file_path=str(target), old_string="1", new_string="2")

    assert result.success is True
    assert len(listener) == 1
    assert listener[0]["change"]["kind"] == "edit"


@pytest.mark.usefixtures("_tool_ctx")
def test_patch_tool_success_broadcasts_per_file(tmp_path: Path, listener):
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("alpha\n", encoding="utf-8")
    second.write_text("beta\n", encoding="utf-8")
    tool = ApplyPatchTool(policy=ToolPolicy(workspace_root=str(tmp_path)))

    result = tool.execute(
        patches=[
            {"file_path": str(first), "old_string": "alpha", "new_string": "ALPHA"},
            {"file_path": str(second), "old_string": "beta", "new_string": "BETA"},
        ]
    )

    assert result.success is True
    kinds = [event["change"]["kind"] for event in listener]
    assert kinds == ["patch", "patch"]
    paths = {event["change"]["path"] for event in listener}
    assert len(paths) == 2
