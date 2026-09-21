"""Test TodoService"""
import tempfile
from datetime import datetime, timezone
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


def test_update_todo(todo_service):
    """Verify update_todo modifies fields"""
    created = todo_service.create_todo(title="Original")
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
