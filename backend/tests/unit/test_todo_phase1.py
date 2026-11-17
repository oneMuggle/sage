"""TodoService 阶段 1 测试：多标签 + 智能视图（today/week/completed/all）。"""
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.data.database import Database
from backend.services.todo_service import TodoService


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


@pytest.fixture()
def frozen_view_clock(monkeypatch):
    """冻结 todo_filters 的时钟，保证 today/week 桶跨午夜稳定。"""
    import backend.services.todo_filters as filters_module

    fixed = datetime(2026, 1, 15, 10, 0, 0)  # noqa: DTZ001

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(filters_module, "datetime", _FixedDatetime)
    return fixed


# --- 多标签 ---


def test_create_todo_with_tags(todo_service):
    todo = todo_service.create_todo(title="写论文", tags=["工作", "论文"])

    assert todo.tags == ["工作", "论文"]


def test_tags_are_normalized(todo_service):
    """去空白、去重、剔除 LIKE 特殊字符、截断到 10 个。"""
    todo = todo_service.create_todo(
        title="T",
        tags=[" 工作 ", "工作", 'a"b', "c%d", "e_f"] + [f"t{i}" for i in range(12)],
    )

    assert todo.tags == ["工作", "ab", "cd", "ef"] + [f"t{i}" for i in range(6)]


def test_update_tags_replaces_and_clears(todo_service):
    todo = todo_service.create_todo(title="T", tags=["a"])

    updated = todo_service.update_todo(todo.id, tags=["b", "c"])
    assert updated.tags == ["b", "c"]

    cleared = todo_service.update_todo(todo.id, tags=[])
    assert cleared.tags == []


def test_list_todos_filters_by_tag(todo_service):
    todo_service.create_todo(title="A", tags=["工作"])
    todo_service.create_todo(title="B", tags=["生活"])
    todo_service.create_todo(title="C", tags=["工作", "论文"])

    results = todo_service.list_todos(tag="工作")

    assert sorted(t.title for t in results) == ["A", "C"]
    assert todo_service.count_todos(tag="工作") == 2


def test_list_tags_aggregates_counts(todo_service):
    todo_service.create_todo(title="A", tags=["工作", "论文"])
    todo_service.create_todo(title="B", tags=["工作"])

    counts = todo_service.list_tags()

    assert counts == [
        {"tag": "工作", "count": 2},
        {"tag": "论文", "count": 1},
    ]


def test_tags_survive_roundtrip_with_bad_json(todo_service):
    """坏 JSON 不阻塞列表渲染，降级为空标签。"""
    todo = todo_service.create_todo(title="T")
    conn = todo_service.db.get_connection()
    conn.execute("UPDATE todos SET tags = ? WHERE id = ?", ("not-json", todo.id))
    conn.commit()

    fetched = todo_service.get_todo(todo.id)
    assert fetched is not None
    assert fetched.tags == []


# --- 智能视图 ---


def test_view_today_only_due_today(todo_service, frozen_view_clock):
    fixed = frozen_view_clock
    todo_service.create_todo(title="今天", due_at=fixed.replace(hour=18).isoformat())
    todo_service.create_todo(
        title="昨天", due_at=(fixed - timedelta(days=1)).isoformat()
    )
    todo_service.create_todo(
        title="明天", due_at=(fixed + timedelta(days=1)).isoformat()
    )
    todo_service.create_todo(title="无日期")

    results = todo_service.list_todos(view="today")

    assert [t.title for t in results] == ["今天"]
    assert todo_service.count_todos(view="today") == 1


def test_view_week_includes_overdue_and_next_7_days(todo_service, frozen_view_clock):
    fixed = frozen_view_clock
    todo_service.create_todo(
        title="逾期", due_at=(fixed - timedelta(hours=1)).isoformat()
    )
    todo_service.create_todo(
        title="三天后", due_at=(fixed + timedelta(days=3)).isoformat()
    )
    todo_service.create_todo(
        title="八天后", due_at=(fixed + timedelta(days=8)).isoformat()
    )
    todo_service.create_todo(title="无日期")

    results = todo_service.list_todos(view="week")

    assert sorted(t.title for t in results) == ["三天后", "逾期"]


def test_view_completed_only_completed(todo_service):
    done = todo_service.create_todo(title="完成")
    todo_service.complete_todo(done.id)
    todo_service.create_todo(title="未完成")

    results = todo_service.list_todos(view="completed")

    assert [t.title for t in results] == ["完成"]


def test_view_all_excludes_completed_and_cancelled(todo_service):
    todo_service.create_todo(title="未完成")
    done = todo_service.create_todo(title="完成")
    todo_service.complete_todo(done.id)
    dropped = todo_service.create_todo(title="取消")
    todo_service.cancel_todo(dropped.id)

    results = todo_service.list_todos(view="all")

    assert [t.title for t in results] == ["未完成"]


def test_view_combines_with_priority_and_tag(todo_service, frozen_view_clock):
    fixed = frozen_view_clock
    todo_service.create_todo(
        title="重要",
        due_at=fixed.replace(hour=18).isoformat(),
        priority="high",
        tags=["工作"],
    )
    todo_service.create_todo(
        title="普通", due_at=fixed.replace(hour=18).isoformat(), tags=["工作"]
    )

    results = todo_service.list_todos(view="today", priority="high")
    assert [t.title for t in results] == ["重要"]

    results = todo_service.list_todos(view="today", tag="工作")
    assert sorted(t.title for t in results) == ["普通", "重要"]
