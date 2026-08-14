"""``orch_routes`` — 编排 run 的读取/resume/计划更新端点（Wave 2 P1-4）。

``list_runs`` / ``get_run`` 供前端历史列表/详情展示；``resume`` 基于已落库的
plan_json 重建新 run；``plan`` 更新仅允许 running 状态（派发后锁定，防改已跑计划）。
由 legacy_router 挂载（``router.include_router``），最终前缀 ``/api/v1/orch``。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.data.orch_run_repo import OrchRun, OrchRunRepository
from backend.data.orch_task_repo import OrchTaskRepository

router = APIRouter(prefix="/orch", tags=["orchestration-runs"])


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
    plan: List[Dict[str, Any]] = Field(min_items=1)  # ≥1 行守卫


class ResumeResponse(BaseModel):
    ok: bool
    new_run_id: str
    session_id: str
    plan: List[Dict[str, Any]]


@router.get("/runs", response_model=List[OrchRunSummary])
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
def update_plan(run_id: str, body: PlanUpdateRequest) -> Dict[str, Any]:
    repo = OrchRunRepository()
    run = repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status != "running":
        raise HTTPException(status_code=409, detail="plan locked after dispatch")
    run.plan_json = json.dumps({"tasks": body.plan, "reasoning": ""}, ensure_ascii=False)
    repo.upsert(run)
    return {"ok": True, "run_id": run_id, "plan": body.plan}
