"""定时任务桌面通知队列测试（2026-11-05）。

从 ``test_scheduler.py`` 拆出：原文件已接近 800 行政策上限。
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.services.scheduler import SchedulerService


@pytest.fixture()
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "scheduled_tasks.json"


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
def scheduler(
    store_path: Path, message_repo: MagicMock, session_repo: MagicMock
) -> SchedulerService:
    return SchedulerService(
        store_path=store_path,
        message_repo=message_repo,
        session_repo=session_repo,
    )


class TestDesktopNotifications:
    """2026-11-05: 定时任务触发后向 Electron 通知队列投递 payload。"""

    def _add_once_task(self, scheduler: SchedulerService, name: str = "日报"):
        return scheduler.add_task(
            name=name,
            task_type="once",
            schedule={"kind": "once", "at": int(time.time() * 1000) + 86_400_000},
            session_id="s-1",
            content="生成日报",
            enabled=False,
        )

    def test_successful_fire_queues_notification(
        self, scheduler: SchedulerService
    ) -> None:
        task = self._add_once_task(scheduler)
        scheduler.run_now(task.id)

        pending = scheduler.drain_pending_notifications()
        assert len(pending) == 1
        item = pending[0]
        assert item["kind"] == "scheduled_task"
        assert item["task_id"] == task.id
        assert item["task_name"] == "日报"
        assert item["status"] == "succeeded"
        assert "✅" in item["title"]
        assert item["body"] == "生成日报"
        assert isinstance(item["created_at"], str)

    def test_failed_delivery_queues_failure_notification(
        self, scheduler: SchedulerService, session_repo: MagicMock
    ) -> None:
        task = self._add_once_task(scheduler)
        session_repo.exists.return_value = False
        scheduler.run_now(task.id)

        pending = scheduler.drain_pending_notifications()
        assert len(pending) == 1
        assert pending[0]["status"] == "failed"
        assert "❌" in pending[0]["title"]

    def test_drain_is_atomic(
        self, scheduler: SchedulerService
    ) -> None:
        task = self._add_once_task(scheduler)
        scheduler.run_now(task.id)
        assert len(scheduler.drain_pending_notifications()) == 1
        assert scheduler.drain_pending_notifications() == []

    def test_manual_rerun_queues_again(
        self, scheduler: SchedulerService
    ) -> None:
        task = self._add_once_task(scheduler)
        scheduler.run_now(task.id)
        scheduler.drain_pending_notifications()
        scheduler.run_now(task.id)
        assert len(scheduler.drain_pending_notifications()) == 1
