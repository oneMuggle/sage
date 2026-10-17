"""JSON → SQLite migration for scheduled tasks.

Covers the one-shot import performed by ``SchedulerService`` when it is
constructed with a ``Database``, plus the guarantee that deleted tasks are not
resurrected from a stale JSON backup on the next restart.
"""
import json
import time
from pathlib import Path

import pytest

from backend.data.database import Database
from backend.services.scheduler import SchedulerService


def json_task(**overrides):
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
        "next_run": None,
        "last_attempt": None,
        "last_status": "never",
        "last_error": None,
        "run_count": 0,
        "max_runs": None,
    }
    row.update(overrides)
    return row


def write_json(path: Path, tasks, version=1):
    path.write_text(
        json.dumps({"version": version, "tasks": tasks}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def db(tmp_path):
    database = Database(str(tmp_path / "scheduled.db"))
    database.init_db()
    yield database
    database.close()


def service(db, store_path):
    return SchedulerService(
        store_path=store_path,
        message_repo=object(),
        session_repo=object(),
        db=db,
    )


def test_json_tasks_are_imported_on_first_startup(db, tmp_path):
    store_path = write_json(tmp_path / "scheduled_tasks.json", [json_task()])

    svc = service(db, store_path)

    assert [t.id for t in svc.list_tasks()] == ["task-9f3a1c02"]
    assert svc.list_tasks()[0].schedule == {"kind": "recurring", "cron": "0 9 * * *"}
    svc.shutdown()


def test_json_file_is_kept_as_a_backup(db, tmp_path):
    store_path = write_json(tmp_path / "scheduled_tasks.json", [json_task()])

    service(db, store_path).shutdown()

    assert store_path.exists(), "迁移后必须保留 JSON 作为备份"


def test_migration_is_idempotent_across_restarts(db, tmp_path):
    store_path = write_json(tmp_path / "scheduled_tasks.json", [json_task()])

    service(db, store_path).shutdown()
    second = service(db, store_path)

    assert len(second.list_tasks()) == 1, "重复启动不得产生重复任务"
    second.shutdown()


def test_deleted_tasks_are_not_resurrected_from_json(db, tmp_path):
    store_path = write_json(tmp_path / "scheduled_tasks.json", [json_task()])
    first = service(db, store_path)
    first.delete_task("task-9f3a1c02")
    first.shutdown()

    second = service(db, store_path)

    assert second.list_tasks() == [], "用户删掉的任务不该被陈旧 JSON 备份复活"
    second.shutdown()


def test_empty_sqlite_with_missing_json_starts_empty(db, tmp_path):
    svc = service(db, tmp_path / "scheduled_tasks.json")

    assert svc.list_tasks() == []
    svc.shutdown()


def test_future_schema_version_is_ignored(db, tmp_path):
    store_path = write_json(tmp_path / "scheduled_tasks.json", [json_task()], version=99)

    svc = service(db, store_path)

    assert svc.list_tasks() == []
    svc.shutdown()


def test_corrupt_json_does_not_block_startup(db, tmp_path):
    store_path = tmp_path / "scheduled_tasks.json"
    store_path.write_text("{ not json", encoding="utf-8")

    svc = service(db, store_path)

    assert svc.list_tasks() == []
    svc.shutdown()


def test_malformed_entries_are_skipped_but_good_ones_import(db, tmp_path):
    store_path = write_json(tmp_path / "scheduled_tasks.json", [
        json_task(id="task-good"),
        {"id": "task-bad"},  # 缺 name/schedule/...
        json_task(id="task-good2", created_at=1770000000001),
    ])

    svc = service(db, store_path)

    assert sorted(t.id for t in svc.list_tasks()) == ["task-good", "task-good2"]
    svc.shutdown()


def test_sqlite_stays_authoritative_after_writes(db, tmp_path):
    """Post-migration writes must land in SQLite and never re-touch the JSON."""
    store_path = write_json(tmp_path / "scheduled_tasks.json", [json_task()])
    svc = service(db, store_path)

    future_ms = int(time.time() * 1000) + 3_600_000
    created = svc.add_task(
        name="一次性提醒",
        task_type="once",
        schedule={"kind": "once", "at": future_ms},
        session_id="sess-0001",
        content="别忘了交周报",
    )
    svc.update_task(created.id, name="改过的名字")
    svc.shutdown()

    on_disk = json.loads(store_path.read_text(encoding="utf-8"))
    assert [t["id"] for t in on_disk["tasks"]] == ["task-9f3a1c02"], \
        "SQLite 模式下不得回写 JSON"

    rows = db.get_connection().execute(
        "SELECT id, name FROM scheduled_tasks ORDER BY created_at, id"
    ).fetchall()
    assert [(r["id"], r["name"]) for r in rows] == [
        ("task-9f3a1c02", "每日晨报"),
        (created.id, "改过的名字"),
    ]


def test_corrupt_json_is_remembered_so_it_is_not_reparsed_every_boot(db, tmp_path):
    store_path = tmp_path / "scheduled_tasks.json"
    store_path.write_text("{ not json", encoding="utf-8")
    service(db, store_path).shutdown()

    store_path.write_text(json.dumps({"version": 1, "tasks": [json_task()]}), encoding="utf-8")
    second = service(db, store_path)

    assert second.list_tasks() == [], "损坏过的 JSON 不应在修复后被二次导入"
    second.shutdown()


def test_legacy_json_mode_still_works_without_a_database(tmp_path):
    """No ``db`` → the pre-existing JSON behaviour must be unchanged."""
    store_path = tmp_path / "scheduled_tasks.json"
    svc = SchedulerService(store_path, object(), object())
    created = svc.add_task(
        name="一次性提醒",
        task_type="once",
        schedule={"kind": "once", "at": int(time.time() * 1000) + 3_600_000},
        session_id="sess-0001",
        content="别忘了交周报",
    )
    svc.shutdown()

    assert json.loads(store_path.read_text(encoding="utf-8"))["tasks"][0]["id"] == created.id

    reopened = SchedulerService(store_path, object(), object())
    assert [t.id for t in reopened.list_tasks()] == [created.id]
    reopened.shutdown()
