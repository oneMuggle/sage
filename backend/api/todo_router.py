"""Todo REST API.

Mount under ``/api/v1`` from ``backend/main.py``. Service dependency is injected
via a ``get_service`` callable so tests can supply an isolated instance.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from backend.services.todo_service import Todo, TodoService

logger = logging.getLogger(__name__)


# ---------- request / response models ----------


class CreateTodoIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    due_at: Optional[str] = None
    priority: str = Field(default="medium", pattern="^(high|medium|low)$")
    project_tag: Optional[str] = None
    recurrence_rule: Optional[str] = None


class UpdateTodoIn(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    due_at: Optional[str] = None
    priority: Optional[str] = Field(default=None, pattern="^(high|medium|low)$")
    project_tag: Optional[str] = None
    status: Optional[str] = Field(
        default=None, pattern="^(pending|in_progress|cancelled)$"
    )
    recurrence_rule: Optional[str] = None

    class Config:
        extra = "forbid"


class TodoOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    status: str
    priority: str
    effective_urgency: Optional[str] = None
    due_at: Optional[str] = None
    completed_at: Optional[str] = None
    project_tag: Optional[str] = None
    project_id: Optional[str] = None
    is_recurring: bool
    recurrence_rule: Optional[str] = None
    parent_id: Optional[int] = None
    created_at: str
    updated_at: str


class TodoListOut(BaseModel):
    items: List[TodoOut]
    total: int
    limit: int
    offset: int


class SummaryOut(BaseModel):
    overdue: List[TodoOut]
    today: List[TodoOut]
    upcoming: List[TodoOut]
    high_priority: List[TodoOut]
    total_pending: int
    total_completed_today: int


def _todo_to_dict(todo: Todo) -> Dict[str, Any]:
    return todo.model_dump()


# ---------- router factory ----------


def build_router(get_service: Callable[[], Optional[TodoService]]) -> APIRouter:
    router = APIRouter()

    def service_dep() -> TodoService:
        svc = get_service()
        if svc is None:
            raise HTTPException(status_code=503, detail="todo service not initialised")
        return svc

    @router.get("/todos", response_model=TodoListOut)
    def list_todos(
        status: Optional[str] = Query(default=None),
        project_tag: Optional[str] = Query(default=None),
        priority: Optional[str] = Query(default=None),
        include_completed: bool = Query(default=False),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        svc: TodoService = Depends(service_dep),
    ) -> Dict[str, Any]:
        items = svc.list_todos(
            status=status,
            project_tag=project_tag,
            priority=priority,
            include_completed=include_completed,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [_todo_to_dict(t) for t in items],
            "total": len(items),
            "limit": limit,
            "offset": offset,
        }

    @router.post(
        "/todos", response_model=TodoOut, status_code=status.HTTP_201_CREATED
    )
    def create_todo(
        payload: CreateTodoIn, svc: TodoService = Depends(service_dep)
    ) -> Dict[str, Any]:
        todo = svc.create_todo(
            title=payload.title,
            description=payload.description,
            due_at=payload.due_at,
            priority=payload.priority,
            project_tag=payload.project_tag,
            recurrence_rule=payload.recurrence_rule,
        )
        return _todo_to_dict(todo)

    @router.get("/todos/summary", response_model=SummaryOut)
    def get_summary(svc: TodoService = Depends(service_dep)) -> Dict[str, Any]:
        return svc.get_startup_summary()

    @router.get("/todos/{todo_id}", response_model=TodoOut)
    def get_todo(
        todo_id: int, svc: TodoService = Depends(service_dep)
    ) -> Dict[str, Any]:
        todo = svc.get_todo(todo_id)
        if todo is None:
            raise HTTPException(status_code=404, detail="todo not found")
        return _todo_to_dict(todo)

    @router.put("/todos/{todo_id}", response_model=TodoOut)
    def update_todo(
        todo_id: int,
        payload: UpdateTodoIn,
        svc: TodoService = Depends(service_dep),
    ) -> Dict[str, Any]:
        changes: Dict[str, Any] = {}
        for field in (
            "title",
            "description",
            "due_at",
            "priority",
            "project_tag",
            "status",
            "recurrence_rule",
        ):
            value = getattr(payload, field)
            if value is not None:
                changes[field] = value
        todo = svc.update_todo(todo_id, **changes)
        if todo is None:
            raise HTTPException(status_code=404, detail="todo not found")
        return _todo_to_dict(todo)

    @router.delete(
        "/todos/{todo_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
    )
    def delete_todo(
        todo_id: int, svc: TodoService = Depends(service_dep)
    ) -> Response:
        deleted = svc.delete_todo(todo_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="todo not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/todos/{todo_id}/complete", response_model=TodoOut)
    def complete_todo(
        todo_id: int, svc: TodoService = Depends(service_dep)
    ) -> Dict[str, Any]:
        todo = svc.complete_todo(todo_id)
        if todo is None:
            raise HTTPException(status_code=404, detail="todo not found")
        return _todo_to_dict(todo)

    @router.post("/todos/{todo_id}/cancel", response_model=TodoOut)
    def cancel_todo(
        todo_id: int, svc: TodoService = Depends(service_dep)
    ) -> Dict[str, Any]:
        cancelled = svc.cancel_todo(todo_id)
        if not cancelled:
            raise HTTPException(status_code=404, detail="todo not found")
        return _todo_to_dict(svc.get_todo(todo_id))

    return router
