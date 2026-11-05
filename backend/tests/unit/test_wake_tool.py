"""``wake_session_at`` LLM 工具单测（2026-11-05）。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from backend.tools.context import (
    ToolExecutionContext,
    current_tool_context,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.wake_tool import WakeSessionAtTool, parse_wake_at

pytestmark = pytest.mark.unit

SESSION_A = "sess-alpha"


def _bind_context(session_id: str = SESSION_A):
    ctx = ToolExecutionContext(
        session_id=session_id,
        stream_id="stream-1",
        binding_generation=0,
        office_doc_scope=frozenset(),
    )
    return set_tool_context(ctx)


class TestParseWakeAt:
    def test_relative_seconds(self) -> None:
        fire_at = parse_wake_at("in:600s")
        parsed = datetime.fromisoformat(fire_at)
        delta = (parsed - datetime.now(timezone.utc)).total_seconds()  # noqa: UP017
        assert 590 <= delta <= 610

    def test_relative_minutes(self) -> None:
        fire_at = parse_wake_at("in:5m")
        parsed = datetime.fromisoformat(fire_at)
        delta = (parsed - datetime.now(timezone.utc)).total_seconds()  # noqa: UP017
        assert 290 <= delta <= 310

    def test_iso_with_z_suffix(self) -> None:
        assert parse_wake_at("2099-01-01T00:00:00Z").startswith("2099-01-01T00:00:00")

    def test_epoch_millis(self) -> None:
        expected = datetime.fromtimestamp(4_071_244_800, tz=timezone.utc).isoformat()  # noqa: UP017
        assert parse_wake_at(4_071_244_800_000) == expected

    @pytest.mark.parametrize("bad", ["", "in:", "in:abc", "in:-5m", "not-a-time", None])
    def test_invalid_values_raise(self, bad) -> None:
        with pytest.raises(ValueError, match="."):
            parse_wake_at(bad)


class TestWakeSessionAtTool:
    def _tool(self) -> WakeSessionAtTool:
        return WakeSessionAtTool()

    def test_requires_tool_context(self) -> None:
        result = self._tool().execute(at="in:60s", note="check")
        assert result.success is False
        assert "上下文" in (result.error or "")

    def test_registers_timer_wake_for_current_session(self, monkeypatch) -> None:
        store = MagicMock()
        monkeypatch.setattr(
            "backend.tools.wake_tool.get_wake_store", lambda: store
        )
        token = _bind_context()
        try:
            result = self._tool().execute(at="in:600s", note="检查 CI")
        finally:
            reset_tool_context(token)

        assert result.success is True
        store.add_wake.assert_called_once()
        wake = store.add_wake.call_args.args[0]
        assert wake.session_id == SESSION_A
        assert wake.kind.value == "timer"
        assert wake.note == "检查 CI"

    def test_rejects_invalid_time(self, monkeypatch) -> None:
        store = MagicMock()
        monkeypatch.setattr(
            "backend.tools.wake_tool.get_wake_store", lambda: store
        )
        token = _bind_context()
        try:
            result = self._tool().execute(at="whenever", note="")
        finally:
            reset_tool_context(token)
        assert result.success is False
        store.add_wake.assert_not_called()

    def test_rejects_overlong_note(self, monkeypatch) -> None:
        store = MagicMock()
        monkeypatch.setattr(
            "backend.tools.wake_tool.get_wake_store", lambda: store
        )
        token = _bind_context()
        try:
            result = self._tool().execute(at="in:60s", note="x" * 2001)
        finally:
            reset_tool_context(token)
        assert result.success is False
        store.add_wake.assert_not_called()

    def test_context_is_restored(self) -> None:
        token = _bind_context()
        reset_tool_context(token)
        assert current_tool_context() is None
