"""Test TodoService"""
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.data.database import Database
from backend.services.todo_service import Todo, TodoService


def test_todo_model_creation():
    """Verify Todo model can be instantiated"""
    todo = Todo(
        id=1,
        title="Test todo",
        status="pending",
        priority="medium",
        created_at="2026-09-21T10:00:00",
        updated_at="2026-09-21T10:00:00"
    )

    assert todo.id == 1
    assert todo.title == "Test todo"
    assert todo.status == "pending"
    assert todo.priority == "medium"
    assert todo.description is None
    assert todo.effective_urgency is None


def test_todo_model_with_all_fields():
    """Verify Todo model accepts all optional fields"""
    todo = Todo(
        id=1,
        title="Test todo",
        description="Detailed description",
        status="in_progress",
        priority="high",
        effective_urgency="urgent",
        due_at="2026-09-22T15:00:00",
        completed_at=None,
        project_tag="Work",
        # projects.id is a TEXT hex/uuid value, never an integer
        project_id="a1b2c3d4e5f60718293a4b5c6d7e8f90",
        is_recurring=False,
        recurrence_rule=None,
        parent_id=None,
        created_at="2026-09-21T10:00:00",
        updated_at="2026-09-21T10:00:00"
    )

    assert todo.description == "Detailed description"
    assert todo.project_tag == "Work"
    assert todo.is_recurring is False


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


def test_create_todo(todo_service):
    """Verify create_todo inserts row and returns Todo"""
    todo = todo_service.create_todo(
        title="Book flight",
        description="Beijing to Shanghai",
        due_at="2026-09-25T15:00:00",
        priority="high",
        project_tag="Work"
    )

    assert todo.id is not None
    assert todo.title == "Book flight"
    assert todo.description == "Beijing to Shanghai"
    assert todo.status == "pending"
    assert todo.priority == "high"
    assert todo.due_at == "2026-09-25T15:00:00"
    assert todo.project_tag == "Work"
    assert todo.created_at is not None
    assert todo.updated_at is not None


def test_get_todo(todo_service):
    """Verify get_todo retrieves by ID"""
    created = todo_service.create_todo(title="Test")
    retrieved = todo_service.get_todo(created.id)

    assert retrieved is not None
    assert retrieved.id == created.id
    assert retrieved.title == "Test"


def test_get_todo_not_found(todo_service):
    """Verify get_todo returns None for non-existent ID"""
    result = todo_service.get_todo(99999)
    assert result is None


def test_list_todos(todo_service):
    """Verify list_todos returns pending by default"""
    todo_service.create_todo(title="Todo 1")
    todo_service.create_todo(title="Todo 2")

    todos = todo_service.list_todos()

    assert len(todos) == 2
    assert all(t.status == "pending" for t in todos)


import time


def test_update_todo(todo_service):
    """Verify update_todo modifies fields"""
    import time as _time

    created = todo_service.create_todo(title="Original")
    _time.sleep(0.02)  # Windows clock resolution (15.6ms tick; 0.01 insufficient — R39, matches release/win7's 0.02)
    updated = todo_service.update_todo(created.id, title="Updated", priority="high")

    assert updated.title == "Updated"
    assert updated.priority == "high"
    assert updated.updated_at != created.updated_at


def test_delete_todo(todo_service):
    """Verify delete_todo removes row"""
    created = todo_service.create_todo(title="To delete")
    result = todo_service.delete_todo(created.id)

    assert result is True
    assert todo_service.get_todo(created.id) is None


# --- fix-round (B/C/D) tests ---


def test_update_returns_none_for_missing_id(todo_service):
    """update_todo returns None for a non-existent id (signature is Optional[Todo])."""
    assert todo_service.update_todo(99999, title="Ghost") is None


def test_update_none_clears_nullable_field(todo_service):
    """Explicit None clears a nullable field (description)."""
    created = todo_service.create_todo(title="X", description="keep me?")
    assert created.description == "keep me?"

    updated = todo_service.update_todo(created.id, description=None)
    assert updated.description is None


