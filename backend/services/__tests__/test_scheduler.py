"""Tests for backend.services.scheduler — APScheduler wrapper + persistence."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.services.scheduler import SchedulerService, TaskNotFoundError, ValidationError


@pytest.fixture()
def store_path(tmp_path: Path) -> Path:
    """Per-test JSON store path (file does not yet exist)."""
    return tmp_path / "scheduled_tasks.json"


@pytest.fixture()
def message_repo() -> MagicMock:
    """Mock message repo that records inserted messages."""
    repo = MagicMock()
    repo.insert = MagicMock(return_value={"id": "msg-1"})
    return repo


@pytest.fixture()
def session_repo() -> MagicMock:
    """Mock session repo that confirms session exists."""
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


class TestLoadOnInit:
    def test_returns_empty_list_when_file_missing(self, scheduler: SchedulerService) -> None:
        assert scheduler.list_tasks() == []

    def test_loads_tasks_from_existing_file(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        store_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "tasks": [
                        {
                            "id": "t-1",
                            "name": "Morning brief",
                            "type": "recurring",
                            "schedule": {"kind": "recurring", "cron": "0 8 * * *"},
                            "session_id": "s-1",
                            "content": "good morning",
                            "enabled": True,
                            "created_at": 1700000000000,
                        }
                    ],
                }
            )
        )
        svc = SchedulerService(
            store_path=store_path, message_repo=message_repo, session_repo=session_repo
        )
        tasks = svc.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == "t-1"
        assert tasks[0].name == "Morning brief"


class TestAddTask:
    def test_adds_recurring_task(self, scheduler: SchedulerService) -> None:
        task = scheduler.add_task(
            name="Daily standup",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 9 * * 1-5"},
            session_id="s-1",
            content="Daily standup reminder",
        )
        assert task.id.startswith("task-")
        assert task.name == "Daily standup"
        assert task.type == "recurring"
        assert task.enabled is True
        assert scheduler.list_tasks()[0].id == task.id

    def test_adds_one_shot_task_with_at_timestamp(self, scheduler: SchedulerService) -> None:
        future_at = int(time.time() * 1000) + 60_000  # 60 seconds from now
        task = scheduler.add_task(
            name="Meeting reminder",
            task_type="once",
            schedule={"kind": "once", "at": future_at},
            session_id="s-1",
            content="Meeting starts in 5 min",
        )
        assert task.type == "once"
        assert task.next_run == future_at

    def test_rejects_invalid_cron_expression(self, scheduler: SchedulerService) -> None:
        with pytest.raises(ValidationError):
            scheduler.add_task(
                name="Bad",
                task_type="recurring",
                schedule={"kind": "recurring", "cron": "this is not cron"},
                session_id="s-1",
                content="x",
            )

    def test_rejects_one_shot_in_the_past(self, scheduler: SchedulerService) -> None:
        past_at = int(time.time() * 1000) - 60_000
        with pytest.raises(ValidationError):
            scheduler.add_task(
                name="Old",
                task_type="once",
                schedule={"kind": "once", "at": past_at},
                session_id="s-1",
                content="x",
            )

    def test_rejects_nonexistent_session(
        self, scheduler: SchedulerService, session_repo: MagicMock
    ) -> None:
        session_repo.exists.return_value = False
        with pytest.raises(ValidationError):
            scheduler.add_task(
                name="Bad session",
                task_type="recurring",
                schedule={"kind": "recurring", "cron": "0 8 * * *"},
                session_id="ghost",
                content="x",
            )

    def test_persists_to_disk(self, scheduler: SchedulerService, store_path: Path) -> None:
        scheduler.add_task(
            name="Persist me",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s-1",
            content="hello",
        )
        assert store_path.exists()
        data = json.loads(store_path.read_text())
        assert data["version"] == 1
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["name"] == "Persist me"


class TestUpdateTask:
    def test_updates_name(self, scheduler: SchedulerService) -> None:
        task = scheduler.add_task(
            name="Old name",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s-1",
            content="x",
        )
        updated = scheduler.update_task(task.id, name="New name")
        assert updated.name == "New name"

    def test_updates_enabled_flag(self, scheduler: SchedulerService) -> None:
        task = scheduler.add_task(
            name="Pauseable",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s-1",
            content="x",
        )
        scheduler.update_task(task.id, enabled=False)
        assert scheduler.get_task(task.id).enabled is False

    def test_raises_on_missing_task(self, scheduler: SchedulerService) -> None:
        with pytest.raises(TaskNotFoundError):
            scheduler.update_task("task-missing", name="x")


class TestDeleteTask:
    def test_removes_task(self, scheduler: SchedulerService) -> None:
        task = scheduler.add_task(
            name="Delete me",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s-1",
            content="x",
        )
        scheduler.delete_task(task.id)
        assert scheduler.list_tasks() == []

    def test_raises_on_missing_task(self, scheduler: SchedulerService) -> None:
        with pytest.raises(TaskNotFoundError):
            scheduler.delete_task("task-missing")

    def test_expected_session_mismatch_refuses_delete(
        self, scheduler: SchedulerService
    ) -> None:
        """2026-09-19 安全审查修复: expected_session_id 与任务归属不符时
        拒绝删除（原子校验，供 LLM 工具消除 TOCTOU 窗口）。"""
        task = scheduler.add_task(
            name="owned by s-1",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s-1",
            content="x",
        )
        with pytest.raises(ValidationError):
            scheduler.delete_task(task.id, expected_session_id="s-2")
        # 任务未被删除
        assert len(scheduler.list_tasks()) == 1

    def test_expected_session_match_deletes(
        self, scheduler: SchedulerService
    ) -> None:
        """归属一致时原子删除成功。"""
        task = scheduler.add_task(
            name="owned by s-1",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s-1",
            content="x",
        )
        scheduler.delete_task(task.id, expected_session_id="s-1")
        assert scheduler.list_tasks() == []


class TestRunNow:
    def test_fires_task_immediately_and_inserts_message(
        self, scheduler: SchedulerService, message_repo: MagicMock
    ) -> None:
        task = scheduler.add_task(
            name="Run now",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s-1",
            content="manual trigger",
        )
        scheduler.run_now(task.id)
        message_repo.insert.assert_called_once()
        kwargs = message_repo.insert.call_args.kwargs
        assert kwargs["session_id"] == "s-1"
        assert kwargs["role"] == "system"
        assert kwargs["content"] == "manual trigger"
        assert kwargs["created_at"] > 0

    def test_skips_when_session_missing(
        self, scheduler: SchedulerService, session_repo: MagicMock, message_repo: MagicMock
    ) -> None:
        task = scheduler.add_task(
            name="Ghost session",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s-1",
            content="x",
        )
        session_repo.exists.return_value = False
        scheduler.run_now(task.id)
        message_repo.insert.assert_not_called()

    def test_disables_one_shot_after_firing(
        self, scheduler: SchedulerService, message_repo: MagicMock
    ) -> None:
        future_at = int(time.time() * 1000) + 60_000
        task = scheduler.add_task(
            name="One shot",
            task_type="once",
            schedule={"kind": "once", "at": future_at},
            session_id="s-1",
            content="once",
        )
        scheduler.run_now(task.id)
        assert scheduler.get_task(task.id).enabled is False


class TestLifecycle:
    def test_start_and_stop_scheduler(self, scheduler: SchedulerService) -> None:
        scheduler.start()
        assert scheduler.is_running() is True
        scheduler.shutdown()
        assert scheduler.is_running() is False

    def test_shutdown_is_idempotent(self, scheduler: SchedulerService) -> None:
        scheduler.start()
        scheduler.shutdown()
        scheduler.shutdown()  # must not raise
        assert scheduler.is_running() is False


class TestAddTaskValidation:
    def test_empty_name_raises(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        svc = SchedulerService(
            store_path=store_path, message_repo=message_repo, session_repo=session_repo
        )
        with pytest.raises(ValidationError, match="name"):
            svc.add_task(
                name="",
                task_type="recurring",
                schedule={"kind": "recurring", "cron": "0 8 * * *"},
                session_id="s",
                content="x",
            )

    def test_empty_content_raises(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        svc = SchedulerService(
            store_path=store_path, message_repo=message_repo, session_repo=session_repo
        )
        with pytest.raises(ValidationError, match="content"):
            svc.add_task(
                name="ok",
                task_type="recurring",
                schedule={"kind": "recurring", "cron": "0 8 * * *"},
                session_id="s",
                content="",
            )

    def test_empty_cron_raises(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        svc = SchedulerService(
            store_path=store_path, message_repo=message_repo, session_repo=session_repo
        )
        with pytest.raises(ValidationError, match="cron"):
            svc.add_task(
                name="ok",
                task_type="recurring",
                schedule={"kind": "recurring", "cron": ""},
                session_id="s",
                content="x",
            )


class TestOnceAtRangeGuard:
    """2026-09-19: 越界 once 'at' 必须在落盘前拦下，且不得阻断重启。

    修复前：at 超界（如 1e17 ms）先被持久化，再在 _schedule_job 抛
    ValueError —— 磁盘上留下无法调度的任务，重启时 _reschedule_all 抛同一
    异常使 SchedulerService 构造失败（后端起不来）。
    """

    def test_unrepresentable_at_rejected_without_persisting(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        svc = SchedulerService(
            store_path=store_path, message_repo=message_repo, session_repo=session_repo
        )
        with pytest.raises(ValidationError, match="representable"):
            svc.add_task(
                name="越界",
                task_type="once",
                schedule={"kind": "once", "at": 99999999999999999},
                session_id="s",
                content="x",
            )
        assert svc.list_tasks() == []
        assert not store_path.exists()

    def test_restart_survives_persisted_unrepresentable_at(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        """磁盘上已有坏条目时，构造不得抛异常（旧版本写入的脏数据）。"""
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "tasks": [
                        {
                            "id": "task-bad",
                            "name": "bad",
                            "type": "once",
                            "schedule": {"kind": "once", "at": 99999999999999999},
                            "session_id": "s",
                            "content": "x",
                            "enabled": True,
                            "created_at": 0,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        svc = SchedulerService(
            store_path=store_path, message_repo=message_repo, session_repo=session_repo
        )
        tasks = svc.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].last_status == "failed"
        assert tasks[0].last_error

    @pytest.mark.timeout(15)
    def test_restart_with_expired_once_task_does_not_deadlock(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        """2026-09-19 安全审查修复: 合法但已过期的一次性任务在重启登记时
        走 missed 分支 → _record_run。修复前 _schedule_job 在持
        ``threading.Lock`` 状态下调用 _record_run（内部再获同一把非重入锁）
        → 死锁，后端 __init__ 永久挂起。

        与上一个用例的区别：``at`` 是**合法可表示但已过去**的毫秒值，能通过
        ``_epoch_ms_to_dt``，从而真正走到锁嵌套代码；越界值在更早处就抛异常，
        掩盖了这条路径。用 pytest-timeout 防止回归时测试自身挂死。"""
        past_ms = int(time.time() * 1000) - 60_000
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "tasks": [
                        {
                            "id": "task-expired",
                            "name": "expired",
                            "type": "once",
                            "schedule": {"kind": "once", "at": past_ms},
                            "session_id": "s",
                            "content": "x",
                            "enabled": True,
                            "created_at": 0,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        svc = SchedulerService(
            store_path=store_path, message_repo=message_repo, session_repo=session_repo
        )
        tasks = svc.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].last_status == "failed"
        assert "missed" in (tasks[0].last_error or "")
        # 一次性任务错过触发点后停用，不自动重放
        assert tasks[0].enabled is False


class TestLoadEdgeCases:
    def test_corrupt_json_falls_back(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        store_path.write_text("{not valid json")
        svc = SchedulerService(
            store_path=store_path, message_repo=message_repo, session_repo=session_repo
        )
        assert svc.list_tasks() == []

    def test_wrong_schema_version_ignored(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        store_path.write_text(json.dumps({"version": 99, "tasks": []}))
        svc = SchedulerService(
            store_path=store_path, message_repo=message_repo, session_repo=session_repo
        )
        assert svc.list_tasks() == []

    def test_malformed_task_skipped(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        store_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "tasks": [
                        {"id": "x", "missing": "fields"},
                        {
                            "id": "good",
                            "name": "ok",
                            "type": "recurring",
                            "schedule": {"kind": "recurring", "cron": "0 8 * * *"},
                            "session_id": "s",
                            "content": "x",
                            "enabled": True,
                            "created_at": 1,
                        },
                    ],
                }
            )
        )
        svc = SchedulerService(
            store_path=store_path, message_repo=message_repo, session_repo=session_repo
        )
        tasks = svc.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == "good"

    def test_corrupt_recurring_cron_does_not_block_startup(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        """2026-09-19: 结构合法但 cron 损坏的 recurring 任务（磁盘脏数据 /
        手改 JSON）此前会在 __init__ → _reschedule_all → _schedule_job 抛
        ValueError，随后 _record_run 经 _next_run_for 再抛 CroniterBadCronError
        （继承 ValueError），击穿逐条容错使后端构造失败。现在 _next_run_for
        对损坏 cron 返回 None，任务标记 failed 但启动不受影响。"""
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "tasks": [
                        {
                            "id": "task-corrupt-cron",
                            "name": "corrupt",
                            "type": "recurring",
                            "schedule": {"kind": "recurring", "cron": "totally-not-a-cron"},
                            "session_id": "s",
                            "content": "x",
                            "enabled": True,
                            "created_at": 0,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        svc = SchedulerService(
            store_path=store_path, message_repo=message_repo, session_repo=session_repo
        )
        tasks = svc.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].last_status == "failed"
        assert tasks[0].next_run is None


class TestRunNowEdgeCases:
    def test_run_now_recurring_keeps_enabled_and_updates_next(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        svc = SchedulerService(
            store_path=store_path, message_repo=message_repo, session_repo=session_repo
        )
        task = svc.add_task(
            name="rec",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s",
            content="x",
        )
        svc.run_now(task.id)
        after = svc.get_task(task.id)
        assert after.enabled is True
        assert after.last_run is not None
        assert after.next_run is not None

    def test_run_now_message_repo_raises_but_state_survives(
        self, store_path: Path, session_repo: MagicMock
    ) -> None:
        repo = MagicMock()
        repo.insert = MagicMock(side_effect=RuntimeError("boom"))
        repo.exists = MagicMock(return_value=True)
        svc = SchedulerService(store_path=store_path, message_repo=repo, session_repo=session_repo)
        task = svc.add_task(
            name="r",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s",
            content="x",
        )
        # must not raise
        svc.run_now(task.id)

    def test_run_now_missing_task_raises(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        svc = SchedulerService(
            store_path=store_path, message_repo=message_repo, session_repo=session_repo
        )
        with pytest.raises(TaskNotFoundError):
            svc.run_now("nope")


class TestUpdateValidation:
    def test_update_invalid_name_type(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        svc = SchedulerService(
            store_path=store_path, message_repo=message_repo, session_repo=session_repo
        )
        task = svc.add_task(
            name="r",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s",
            content="x",
        )
        with pytest.raises(ValidationError):
            svc.update_task(task.id, name="")


class TestGetTaskMissing:
    def test_get_task_missing_raises(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        svc = SchedulerService(
            store_path=store_path, message_repo=message_repo, session_repo=session_repo
        )
        with pytest.raises(TaskNotFoundError):
            svc.get_task("nope")


class TestGlobalService:
    def test_init_scheduler_service_global(
        self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock
    ) -> None:
        from backend.services import scheduler as mod

        mod._global_service = None
        try:
            svc = mod.init_scheduler_service(
                store_path=store_path,
                message_repo=message_repo,
                session_repo=session_repo,
            )
            assert mod.get_scheduler_service() is svc
        finally:
            mod._global_service = None


class TestSessionRepoFallbacks:
    def test_session_repo_with_get_returns_none(
        self, store_path: Path, message_repo: MagicMock
    ) -> None:
        repo = MagicMock(spec=["get"])
        repo.get = MagicMock(return_value=None)
        svc = SchedulerService(store_path=store_path, message_repo=message_repo, session_repo=repo)
        with pytest.raises(ValidationError, match="session"):
            svc.add_task(
                name="r",
                task_type="recurring",
                schedule={"kind": "recurring", "cron": "0 8 * * *"},
                session_id="ghost",
                content="x",
            )

    def test_session_repo_with_no_methods_allows(
        self, store_path: Path, message_repo: MagicMock
    ) -> None:
        # Empty MagicMock with no exists/get attrs behaves as allow
        svc = SchedulerService(
            store_path=store_path,
            message_repo=message_repo,
            session_repo=MagicMock(),
        )
        # Should not raise
        task = svc.add_task(
            name="r",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="ghost",
            content="x",
        )
        assert task.id.startswith("task-")


# ------------------------------------------------------------------ #
# PR-C §5.1: evolution task scheduler wire-up                     #
# ------------------------------------------------------------------ #


class TestRegisterEvolutionTask:
    """Tests for SchedulerService.register_evolution_task()."""

    def test_cron_expr_only_registers_job(
        self, scheduler: SchedulerService
    ) -> None:
        mock_task = MagicMock()
        scheduler.register_evolution_task(
            name="t1", task=mock_task, cron_expr="0 3 * * *"
        )
        job = scheduler._scheduler.get_job("evolution/t1")
        assert job is not None
        assert scheduler._evolution_tasks["t1"] is mock_task

    def test_hour_minute_builds_cron(
        self, scheduler: SchedulerService
    ) -> None:
        mock_task = MagicMock()
        scheduler.register_evolution_task(
            name="t2", task=mock_task, hour=4, minute=30
        )
        job = scheduler._scheduler.get_job("evolution/t2")
        assert job is not None
        # 验证 cron expr 通过 trigger 的 str repr 包含 30 4
        trigger_str = str(job.trigger)
        assert "30" in trigger_str
        assert "4" in trigger_str
        # 验证 fields 至少一个含 hour=4 + minute=30 + dow=*
        all_exprs = []
        for f in job.trigger.fields:
            for e in f.expressions:
                all_exprs.append(str(e))
        assert "4" in all_exprs
        assert "30" in all_exprs
        assert "*" in all_exprs

    def test_hour_minute_day_of_week_builds_cron(
        self, scheduler: SchedulerService
    ) -> None:
        mock_task = MagicMock()
        scheduler.register_evolution_task(
            name="t3", task=mock_task,
            hour=4, minute=30, day_of_week="0",
        )
        job = scheduler._scheduler.get_job("evolution/t3")
        all_exprs = []
        for f in job.trigger.fields:
            for e in f.expressions:
                all_exprs.append(str(e))
        # dow=0 出现,无 '*'
        assert "0" in all_exprs
        assert "4" in all_exprs
        assert "30" in all_exprs

    def test_cron_and_hour_mutually_exclusive_raises(
        self, scheduler: SchedulerService
    ) -> None:
        mock_task = MagicMock()
        with pytest.raises(ValueError, match="互斥"):
            scheduler.register_evolution_task(
                name="t4", task=mock_task,
                cron_expr="0 3 * * *", hour=4, minute=30,
            )

    def test_missing_both_raises(
        self, scheduler: SchedulerService
    ) -> None:
        mock_task = MagicMock()
        with pytest.raises(ValueError, match="必须传"):
            scheduler.register_evolution_task(name="t5", task=mock_task)

    def test_replace_existing_overwrites(
        self, scheduler: SchedulerService
    ) -> None:
        t1 = MagicMock(name="t1")
        t2 = MagicMock(name="t2")
        scheduler.register_evolution_task(
            name="t6", task=t1, cron_expr="0 3 * * *"
        )
        scheduler.register_evolution_task(
            name="t6", task=t2, cron_expr="0 4 * * *"
        )
        assert scheduler._evolution_tasks["t6"] is t2


class TestTriggerEvolutionTask:
    def test_unknown_name_returns_false(
        self, scheduler: SchedulerService
    ) -> None:
        assert scheduler.trigger_evolution_task("nope") is False

    def test_known_name_runs_task(
        self, scheduler: SchedulerService
    ) -> None:
        mock_task = MagicMock()
        mock_task.run.return_value = {"status": "ok"}
        scheduler.register_evolution_task(
            name="r1", task=mock_task, cron_expr="0 3 * * *"
        )
        assert scheduler.trigger_evolution_task("r1") is True
        mock_task.run.assert_called_once()


class TestGetEvolutionTaskNames:
    def test_empty_initially(
        self, scheduler: SchedulerService
    ) -> None:
        assert scheduler.get_evolution_task_names() == []

    def test_lists_after_register(
        self, scheduler: SchedulerService
    ) -> None:
        for n in ("a", "b", "c"):
            scheduler.register_evolution_task(
                name=n, task=MagicMock(), cron_expr="0 3 * * *"
            )
        assert set(scheduler.get_evolution_task_names()) == {"a", "b", "c"}
