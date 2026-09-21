"""Test TodoService"""
import pytest
from datetime import datetime
from backend.services.todo_service import Todo


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
        project_id=5,
        is_recurring=False,
        recurrence_rule=None,
        parent_id=None,
        created_at="2026-09-21T10:00:00",
        updated_at="2026-09-21T10:00:00"
    )

    assert todo.description == "Detailed description"
    assert todo.project_tag == "Work"
    assert todo.is_recurring is False