def test_update_absent_key_leaves_field_unchanged(todo_service):
    """A key not passed at all leaves its column untouched."""
    created = todo_service.create_todo(title="X", description="keep me")
    updated = todo_service.update_todo(created.id, title="New title")

    assert updated.title == "New title"
    assert updated.description == "keep me"


def test_update_rejects_none_title(todo_service):
    """title is NOT NULL in the schema; explicit None must raise, not crash as IntegrityError."""
    created = todo_service.create_todo(title="Original")

    with pytest.raises(ValueError, match="title is NOT NULL"):
        todo_service.update_todo(created.id, title=None)


def test_update_none_project_tag_clears_project_id(todo_service):
    """Explicit project_tag=None must clear both the tag and the auto-linked project id."""
    conn = todo_service.db.get_connection()
    pid = "abcdef01234567890abcdef012345678"
    conn.execute(
        "INSERT INTO projects (id, path, name, created_at, last_opened_at) VALUES (?,?,?,?,?)",
        (pid, "/tmp/y", "Work", 0, 0),
    )
    conn.commit()

    linked = todo_service.create_todo(title="T", project_tag="Work")
    assert linked.project_tag == "Work"
    assert linked.project_id == pid

    cleared = todo_service.update_todo(linked.id, project_tag=None)
    assert cleared.project_tag is None
    assert cleared.project_id is None


def test_tz_aware_due_at_normalized_on_create(todo_service):
    """A tz-aware due_at (e.g. from ``Date.toISOString()``) is normalized to naive local."""
    todo = todo_service.create_todo(title="T", due_at="2026-09-25T15:00:00+00:00")

    parsed = datetime.fromisoformat(todo.due_at)
    assert parsed.tzinfo is None
    # Same UTC instant, rendered in local time
    expected = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)  # noqa: UP017
    assert parsed.astimezone(timezone.utc) == expected  # noqa: UP017


def test_tz_aware_due_at_with_z_normalized_on_create(todo_service):
    """``...Z`` suffix (the canonical JS ``Date.toISOString()`` output) must parse."""
    todo = todo_service.create_todo(title="T", due_at="2026-09-25T15:00:00Z")
    parsed = datetime.fromisoformat(todo.due_at)
    assert parsed.tzinfo is None
    expected = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)  # noqa: UP017
    assert parsed.astimezone(timezone.utc) == expected  # noqa: UP017


def test_update_due_at_normalized(todo_service):
    """update_todo also normalizes a tz-aware due_at."""
    created = todo_service.create_todo(title="T")
    updated = todo_service.update_todo(created.id, due_at="2026-09-25T15:00:00+00:00")

    parsed = datetime.fromisoformat(updated.due_at)
    assert parsed.tzinfo is None
    expected = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)  # noqa: UP017
    assert parsed.astimezone(timezone.utc) == expected  # noqa: UP017


def test_naive_due_at_is_unchanged(todo_service):
    """Naive inputs pass through untouched (no conversion)."""
    todo = todo_service.create_todo(title="T", due_at="2026-09-25T15:00:00")
    assert todo.due_at == "2026-09-25T15:00:00"


# --- Task 4: state changes & urgency ---


def test_complete_todo(todo_service):
    """Verify complete_todo marks as completed and returns updated Todo."""
    created = todo_service.create_todo(title="To complete")
    completed = todo_service.complete_todo(created.id)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.completed_at is not None
    # R97 跟进: != 断言依赖时钟前进，Windows 粒度下两操作可同微秒（脆弱）
    assert completed.updated_at >= created.updated_at


def test_complete_todo_missing_returns_none(todo_service):
    """complete_todo on a non-existent id returns None (not an error)."""
    assert todo_service.complete_todo(99999) is None


