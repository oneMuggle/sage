"""evolution_runner 执行包装测试（2026-11-26 P1：取消 / 通知 / 终态登记）。"""

from __future__ import annotations

import pytest

from backend.scheduler.evolution import EvolutionTaskCancelled
from backend.scheduler.evolution_run_registry import (
    STATE_CANCELLED,
    STATE_FAILED,
    STATE_SUCCEEDED,
    get_evolution_run_registry,
)
from backend.scheduler.evolution_runner import run_evolution_task
from backend.services.background_notifications import get_background_notification_queue

pytestmark = pytest.mark.unit


class _FakeTask:
    """最小任务桩：只需 runner 用到的接口。"""

    def __init__(
        self,
        result: object = None,
        error: Exception | None = None,
        cancelled: bool = False,
    ) -> None:
        self.result = result
        self.error = error
        self.cancelled = cancelled
        self.progress_reporter = None
        self.cancel_check = None

    def set_progress_reporter(self, reporter) -> None:  # noqa: ANN001 — 接口契约
        self.progress_reporter = reporter

    def set_cancel_check(self, checker) -> None:  # noqa: ANN001 — 接口契约
        self.cancel_check = checker

    def run(self):
        if self.cancelled:
            raise EvolutionTaskCancelled()
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture(autouse=True)
def _reset_state():
    get_evolution_run_registry().reset()
    get_background_notification_queue().drain()
    yield
    get_evolution_run_registry().reset()
    get_background_notification_queue().drain()


def test_manual_success_registers_state_and_notifies() -> None:
    result = run_evolution_task(
        "memory_reflection", _FakeTask({"deduped": 2, "merged": 1}), trigger="manual"
    )

    assert result == {"deduped": 2, "merged": 1}
    snap = get_evolution_run_registry().snapshot("memory_reflection")
    assert snap["state"] == STATE_SUCCEEDED
    assert snap["result"] == {"deduped": 2, "merged": 1}

    items = get_background_notification_queue().drain()
    assert len(items) == 1
    assert items[0]["kind"] == "evolution_task"
    assert items[0]["title"] == "✅ 记忆整理完成"
    assert "deduped: 2" in items[0]["body"]
    assert "reflection_backlog_cursor_ms" not in items[0]["body"]


def test_cron_success_does_not_notify() -> None:
    run_evolution_task("memory_reflection", _FakeTask({"total": 1}), trigger="scheduled")

    assert get_background_notification_queue().drain() == []
    snap = get_evolution_run_registry().snapshot("memory_reflection")
    assert snap["state"] == STATE_SUCCEEDED
    assert snap["trigger"] == "scheduled"


def test_cancel_registers_cancelled_state_and_notifies() -> None:
    result = run_evolution_task("memory_reflection", _FakeTask(cancelled=True), trigger="manual")

    assert result is None
    snap = get_evolution_run_registry().snapshot("memory_reflection")
    assert snap["state"] == STATE_CANCELLED
    assert snap["phase_label"] == "已取消"

    items = get_background_notification_queue().drain()
    assert items[0]["title"] == "⏹ 记忆整理已取消"


def test_failure_registers_failed_state_and_notifies() -> None:
    result = run_evolution_task(
        "memory_pruning", _FakeTask(error=RuntimeError("boom")), trigger="manual"
    )

    assert result is None
    snap = get_evolution_run_registry().snapshot("memory_pruning")
    assert snap["state"] == STATE_FAILED
    assert "boom" in (snap["error"] or "")

    items = get_background_notification_queue().drain()
    assert items[0]["title"] == "❌ 记忆修剪失败"
    assert "boom" in items[0]["body"]


def test_cancel_check_injected_and_cleared() -> None:
    task = _FakeTask({"total": 0})
    run_evolution_task("memory_reflection", task, trigger="manual")

    # finally 清理：任务对象不残留执行器回调（避免下一轮误用）
    assert task.cancel_check is None
    assert task.progress_reporter is None
