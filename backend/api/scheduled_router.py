"""Scheduled tasks REST API.

Mount under ``/api/v1`` from ``backend/main.py``. Service dependency is injected
via a ``get_service`` callable so tests can supply an isolated instance with
mocked repos.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from backend.services.scheduler import SchedulerService, TaskNotFoundError, ValidationError

logger = logging.getLogger(__name__)


# ---------- request / response models ----------


class ScheduleIn(BaseModel):
    kind: Literal["once", "recurring"]
    at: Optional[int] = None
    cron: Optional[str] = None


class ScheduleOut(BaseModel):
    kind: Literal["once", "recurring"]
    at: Optional[int] = None
    cron: Optional[str] = None


class CreateTaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: Literal["once", "recurring"]
    schedule: ScheduleIn
    session_id: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=4000)


class UpdateTaskIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    enabled: Optional[bool] = None


class TaskOut(BaseModel):
    id: str
    name: str
    type: Literal["once", "recurring"]
    schedule: ScheduleOut
    session_id: str
    content: str
    enabled: bool
    created_at: int
    last_run: Optional[int] = None
    next_run: Optional[int] = None


def _task_to_dict(task: Any) -> Dict[str, Any]:
    return {
        "id": task.id,
        "name": task.name,
        "type": task.type,
        "schedule": dict(task.schedule),
        "session_id": task.session_id,
        "content": task.content,
        "enabled": task.enabled,
        "created_at": task.created_at,
        "last_run": task.last_run,
        "next_run": task.next_run,
    }


def _schedule_in_to_dict(s: ScheduleIn) -> Dict[str, Any]:
    if s.kind == "once":
        if s.at is None:
            raise ValueError("'at' is required for one-shot tasks")
        return {"kind": "once", "at": s.at}
    if not s.cron:
        raise ValueError("'cron' is required for recurring tasks")
    return {"kind": "recurring", "cron": s.cron}


# ---------- router factory ----------


def build_router(get_service: Callable[[], SchedulerService | None]) -> APIRouter:
    router = APIRouter()

    def service_dep() -> SchedulerService:
        svc = get_service()
        if svc is None:
            raise HTTPException(status_code=503, detail="scheduler not initialised")
        return svc

    @router.get("/scheduled/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    @router.get("/scheduled/tasks", response_model=List[TaskOut])
    def list_tasks(svc: SchedulerService = Depends(service_dep)) -> List[Dict[str, Any]]:
        return [_task_to_dict(t) for t in svc.list_tasks()]

    @router.post("/scheduled/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
    def create_task(
        payload: CreateTaskIn, svc: SchedulerService = Depends(service_dep)
    ) -> Dict[str, Any]:
        try:
            schedule_dict = _schedule_in_to_dict(payload.schedule)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            task = svc.add_task(
                name=payload.name,
                task_type=payload.type,
                schedule=schedule_dict,
                session_id=payload.session_id,
                content=payload.content,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _task_to_dict(task)

    @router.patch("/scheduled/tasks/{task_id}", response_model=TaskOut)
    def update_task(
        task_id: str,
        payload: UpdateTaskIn,
        svc: SchedulerService = Depends(service_dep),
    ) -> Dict[str, Any]:
        changes: Dict[str, Any] = {}
        if payload.name is not None:
            changes["name"] = payload.name
        if payload.enabled is not None:
            changes["enabled"] = payload.enabled
        try:
            return _task_to_dict(svc.update_task(task_id, **changes))
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.delete(
        "/scheduled/tasks/{task_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
    )
    def delete_task(task_id: str, svc: SchedulerService = Depends(service_dep)) -> Response:
        try:
            svc.delete_task(task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/scheduled/tasks/{task_id}/run", response_model=TaskOut)
    def run_task(task_id: str, svc: SchedulerService = Depends(service_dep)) -> Dict[str, Any]:
        try:
            svc.run_now(task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _task_to_dict(svc.get_task(task_id))

    return router