def test_cancel_todo(todo_service):
    """Verify cancel_todo marks as cancelled and returns True."""
    created = todo_service.create_todo(title="To cancel")
    result = todo_service.cancel_todo(created.id)

    assert result is True
    cancelled = todo_service.get_todo(created.id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.completed_at is None  # only complete_todo sets completed_at


def test_cancel_todo_missing_returns_false(todo_service):
    """cancel_todo on a non-existent id returns False."""
    assert todo_service.cancel_todo(99999) is False


def test_refresh_effective_urgency(todo_service):
    """Verify urgency calculation for critical / urgent / normal buckets."""
    # Due in 30 minutes → critical
    due_soon = datetime.now() + timedelta(minutes=30)
    todo_service.create_todo(title="Urgent", due_at=due_soon.isoformat())

    # Due in 12 hours → urgent
    due_today = datetime.now() + timedelta(hours=12)
    todo_service.create_todo(title="Today", due_at=due_today.isoformat())

    # Due in 3 days → normal
    due_later = datetime.now() + timedelta(days=3)
    todo_service.create_todo(title="Later", due_at=due_later.isoformat())

    updated = todo_service.refresh_effective_urgency()
    assert updated == 3

    todos = todo_service.list_todos(include_completed=True)
    urgent_todo = next(t for t in todos if t.title == "Urgent")
    today_todo = next(t for t in todos if t.title == "Today")
    later_todo = next(t for t in todos if t.title == "Later")

    assert urgent_todo.effective_urgency == "critical"
    assert today_todo.effective_urgency == "urgent"
    assert later_todo.effective_urgency == "normal"


def test_refresh_effective_urgency_null_due_at_is_normal(todo_service):
    """A todo with due_at=NULL defaults to normal urgency."""
    todo_service.create_todo(title="No due")
    todo_service.refresh_effective_urgency()

    todos = todo_service.list_todos()
    assert todos[0].effective_urgency == "normal"


def test_refresh_effective_urgency_high_priority_upgrades_to_critical(todo_service):
    """high priority + due < 24h → critical (even if hours >= 1)."""
    due = datetime.now() + timedelta(hours=12)
    todo_service.create_todo(title="High Soon", due_at=due.isoformat(), priority="high")

    todo_service.refresh_effective_urgency()

    todos = todo_service.list_todos()
    assert todos[0].effective_urgency == "critical"


def test_refresh_skips_completed_and_cancelled(todo_service):
    """refresh_effective_urgency only touches pending/in_progress rows."""
    due_soon = datetime.now() + timedelta(minutes=30)
    t1 = todo_service.create_todo(title="T1", due_at=due_soon.isoformat())
    t2 = todo_service.create_todo(title="T2", due_at=due_soon.isoformat())

    todo_service.complete_todo(t1.id)
    todo_service.cancel_todo(t2.id)

    updated = todo_service.refresh_effective_urgency()
    assert updated == 0


def test_get_due_soon_todos(todo_service):
    """Verify get_due_soon_todos filters by within_seconds window."""
    # Due in 30 minutes — inside the 1h window
    due_soon = datetime.now() + timedelta(minutes=30)
    todo_service.create_todo(title="Soon", due_at=due_soon.isoformat())

    # Due in 2 hours — outside the 1h window
    due_later = datetime.now() + timedelta(hours=2)
    todo_service.create_todo(title="Later", due_at=due_later.isoformat())

    # Already past — excluded (past is not "due soon")
    due_past = datetime.now() - timedelta(hours=1)
    todo_service.create_todo(title="Past", due_at=due_past.isoformat())

    due_soon_todos = todo_service.get_due_soon_todos(within_seconds=3600)

    assert len(due_soon_todos) == 1
    assert due_soon_todos[0].title == "Soon"


def test_get_overdue_todos(todo_service):
    """Verify get_overdue_todos returns only past-due pending items."""
    # Overdue by 1 hour
    overdue = datetime.now() - timedelta(hours=1)
    todo_service.create_todo(title="Overdue", due_at=overdue.isoformat())

    # Future — not overdue
    future = datetime.now() + timedelta(hours=1)
    todo_service.create_todo(title="Future", due_at=future.isoformat())

    # No due_at — not overdue
    todo_service.create_todo(title="No due")

    overdue_todos = todo_service.get_overdue_todos()

    assert len(overdue_todos) == 1
    assert overdue_todos[0].title == "Overdue"


def test_get_overdue_todos_excludes_completed(todo_service):
    """Completed items are not reported as overdue, even if past due."""
    overdue = datetime.now() - timedelta(hours=1)
    created = todo_service.create_todo(title="Done late", due_at=overdue.isoformat())
    todo_service.complete_todo(created.id)

    assert todo_service.get_overdue_todos() == []


def test_get_startup_summary_structure(todo_service):
    """Verify startup summary returns the documented keys."""
    todo_service.create_todo(title="Pending 1")
    todo_service.create_todo(title="Pending 2")

    summary = todo_service.get_startup_summary()

    for key in ("overdue", "today", "upcoming", "high_priority",
                "total_pending", "total_completed_today"):
        assert key in summary

    assert summary["total_pending"] == 2
    assert summary["total_completed_today"] == 0


def test_get_startup_summary_buckets(todo_service, monkeypatch):
    """Todos land in the correct summary bucket.

    R97 跟进：冻结服务时钟到上午 10 点 —— 原实现用真实 now+1h 构造
    today 桶条目，CI 在 23:00-23:59 运行时跨过午夜落入 upcoming
    （today_end = 当日 23:59:59），today 断言必炸。冻结后彻底确定性。
    """
    import backend.services.todo_service as todo_service_module

    # 与服务一致使用 tz-naive；本地裸 datetime 构造豁免 DTZ001
    fixed_now = datetime(2026, 1, 15, 10, 0, 0)  # noqa: DTZ001

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(todo_service_module, "datetime", _FixedDatetime)
    todo_service.create_todo(title="Overdue", due_at=(fixed_now - timedelta(hours=2)).isoformat())
    todo_service.create_todo(title="Today", due_at=(fixed_now + timedelta(hours=1)).isoformat())
    todo_service.create_todo(title="Upcoming", due_at=(fixed_now + timedelta(days=3)).isoformat())
    todo_service.create_todo(title="High", priority="high")

    summary = todo_service.get_startup_summary()

    assert [t.title for t in summary["overdue"]] == ["Overdue"]
    assert [t.title for t in summary["today"]] == ["Today"]
    assert [t.title for t in summary["upcoming"]] == ["Upcoming"]
    assert [t.title for t in summary["high_priority"]] == ["High"]


def test_get_startup_summary_total_completed_today(todo_service):
    """total_completed_today counts only rows completed on the current date."""
    t1 = todo_service.create_todo(title="T1")
    t2 = todo_service.create_todo(title="T2")
    todo_service.create_todo(title="T3")  # left pending

    todo_service.complete_todo(t1.id)
    todo_service.complete_todo(t2.id)

    summary = todo_service.get_startup_summary()

    assert summary["total_pending"] == 1
    assert summary["total_completed_today"] == 2


# --- fix round 1: sort params + get_todo_stats ---


def test_list_todos_default_sort_puts_undated_last(todo_service):
    """Default due_at sort: SQLite's bare ``due_at ASC`` puts NULLs first, which
    reads backwards to a user — undated items must sort *after* dated ones."""
    todo_service.create_todo(title="undated")
    todo_service.create_todo(title="dated", due_at="2099-01-01T00:00:00")

    todos = todo_service.list_todos()

    assert [t.title for t in todos] == ["dated", "undated"]


def test_get_todo_stats_counts_all_statuses(todo_service):
    """``total`` is all-rows, unlike /summary which only counts pending/in_progress."""
    todo_service.create_todo(title="Pending")
    done = todo_service.create_todo(title="Done")
    dropped = todo_service.create_todo(title="Dropped")

    todo_service.complete_todo(done.id)
    todo_service.cancel_todo(dropped.id)

    stats = todo_service.get_todo_stats()

    assert stats["total"] == 3
    assert stats["by_status"] == {
        "pending": 1,
        "completed": 1,
        "cancelled": 1,
    }


def test_count_todos_matches_list_todos_filters(todo_service):
    """count_todos must mirror list_todos' filter block exactly — if the two
    drift, the REST layer's ``total`` starts describing a different match set
    than ``items``."""
    todo_service.create_todo(title="P1")
    todo_service.create_todo(title="P2", priority="high")
    done = todo_service.create_todo(title="Done")
    todo_service.complete_todo(done.id)

    # default: pending/in_progress only
    assert todo_service.count_todos() == 2
    # include_completed widens to every status
    assert todo_service.count_todos(include_completed=True) == 3
    # status="all" widens the same way
    assert todo_service.count_todos(status="all") == 3
    # priority filter
    assert todo_service.count_todos(priority="high") == 1
    # combined
    assert todo_service.count_todos(priority="high", include_completed=True) == 1

    # and the count agrees with what list_todos would return unbounded
    for kwargs in (
        {},
        {"include_completed": True},
        {"status": "all"},
        {"priority": "high"},
    ):
        assert todo_service.count_todos(**kwargs) == len(
            todo_service.list_todos(limit=1000, **kwargs)
        )


# --- Task 7: reminder bookkeeping ---


def test_get_unfired_24h_reminders_filters_correctly(todo_service):
    """Only pending/in_progress, within 24 h, with latch = 0."""
    now = datetime.now()
    todo_service.create_todo(
        title="soon", due_at=(now + timedelta(hours=12)).isoformat()
    )
    todo_service.create_todo(
        title="later", due_at=(now + timedelta(hours=36)).isoformat()
    )
    todo_service.create_todo(
        title="past", due_at=(now - timedelta(hours=1)).isoformat()
    )
    done = todo_service.create_todo(
        title="done", due_at=(now + timedelta(hours=6)).isoformat()
    )
    todo_service.complete_todo(done.id)

    unfired = todo_service.get_unfired_24h_reminders()
    assert [t.title for t in unfired] == ["soon"]


def test_mark_24h_fired_removes_todo_from_next_query(todo_service):
    """mark_24h_fired is the latch — calling it makes the todo disappear from
    ``get_unfired_24h_reminders``."""
    now = datetime.now()
    created = todo_service.create_todo(
        title="soon", due_at=(now + timedelta(hours=12)).isoformat()
    )

    assert len(todo_service.get_unfired_24h_reminders()) == 1

    todo_service.mark_24h_fired(created.id)
    assert todo_service.get_unfired_24h_reminders() == []


def test_mark_1h_fired_same_behavior(todo_service):
    now = datetime.now()
    created = todo_service.create_todo(
        title="very soon", due_at=(now + timedelta(minutes=45)).isoformat()
    )
    assert len(todo_service.get_unfired_1h_reminders()) == 1
    todo_service.mark_1h_fired(created.id)
    assert todo_service.get_unfired_1h_reminders() == []


def test_update_due_at_resets_both_latches(todo_service):
    """Changing due_at resets both latches — a rescheduled todo must remind."""
    now = datetime.now()
    created = todo_service.create_todo(
        title="T", due_at=(now + timedelta(hours=12)).isoformat()
    )
    todo_service.mark_24h_fired(created.id)
    todo_service.mark_1h_fired(created.id)

    # 23 h, not the brief's 36 h: 36 h falls outside the 24 h window that
    # ``get_unfired_24h_reminders`` queries, which would make the ``== 1``
    # assertion false with *or* without the reset — vacuous. 23 h is inside
    # the 24 h window (reset observable) and outside the 1 h window (so the
    # companion ``== 0`` assertion still holds). See Ruling 12.
    time.sleep(0.02)  # Windows clock resolution (15.6ms tick; 0.01 insufficient — R39, matches release/win7's 0.02)
    todo_service.update_todo(
        created.id, due_at=(now + timedelta(hours=23)).isoformat()
    )

    assert len(todo_service.get_unfired_24h_reminders()) == 1
    assert len(todo_service.get_unfired_1h_reminders()) == 0


def test_update_status_resets_both_latches(todo_service):
    """Reopening a completed todo resets both latches."""
    now = datetime.now()
    created = todo_service.create_todo(
        title="T", due_at=(now + timedelta(hours=12)).isoformat()
    )
    todo_service.mark_24h_fired(created.id)
    todo_service.complete_todo(created.id)

    todo_service.update_todo(created.id, status="pending")
    assert len(todo_service.get_unfired_24h_reminders()) == 1


def test_update_unrelated_field_does_not_reset_latches(todo_service):
    """Changing title/priority must NOT reset the latches."""
    now = datetime.now()
    created = todo_service.create_todo(
        title="T", due_at=(now + timedelta(hours=12)).isoformat()
    )
    todo_service.mark_24h_fired(created.id)

    todo_service.update_todo(created.id, title="New title", priority="high")
    assert todo_service.get_unfired_24h_reminders() == []
