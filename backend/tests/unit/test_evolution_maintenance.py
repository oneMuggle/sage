"""evolution_maintenance 补跑/空闲门控测试。"""

import json
import time
import uuid

from backend.scheduler.evolution_maintenance import (
    DAILY_CADENCE_SECONDS,
    HEAVY_TASKS,
    WEEKLY_CADENCE_SECONDS,
    compute_overdue_tasks,
    reset_maintenance_state,
    run_overdue_tasks,
    start_maintenance,
)


class FakeScheduler:
    def __init__(self, names, results=None):
        self.names = list(names)
        self.results = results or {}
        self.calls = []
        self.system_tasks = []

    def get_evolution_task_names(self):
        return list(self.names)

    def run_evolution_task_now(self, name):
        self.calls.append(name)
        return self.results.get(name, {"ok": True})

    def register_system_task(self, name, fn, cron_expr):
        self.system_tasks.append((name, fn, cron_expr))


def _insert_log(db, evolution_type, status, created_at_s):
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO evolution_log
        (id, evolution_type, description, status, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), evolution_type, "test", status, int(created_at_s)),
    )
    conn.commit()


def test_compute_overdue_tasks_marks_never_ran_and_stale(setup_test_db):
    db = setup_test_db
    now_ms_value = 1_800_000_000_000
    now_s = now_ms_value // 1000
    _insert_log(db, "daily_summary", "success", now_s - 10 * 3600)
    _insert_log(db, "memory_reflection", "success", now_s - WEEKLY_CADENCE_SECONDS - 3600)
    scheduler = FakeScheduler(["daily_summary", "memory_reflection", "memory_pruning"])

    overdue = compute_overdue_tasks(db, scheduler, now_ms_value=now_ms_value)

    assert "daily_summary" not in overdue
    assert "memory_reflection" in overdue
    assert "memory_pruning" in overdue


def test_failed_recent_attempt_defers_retry(setup_test_db):
    db = setup_test_db
    now_ms_value = 1_800_000_000_000
    now_s = now_ms_value // 1000
    _insert_log(db, "memory_pruning", "failed", now_s - 10 * 60)
    scheduler = FakeScheduler(["memory_pruning"])

    assert compute_overdue_tasks(db, scheduler, now_ms_value=now_ms_value) == []

    # 失败超过 1 小时后允许重试
    assert compute_overdue_tasks(db, scheduler, now_ms_value=now_ms_value + 2 * 3600 * 1000) == [
        "memory_pruning"
    ]


def test_run_overdue_skips_heavy_tasks_when_user_active(setup_test_db):
    reset_maintenance_state()
    db = setup_test_db
    scheduler = FakeScheduler(["daily_summary", "memory_reflection"])
    now_ms_value = 1_800_000_000_000

    executed = run_overdue_tasks(
        scheduler,
        db,
        idle_check=lambda: False,
        now_ms_value=now_ms_value,
    )

    assert executed == ["daily_summary"]
    assert scheduler.calls == ["daily_summary"]
    assert "memory_reflection" not in scheduler.calls


def test_run_overdue_runs_heavy_task_when_idle(setup_test_db):
    reset_maintenance_state()
    db = setup_test_db
    scheduler = FakeScheduler(["memory_reflection"])
    now_ms_value = 1_800_000_000_000

    executed = run_overdue_tasks(
        scheduler,
        db,
        idle_check=lambda: True,
        now_ms_value=now_ms_value,
    )

    assert executed == ["memory_reflection"]
    assert scheduler.calls == ["memory_reflection"]


def test_run_overdue_writes_catchup_log(setup_test_db):
    reset_maintenance_state()
    db = setup_test_db
    scheduler = FakeScheduler(["daily_summary"])
    now_ms_value = 1_800_000_000_000

    run_overdue_tasks(
        scheduler,
        db,
        idle_check=lambda: True,
        now_ms_value=now_ms_value,
    )

    row = (
        db.get_connection()
        .execute(
            """
        SELECT trigger_type, status, metrics_json
        FROM evolution_log
        WHERE evolution_type = 'maintenance_catchup'
        ORDER BY rowid DESC LIMIT 1
        """
        )
        .fetchone()
    )
    assert row is not None
    assert row["trigger_type"] == "catch_up"
    assert row["status"] == "success"
    metrics = json.loads(row["metrics_json"])
    assert metrics["executed"] == ["daily_summary"]


def test_start_maintenance_registers_system_task(setup_test_db):
    reset_maintenance_state()
    db = setup_test_db
    scheduler = FakeScheduler([])

    start_maintenance(scheduler, db, startup_delay_seconds=0)
    # 延迟线程是 daemon；给注册动作一个短暂窗口（注册是同步完成的，
    # 这里主要验证幂等与 cron 表达式）。
    time.sleep(0.05)

    assert scheduler.system_tasks
    name, _fn, cron_expr = scheduler.system_tasks[0]
    assert name == "evolution-catchup"
    assert cron_expr == "7,37 * * * *"

    # 幂等：再次调用不重复注册
    start_maintenance(scheduler, db, startup_delay_seconds=0)
    assert len(scheduler.system_tasks) == 1

    reset_maintenance_state()


def test_heavy_tasks_are_the_expected_set():
    expected = {
        "memory_reflection",
        "memory_consolidation",
        "skill_consolidation",
    }
    assert expected == HEAVY_TASKS
    assert DAILY_CADENCE_SECONDS < WEEKLY_CADENCE_SECONDS
