"""Minimal packaged-runtime health/lifespan contract tests."""

import os

import pytest

from backend.main import (
    _build_health_metadata,
    _shutdown_bash_sessions,
    _shutdown_repl_cleanups,
)


@pytest.mark.integration()
def test_lifespan_health_metadata_uses_runtime_ownership_envelope(monkeypatch):
    """Health metadata is derived from the process environment and is JSON-safe."""
    monkeypatch.setenv("SAGE_BUILD_ID", "test-build")
    monkeypatch.setenv("SAGE_BACKEND_GENERATION", "7")
    monkeypatch.setenv("SAGE_BACKEND_OWNERSHIP_TOKEN", "token-7")

    metadata = _build_health_metadata()

    assert metadata["buildId"] == "test-build"
    assert metadata["generation"] == 7
    assert "ownershipToken" not in metadata
    assert metadata["pid"] == os.getpid()
    assert set(metadata) == {"buildId", "pid", "generation"}


def test_shutdown_bash_sessions_clears_registry(monkeypatch):
    registry = type("Registry", (), {"clear": lambda self: setattr(self, "cleared", True)})()
    monkeypatch.setattr("backend.tools.bash_session.get_registry", lambda: registry)

    _shutdown_bash_sessions()

    assert registry.cleared is True


def test_shutdown_bash_sessions_swallows_cleanup_failure(monkeypatch):
    monkeypatch.setattr(
        "backend.tools.bash_session.get_registry",
        lambda: (_ for _ in ()).throw(RuntimeError("cleanup failed")),
    )

    _shutdown_bash_sessions()


def test_shutdown_repl_cleanups_calls_pending_cleanup(monkeypatch):
    called = []
    monkeypatch.setattr(
        "backend.tools.repl_tool.shutdown_pending_cleanups",
        lambda: called.append(True),
    )

    _shutdown_repl_cleanups()

    assert called == [True]


def test_shutdown_repl_cleanups_swallows_cleanup_failure(monkeypatch):
    monkeypatch.setattr(
        "backend.tools.repl_tool.shutdown_pending_cleanups",
        lambda: (_ for _ in ()).throw(RuntimeError("cleanup failed")),
    )

    _shutdown_repl_cleanups()


# ---------- M4: scheduled task executor wiring ----------


def test_wire_scheduler_executor_returns_false_when_scheduler_missing():
    """scheduler 缺失时 helper 不抛异常，只返回 False（启动不阻塞）。"""
    import asyncio
    from types import SimpleNamespace

    from backend.main import _wire_scheduler_executor

    app = SimpleNamespace(state=SimpleNamespace())

    loop = asyncio.new_event_loop()
    try:
        assert _wire_scheduler_executor(app, loop) is False
    finally:
        loop.close()


def test_wire_scheduler_executor_returns_false_when_chat_service_missing():
    """chat_service 缺失但 scheduler 存在 → 返回 False，set_executor 不被调用。"""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from backend.main import _wire_scheduler_executor

    state = SimpleNamespace(scheduler=MagicMock())

    loop = asyncio.new_event_loop()
    try:
        assert _wire_scheduler_executor(SimpleNamespace(state=state), loop) is False
        state.scheduler.set_executor.assert_not_called()
    finally:
        loop.close()


def test_wire_scheduler_executor_sets_executor_when_both_ready():
    """两端都就绪 → 调用 set_executor，传入一个 callable。"""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from backend.main import _wire_scheduler_executor

    state = SimpleNamespace(scheduler=MagicMock(), chat_service=MagicMock())

    loop = asyncio.new_event_loop()
    try:
        assert _wire_scheduler_executor(SimpleNamespace(state=state), loop) is True
        state.scheduler.set_executor.assert_called_once()
        executor = state.scheduler.set_executor.call_args.args[0]
        assert callable(executor)
    finally:
        loop.close()


def test_wire_scheduler_executor_callable_returns_failed_on_bad_loop():
    """装配后的 executor 在 loop 关闭情况下返回 failed RunOutcome，不抛异常。"""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from backend.main import _wire_scheduler_executor

    scheduler_mock = MagicMock()
    chat_mock = MagicMock()
    chat_mock.run_turn_tracked = MagicMock(
        side_effect=AssertionError("never called")
    )
    state = SimpleNamespace(scheduler=scheduler_mock, chat_service=chat_mock)

    loop = asyncio.new_event_loop()
    try:
        _wire_scheduler_executor(SimpleNamespace(state=state), loop)
        executor = scheduler_mock.set_executor.call_args.args[0]
    finally:
        loop.close()

    fake_task = MagicMock()
    fake_task.session_id = "sess-x"
    fake_task.content = "prompt"
    fake_task.id = "task-x"

    outcome = executor(fake_task)

    assert outcome.status == "failed"
    assert outcome.message_id is None
    assert outcome.duration_ms >= 0
