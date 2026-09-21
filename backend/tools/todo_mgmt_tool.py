"""LLM tools for persistent todo management (Task 5).

Five tools that wrap :class:`TodoService` for LLM consumption:

- :class:`AddTodoTool`       -- create a new todo (WRITE_LOCAL)
- :class:`ListTodosTool`     -- query the todo list (READ)
- :class:`CompleteTodoTool`  -- mark a todo as completed (WRITE_LOCAL)
- :class:`UpdateTodoTool`    -- update a todo's fields (WRITE_LOCAL)
- :class:`DeleteTodoTool`    -- permanently remove a todo (WRITE_LOCAL)

These are distinct from :class:`TodoWriteTool` (``todo_tool.py``) which is
the claw-code session-scratch list (full-replace semantics, in-memory,
per-session). The tools in *this* module operate on the persistent
``todos`` SQLite table via :class:`TodoService`.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy  # noqa: F401 -- for type hint
from backend.services.todo_service import TodoService
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


TodoServiceGetter = Callable[[], Optional[TodoService]]  # noqa: UP045 — Py3.8 compat (UP007/UP035 already disabled)

NO_SERVICE_ERROR = "待办服务未初始化，无法执行本操作。"


def _default_todo_service_getter() -> Optional[TodoService]:  # noqa: UP045 — Py3.8 compat
    """Return no service unless the application composition root injects one.

    Tools are wired up via ``register_all_tools(..., todo_service_getter=...)``.
    In tests and isolated fixtures the getter returns None and tools degrade
    gracefully rather than crashing on ``None.todo_service.method()``.
    """
    return None


class _TodoServiceMixin:
    """Shared constructor for the todo-service-backed tools.

    Mirrors :class:`schedule_tool.ScheduleTaskTool` getter pattern: the service
    is resolved lazily per execute call, so an uninitialised ``TodoService``
    yields a friendly "未初始化" ``ToolResult`` instead of a ``None`` AttributeError.
    """

    def __init__(
        self,
        *,
        policy: Optional[ToolPolicy] = None,  # noqa: UP045 — Py3.8 compat
        todo_service_getter: Optional[TodoServiceGetter] = None,  # noqa: UP045 — Py3.8 compat
        **kwargs: Any,
    ) -> None:
        # Forward to BaseTool.__init__ (which accepts policy). Extra kwargs are
        # accepted but not used -- allows forward-compatible kwarg expansion.
        super().__init__(policy=policy, **kwargs)  # type: ignore[arg-type]
        self._todo_service_getter: TodoServiceGetter = (
            todo_service_getter or _default_todo_service_getter
        )

    def _get_service(self) -> Optional[TodoService]:  # noqa: UP045 — Py3.8 compat
        """Resolve the service lazily (per execute call)."""
        return self._todo_service_getter()


class AddTodoTool(_TodoServiceMixin, BaseTool):
    """Create a new todo item."""

    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="add_todo",
            description=(
                "创建一个新的待办事项。支持设置截止时间、优先级、项目标签。"
                "LLM 负责将用户的自然语言时间转换为 ISO8601 格式。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "待办标题"},
                    "description": {
                        "type": "string",
                        "description": "详细描述（可选）",
                    },
                    "due_at": {
                        "type": "string",
                        "description": "ISO8601 截止时间（可选）",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "优先级（默认 medium）",
                    },
                    "project_tag": {
                        "type": "string",
                        "description": "项目标签（可选）",
                    },
                    "recurrence_rule": {
                        "type": "string",
                        "description": "5 字段 cron 表达式（可选）",
                    },
                },
                "required": ["title"],
            },
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        service = self._get_service()
        if service is None:
            return ToolResult(success=False, error=NO_SERVICE_ERROR)
        try:
            todo = service.create_todo(
                title=kwargs["title"],
                description=kwargs.get("description"),
                due_at=kwargs.get("due_at"),
                priority=kwargs.get("priority", "medium"),
                project_tag=kwargs.get("project_tag"),
                recurrence_rule=kwargs.get("recurrence_rule"),
            )
            return ToolResult(
                success=True,
                content={"id": todo.id, "title": todo.title, "status": todo.status},
                output=todo,
            )
        except Exception as exc:  # noqa: BLE001 -- tool boundary: surface as ToolResult
            logger.error("add_todo failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


class ListTodosTool(_TodoServiceMixin, BaseTool):
    """Query the todo list with filters."""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="list_todos",
            description="查询待办列表。可按状态、项目、优先级筛选。",
            parameters={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": [
                            "pending",
                            "in_progress",
                            "completed",
                            "cancelled",
                            "all",
                        ],
                        "description": "状态筛选（默认 pending）",
                    },
                    "project_tag": {
                        "type": "string",
                        "description": "项目标签筛选",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "优先级筛选",
                    },
                    "include_completed": {
                        "type": "boolean",
                        "description": "是否包含已完成（默认 false）",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制（默认 50）",
                    },
                },
                "required": [],
            },
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        service = self._get_service()
        if service is None:
            return ToolResult(success=False, error=NO_SERVICE_ERROR)
        try:
            status = kwargs.get("status")
            include_completed = kwargs.get("include_completed", False)
            if status == "all":
                include_completed = True
            todos = service.list_todos(
                status=status,
                project_tag=kwargs.get("project_tag"),
                priority=kwargs.get("priority"),
                include_completed=include_completed,
                limit=kwargs.get("limit", 50),
            )
            return ToolResult(
                success=True,
                content={
                    "todos": [
                        {
                            "id": t.id,
                            "title": t.title,
                            "status": t.status,
                            "priority": t.priority,
                            "due_at": t.due_at,
                            "project_tag": t.project_tag,
                        }
                        for t in todos
                    ],
                    "count": len(todos),
                },
            )
        except Exception as exc:  # noqa: BLE001 -- tool boundary
            logger.error("list_todos failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


class CompleteTodoTool(_TodoServiceMixin, BaseTool):
    """Mark a todo as completed."""

    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="complete_todo",
            description="标记待办完成。循环待办自动生成下一个实例。",
            parameters={
                "type": "object",
                "properties": {
                    "todo_id": {"type": "integer", "description": "待办 ID"},
                },
                "required": ["todo_id"],
            },
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        service = self._get_service()
        if service is None:
            return ToolResult(success=False, error=NO_SERVICE_ERROR)
        try:
            todo_id = kwargs["todo_id"]
            todo = service.complete_todo(todo_id)
            if todo is None:
                return ToolResult(
                    success=False, error=f"todo {todo_id} not found"
                )
            return ToolResult(
                success=True,
                content={
                    "id": todo.id,
                    "status": todo.status,
                    "completed_at": todo.completed_at,
                },
                output=todo,
            )
        except Exception as exc:  # noqa: BLE001 -- tool boundary
            logger.error("complete_todo failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


class UpdateTodoTool(_TodoServiceMixin, BaseTool):
    """Update a todo's fields."""

    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="update_todo",
            description="更新待办字段。",
            parameters={
                "type": "object",
                "properties": {
                    "todo_id": {"type": "integer", "description": "待办 ID"},
                    "title": {"type": "string", "description": "标题"},
                    "description": {"type": "string", "description": "描述"},
                    "due_at": {"type": "string", "description": "截止时间"},
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "优先级",
                    },
                    "project_tag": {"type": "string", "description": "项目标签"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "cancelled"],
                        "description": "状态",
                    },
                },
                "required": ["todo_id"],
            },
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        service = self._get_service()
        if service is None:
            return ToolResult(success=False, error=NO_SERVICE_ERROR)
        try:
            todo_id = kwargs.pop("todo_id")
            todo = service.update_todo(todo_id, **kwargs)
            if todo is None:
                return ToolResult(
                    success=False, error=f"todo {todo_id} not found"
                )
            return ToolResult(
                success=True,
                content={
                    "id": todo.id,
                    "title": todo.title,
                    "status": todo.status,
                },
                output=todo,
            )
        except Exception as exc:  # noqa: BLE001 -- tool boundary
            logger.error("update_todo failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


class DeleteTodoTool(_TodoServiceMixin, BaseTool):
    """Permanently delete a todo."""

    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="delete_todo",
            description="永久删除待办。",
            parameters={
                "type": "object",
                "properties": {
                    "todo_id": {"type": "integer", "description": "待办 ID"},
                },
                "required": ["todo_id"],
            },
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        service = self._get_service()
        if service is None:
            return ToolResult(success=False, error=NO_SERVICE_ERROR)
        try:
            todo_id = kwargs["todo_id"]
            deleted = service.delete_todo(todo_id)
            if not deleted:
                return ToolResult(
                    success=False, error=f"todo {todo_id} not found"
                )
            return ToolResult(
                success=True,
                content={"deleted": True, "todo_id": todo_id},
            )
        except Exception as exc:  # noqa: BLE001 -- tool boundary
            logger.error("delete_todo failed: %s", exc)
            return ToolResult(success=False, error=str(exc))
