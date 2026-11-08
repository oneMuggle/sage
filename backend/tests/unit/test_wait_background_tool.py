"""``wait_background`` LLM 工具单测（2026-11-06 Phase 1）。"""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

import pytest

from backend.tools.bash_session import STATUS_EXITED, STATUS_RUNNING
from backend.tools.wait_background_tool import WaitBackgroundTool

pytestmark = pytest.mark.unit


def _registry(status: str, payload: Optional[dict] = None) -> MagicMock:
    registry = MagicMock()
    session = MagicMock()
    session.status.return_value = status
    registry.get.return_value = session
    registry.read_increment.return_value = payload or {
        "status": status,
        "exit_code": 0 if status == STATUS_EXITED else None,
        "stdout": "done\n",
        "stderr": "",
        "truncated": False,
    }
    return registry


def test_rejects_empty_shell_id() -> None:
    result = WaitBackgroundTool().execute(shell_id="")
    assert result.success is False


def test_unknown_shell_returns_error(monkeypatch) -> None:
    registry = MagicMock()
    registry.get.return_value = None
    monkeypatch.setattr(
        "backend.tools.wait_background_tool.get_registry", lambda: registry
    )
    result = WaitBackgroundTool().execute(shell_id="sh-missing")
    assert result.success is False
    assert "未知" in (result.error or "")


def test_exited_shell_returns_output(monkeypatch) -> None:
    registry = _registry(STATUS_EXITED)
    monkeypatch.setattr(
        "backend.tools.wait_background_tool.get_registry", lambda: registry
    )
    result = WaitBackgroundTool().execute(shell_id="sh-1", timeout_s=5)
    assert result.success is True
    content = result.content
    assert content["status"] == STATUS_EXITED
    assert content["timed_out"] is False
    assert content["exit_code"] == 0
    assert content["stdout"] == "done\n"


def test_running_shell_times_out(monkeypatch) -> None:
    registry = _registry(STATUS_RUNNING)
    monkeypatch.setattr(
        "backend.tools.wait_background_tool.get_registry", lambda: registry
    )
    # timeout 下限 1s —— 只等待 1 秒
    result = WaitBackgroundTool().execute(shell_id="sh-1", timeout_s=1)
    assert result.success is True
    assert result.content["status"] == STATUS_RUNNING
    assert result.content["timed_out"] is True


def test_timeout_clamped(monkeypatch) -> None:
    from backend.tools import wait_background_tool as mod

    registry = _registry(STATUS_EXITED)
    monkeypatch.setattr(mod, "get_registry", lambda: registry)
    # 超过上限的 timeout 应被 clamp，而不是抛错
    result = mod.WaitBackgroundTool().execute(shell_id="sh-1", timeout_s=10_000)
    assert result.success is True
