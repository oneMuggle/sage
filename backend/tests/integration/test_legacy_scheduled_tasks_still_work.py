"""Phase 8 ScheduledTask 零回归测试 (PR-C §5.1).

§5.1 在 SchedulerService 上加 4 个 evolution 方法时,确保原有
add_task / JSON 持久化 / task- 前缀 job_id 行为未受影响。
"""

from __future__ import annotations

import json
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


def _add_recurring_task(
    scheduler: SchedulerService, name: str = "user-task"
) -> str:
    """Phase 8 user task: cron recurring. Returns task id."""
    future = int(time.time() * 1000) + 60_000
    task = scheduler.add_task(
        name=name,
        task_type="once",
        schedule={"at": future},
        session_id="s-1",
        content="echo",
    )
    return task.id


def test_add_task_persists_to_json(
    scheduler: SchedulerService, store_path: Path
) -> None:
    """add_task 写 JSON 文件,包含新增任务。"""
    _add_recurring_task(scheduler, name="persist-me")
    assert store_path.is_file()
    data = json.loads(store_path.read_text("utf-8"))
    tasks = data["tasks"] if isinstance(data, dict) else data
    assert len(tasks) == 1
    assert tasks[0]["name"] == "persist-me"


def test_add_task_job_visible_in_scheduler(scheduler: SchedulerService) -> None:
    """add_task 后 _scheduler 包含 task- 前缀 job。"""
    tid = _add_recurring_task(scheduler)
    jobs = scheduler._scheduler.get_jobs()  # noqa: SLF001
    job_ids = {j.id for j in jobs}
    assert tid in job_ids


def test_register_evolution_task_does_not_interfere(
    scheduler: SchedulerService, store_path: Path
) -> None:
    """混合 evolution + Phase 8 user task:两种 job_id 前缀共存不冲突。"""
    from backend.services._evolution_register import _register_evolution_tasks

    _register_evolution_tasks(scheduler, config_path=store_path)
    user_tid = _add_recurring_task(scheduler)

    job_ids = {j.id for j in scheduler._scheduler.get_jobs()}  # noqa: SLF001
    evolution_jobs = {j for j in job_ids if j.startswith("evolution/")}
    user_jobs = {j for j in job_ids if j.startswith("task-")}

    assert len(evolution_jobs) == 5
    assert user_tid in user_jobs
    # JSON 持久化层只有 user task,evolution task 是 in-process 内存态
    data = json.loads(store_path.read_text("utf-8"))
    tasks = data["tasks"] if isinstance(data, dict) else data
    assert len(tasks) == 1
    assert tasks[0]["name"] == "user-task"
