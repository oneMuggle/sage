"""Unit tests for scheduler mode (deliver vs execute)."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.scheduler import ScheduledTask, SchedulerService


@pytest.fixture()
def message_repo() -> MagicMock:
    repo = MagicMock()
    repo.insert = MagicMock(return_value={"id": "msg-1"})
    return repo


@pytest.fixture()
def session_repo() -> MagicMock:
    repo = MagicMock()
    repo.exists = MagicMock(return_value=True)
    return repo


@pytest.fixture()
def scheduler(tmp_path: Path, message_repo: MagicMock, session_repo: MagicMock) -> SchedulerService:
    return SchedulerService(
        store_path=tmp_path / "scheduled_tasks.json",
        message_repo=message_repo,
        session_repo=session_repo,
    )


def _make_task(scheduler: SchedulerService, mode: str = "deliver") -> ScheduledTask:
    """Register a task directly in the scheduler's internal map."""
    task = ScheduledTask(
        id="test-task-1",
        name="Test task",
        type="once",
        schedule={"kind": "once", "at": int(time.time() * 1000) + 60_000},
        session_id="session-123",
        content="Hello from scheduled task",
        enabled=True,
        created_at=int(time.time() * 1000),
        mode=mode,  # type: ignore[arg-type]
    )
    scheduler._tasks[task.id] = task
    return task


class TestScheduledTaskMode:
    """Test mode field on the ScheduledTask dataclass."""

    def test_default_mode_is_deliver(self) -> None:
        task = ScheduledTask(
            id="t1", name="test", type="once",
            schedule={"kind": "once", "at": 0}, session_id="s1",
            content="c", enabled=True, created_at=0,
        )
        assert task.mode == "deliver"

    def test_explicit_execute_mode(self) -> None:
        task = ScheduledTask(
            id="t1", name="test", type="once",
            schedule={"kind": "once", "at": 0}, session_id="s1",
            content="c", enabled=True, created_at=0, mode="execute",
        )
        assert task.mode == "execute"

    def test_from_dict_defaults_to_deliver(self) -> None:
        raw = {
            "id": "t1", "name": "test", "type": "once",
            "schedule": {"kind": "once", "at": 0}, "session_id": "s1",
            "content": "c", "enabled": True, "created_at": 0,
        }
        assert ScheduledTask.from_dict(raw).mode == "deliver"

    def test_from_dict_preserves_execute(self) -> None:
        raw = {
            "id": "t1", "name": "test", "type": "once",
            "schedule": {"kind": "once", "at": 0}, "session_id": "s1",
            "content": "c", "enabled": True, "created_at": 0, "mode": "execute",
        }
        assert ScheduledTask.from_dict(raw).mode == "execute"

    def test_from_dict_invalid_mode_falls_back(self) -> None:
        raw = {
            "id": "t1", "name": "test", "type": "once",
            "schedule": {"kind": "once", "at": 0}, "session_id": "s1",
            "content": "c", "enabled": True, "created_at": 0, "mode": "bogus",
        }
        assert ScheduledTask.from_dict(raw).mode == "deliver"


class TestFireDeliveryMode:
    """Test _fire() with mode='deliver' (default)."""

    def test_deliver_inserts_system_message(
        self, scheduler: SchedulerService, message_repo: MagicMock
    ) -> None:
        task = _make_task(scheduler, mode="deliver")
        scheduler._fire(task)
        message_repo.insert.assert_called_once()
        kwargs = message_repo.insert.call_args.kwargs
        assert kwargs["session_id"] == "session-123"
        assert kwargs["role"] == "system"
        assert kwargs["content"] == "Hello from scheduled task"

    def test_deliver_records_success(
        self, scheduler: SchedulerService, message_repo: MagicMock
    ) -> None:
        task = _make_task(scheduler, mode="deliver")
        scheduler._fire(task)
        updated = scheduler._tasks[task.id]
        assert updated.run_count == 1
        assert updated.last_status == "succeeded"


class TestFireExecuteMode:
    """Test _fire() with mode='execute'."""

    def test_execute_without_executor_falls_back_to_deliver(
        self, scheduler: SchedulerService, message_repo: MagicMock
    ) -> None:
        task = _make_task(scheduler, mode="execute")
        scheduler._fire(task)
        message_repo.insert.assert_called_once()
        assert message_repo.insert.call_args.kwargs["role"] == "system"

    def test_execute_with_executor_calls_executor(
        self, scheduler: SchedulerService, message_repo: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        task = _make_task(scheduler, mode="execute")
        mock_executor = AsyncMock()
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        scheduler.set_executor(mock_executor, mock_loop)

        mock_future = MagicMock()
        captured: dict = {}

        def fake_run_coro(coro, loop):
            captured["coro"] = coro
            captured["loop"] = loop
            coro.close()  # avoid "never awaited" warning
            return mock_future

        monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", fake_run_coro)

        scheduler._fire(task)

        assert captured["loop"] is mock_loop
        mock_future.add_done_callback.assert_called_once()
        message_repo.insert.assert_not_called()
        updated = scheduler._tasks[task.id]
        assert updated.run_count == 1
        assert updated.last_status == "succeeded"

    def test_execute_submission_failure_records_error(
        self, scheduler: SchedulerService, message_repo: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        task = _make_task(scheduler, mode="execute")
        scheduler.set_executor(AsyncMock(), MagicMock(spec=asyncio.AbstractEventLoop))

        def boom(coro, loop):
            coro.close()
            raise RuntimeError("loop is closed")

        monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", boom)

        scheduler._fire(task)

        updated = scheduler._tasks[task.id]
        assert updated.last_status == "failed"
        assert updated.last_error is not None

    def test_execute_does_not_block_on_llm_completion(
        self, scheduler: SchedulerService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fire must return while the turn is still running (no future.result)."""
        task = _make_task(scheduler, mode="execute")
        scheduler.set_executor(AsyncMock(), MagicMock(spec=asyncio.AbstractEventLoop))

        never_finishing = MagicMock()
        never_finishing.result.side_effect = AssertionError("must not block on completion")

        monkeypatch.setattr(
            asyncio, "run_coroutine_threadsafe",
            lambda coro, loop: (coro.close(), never_finishing)[1],
        )

        scheduler._fire(task)

        never_finishing.result.assert_not_called()

    def test_execute_failure_is_logged_by_callback(
        self, scheduler: SchedulerService, caplog: pytest.LogCaptureFixture
    ) -> None:
        failed = MagicMock()
        failed.exception.return_value = RuntimeError("turn exploded")
        with caplog.at_level("ERROR", logger="backend.services.scheduler"):
            SchedulerService._log_execute_result("task-xyz", failed)
        assert "task-xyz" in caplog.text
        assert "turn exploded" in caplog.text


class TestSetExecutor:
    """Test set_executor() method."""

    def test_stores_executor_and_loop(self, scheduler: SchedulerService) -> None:
        mock_executor = AsyncMock()
        mock_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        scheduler.set_executor(mock_executor, mock_loop)
        assert scheduler._executor is mock_executor
        assert scheduler._loop is mock_loop

    def test_loop_defaults_to_none(self, scheduler: SchedulerService) -> None:
        mock_executor = AsyncMock()
        scheduler.set_executor(mock_executor)
        assert scheduler._executor is mock_executor
        assert scheduler._loop is None
