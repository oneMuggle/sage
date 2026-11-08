"""M2：SchedulerService 执行分支 + 线程安全桥接单测。"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.application.services.scheduled_task_executor import make_threadsafe_runner
from backend.services.scheduler import (
    RunOutcome,
    ScheduledTask,
    SchedulerService,
)

pytestmark = pytest.mark.unit


def _task(**overrides) -> ScheduledTask:
    """造一个最小可用的 ScheduledTask，默认 mode=execute。"""
    base = {
        "id": "task-0001",
        "name": "daily check",
        "type": "recurring",
        "schedule": {"kind": "recurring", "cron": "* * * * *"},
        "session_id": "sess-abc",
        "content": "ping",
        "enabled": True,
        "created_at": 1700000000000,
        "mode": "execute",
    }
    base.update(overrides)
    return ScheduledTask(**base)


def _service(tmp_path: Path, *, session_exists: bool = True) -> SchedulerService:
    """用 MagicMock repos 构造 SchedulerService（不接 DB，走 JSON 持久化）。"""
    svc = SchedulerService(
        store_path=tmp_path / "scheduled_tasks.json",
        message_repo=MagicMock(),
        session_repo=MagicMock(),
    )
    # 默认让 _session_repo_exists 返回 True（通过 mock session_repo）
    svc._session_repo_exists = MagicMock(return_value=session_exists)  # type: ignore[attr-defined]
    return svc


# ------------------------------------------------------------------ #
# ScheduledTask dataclass 默认值 / from_dict 兼容
# ------------------------------------------------------------------ #


class TestScheduledTaskM2Fields:
    def test_dataclass_defaults_to_deliver(self):
        """存量 from_dict 缺失 mode 时默认 deliver。"""
        raw = {
            "id": "t1", "name": "n", "type": "once",
            "schedule": {"kind": "once", "at": int(time.time() * 1000) + 60000},
            "session_id": "s", "content": "c", "enabled": True,
            "created_at": 1700000000000,
        }
        task = ScheduledTask.from_dict(raw)
        assert task.mode == "deliver"
        assert task.last_result_message_id is None
        assert task.last_duration_ms is None

    def test_from_dict_preserves_execute_mode(self):
        """from_dict 显式传入 mode='execute' 时正确保留。"""
        raw = {
            "id": "t2", "name": "n", "type": "once",
            "schedule": {"kind": "once", "at": int(time.time() * 1000) + 60000},
            "session_id": "s", "content": "c", "enabled": True,
            "created_at": 1700000000000,
            "mode": "execute",
            "last_result_message_id": "msg-xyz",
            "last_duration_ms": 1234,
        }
        task = ScheduledTask.from_dict(raw)
        assert task.mode == "execute"
        assert task.last_result_message_id == "msg-xyz"
        assert task.last_duration_ms == 1234


# ------------------------------------------------------------------ #
# set_executor + _fire 模式分支
# ------------------------------------------------------------------ #


class TestSchedulerFireModeBranching:
    def test_set_executor_attaches_runner(self, tmp_path):
        svc = _service(tmp_path)
        runner = MagicMock(return_value=RunOutcome(status="succeeded", message_id="m1", duration_ms=50))
        svc.set_executor(runner)
        assert svc._executor is runner

    def test_execute_mode_calls_runner_and_records_outcome(self, tmp_path):
        svc = _service(tmp_path)
        task = _task(id="ex1", mode="execute")
        svc._tasks[task.id] = task  # type: ignore[attr-defined]

        runner = MagicMock(return_value=RunOutcome(status="succeeded", message_id="msg-1", duration_ms=123))
        svc.set_executor(runner)

        svc._fire(task)

        runner.assert_called_once_with(task)
        updated = svc._tasks[task.id]  # type: ignore[attr-defined]
        assert updated.last_status == "succeeded"
        assert updated.last_result_message_id == "msg-1"
        assert updated.last_duration_ms == 123
        assert updated.run_count == 1
        # execute 模式下不应再写 system 消息
        svc._message_repo.insert.assert_not_called()  # type: ignore[attr-defined]

    def test_execute_mode_failed_outcome_records_error(self, tmp_path):
        svc = _service(tmp_path)
        task = _task(id="ex2", mode="execute")
        svc._tasks[task.id] = task  # type: ignore[attr-defined]

        runner = MagicMock(return_value=RunOutcome(status="failed", error="Execution timed out", duration_ms=300_000))
        svc.set_executor(runner)

        svc._fire(task)

        updated = svc._tasks[task.id]  # type: ignore[attr-defined]
        assert updated.last_status == "failed"
        assert updated.last_error == "Execution timed out"
        assert updated.last_result_message_id is None
        assert updated.last_duration_ms == 300_000
        # 失败不递增 run_count
        assert updated.run_count == 0

    def test_deliver_mode_does_not_call_runner(self, tmp_path):
        svc = _service(tmp_path)
        task = _task(id="dl1", mode="deliver")
        svc._tasks[task.id] = task  # type: ignore[attr-defined]

        runner = MagicMock()
        svc.set_executor(runner)

        svc._fire(task)

        runner.assert_not_called()
        svc._message_repo.insert.assert_called_once()  # type: ignore[attr-defined]
        call_kwargs = svc._message_repo.insert.call_args.kwargs  # type: ignore[attr-defined]
        assert call_kwargs["role"] == "system"
        assert call_kwargs["session_id"] == "sess-abc"
        assert call_kwargs["content"] == "ping"

    def test_execute_mode_without_runner_degrades_to_deliver(self, tmp_path, caplog):
        """executor 未注入时降级到 deliver，并打 warning（方案 §3.8）。"""
        svc = _service(tmp_path)
        task = _task(id="dl2", mode="execute")
        svc._tasks[task.id] = task  # type: ignore[attr-defined]
        assert svc._executor is None  # 默认未注入

        with caplog.at_level("WARNING", logger="backend.services.scheduler"):
            svc._fire(task)

        svc._message_repo.insert.assert_called_once()  # type: ignore[attr-defined]
        assert any("degrading to deliver" in msg for msg in caplog.messages)
        updated = svc._tasks[task.id]  # type: ignore[attr-defined]
        # 降级路径视为成功（不标记失败，用户提醒已送达）
        assert updated.last_status == "succeeded"

    def test_runner_exception_is_caught_and_recorded_as_failed(self, tmp_path):
        """runner 抛错不应穿透 _fire，而是降级为 failed outcome。"""
        svc = _service(tmp_path)
        task = _task(id="ex3", mode="execute")
        svc._tasks[task.id] = task  # type: ignore[attr-defined]

        runner = MagicMock(side_effect=RuntimeError("boom"))
        svc.set_executor(runner)

        # _fire 内部 try/except 包裹 runner 调用 —— runner 抛错被外层 try/except
        # 捕获记为 delivery 失败
        svc._fire(task)
        updated = svc._tasks[task.id]  # type: ignore[attr-defined]
        assert updated.last_status == "failed"
        # error 文案来自外层 delivery 兜底
        assert updated.last_error is not None

    def test_session_deleted_blocks_execute(self, tmp_path):
        """目标会话不存在时 execute 直接失败，不调用 runner。"""
        svc = _service(tmp_path, session_exists=False)
        task = _task(id="ex4", mode="execute")
        svc._tasks[task.id] = task  # type: ignore[attr-defined]

        runner = MagicMock()
        svc.set_executor(runner)

        svc._fire(task)

        runner.assert_not_called()
        updated = svc._tasks[task.id]  # type: ignore[attr-defined]
        assert updated.last_status == "failed"
        assert "session" in (updated.last_error or "").lower()


# ------------------------------------------------------------------ #
# update_task 允许 mode 字段
# ------------------------------------------------------------------ #


class TestUpdateTaskMode:
    def test_update_task_accepts_mode(self, tmp_path):
        svc = _service(tmp_path)
        task = _task(id="up1", mode="deliver")
        svc._tasks[task.id] = task  # type: ignore[attr-defined]

        updated = svc.update_task(task.id, mode="execute")
        assert updated.mode == "execute"

    def test_update_task_rejects_invalid_mode(self, tmp_path):
        from backend.services.scheduler import ValidationError

        svc = _service(tmp_path)
        task = _task(id="up2", mode="deliver")
        svc._tasks[task.id] = task  # type: ignore[attr-defined]

        with pytest.raises(ValidationError):
            svc.update_task(task.id, mode="bogus")


# ------------------------------------------------------------------ #
# make_threadsafe_runner 桥接
# ------------------------------------------------------------------ #


class TestThreadsafeBridge:
    def test_success_returns_assistant_id_and_duration(self, tmp_path):
        """真实 loop 在子线程跑 runner：成功路径返回 message_id + duration_ms。"""
        mock_chat = MagicMock()

        async def _fake_run(session_id, message, *, max_iterations=1):
            return [], "asst-abc"
        mock_chat.run_turn_tracked = _fake_run

        loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        t = threading.Thread(target=_run_loop, daemon=True)
        t.start()
        try:
            runner = make_threadsafe_runner(mock_chat, loop, timeout=5)
            task = _task(id="br1")
            outcome = runner(task)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            t.join(timeout=2)
            loop.close()

        assert outcome.status == "succeeded"
        assert outcome.message_id == "asst-abc"
        assert outcome.duration_ms >= 0

    def test_timeout_returns_failed_with_redacted_error(self, tmp_path):
        """run_turn_tracked 挂死 → runner 在 timeout 后返回 failed。"""
        mock_chat = MagicMock()

        async def _hang(*_args, **_kwargs):
            await asyncio.sleep(10)
            return [], "never"
        mock_chat.run_turn_tracked = _hang

        loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        t = threading.Thread(target=_run_loop, daemon=True)
        t.start()
        try:
            runner = make_threadsafe_runner(mock_chat, loop, timeout=1)
            task = _task(id="br2")
            outcome = runner(task)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            t.join(timeout=2)
            loop.close()

        assert outcome.status == "failed"
        assert outcome.error == "Execution timed out"
        assert outcome.duration_ms >= 900  # 至少接近 1 秒

    def test_exception_returns_failed_with_redacted_error(self, tmp_path):
        """run_turn_tracked 抛错 → runner 返回 failed，错误文案脱敏。"""
        mock_chat = MagicMock()

        async def _boom(*_args, **_kwargs):
            raise ValueError("very sensitive internal path / api key")
        mock_chat.run_turn_tracked = _boom

        loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        t = threading.Thread(target=_run_loop, daemon=True)
        t.start()
        try:
            runner = make_threadsafe_runner(mock_chat, loop, timeout=5)
            task = _task(id="br3")
            outcome = runner(task)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            t.join(timeout=2)
            loop.close()

        assert outcome.status == "failed"
        # 错误文案绝不能包含原始异常文本
        assert outcome.error == "Execution failed; see backend logs for details"
        assert "sensitive" not in (outcome.error or "")

    def test_closed_loop_returns_failed(self, tmp_path):
        """loop 已关闭 → run_coroutine_threadsafe 抛错 → 转 failed outcome（不抛回调用方）。"""
        mock_chat = MagicMock()

        async def _real_coro(*_args, **_kwargs):
            return [], "never"
        mock_chat.run_turn_tracked = _real_coro

        closed_loop = asyncio.new_event_loop()
        closed_loop.close()

        runner = make_threadsafe_runner(mock_chat, closed_loop, timeout=5)
        task = _task(id="br4")
        outcome = runner(task)

        assert outcome.status == "failed"
        assert outcome.error == "Execution failed; see backend logs for details"
