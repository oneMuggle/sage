"""Worklog REST API (P2).

Mounted under ``/api/v1`` from ``backend/main.py``. The service dependency is
injected via a ``get_service`` callable so tests can supply an isolated
instance — same contract as ``todo_router.build_router``.

**Endpoint order matters**: ``/worklogs/summary`` and ``/worklogs/extract`` are
registered **before** ``/worklogs/{worklog_id}`` so the literal paths are not
swallowed by the integer path parameter (422).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from backend.services.worklog_models import WorkLog
from backend.services.worklog_service import MAX_PAGE_SIZE, WorklogService

logger = logging.getLogger(__name__)


# ---------- request / response models ----------


class CreateWorklogIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    kind: str = Field(default="progress", pattern="^(progress|done|blocker|next)$")
    session_id: Optional[str] = Field(default=None, max_length=200)
    progress_text: Optional[str] = Field(default=None, max_length=2000)
    blocker: Optional[str] = Field(default=None, max_length=2000)
    todo_id: Optional[int] = None
    project_id: Optional[str] = Field(default=None, max_length=200)
    project_tag: Optional[str] = Field(default=None, max_length=100)
    source_type: str = Field(default="manual", pattern="^(chat|manual|agent)$")
    source_ref: Optional[str] = Field(default=None, max_length=200)

    class Config:
        extra = "forbid"


class UpdateWorklogIn(BaseModel):
    """编辑工作日志。

    **不含** ``status`` —— 状态迁移只走 ``/confirm`` 与 ``/dismiss`` 两个
    显式端点，避免「编辑正文」意外改变一条记录是否进报告。

    ``exclude_unset=True`` 让「键缺席 = 不动该列」与「显式 null = 清空」两
    种语义在 Pydantic v1 / v2 下保持一致。
    """

    content: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    kind: Optional[str] = Field(default=None, pattern="^(progress|done|blocker|next)$")
    session_id: Optional[str] = Field(default=None, max_length=200)
    progress_text: Optional[str] = Field(default=None, max_length=2000)
    blocker: Optional[str] = Field(default=None, max_length=2000)
    todo_id: Optional[int] = None
    project_id: Optional[str] = Field(default=None, max_length=200)
    project_tag: Optional[str] = Field(default=None, max_length=100)
    source_type: Optional[str] = Field(default=None, pattern="^(chat|manual|agent)$")
    source_ref: Optional[str] = Field(default=None, max_length=200)

    class Config:
        extra = "forbid"


class WorklogListOut(BaseModel):
    items: List[WorkLog]
    total: int
    limit: int
    offset: int


class WorklogSummaryOut(BaseModel):
    """时间窗内的统计快照 —— **只统计已确认**的记录。"""

    total: int
    by_kind: Dict[str, int]
    sessions: int


class ExtractWorklogsIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    message_ids: Optional[List[str]] = None

    class Config:
        extra = "forbid"


class ExtractWorklogCandidateOut(BaseModel):
    content: str
    kind: str
    progress_text: Optional[str] = None
    blocker: Optional[str] = None


class ExtractWorklogsOut(BaseModel):
    candidates: List[ExtractWorklogCandidateOut]


def _worklog_to_dict(worklog: WorkLog) -> Dict[str, Any]:
    return worklog.model_dump()


# ---------- router factory ----------


def build_router(get_service: Callable[[], Optional[WorklogService]]) -> APIRouter:
    router = APIRouter()

    def service_dep() -> WorklogService:
        svc = get_service()
        if svc is None:
            raise HTTPException(
                status_code=503, detail="worklog service not initialised"
            )
        return svc

    @router.get("/worklogs", response_model=WorklogListOut)
    def list_worklogs(
        status_: Optional[str] = Query(
            default=None,
            alias="status",
            pattern="^(pending|confirmed|dismissed)$",
        ),
        kind: Optional[str] = Query(
            default=None, pattern="^(progress|done|blocker|next)$"
        ),
        date_from: Optional[str] = Query(default=None, alias="from"),
        date_to: Optional[str] = Query(default=None, alias="to"),
        todo_id: Optional[int] = Query(default=None),
        project_tag: Optional[str] = Query(default=None, max_length=100),
        session_id: Optional[str] = Query(default=None, max_length=200),
        limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
        offset: int = Query(default=0, ge=0),
        svc: WorklogService = Depends(service_dep),
    ) -> Dict[str, Any]:
        try:
            items = svc.list_worklogs(
                status=status_,
                kind=kind,
                date_from=date_from,
                date_to=date_to,
                todo_id=todo_id,
                project_tag=project_tag,
                session_id=session_id,
                limit=limit,
                offset=offset,
            )
            # ``total`` counts every row matching the filters, not this page.
            total = svc.count_worklogs(
                status=status_,
                kind=kind,
                date_from=date_from,
                date_to=date_to,
                todo_id=todo_id,
                project_tag=project_tag,
                session_id=session_id,
            )
        except ValueError as exc:
            # 非法 ``from`` / ``to`` 日期 → 400，与 create/update 一致；
            # 不拦截会冒泡成 500。
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "items": [_worklog_to_dict(item) for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @router.get("/worklogs/summary", response_model=WorklogSummaryOut)
    def summarize_worklogs(
        date_from: Optional[str] = Query(default=None, alias="from"),
        date_to: Optional[str] = Query(default=None, alias="to"),
        todo_id: Optional[int] = Query(default=None),
        project_tag: Optional[str] = Query(default=None, max_length=100),
        svc: WorklogService = Depends(service_dep),
    ) -> Dict[str, Any]:
        try:
            return svc.summarize(
                date_from=date_from,
                date_to=date_to,
                todo_id=todo_id,
                project_tag=project_tag,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/worklogs/extract", response_model=ExtractWorklogsOut)
    async def extract_worklogs(payload: ExtractWorklogsIn) -> Dict[str, Any]:
        """从会话中抽取工作日志候选（**不落库**，由用户逐条确认）。"""
        from backend.services import worklog_ai

        try:
            candidates = await worklog_ai.extract_worklogs(
                session_id=payload.session_id, message_ids=payload.message_ids
            )
        except worklog_ai.LLMNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — 上游 LLM 失败统一 502
            logger.exception("worklog extract failed")
            raise HTTPException(
                status_code=502, detail=f"工作日志提炼失败: {exc}"
            ) from exc
        return {"candidates": candidates}

    @router.post(
        "/worklogs", response_model=WorkLog, status_code=status.HTTP_201_CREATED
    )
    def create_worklog(
        payload: CreateWorklogIn, svc: WorklogService = Depends(service_dep)
    ) -> Dict[str, Any]:
        try:
            worklog = svc.create_worklog(
                content=payload.content,
                kind=payload.kind,
                session_id=payload.session_id,
                progress_text=payload.progress_text,
                blocker=payload.blocker,
                todo_id=payload.todo_id,
                project_id=payload.project_id,
                project_tag=payload.project_tag,
                source_type=payload.source_type,
                source_ref=payload.source_ref,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _worklog_to_dict(worklog)

    @router.get("/worklogs/{worklog_id}", response_model=WorkLog)
    def get_worklog(
        worklog_id: int, svc: WorklogService = Depends(service_dep)
    ) -> Dict[str, Any]:
        worklog = svc.get_worklog(worklog_id)
        if worklog is None:
            raise HTTPException(status_code=404, detail="worklog not found")
        return _worklog_to_dict(worklog)

    @router.put("/worklogs/{worklog_id}", response_model=WorkLog)
    def update_worklog(
        worklog_id: int,
        payload: UpdateWorklogIn,
        svc: WorklogService = Depends(service_dep),
    ) -> Dict[str, Any]:
        try:
            worklog = svc.update_worklog(
                worklog_id, **payload.model_dump(exclude_unset=True)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if worklog is None:
            raise HTTPException(status_code=404, detail="worklog not found")
        return _worklog_to_dict(worklog)

    @router.delete(
        "/worklogs/{worklog_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
    )
    def delete_worklog(
        worklog_id: int, svc: WorklogService = Depends(service_dep)
    ) -> Response:
        if not svc.delete_worklog(worklog_id):
            raise HTTPException(status_code=404, detail="worklog not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/worklogs/{worklog_id}/confirm", response_model=WorkLog)
    def confirm_worklog(
        worklog_id: int, svc: WorklogService = Depends(service_dep)
    ) -> Dict[str, Any]:
        worklog = svc.confirm_worklog(worklog_id)
        if worklog is None:
            raise HTTPException(status_code=404, detail="worklog not found")
        return _worklog_to_dict(worklog)

    @router.post("/worklogs/{worklog_id}/dismiss", response_model=WorkLog)
    def dismiss_worklog(
        worklog_id: int, svc: WorklogService = Depends(service_dep)
    ) -> Dict[str, Any]:
        worklog = svc.dismiss_worklog(worklog_id)
        if worklog is None:
            raise HTTPException(status_code=404, detail="worklog not found")
        return _worklog_to_dict(worklog)

    return router
