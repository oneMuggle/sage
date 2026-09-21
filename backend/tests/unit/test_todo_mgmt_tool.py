"""Tests for todo LLM tools (Task 5: persistent todo management)

These tools wrap :class:`TodoService` for LLM consumption. Distinct from
``TodoWriteTool`` (``todo_tool.py``) which is the claw-code session-scratch
list; these five tools operate on the persistent ``todos`` table via
``TodoService``.
"""
from unittest.mock import Mock

from backend.domain.risk import RiskClass
from backend.services.todo_service import Todo, TodoService
from backend.tools.todo_mgmt_tool import (
    AddTodoTool,
    CompleteTodoTool,
    DeleteTodoTool,
    ListTodosTool,
    UpdateTodoTool,
)


def _make_todo(**overrides):
    base = {
        "id": 1,
        "title": "Test",
        "status": "pending",
        "priority": "medium",
        "created_at": "2026-09-21T10:00:00",
        "updated_at": "2026-09-21T10:00:00",
    }
    base.update(overrides)
    return Todo(**base)


def test_add_todo_tool_schema():
    """Verify add_todo tool schema and risk class."""
    mock_service = Mock(spec=TodoService)
    tool = AddTodoTool(todo_service_getter=lambda: mock_service)

    assert tool.schema.name == "add_todo"
    assert "title" in tool.schema.parameters["properties"]
    assert tool.risk == RiskClass.WRITE_LOCAL


def test_add_todo_tool_execute():
    """Verify add_todo calls service correctly."""
    mock_service = Mock(spec=TodoService)
    mock_service.create_todo.return_value = _make_todo()

    tool = AddTodoTool(todo_service_getter=lambda: mock_service)
    result = tool.execute(title="Test", priority="medium")

    assert result.success is True
    mock_service.create_todo.assert_called_once()


def test_list_todos_tool_execute():
    """Verify list_todos returns formatted results."""
    mock_service = Mock(spec=TodoService)
    mock_service.list_todos.return_value = [_make_todo()]

    tool = ListTodosTool(todo_service_getter=lambda: mock_service)
    result = tool.execute()

    assert result.success is True
    assert len(result.content["todos"]) == 1


def test_list_todos_all_includes_completed():
    """status='all' widens the query to include completed todos."""
    mock_service = Mock(spec=TodoService)
    mock_service.list_todos.return_value = []

    tool = ListTodosTool(todo_service_getter=lambda: mock_service)
    result = tool.execute(status="all")

    assert result.success is True
    mock_service.list_todos.assert_called_once_with(
        status="all",
        project_tag=None,
        priority=None,
        include_completed=True,
        limit=50,
    )


def test_complete_todo_tool_execute():
    """Verify complete_todo marks todo as completed."""
    mock_service = Mock(spec=TodoService)
    mock_service.complete_todo.return_value = _make_todo(
        status="completed",
        completed_at="2026-09-21T11:00:00",
        updated_at="2026-09-21T11:00:00",
    )

    tool = CompleteTodoTool(todo_service_getter=lambda: mock_service)
    result = tool.execute(todo_id=1)

    assert result.success is True
    mock_service.complete_todo.assert_called_once_with(1)


def test_update_todo_tool_execute():
    """Verify update_todo updates fields."""
    mock_service = Mock(spec=TodoService)
    mock_service.update_todo.return_value = _make_todo(
        title="Updated",
        priority="high",
        updated_at="2026-09-21T11:00:00",
    )

    tool = UpdateTodoTool(todo_service_getter=lambda: mock_service)
    result = tool.execute(todo_id=1, title="Updated", priority="high")

    assert result.success is True


def test_delete_todo_tool_execute():
    """Verify delete_todo removes todo."""
    mock_service = Mock(spec=TodoService)
    mock_service.delete_todo.return_value = True

    tool = DeleteTodoTool(todo_service_getter=lambda: mock_service)
    result = tool.execute(todo_id=1)

    assert result.success is True
    mock_service.delete_todo.assert_called_once_with(1)


def test_list_todos_tool_risk_is_read():
    """list_todos is a pure query -- RiskClass.READ."""
    mock_service = Mock(spec=TodoService)
    tool = ListTodosTool(todo_service_getter=lambda: mock_service)
    assert tool.risk == RiskClass.READ


def test_mutating_tools_risk_is_write_local():
    """add/complete/update/delete mutate local state -- RiskClass.WRITE_LOCAL."""
    mock_service = Mock(spec=TodoService)
    assert AddTodoTool(todo_service_getter=lambda: mock_service).risk == RiskClass.WRITE_LOCAL
    assert CompleteTodoTool(todo_service_getter=lambda: mock_service).risk == RiskClass.WRITE_LOCAL
    assert UpdateTodoTool(todo_service_getter=lambda: mock_service).risk == RiskClass.WRITE_LOCAL
    assert DeleteTodoTool(todo_service_getter=lambda: mock_service).risk == RiskClass.WRITE_LOCAL


def test_complete_todo_not_found():
    """complete_todo returns failure when the todo does not exist."""
    mock_service = Mock(spec=TodoService)
    mock_service.complete_todo.return_value = None

    tool = CompleteTodoTool(todo_service_getter=lambda: mock_service)
    result = tool.execute(todo_id=404)

    assert result.success is False
    assert "not found" in result.error


def test_delete_todo_not_found():
    """delete_todo returns failure when the todo does not exist."""
    mock_service = Mock(spec=TodoService)
    mock_service.delete_todo.return_value = False

    tool = DeleteTodoTool(todo_service_getter=lambda: mock_service)
    result = tool.execute(todo_id=404)

    assert result.success is False
    assert "not found" in result.error


def test_update_todo_not_found():
    """update_todo returns failure when the todo does not exist."""
    mock_service = Mock(spec=TodoService)
    mock_service.update_todo.return_value = None

    tool = UpdateTodoTool(todo_service_getter=lambda: mock_service)
    result = tool.execute(todo_id=404)

    assert result.success is False
    assert "not found" in result.error


def test_add_todo_service_exception_returns_failure():
    """Service exceptions are surfaced as ToolResult(success=False)."""
    mock_service = Mock(spec=TodoService)
    mock_service.create_todo.side_effect = RuntimeError("db down")

    tool = AddTodoTool(todo_service_getter=lambda: mock_service)
    result = tool.execute(title="Test")

    assert result.success is False
    assert "db down" in result.error


def test_tool_reports_uninitialized_service():
    """Tool returns NO_SERVICE_ERROR when getter returns None."""
    tool = AddTodoTool(todo_service_getter=lambda: None)
    result = tool.execute(title="Test")

    assert result.success is False
    assert "未初始化" in (result.error or "")
