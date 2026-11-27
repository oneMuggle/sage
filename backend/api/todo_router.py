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

from backend.services import todo_order, todo_status
from backend.services.todo_service import Todo, TodoService

logger = logging.getLogger(__name__)


def _worklog_service() -> Optional[Any]:
    """取工作日志服务；未初始化时返回 ``None``。

    日报 / 周报是「双来源」聚合（待办 + 工作日志）。工作日志子系统缺席
    时（早期启动、单测）简报退化成「纯待办版」，而不是整条端点报错。
    """
    from backend.services.worklog_service import get_worklog_service

    return get_worklog_service()


# ---------- request / response models ----------


class CreateTodoIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    due_at: Optional[str] = None
    priority: str = Field(default="medium", pattern="^(high|medium|low)$")
    project_tag: Optional[str] = None
    recurrence_rule: Optional[str] = None
    parent_id: Optional[int] = None
    tags: Optional[List[str]] = None
    reminder_offsets: Optional[List[int]] = None
    source_type: Optional[str] = Field(default=None, max_length=32)
    source_ref: Optional[str] = Field(default=None, max_length=200)
    specialist_id: Optional[str] = Field(default=None, max_length=100)

    class Config:
        extra = "forbid"


class UpdateTodoIn(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    due_at: Optional[str] = None
    priority: Optional[str] = Field(default=None, pattern="^(high|medium|low)$")
    project_tag: Optional[str] = None
    status: Optional[str] = Field(
        default=None, pattern="^(pending|in_progress|completed|cancelled)$"
    )
    recurrence_rule: Optional[str] = None
    parent_id: Optional[int] = None
    tags: Optional[List[str]] = None
    reminder_offsets: Optional[List[int]] = None
    specialist_id: Optional[str] = Field(default=None, max_length=100)

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
    tags: List[str] = Field(default_factory=list)
    reminder_offsets: List[int] = Field(default_factory=list)
    source_type: Optional[str] = None
    source_ref: Optional[str] = None
    specialist_id: Optional[str] = None
    snooze_count: int = 0
    is_recurring: bool
    recurrence_rule: Optional[str] = None
    parent_id: Optional[int] = None
    # 同层内的手工次序（P1 拖拽排序）。旧行默认 0，由 id 次序兜底。
    sort_order: float = 0.0
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


class StatsOut(BaseModel):
    total: int
    by_status: Dict[str, int]
    by_priority: Dict[str, int]
    overdue: int
    due_today: int
    completed_today: int


class BatchIdsIn(BaseModel):
    ids: List[int]

    class Config:
        extra = "forbid"


class BatchCompleteOut(BaseModel):
    completed: int
    missing: List[int]


class BatchDeleteOut(BaseModel):
    deleted: int


class ExportOut(BaseModel):
    filename: str
    format: str
    content: str


class TagCountOut(BaseModel):
    tag: str
    count: int


class ExtractTodosIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    message_ids: Optional[List[str]] = None

    class Config:
        extra = "forbid"


class ExtractCandidateOut(BaseModel):
    title: str
    due_at: Optional[str] = None
    priority: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class ExtractTodosOut(BaseModel):
    candidates: List[ExtractCandidateOut]


class BatchCreateIn(BaseModel):
    items: List[CreateTodoIn]

    class Config:
        extra = "forbid"


class BatchCreateOut(BaseModel):
    items: List[TodoOut]


class AiTextOut(BaseModel):
    content: str


class HeatmapDayOut(BaseModel):
    date: str
    count: int


class HeatmapOut(BaseModel):
    days: List[HeatmapDayOut]
    total: int
    max: int


class SnoozeIn(BaseModel):
    minutes: int = Field(ge=1, le=7 * 24 * 60)

    class Config:
        extra = "forbid"


class MoveTodoIn(BaseModel):
    """拖拽移动请求（P1 拖拽排序与拖拽嵌套）。

    ``target_parent_id`` 是三态：

    - 省略 → 目标层跟随参照待办所在层（``todo_order.INHERIT``）；
    - 显式 ``null`` → 强制回顶层；
    - 给 id → 成为该待办的子任务。

    ``position`` 为 ``before`` / ``after``，相对 ``reference_id`` 落位；
    ``reference_id`` 为 ``None`` 时追加到目标层末尾。
    """

    position: str = Field(pattern="^(before|after)$")
    reference_id: Optional[int] = None
    target_parent_id: Optional[int] = None

    class Config:
        extra = "forbid"


class MoveTodoOut(BaseModel):
    todo: TodoOut
    affected: int


def _todo_to_dict(todo: Todo) -> Dict[str, Any]:
    return todo.model_dump()


def _validate_batch_ids(ids: List[int]) -> None:
    """批量操作入参守卫：非空、上限 500（与 list 的 limit 上界一致）。"""
    if not ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    if len(ids) > 500:
        raise HTTPException(status_code=400, detail="单次批量操作上限 500 条")


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
        status: Optional[str] = Query(
            default=None,
            pattern="^(pending|in_progress|completed|cancelled|all)$",
        ),
        project_tag: Optional[str] = Query(default=None),
        priority: Optional[str] = Query(default=None, pattern="^(high|medium|low)$"),
        include_completed: bool = Query(default=False),
        sort_by: str = Query(
            default="due_at", pattern="^(due_at|priority|created_at|manual)$"
        ),
        sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        q: Optional[str] = Query(default=None, max_length=200),
        tag: Optional[str] = Query(default=None, max_length=50),
        view: Optional[str] = Query(
            default=None, pattern="^(all|today|week|completed)$"
        ),
        specialist_id: Optional[str] = Query(default=None, max_length=100),
        svc: TodoService = Depends(service_dep),
    ) -> Dict[str, Any]:
        # ``status=all`` is the documented escape hatch for the
        # pending/in_progress-only default, so it has to reach the service as
        # ``include_completed=True`` — the filter block treats any other
        # ``status`` value as an equality match and would return 0 rows.
        include_completed = include_completed or status == "all"
        items = svc.list_todos(
            status=status,
            project_tag=project_tag,
            priority=priority,
            include_completed=include_completed,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
            q=q,
            tag=tag,
            view=view,
            specialist_id=specialist_id,
        )
        # ``total`` is the number of rows matching the filters, NOT the length
        # of this page — a ``?limit=2`` response must still report the full
        # match count or the client cannot render pagination controls.
        total = svc.count_todos(
            status=status,
            project_tag=project_tag,
            priority=priority,
            include_completed=include_completed,
            q=q,
            tag=tag,
            view=view,
            specialist_id=specialist_id,
        )
        return {
            "items": [_todo_to_dict(t) for t in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @router.post(
        "/todos", response_model=TodoOut, status_code=status.HTTP_201_CREATED
    )
    def create_todo(
        payload: CreateTodoIn, svc: TodoService = Depends(service_dep)
    ) -> Dict[str, Any]:
        try:
            todo = svc.create_todo(
                title=payload.title,
                description=payload.description,
                due_at=payload.due_at,
                priority=payload.priority,
                project_tag=payload.project_tag,
                recurrence_rule=payload.recurrence_rule,
                parent_id=payload.parent_id,
                tags=payload.tags,
                reminder_offsets=payload.reminder_offsets,
                source_type=payload.source_type,
                source_ref=payload.source_ref,
                specialist_id=payload.specialist_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _todo_to_dict(todo)

    @router.get("/todos/summary", response_model=SummaryOut)
    def get_summary(svc: TodoService = Depends(service_dep)) -> Dict[str, Any]:
        return svc.get_startup_summary()

    @router.get("/todos/stats", response_model=StatsOut)
    def get_stats(svc: TodoService = Depends(service_dep)) -> Dict[str, Any]:
        return svc.get_todo_stats()

    @router.get("/todos/tags", response_model=List[TagCountOut])
    def list_tags(svc: TodoService = Depends(service_dep)) -> List[Dict[str, Any]]:
        return svc.list_tags()

    # NOTE: /todos/export 与 /todos/batch/* 必须注册在 /todos/{todo_id} 等
    # 动态路由之前，否则会被 int 路径参数捕获成 422。
    @router.get("/todos/export", response_model=ExportOut)
    def export_todos(
        format_: str = Query(default="json", alias="format", pattern="^(json|md)$"),
        include_completed: bool = Query(default=False),
        svc: TodoService = Depends(service_dep),
    ) -> Dict[str, str]:
        return svc.export_todos(include_completed=include_completed, fmt=format_)

    @router.post("/todos/batch/complete", response_model=BatchCompleteOut)
    def batch_complete(
        payload: BatchIdsIn, svc: TodoService = Depends(service_dep)
    ) -> Dict[str, Any]:
        _validate_batch_ids(payload.ids)
        return svc.complete_many(payload.ids)

    @router.post("/todos/batch/delete", response_model=BatchDeleteOut)
    def batch_delete(
        payload: BatchIdsIn, svc: TodoService = Depends(service_dep)
    ) -> Dict[str, Any]:
        _validate_batch_ids(payload.ids)
        return {"deleted": svc.delete_many(payload.ids)}

    # --- 阶段 2：AI 能力（对话提炼 / 每日简报 / 周回顾） ---

    @router.post("/todos/batch/create", response_model=BatchCreateOut)
    def batch_create(
        payload: BatchCreateIn, svc: TodoService = Depends(service_dep)
    ) -> Dict[str, Any]:
        if not payload.items:
            raise HTTPException(status_code=400, detail="items 不能为空")
        if len(payload.items) > 20:
            raise HTTPException(status_code=400, detail="单次批量创建上限 20 条")
        try:
            created = svc.create_many(
                [item.model_dump() for item in payload.items]
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"items": [_todo_to_dict(t) for t in created]}

    @router.post("/todos/extract", response_model=ExtractTodosOut)
    async def extract_todos(payload: ExtractTodosIn) -> Dict[str, Any]:
        from backend.services import todo_ai

        try:
            candidates = await todo_ai.extract_todos(
                session_id=payload.session_id, message_ids=payload.message_ids
            )
        except todo_ai.LLMNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — 上游 LLM 失败统一 502
            logger.exception("todo extract failed")
            raise HTTPException(
                status_code=502, detail=f"待办提炼失败: {exc}"
            ) from exc
        return {"candidates": candidates}

    @router.get("/todos/brief", response_model=AiTextOut)
    async def daily_brief(
        svc: TodoService = Depends(service_dep),
    ) -> Dict[str, Any]:
        from backend.services import report_ai, todo_ai

        # 双来源（P3.5）：报告引擎把「工作日志 + 待办」聚成一份上下文，
        # 其中工作日志段并进启动摘要 —— 只看待办会漏掉「没建待办但确实
        # 干了」的工作。工作日志服务缺席时该段为空，不报错。
        period_start, period_end = report_ai.today_period()
        context = report_ai.build_report_context(
            db=svc.db,
            worklog_service=_worklog_service(),
            report_type="daily",
            period_start=period_start,
            period_end=period_end,
        )
        summary = svc.get_startup_summary()
        summary["worklogs"] = context["worklogs"]
        try:
            content = await todo_ai.generate_daily_brief(summary)
        except todo_ai.LLMNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("todo daily brief failed")
            raise HTTPException(
                status_code=502, detail=f"生成简报失败: {exc}"
            ) from exc
        return {"content": content}

    @router.get("/todos/weekly-review", response_model=AiTextOut)
    async def weekly_review(
        svc: TodoService = Depends(service_dep),
    ) -> Dict[str, Any]:
        from backend.services import report_ai, todo_ai

        period_start, period_end = report_ai.week_period()
        context = report_ai.build_report_context(
            db=svc.db,
            worklog_service=_worklog_service(),
            report_type="weekly",
            period_start=period_start,
            period_end=period_end,
        )
        stats = svc.get_todo_stats()
        # 双来源（P3.5）：工作日志摘要进统计字典，「本周完成」换成窗口内
        # 真正完成的待办（报告引擎口径）。
        stats["worklogs"] = context["worklogs"]
        completed = context["todos"]["completed"]
        high_pending = svc.list_todos(priority="high", limit=20)
        snoozed = svc.get_most_snoozed(5)
        try:
            content = await todo_ai.generate_weekly_review(
                stats,
                list(completed),
                [t.title for t in high_pending],
                [f"{t.title}（推迟 {t.snooze_count} 次）" for t in snoozed],
            )
        except todo_ai.LLMNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("todo weekly review failed")
            raise HTTPException(
                status_code=502, detail=f"生成周回顾失败: {exc}"
            ) from exc
        return {"content": content}

    # --- 阶段 3：完成热力图 / snooze ---

    @router.get("/todos/heatmap", response_model=HeatmapOut)
    def heatmap(
        days: int = Query(default=91, ge=7, le=366),
        svc: TodoService = Depends(service_dep),
    ) -> Dict[str, Any]:
        return svc.completion_heatmap(days=days)

    @router.post("/todos/{todo_id}/snooze", response_model=TodoOut)
    def snooze_todo(
        todo_id: int,
        payload: SnoozeIn,
        svc: TodoService = Depends(service_dep),
    ) -> Dict[str, Any]:
        todo = svc.snooze_todo(todo_id, payload.minutes)
        if todo is None:
            raise HTTPException(status_code=404, detail="todo not found")
        return _todo_to_dict(todo)

    @router.post("/todos/{todo_id}/move", response_model=MoveTodoOut)
    def move_todo(
        todo_id: int,
        payload: MoveTodoIn,
        svc: TodoService = Depends(service_dep),
    ) -> Dict[str, Any]:
        """移动待办：同层排序 / 拖拽成子任务（P1 拖拽排序与嵌套）。"""
        # ``exclude_unset`` 是这里的关键：``target_parent_id`` 省略与显式
        # ``null`` 语义不同 —— 省略表示「目标层跟随参照待办所在层」，显式
        # ``null`` 表示「强制回顶层」。``model_dump`` 会把没传的字段丢掉，
        # 显式传 ``null`` 的字段仍在（值为 ``None``），两者因此可区分。
        changes = payload.model_dump(exclude_unset=True)
        target_parent_id = changes.get("target_parent_id", todo_order.INHERIT)
        try:
            result = svc.move_todo(
                todo_id,
                payload.position,
                reference_id=changes.get("reference_id"),
                target_parent_id=target_parent_id,
            )
        except ValueError as exc:
            # 层级超限 / 自我嵌套 / 参照物不同层 —— 请求不合法，不是服务端故障。
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="todo not found")
        return {
            "todo": _todo_to_dict(result["todo"]),
            "affected": result["affected"],
        }

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
        # ``exclude_unset`` preserves the three-way distinction
        # :meth:`TodoService.update_todo` documents: a key absent from the
        # payload leaves the column untouched, while an explicit ``null``
        # clears it. The previous ``if value is not None`` loop collapsed
        # "clear this field" into "leave it alone", so no nullable column
        # could ever be cleared over REST.
        changes = payload.model_dump(exclude_unset=True)
        # ``completed`` 走 ``complete_todo``：与 ``POST /todos/{id}/complete``
        # 同语义（补 completed_at + 为循环待办派生下一个实例）。否则「行内
        # 三态循环」和「标记完成」两条路径会给出不同的完成副作用。
        requested_status = changes.pop("status", None)
        try:
            if requested_status == todo_status.COMPLETED:
                # 先写普通字段：这一步可能因 parent_id 非法 / title 清空等抛
                # ValueError。若先 complete 再更新，失败时会留下「已标完成、
                # 但字段没改」的半写入状态。
                if changes:
                    todo = svc.update_todo(todo_id, **changes)
                    if todo is None:
                        raise HTTPException(status_code=404, detail="todo not found")
                todo = svc.complete_todo(todo_id)
            else:
                if requested_status is not None:
                    changes["status"] = requested_status
                todo = svc.update_todo(todo_id, **changes)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        todo = svc.get_todo(todo_id)
        if todo is None:
            # The row vanished between the UPDATE and the re-fetch (a
            # concurrent DELETE). ``_todo_to_dict(None)`` would raise
            # AttributeError and surface as an opaque 500.
            raise HTTPException(status_code=404, detail="todo not found")
        return _todo_to_dict(todo)

    return router
