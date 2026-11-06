"""``wake_on_background`` LLM 工具单测（2026-11-06 Phase 1）。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.tools.bash_session import STATUS_EXITED, STATUS_RUNNING
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.wake_on_background_tool import WakeOnBackgroundTool

pytestmark = pytest.mark.unit

SESSION_A = "sess-alpha"


def _bind_context(session_id: str = SESSION_A):
    return set_tool_context(
        ToolExecutionContext(
            session_id=session_id,
            stream_id="stream-1",
            binding_generation=0,
            office_doc_scope=frozenset(),
        )
    )


def _registry_with(status: str) -> MagicMock:
    registry = MagicMock()
    session = MagicMock()
    session.status.return_value = status
    registry.get.return_value = session
    return registry


def test_requires_tool_context() -> None:
    result = WakeOnBackgroundTool().execute(shell_id="sh-1", note="x")
    assert result.success is False
    assert "上下文" in (result.error or "")


def test_rejects_empty_shell_id() -> None:
    token = _bind_context()
    try:
        result = WakeOnBackgroundTool().execute(shell_id="  ")
    finally:
        reset_tool_context(token)
    assert result.success is False


def test_unknown_shell_id(monkeypatch) -> None:
    registry = MagicMock()
    registry.get.return_value = None
    monkeypatch.setattr(
        "backend.tools.wake_on_background_tool.get_registry", lambda: registry
    )
    token = _bind_context()
    try:
        result = WakeOnBackgroundTool().execute(shell_id="sh-missing")
    finally:
        reset_tool_context(token)
    assert result.success is False
    assert "未知" in (result.error or "")


def test_running_shell_registers_completion_wake(monkeypatch) -> None:
    registry = _registry_with(STATUS_RUNNING)
    store = MagicMock()
    monkeypatch.setattr(
        "backend.tools.wake_on_background_tool.get_registry", lambda: registry
    )
    monkeypatch.setattr(
        "backend.tools.wake_on_background_tool.get_wake_store", lambda: store
    )
    token = _bind_context()
    try:
        result = WakeOnBackgroundTool().execute(shell_id="sh-1", note="检查测试结果")
    finally:
        reset_tool_context(token)

    assert result.success is True
    store.add_wake.assert_called_once()
    wake = store.add_wake.call_args.args[0]
    assert wake.session_id == SESSION_A
    assert wake.kind.value == "completion"
    assert wake.job_id == "sh-1"
    assert wake.note == "检查测试结果"
    registry.register_watcher.assert_called_once()


def test_exited_shell_registers_immediate_timer_wake(monkeypatch) -> None:
    registry = _registry_with(STATUS_EXITED)
    store = MagicMock()
    monkeypatch.setattr(
        "backend.tools.wake_on_background_tool.get_registry", lambda: registry
    )
    monkeypatch.setattr(
        "backend.tools.wake_on_background_tool.get_wake_store", lambda: store
    )
    token = _bind_context()
    try:
        result = WakeOnBackgroundTool().execute(shell_id="sh-1", note="")
    finally:
        reset_tool_context(token)

    assert result.success is True
    wake = store.add_wake.call_args.args[0]
    assert wake.kind.value == "timer"
    assert wake.fire_at is not None
    registry.register_watcher.assert_not_called()


def test_overlong_note_rejected(monkeypatch) -> None:
    registry = _registry_with(STATUS_RUNNING)
    monkeypatch.setattr(
        "backend.tools.wake_on_background_tool.get_registry", lambda: registry
    )
    token = _bind_context()
    try:
        result = WakeOnBackgroundTool().execute(shell_id="sh-1", note="x" * 2001)
    finally:
        reset_tool_context(token)
    assert result.success is False
