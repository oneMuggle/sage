"""``orch_routes`` — 编排 run 的详情/计划更新/取消端点（Wave 2 P1-4）。

``get_run`` 供前端详情展示；``plan`` 更新仅允许未派发状态（首次 dispatch 后锁定,
防改已跑计划,返回 409）。由 legacy_router 挂载（``router.include_router``），
最终前缀 ``/api/v1/orch``。

Wave 4 (2026-09-06): 历史编排记录功能移除 —— 删除 ``list_runs`` (GET /runs)
和 ``resume_run`` (POST /runs/{id}/resume) 端点及其模型 (OrchRunSummary /
ResumeResponse)。
"""

from __future__ import annotations

import functools
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from backend.data.database import _SQLITE_LOCK
from backend.data.orch_run_repo import OrchRun, OrchRunRepository
from backend.data.orch_task_repo import OrchTaskRepository

router = APIRouter(prefix="/orch", tags=["orchestration-runs"])


def with_db_lock(func):
    """装饰器：把 sync 函数包在全局 `_SQLITE_LOCK` 内,串行化 SQLite 访问。

    与 legacy_routes.py 的本地同名装饰器共用同一把 `_SQLITE_LOCK`。
    **必须定义在本模块**（而非 database.py）：FastAPI 在 get_typed_signature
    用 ``call.__globals__`` 解析 future-import 字符串注解（PlanUpdateRequest 等
    body 模型），wrapper.__globals__ 是定义装饰器模块的 dict —— 定义在别的模块
    会报 PydanticUndefinedAnnotation。
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _SQLITE_LOCK:
            return func(*args, **kwargs)

    return wrapper


class OrchRunDetail(BaseModel):
    run_id: str
    session_id: str
    status: str
    created_at: int
    plan: List[Dict[str, Any]]
    tasks: List[Dict[str, Any]]
    # Wave 3 A9: resume 恢复流原始请求
    original_request: Optional[str] = None


class SessionRunsResponse(BaseModel):
    """C1 (2026-09-09): 会话编排 run 列表（历史任务板恢复数据源）。"""

    runs: List[OrchRunDetail]


class PlanUpdateRequest(BaseModel):
    plan: List[Dict[str, Any]] = Field()  # ≥1 行守卫

    @field_validator("plan")
    @classmethod
    def _require_plan(cls, value: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not value:
            raise ValueError("plan must contain at least one item")
        return value


def _run_detail(run: OrchRun) -> OrchRunDetail:
    """C1 (2026-09-09): OrchRun → OrchRunDetail（get_run / 会话列表共用）。"""
    task_repo = OrchTaskRepository()
    plan = json.loads(run.plan_json).get("tasks", [])
    tasks = [
        {
            "task_id": t.task_id,
            "run_id": t.run_id,
            "agent_id": t.agent_id,
            "goal": t.goal,
            "status": t.status,
            "retry_count": t.retry_count,
            "error": t.error,
            "output_preview": t.output_preview,
            "started_at": t.started_at,
            "finished_at": t.finished_at,
        }
        for t in task_repo.list_by_run(run.run_id)
    ]
    return OrchRunDetail(
        run_id=run.run_id,
        session_id=run.session_id,
        status=run.status,
        created_at=run.created_at,
        plan=plan,
        tasks=tasks,
        original_request=run.original_request,
    )


@router.get("/runs", response_model=SessionRunsResponse)
@with_db_lock
def list_session_runs(
    session_id: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> SessionRunsResponse:
    """C1 (2026-09-09): 按会话列编排 run（新→旧），历史任务板恢复数据源。

    Wave 4 曾删除无过滤的 ``GET /runs``；本端点是带 session_id 归属过滤的
    窄口 —— 只返回该会话自己的 run（plan + tasks + 状态）。
    """
    runs = OrchRunRepository().list_by_session(session_id, limit=limit)
    return SessionRunsResponse(runs=[_run_detail(r) for r in runs])


@router.get("/runs/{run_id}", response_model=OrchRunDetail)
@with_db_lock
def get_run(run_id: str) -> OrchRunDetail:
    run_repo = OrchRunRepository()
    run = run_repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_detail(run)


@router.post("/runs/{run_id}/plan")
@with_db_lock
def update_plan(run_id: str, body: PlanUpdateRequest) -> Dict[str, Any]:
    repo = OrchRunRepository()
    run = repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.dispatched_at is not None or run.status != "running":
        raise HTTPException(status_code=409, detail="plan locked after dispatch")
    run.plan_json = json.dumps({"tasks": body.plan, "reasoning": ""}, ensure_ascii=False)
    repo.upsert(run)
    return {"ok": True, "run_id": run_id, "plan": body.plan}


class CancelRunRequest(BaseModel):
    reason: str = "user_cancelled"


class CancelRunResponse(BaseModel):
    ok: bool
    run_id: str
    status: str


class ApprovalModeRequest(BaseModel):
    """run 级子代理审批模式切换请求（live-events P1）。"""

    mode: str

    @field_validator("mode")
    @classmethod
    def _require_known_mode(cls, value: str) -> str:
        if value not in ("ask", "auto"):
            raise ValueError("mode must be 'ask' or 'auto'")
        return value


@router.post("/runs/{run_id}/approval-mode")
def set_approval_mode(run_id: str, body: ApprovalModeRequest) -> Dict[str, Any]:
    """切换本 run 的子代理审批模式（live-events P1 分级信任）。

    - ``ask``：风险工具逐次审批（默认；子代理审批请求会转发前端弹窗）
    - ``auto``：非危险工具自动批准，破坏性/可疑/边界升级仍转人工

    仅作用于**活动中的 run**（进程内注册表命中）；历史 run / 未派发 run
    返回 404 —— 模式不持久化，新 run 继承全局 orch 设置
    ``orch.subagentApprovalMode``。切换成功即向聊天流推 ``approval_mode``
    事件供前端任务树头部开关回显。
    """
    from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

    dispatcher = _ACTIVE_DISPATCHERS.get(run_id)
    if dispatcher is None:
        raise HTTPException(status_code=404, detail="active run not found")
    if not dispatcher.set_approval_mode(body.mode):
        raise HTTPException(status_code=422, detail=f"invalid mode: {body.mode}")
    return {"ok": True, "run_id": run_id, "mode": body.mode}


@router.post("/runs/{run_id}/cancel", response_model=CancelRunResponse)
@with_db_lock
def cancel_run(run_id: str, body: Optional[CancelRunRequest] = None) -> CancelRunResponse:
    """Run 级取消：置 cancelled + 停 dispatcher 新任务（running 不硬杀）。"""
    repo = OrchRunRepository()
    run = repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status in ("cancelled", "completed", "failed"):
        raise HTTPException(status_code=409, detail=f"run already in terminal state: {run.status}")
    repo.update_status(run_id, "cancelled")
    # Fix #3 (2026-09-06): 若 producer 正在等待用户确认,唤醒它以取消状态退出。
    try:
        from backend.api.legacy_routes import _RUN_CONFIRM_EVENTS

        evt = _RUN_CONFIRM_EVENTS.get(run_id)
        if evt is not None:
            evt.set()
    except Exception:  # noqa: BLE001
        pass
    # 进程内注册表定位 dispatcher 与 primary agent 并置位。
    # late import 避免 orch_routes ↔ legacy_routes 的模块初始化环。
    try:
        from backend.api.legacy_routes import interrupt_run

        interrupt_run(run_id)
    except Exception as exc:  # noqa: BLE001 — 注册表命中失败不阻塞状态落库
        # Durable cancellation remains authoritative; log control-plane failure
        # so operators can detect a run that may still be executing.
        import logging

        logging.getLogger(__name__).warning(
            "run cancellation bridge failed for %s: %s", run_id, exc
        )
    return CancelRunResponse(ok=True, run_id=run_id, status="cancelled")


class CancelTaskResponse(BaseModel):
    ok: bool
    run_id: str
    task_id: str
    status: str


@router.post("/runs/{run_id}/tasks/{task_id}/cancel", response_model=CancelTaskResponse)
def cancel_run_task(run_id: str, task_id: str) -> CancelTaskResponse:
    """B3 (2026-09-09): 单任务跳过 —— 只停一个子任务，不影响其余。

    进程内注册表定位活动 dispatcher；queued 任务 acquire 后短路、running
    任务经 interrupt 通道软中断（同 run 级取消语义）。run 不活动 / 任务
    不在本批或已终态分别 404 / 409。
    """
    from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

    dispatcher = _ACTIVE_DISPATCHERS.get(run_id)
    if dispatcher is None:
        raise HTTPException(status_code=404, detail="active run not found")
    if not dispatcher.cancel_task(task_id):
        raise HTTPException(
            status_code=409,
            detail=f"task not cancellable (unknown/terminal): {task_id}",
        )
    return CancelTaskResponse(
        ok=True, run_id=run_id, task_id=task_id, status="cancelling"
    )


# Fix #3 (2026-09-06): 用户确认端点 —— 前端 PlanCard "开始执行" 按钮调用。
# 唤醒在 legacy_routes.producer 中等待的 asyncio.Event,触发 conductor 启动。


class ConfirmRunResponse(BaseModel):
    ok: bool
    run_id: str


@router.post("/runs/{run_id}/confirm", response_model=ConfirmRunResponse)
def confirm_run(run_id: str) -> ConfirmRunResponse:
    """用户确认编排计划 → 唤醒 producer 开始 conductor 执行。

    前置条件: run 状态为 running 且尚未派发 (dispatched_at is None)。
    若 run 不存在或已终态 → 404/409。
    """
    repo = OrchRunRepository()
    run = repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status != "running":
        raise HTTPException(
            status_code=409, detail=f"run not in running state: {run.status}"
        )
    # 设置确认事件唤醒 producer。
    try:
        from backend.api.legacy_routes import _RUN_CONFIRM_EVENTS

        evt = _RUN_CONFIRM_EVENTS.get(run_id)
        if evt is not None:
            evt.set()
        else:
            # producer 可能已跳过等待（超时或竞态）,不影响确认语义
            import logging

            logging.getLogger(__name__).debug(
                "confirm_run: no pending confirm event for %s (producer may have passed)",
                run_id,
            )
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning(
            "confirm_run: failed to set confirm event for %s: %s", run_id, exc
        )
    return ConfirmRunResponse(ok=True, run_id=run_id)
