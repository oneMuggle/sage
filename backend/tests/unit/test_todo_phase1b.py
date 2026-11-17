"""TodoService 阶段 1b 测试：自定义提醒档位（reminder_offsets）。"""
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.data.database import Database
from backend.services.todo_service import Todo, TodoService


@pytest.fixture()
def todo_service():
    """Create TodoService with temporary database"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path=str(db_path))
        db.init_db()

        service = TodoService(db)

        yield service

        db.close()


def test_create_todo_with_reminder_offsets(todo_service):
    todo = todo_service.create_todo(title="T", reminder_offsets=[60, 10])
    assert todo.reminder_offsets == [10, 60]


def test_reminder_offsets_normalized(todo_service):
    """去重/过滤非法值/升序/上限 5 档。"""
    todo = todo_service.create_todo(
        title="T",
        reminder_offsets=[60, 60, 0, -5, 10, 11, 12, 13, 20000],
    )
    # 合法且去重后：[10, 11, 12, 13, 60]（20000 超 7 天、0/-5 非法被剔除）
    assert todo.reminder_offsets == [10, 11, 12, 13, 60]


def test_update_reminder_offsets_resets_fired_bookmarks(todo_service):
    due = (datetime.now() + timedelta(hours=1)).isoformat()
    todo = todo_service.create_todo(title="T", due_at=due, reminder_offsets=[30])
    todo_service.mark_custom_reminder_fired(todo.id, 30)
    assert todo_service.get_fired_reminder_offsets(todo.id) == [30]

    updated = todo_service.update_todo(todo.id, reminder_offsets=[60])

    assert updated is not None
    assert updated.reminder_offsets == [60]
    assert todo_service.get_fired_reminder_offsets(todo.id) == []


def test_update_due_at_resets_fired_bookmarks(todo_service):
    due = (datetime.now() + timedelta(hours=1)).isoformat()
    todo = todo_service.create_todo(title="T", due_at=due, reminder_offsets=[30])
    todo_service.mark_custom_reminder_fired(todo.id, 30)

    todo_service.update_todo(
        todo.id, due_at=(datetime.now() + timedelta(hours=2)).isoformat()
    )

    assert todo_service.get_fired_reminder_offsets(todo.id) == []


def test_mark_custom_reminder_fired_is_idempotent(todo_service):
    todo = todo_service.create_todo(title="T")

    todo_service.mark_custom_reminder_fired(todo.id, 10)
    todo_service.mark_custom_reminder_fired(todo.id, 10)
    todo_service.mark_custom_reminder_fired(todo.id, 60)

    assert todo_service.get_fired_reminder_offsets(todo.id) == [10, 60]


def test_custom_reminder_candidates_filters(todo_service):
    future = todo_service.create_todo(
        title="未来",
        due_at=(datetime.now() + timedelta(hours=2)).isoformat(),
        reminder_offsets=[10],
    )
    todo_service.create_todo(
        title="无档位", due_at=(datetime.now() + timedelta(hours=2)).isoformat()
    )
    todo_service.create_todo(
        title="已过期",
        due_at=(datetime.now() - timedelta(minutes=5)).isoformat(),
        reminder_offsets=[10],
    )
    done = todo_service.create_todo(
        title="已完成",
        due_at=(datetime.now() + timedelta(hours=2)).isoformat(),
        reminder_offsets=[10],
    )
    todo_service.complete_todo(done.id)

    candidates = todo_service.get_custom_reminder_candidates()

    assert [t.id for t in candidates] == [future.id]


def test_recurring_instance_copies_reminder_offsets(todo_service):
    created = todo_service.create_todo(
        title="每日站会",
        due_at=(datetime.now() - timedelta(hours=1)).isoformat(),
        recurrence_rule="0 9 * * *",
        reminder_offsets=[15],
        tags=["工作"],
    )

    todo_service.complete_todo(created.id)

    spawned = todo_service.list_todos()
    assert len(spawned) == 1
    assert spawned[0].reminder_offsets == [15]
    assert spawned[0].tags == ["工作"]


def test_todo_model_defaults_reminder_offsets_empty():
    todo = Todo(
        id=1,
        title="T",
        status="pending",
        priority="medium",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    assert todo.reminder_offsets == []
