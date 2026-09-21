"""Test TodoService"""
import tempfile
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
