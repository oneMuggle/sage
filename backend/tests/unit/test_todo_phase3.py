"""TodoService 阶段 3 测试：专家专属待办 / snooze / 完成热力图。"""
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.data.database import Database
from backend.services.todo_service import TodoService


@pytest.fixture()
def todo_service():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path=str(db_path))
        db.init_db()
        service = TodoService(db)
        yield service
        db.close()


# --- 专家专属待办 ---


def test_create_todo_with_specialist(todo_service):
    todo = todo_service.create_todo(title="专家任务", specialist_id="writer")
    assert todo.specialist_id == "writer"


def test_list_todos_filters_by_specialist(todo_service):
    todo_service.create_todo(title="A", specialist_id="writer")
    todo_service.create_todo(title="B", specialist_id="coder")
    todo_service.create_todo(title="C")

    results = todo_service.list_todos(specialist_id="writer")

    assert [t.title for t in results] == ["A"]
    assert todo_service.count_todos(specialist_id="writer") == 1


def test_update_todo_clears_specialist(todo_service):
    todo = todo_service.create_todo(title="T", specialist_id="writer")
    updated = todo_service.update_todo(todo.id, specialist_id=None)
    assert updated is not None
    assert updated.specialist_id is None


# --- snooze ---


def test_snooze_shifts_due_at_and_increments_count(todo_service):
    due = datetime.now() + timedelta(minutes=30)
    todo = todo_service.create_todo(title="T", due_at=due.isoformat())
    assert todo.snooze_count == 0

    snoozed = todo_service.snooze_todo(todo.id, 60)

    assert snoozed is not None
    assert snoozed.snooze_count == 1
    new_due = datetime.fromisoformat(snoozed.due_at)
    assert new_due == due + timedelta(minutes=60)


def test_snooze_without_due_at_starts_from_now(todo_service):
    todo = todo_service.create_todo(title="T")
    snoozed = todo_service.snooze_todo(todo.id, 10)
    assert snoozed is not None
    new_due = datetime.fromisoformat(snoozed.due_at)
    assert new_due > datetime.now() + timedelta(minutes=5)


def test_snooze_missing_todo_returns_none(todo_service):
    assert todo_service.snooze_todo(99999, 10) is None


def test_snooze_clamps_minutes(todo_service):
    todo = todo_service.create_todo(
        title="T", due_at=datetime.now().isoformat()
    )
    snoozed = todo_service.snooze_todo(todo.id, 10 ** 9)  # 上限 7 天
    assert snoozed is not None
    new_due = datetime.fromisoformat(snoozed.due_at)
    assert new_due <= datetime.now() + timedelta(days=7, minutes=1)


def test_get_most_snoozed(todo_service):
    t1 = todo_service.create_todo(title="常推迟")
    t2 = todo_service.create_todo(title="偶尔推迟")
    todo_service.create_todo(title="从未推迟")
    todo_service.snooze_todo(t1.id, 10)
    todo_service.snooze_todo(t1.id, 10)
    todo_service.snooze_todo(t1.id, 10)
    todo_service.snooze_todo(t2.id, 10)

    results = todo_service.get_most_snoozed(5)

    assert [t.title for t in results] == ["常推迟"]  # ≥2 次才算


# --- 完成热力图 ---


def test_completion_heatmap_series(todo_service):
    done = todo_service.create_todo(title="完成项")
    todo_service.complete_todo(done.id)
    todo_service.create_todo(title="未完成")

    heatmap = todo_service.completion_heatmap(days=7)

    assert len(heatmap["days"]) == 7
    assert heatmap["total"] == 1
    assert heatmap["max"] == 1
    today = datetime.now().date().isoformat()
    entry = next(d for d in heatmap["days"] if d["date"] == today)
    assert entry["count"] == 1


def test_completion_heatmap_empty(todo_service):
    heatmap = todo_service.completion_heatmap(days=7)
    assert heatmap["total"] == 0
    assert heatmap["max"] == 0
    assert all(day["count"] == 0 for day in heatmap["days"])
