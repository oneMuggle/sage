"""Real SQLite coverage for scheduled-task persistence."""

import json
import sqlite3

import pytest

from backend.data.database import Database
from backend.services.scheduler_repository import ScheduledTaskRepository


def task(**overrides):
    row = {
        "id": "task-9f3a1c02",
        "name": "每日晨报",
        "type": "recurring",
        "schedule": {"kind": "recurring", "cron": "0 9 * * *"},
        "session_id": "sess-0001",
        "content": "汇总昨日未完成待办",
        "enabled": True,
        "created_at": 1770000000000,
        "last_run": None,
        "next_run": 1770086400000,
        "last_attempt": None,
        "last_status": "never",
        "last_error": None,
        "run_count": 0,
        "max_runs": None,
    }
    row.update(overrides)
    return row


@pytest.fixture()
def repo(tmp_path):
    db = Database(str(tmp_path / "scheduled.db"))
    db.init_db()
    yield ScheduledTaskRepository(db)
    db.close()


def test_upsert_then_get_roundtrips_every_field(repo):
    repo.upsert(task())

    stored = repo.get("task-9f3a1c02")

    assert stored == task()


def test_upsert_encodes_schedule_as_json_text(repo):
    repo.upsert(task())
    raw = repo.db.get_connection().execute(
        "SELECT schedule, enabled FROM scheduled_tasks WHERE id=?", ("task-9f3a1c02",)
    ).fetchone()

    assert json.loads(raw["schedule"]) == {"kind": "recurring", "cron": "0 9 * * *"}
    assert raw["enabled"] == 1


def test_get_returns_none_for_unknown_id(repo):
    assert repo.get("task-missing") is None


def test_upsert_replaces_instead_of_duplicating(repo):
    repo.upsert(task())
    repo.upsert(task(name="改后的名字", enabled=False, run_count=3))

    assert repo.count() == 1
    stored = repo.get("task-9f3a1c02")
    assert stored["name"] == "改后的名字"
    assert stored["enabled"] is False
    assert stored["run_count"] == 3


def test_list_all_orders_by_creation_then_id(repo):
    repo.upsert(task(id="task-b", created_at=2000))
    repo.upsert(task(id="task-a", created_at=1000))
    repo.upsert(task(id="task-c", created_at=1000))

    assert [row["id"] for row in repo.list_all()] == ["task-a", "task-c", "task-b"]


def test_delete_reports_whether_a_row_was_removed(repo):
    repo.upsert(task())

    assert repo.delete("task-9f3a1c02") is True
    assert repo.delete("task-9f3a1c02") is False
    assert repo.count() == 0


def test_bulk_upsert_writes_every_row_and_returns_the_count(repo):
    written = repo.bulk_upsert([
        task(id="task-a", created_at=1000),
        task(id="task-b", created_at=2000),
    ])

    assert written == 2
    assert repo.count() == 2


def test_bulk_upsert_of_empty_list_is_a_noop(repo):
    assert repo.bulk_upsert([]) == 0
    assert repo.count() == 0


def test_bulk_upsert_leaves_existing_rows_untouched_on_failure(repo):
    repo.upsert(task(id="task-a", created_at=1000))

    with pytest.raises(sqlite3.IntegrityError):
        # ``type`` violates the CHECK constraint, so the whole batch rolls back.
        repo.bulk_upsert([
            task(id="task-b", created_at=2000),
            task(id="task-c", type="weekly"),
        ])

    assert [row["id"] for row in repo.list_all()] == ["task-a"]


def test_one_shot_task_keeps_null_time_columns(repo):
    repo.upsert(task(type="once", schedule={"kind": "once", "at": 1770086400000}))

    stored = repo.get("task-9f3a1c02")
    assert stored["schedule"] == {"kind": "once", "at": 1770086400000}
    assert stored["last_run"] is None
    assert stored["last_attempt"] is None
    assert stored["max_runs"] is None
