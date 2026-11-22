"""M2.5: 任务 / run 级暂停与恢复端点。

从 ``orch_routes`` 拆出（保持单文件 < 800 行棘轮）。路由前缀一致，
由 ``orch_routes.router`` include 后随 legacy_router 一起挂载。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["orchestration-runs"])


class TaskPauseResponse(BaseModel):
    ok: bool
    run_id: str
    task_id: str
    status: str


class RunPauseResponse(BaseModel):
    ok: bool
    run_id: str
    status: str
    affected: int


@router.post(
    "/runs/{run_id}/tasks/{task_id}/pause", response_model=TaskPauseResponse
)
def pause_run_task(run_id: str, task_id: str) -> TaskPauseResponse:
    """M2.5: 暂停单个运行中的子任务（下一迭代边界生效，不消耗 token）。"""
    from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

    dispatcher = _ACTIVE_DISPATCHERS.get(run_id)
    if dispatcher is None:
        raise HTTPException(status_code=404, detail="active run not found")
    if not dispatcher.pause_task(task_id):
        raise HTTPException(
            status_code=409,
            detail=f"task not pausable (unknown/not running): {task_id}",
        )
    return TaskPauseResponse(ok=True, run_id=run_id, task_id=task_id, status="paused")


@router.post(
    "/runs/{run_id}/tasks/{task_id}/resume", response_model=TaskPauseResponse
)
def resume_run_task(run_id: str, task_id: str) -> TaskPauseResponse:
    """M2.5: 恢复已暂停的子任务。"""
    from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

    dispatcher = _ACTIVE_DISPATCHERS.get(run_id)
    if dispatcher is None:
        raise HTTPException(status_code=404, detail="active run not found")
    if not dispatcher.resume_task(task_id):
        raise HTTPException(
            status_code=409,
            detail=f"task not resumable (unknown/not paused): {task_id}",
        )
    return TaskPauseResponse(ok=True, run_id=run_id, task_id=task_id, status="running")


@router.post("/runs/{run_id}/pause", response_model=RunPauseResponse)
def pause_run(run_id: str) -> RunPauseResponse:
    """M2.5: 暂停本 run 全部运行中任务。"""
    from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

    dispatcher = _ACTIVE_DISPATCHERS.get(run_id)
    if dispatcher is None:
        raise HTTPException(status_code=404, detail="active run not found")
    affected = dispatcher.pause_run()
    if affected == 0:
        raise HTTPException(status_code=409, detail="no running tasks to pause")
    return RunPauseResponse(
        ok=True, run_id=run_id, status="paused", affected=affected
    )


@router.post("/runs/{run_id}/resume", response_model=RunPauseResponse)
def resume_run(run_id: str) -> RunPauseResponse:
    """M2.5: 恢复本 run 全部已暂停任务。"""
    from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

    dispatcher = _ACTIVE_DISPATCHERS.get(run_id)
    if dispatcher is None:
        raise HTTPException(status_code=404, detail="active run not found")
    affected = dispatcher.resume_run()
    if affected == 0:
        raise HTTPException(status_code=409, detail="no paused tasks to resume")
    return RunPauseResponse(
        ok=True, run_id=run_id, status="running", affected=affected
    )
