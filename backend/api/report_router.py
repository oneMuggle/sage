"""Report REST API (P3) —— 日报 / 周报的生成、存档、列表与详情。

Mounted under ``/api/v1`` from ``backend/main.py``. 与 ``todo_router`` /
``worklog_router`` 同款：服务依赖经 ``get_service`` 注入，测试可喂隔离实例。

**生成即存档**（``POST /reports/generate``）：一次调用完成「聚合 → 生成 →
落库」，返回的 ``report`` 就是已经存好的那条记录。报告正文与统计快照在生成
时刻冻结 —— 之后工作日志再改，历史报告也不回写。

**端点顺序**：``/reports/generate`` 注册在 ``/reports/{report_id}`` 之前，
避免字面量路径被整数路径参数吞掉。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.services import report_ai
from backend.services.report_models import REPORT_TYPES, Report
from backend.services.report_service import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ReportService,
)
from backend.services.worklog_service import WorklogService

logger = logging.getLogger(__name__)


# ---------- request / response models ----------


class GenerateReportIn(BaseModel):
    """生成一份报告。

    ``period_start`` / ``period_end`` 缺省时按类型取默认窗：日报 = 今天，
    周报 = 近 7 天（含今天）。显式传入时以传入值为准。
    """

    report_type: str = Field(default="daily", pattern="^(daily|weekly)$")
    period_start: Optional[str] = Field(default=None, max_length=10)
    period_end: Optional[str] = Field(default=None, max_length=10)
    title: Optional[str] = Field(default=None, max_length=200)

    class Config:
        extra = "forbid"


class ReportOut(BaseModel):
    """存档后的报告（含生成时刻的统计快照）。"""

    id: int
    title: str
    report_type: str
    period_start: str
    period_end: str
    content: str
    stats: Optional[Dict[str, Any]] = None
    created_at: str
    updated_at: str


class ReportGenerateOut(BaseModel):
    report: ReportOut


class ReportListOut(BaseModel):
    items: List[ReportOut]
    total: int
    limit: int
    offset: int


def _report_to_dict(report: Report) -> Dict[str, Any]:
    return report.model_dump()


# ---------- router factory ----------


def build_router(
    get_service: Callable[[], Optional[ReportService]],
    get_worklog_service: Callable[[], Optional[WorklogService]],
) -> APIRouter:
    router = APIRouter()

    def service_dep() -> ReportService:
        svc = get_service()
        if svc is None:
            raise HTTPException(
                status_code=503, detail="report service not initialised"
            )
        return svc

    @router.post(
        "/reports/generate",
        response_model=ReportGenerateOut,
        status_code=status.HTTP_201_CREATED,
    )
    async def generate_report(
        payload: GenerateReportIn,
        svc: ReportService = Depends(service_dep),
    ) -> Dict[str, Any]:
        """聚合工作日志 + 待办 → 生成 Markdown → 存档。"""
        report_type = payload.report_type
        if report_type not in REPORT_TYPES:  # pragma: no cover — pydantic 已拦
            raise HTTPException(
                status_code=400, detail=f"invalid report_type: {report_type!r}"
            )

        if payload.period_start and payload.period_end:
            period_start, period_end = payload.period_start, payload.period_end
        else:
            if report_type == "daily":
                default_start, default_end = report_ai.today_period()
            else:
                default_start, default_end = report_ai.week_period()
            period_start = payload.period_start or default_start
            period_end = payload.period_end or default_end

        worklog_service = get_worklog_service()
        try:
            context = report_ai.build_report_context(
                db=svc.db,
                worklog_service=worklog_service,
                report_type=report_type,
                period_start=period_start,
                period_end=period_end,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            content, ai_generated = await report_ai.generate_with_fallback(context)
        except report_ai.LLMNotConfiguredError as exc:  # pragma: no cover — 已被降级兜住
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — 上游 LLM 失败统一 502
            logger.exception("report generation failed")
            raise HTTPException(
                status_code=502, detail=f"报告生成失败: {exc}"
            ) from exc

        stats = {
            "ai_generated": ai_generated,
            "worklogs": context.get("worklogs"),
            "todos": context.get("todos"),
        }
        try:
            report = svc.create_report(
                title=payload.title,
                report_type=report_type,
                period_start=period_start,
                period_end=period_end,
                content=content,
                stats=stats,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"report": _report_to_dict(report)}

    @router.get("/reports", response_model=ReportListOut)
    def list_reports(
        report_type: Optional[str] = Query(
            default=None, pattern="^(daily|weekly)$"
        ),
        limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        offset: int = Query(default=0, ge=0),
        svc: ReportService = Depends(service_dep),
    ) -> Dict[str, Any]:
        items = svc.list_reports(report_type=report_type, limit=limit, offset=offset)
        total = svc.count_reports(report_type=report_type)
        return {
            "items": [_report_to_dict(item) for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @router.get("/reports/{report_id}", response_model=ReportOut)
    def get_report(
        report_id: int, svc: ReportService = Depends(service_dep)
    ) -> Dict[str, Any]:
        report = svc.get_report(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        return _report_to_dict(report)

    return router
