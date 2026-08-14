"""``orch_routes`` — 编排 run 的读取/resume/计划更新端点（Wave 2 P1-4）。

``list_runs`` / ``get_run`` 供前端历史列表/详情展示；``resume`` 基于已落库的
plan_json 重建新 run；``plan`` 更新仅允许未派发状态（首次 dispatch 后锁定,
防改已跑计划,返回 409）。由 legacy_router 挂载（``router.include_router``），
最终前缀 ``/api/v1/orch``。
"""

from __future__ import annotations

import functools
import json
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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


class OrchRunSummary(BaseModel):
    run_id: str
    session_id: str
    status: str
    created_at: int
    final_summary: Optional[str] = None


class OrchRunDetail(BaseModel):
    run_id: str
    session_id: str
    status: str
    created_at: int
    plan: List[Dict[str, Any]]
    tasks: List[Dict[str, Any]]


class PlanUpdateRequest(BaseModel):
    plan: List[Dict[str, Any]] = Field(min_length=1)  # ≥1 行守卫


class ResumeResponse(BaseModel):
    ok: bool
    new_run_id: str
    session_id: str
    plan: List[Dict[str, Any]]


@router.get("/runs", response_model=List[OrchRunSummary])
@with_db_lock
def list_runs(limit: int = 50, offset: int = 0) -> List[OrchRunSummary]:
    repo = OrchRunRepository()
    return [
        OrchRunSummary(
            run_id=r.run_id,
            session_id=r.session_id,
            status=r.status,
            created_at=r.created_at,
            final_summary=r.final_summary,
        )
        for r in repo.list(limit=limit, offset=offset)
    ]


@router.get("/runs/{run_id}", response_model=OrchRunDetail)
@with_db_lock
def get_run(run_id: str) -> OrchRunDetail:
    run_repo = OrchRunRepository()
    task_repo = OrchTaskRepository()
    run = run_repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
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
        for t in task_repo.list_by_run(run_id)
    ]
    return OrchRunDetail(
        run_id=run.run_id,
        session_id=run.session_id,
        status=run.status,
        created_at=run.created_at,
        plan=plan,
        tasks=tasks,
    )


@router.post("/runs/{run_id}/resume", response_model=ResumeResponse)
@with_db_lock
def resume_run(run_id: str) -> ResumeResponse:
    repo = OrchRunRepository()
    run = repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    new_run_id = f"orch-{uuid.uuid4().hex[:12]}"
    repo.upsert(OrchRun(
        run_id=new_run_id,
        session_id=run.session_id,
        status="running",
        created_at=int(time.time() * 1000),
        plan_json=run.plan_json,
    ))
    plan = json.loads(run.plan_json).get("tasks", [])
    return ResumeResponse(
        ok=True,
        new_run_id=new_run_id,
        session_id=run.session_id,
        plan=plan,
    )


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
    # 进程内注册表定位 dispatcher 并置位（同步 set event，无需 await）。
    try:
        from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

        dispatcher = _ACTIVE_DISPATCHERS.get(run_id)
        if dispatcher is not None:
            dispatcher.cancel()
    except Exception:  # noqa: BLE001 — 注册表命中失败不阻塞状态落库
        pass
    return CancelRunResponse(ok=True, run_id=run_id, status="cancelled")
