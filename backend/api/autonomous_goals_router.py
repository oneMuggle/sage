"""
闲时自主目标执行系统 — REST API

端点:
- GET    /goals              — 列出目标
- POST   /goals              — 创建目标
- GET    /goals/{goal_id}    — 获取目标详情
- PUT    /goals/{goal_id}    — 更新目标
- DELETE /goals/{goal_id}    — 删除目标
- POST   /goals/{goal_id}/start               — 启动执行
- POST   /goals/{goal_id}/pause               — 暂停执行
- POST   /goals/{goal_id}/cancel              — 取消执行
- GET    /goals/{goal_id}/report              — 获取执行报告
- POST   /goals/{goal_id}/generate-checkpoints — LLM 生成检查点
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from backend.domain.autonomous_goals import (
    Checkpoint,
    ExecutionBudget,
    Goal,
    GoalStatus,
    TimeWindow,
)
from backend.services.checkpoint_manager import CheckpointManager
from backend.services.goal_service import GoalService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/goals", tags=["autonomous-goals"])


# ─── 请求/响应模型 ───────────────────────────────────────────────────


class TimeWindowPayload(BaseModel):
    """时间窗口配置"""

    off_peak_start: str = Field(default="22:00", description="闲时开始 HH:MM")
    off_peak_end: str = Field(default="06:00", description="闲时结束 HH:MM")
    weekends_off_peak: bool = Field(default=True, description="周末全天闲时")
    holidays: List[str] = Field(default_factory=list, description="节假日列表 YYYY-MM-DD")
    min_pricing_tier: str = Field(default="off_peak", description="最低定价等级")
    timezone: str = Field(default="Asia/Shanghai", description="时区")

    class Config:
        extra = "forbid"


class BudgetPayload(BaseModel):
    """执行预算配置"""

    max_rounds: int = Field(default=10, ge=1, le=1000, description="最大轮次")
    max_hours: float = Field(default=8.0, ge=0.1, le=24.0, description="最大执行时间（小时）")
    max_tokens: int = Field(default=1_000_000, ge=1000, description="最大 token 消耗")
    stop_on_failure: bool = Field(default=False, description="失败时立即停止")

    class Config:
        extra = "forbid"


class CreateGoalIn(BaseModel):
    """创建目标请求"""

    name: str = Field(min_length=1, max_length=200, description="目标名称")
    description: str = Field(min_length=1, max_length=5000, description="目标描述")
    session_id: Optional[str] = Field(default=None, description="关联会话 ID")
    time_window: Optional[TimeWindowPayload] = None
    budget: Optional[BudgetPayload] = None
    auto_generate_checkpoints: bool = Field(
        default=False, description="创建时自动生成检查点"
    )

    class Config:
        extra = "forbid"


class UpdateGoalIn(BaseModel):
    """更新目标请求"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, min_length=1, max_length=5000)
    time_window: Optional[TimeWindowPayload] = None
    budget: Optional[BudgetPayload] = None
    status: Optional[str] = Field(
        default=None,
        pattern="^(pending|running|paused|completed|failed|cancelled)$",
    )

    class Config:
        extra = "forbid"


class CheckpointOut(BaseModel):
    """检查点输出"""

    id: str
    type: str
    description: str
    file_path: Optional[str] = None
    verification_command: Optional[str] = None
    expected_pattern: Optional[str] = None
    verified: bool = False

    @classmethod
    def from_checkpoint(cls, cp: Checkpoint) -> CheckpointOut:
        return cls(
            id=cp.id,
            type=cp.type.value,
            description=cp.description,
            file_path=cp.file_path,
            verification_command=cp.verification_command,
            expected_pattern=cp.expected_pattern,
            verified=cp.verified,
        )


class GoalOut(BaseModel):
    """目标详情输出"""

    id: str
    name: str
    description: str
    status: str
    session_id: Optional[str] = None
    time_window: Dict[str, Any]
    budget: Dict[str, Any]
    checkpoints: List[CheckpointOut]
    current_round: int
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    total_tokens_used: int
    completion_percentage: float
    degradation_level: str
    last_error: Optional[str] = None

    @classmethod
    def from_goal(cls, goal: Goal) -> GoalOut:
        return cls(
            id=goal.id,
            name=goal.name,
            description=goal.description,
            status=goal.status.value,
            session_id=goal.session_id,
            time_window=goal.time_window.to_dict(),
            budget=goal.budget.to_dict(),
            checkpoints=[CheckpointOut.from_checkpoint(c) for c in goal.checkpoints],
            current_round=goal.current_round,
            created_at=goal.created_at.isoformat(),
            started_at=goal.started_at.isoformat() if goal.started_at else None,
            completed_at=goal.completed_at.isoformat() if goal.completed_at else None,
            total_tokens_used=goal.total_tokens_used,
            completion_percentage=goal.completion_percentage,
            degradation_level=goal.degradation_level.value,
            last_error=goal.last_error,
        )


class GoalListOut(BaseModel):
    """目标列表输出"""

    items: List[GoalOut]
    total: int
    limit: int
    offset: int


class ExecutionReportOut(BaseModel):
    """执行报告输出"""

    goal_id: str
    goal_name: str
    status: str
    total_rounds: int
    total_tasks: int
    tasks_succeeded: int
    tasks_failed: int
    total_tokens_used: int
    completion_percentage: float
    duration_hours: float
    degradation_level: str
    last_error: Optional[str] = None


class GenerateCheckpointsOut(BaseModel):
    """生成检查点结果"""

    goal_id: str
    generated_count: int
    checkpoints: List[CheckpointOut]


# ─── 服务工厂 ─────────────────────────────────────────────────────────


def _get_goal_service() -> GoalService:
    """获取 GoalService 实例（可被测试替换）"""
    return GoalService()


def _get_checkpoint_manager() -> CheckpointManager:
    """获取 CheckpointManager 实例"""
    return CheckpointManager()


# ─── CRUD 端点 ────────────────────────────────────────────────────────


@router.get("", response_model=GoalListOut)
async def list_goals(
    status_filter: Optional[str] = Query(
        default=None, alias="status", description="按状态过滤"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> GoalListOut:
    """列出所有目标"""
    service = _get_goal_service()

    status_enum = None
    if status_filter:
        try:
            status_enum = GoalStatus(status_filter)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}",
            )

    goals = await service.list_goals(status=status_enum, limit=limit, offset=offset)
    all_goals = await service.list_goals(status=status_enum)

    return GoalListOut(
        items=[GoalOut.from_goal(g) for g in goals],
        total=len(all_goals),
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=GoalOut, status_code=status.HTTP_201_CREATED)
async def create_goal(payload: CreateGoalIn) -> GoalOut:
    """创建新目标"""
    service = _get_goal_service()

    time_window = None
    if payload.time_window:
        tw = payload.time_window
        from backend.domain.autonomous_goals import PricingTier

        time_window = TimeWindow(
            off_peak_start=tw.off_peak_start,
            off_peak_end=tw.off_peak_end,
            weekends_off_peak=tw.weekends_off_peak,
            holidays=tw.holidays,
            min_pricing_tier=PricingTier(tw.min_pricing_tier),
            timezone=tw.timezone,
        )

    budget = None
    if payload.budget:
        b = payload.budget
        budget = ExecutionBudget(
            max_rounds=b.max_rounds,
            max_hours=b.max_hours,
            max_tokens=b.max_tokens,
            stop_on_failure=b.stop_on_failure,
        )

    goal = await service.create_goal(
        name=payload.name,
        description=payload.description,
        time_window=time_window,
        budget=budget,
        session_id=payload.session_id,
    )

    # 自动生成检查点
    if payload.auto_generate_checkpoints:
        try:
            from backend.orchestration.llm_factory import load_llm_config_from_settings

            llm_config = load_llm_config_from_settings()
            checkpoint_mgr = _get_checkpoint_manager()
            checkpoints = await checkpoint_mgr.generate_checkpoints(goal, llm_config=llm_config)
            if checkpoints:
                goal.checkpoints = checkpoints
                await service.update_goal(goal)
                logger.info(
                    f"Auto-generated {len(checkpoints)} checkpoints for goal {goal.id}"
                )
        except Exception as e:
            logger.warning(f"Auto-generate checkpoints failed: {e}")

    return GoalOut.from_goal(goal)


@router.get("/{goal_id}", response_model=GoalOut)
async def get_goal(goal_id: str) -> GoalOut:
    """获取目标详情"""
    service = _get_goal_service()
    goal = await service.get_goal(goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    return GoalOut.from_goal(goal)


@router.put("/{goal_id}", response_model=GoalOut)
async def update_goal(goal_id: str, payload: UpdateGoalIn) -> GoalOut:
    """更新目标"""
    service = _get_goal_service()
    goal = await service.get_goal(goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    # 更新字段
    if payload.name is not None:
        goal.name = payload.name
    if payload.description is not None:
        goal.description = payload.description
    if payload.status is not None:
        goal.status = GoalStatus(payload.status)
    if payload.time_window is not None:
        tw = payload.time_window
        from backend.domain.autonomous_goals import PricingTier

        goal.time_window = TimeWindow(
            off_peak_start=tw.off_peak_start,
            off_peak_end=tw.off_peak_end,
            weekends_off_peak=tw.weekends_off_peak,
            holidays=tw.holidays,
            min_pricing_tier=PricingTier(tw.min_pricing_tier),
            timezone=tw.timezone,
        )
    if payload.budget is not None:
        b = payload.budget
        goal.budget = ExecutionBudget(
            max_rounds=b.max_rounds,
            max_hours=b.max_hours,
            max_tokens=b.max_tokens,
            stop_on_failure=b.stop_on_failure,
        )

    updated = await service.update_goal(goal)
    return GoalOut.from_goal(updated)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_goal(goal_id: str) -> Response:
    """删除目标"""
    service = _get_goal_service()
    goal = await service.get_goal(goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    if goal.status == GoalStatus.RUNNING:
        raise HTTPException(
            status_code=409, detail="Cannot delete a running goal, cancel it first"
        )

    await service.delete_goal(goal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── 执行控制端点 ──────────────────────────────────────────────────────


@router.post("/{goal_id}/start", response_model=GoalOut)
async def start_goal(goal_id: str) -> GoalOut:
    """启动目标执行"""
    service = _get_goal_service()
    try:
        goal = await service.start_execution(goal_id)
        return GoalOut.from_goal(goal)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{goal_id}/pause", response_model=GoalOut)
async def pause_goal(goal_id: str) -> GoalOut:
    """暂停目标执行"""
    service = _get_goal_service()
    try:
        goal = await service.pause_execution(goal_id)
        return GoalOut.from_goal(goal)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{goal_id}/cancel", response_model=GoalOut)
async def cancel_goal(goal_id: str) -> GoalOut:
    """取消目标执行"""
    service = _get_goal_service()
    try:
        goal = await service.cancel_execution(goal_id)
        return GoalOut.from_goal(goal)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 报告与辅助端点 ────────────────────────────────────────────────────


@router.get("/{goal_id}/report", response_model=ExecutionReportOut)
async def get_execution_report(goal_id: str) -> ExecutionReportOut:
    """获取执行报告"""
    service = _get_goal_service()
    try:
        report = await service.get_execution_report(goal_id)
        return ExecutionReportOut(**report)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{goal_id}/generate-checkpoints", response_model=GenerateCheckpointsOut)
async def generate_checkpoints(goal_id: str) -> GenerateCheckpointsOut:
    """使用 LLM 生成检查点"""
    service = _get_goal_service()
    checkpoint_mgr = _get_checkpoint_manager()

    goal = await service.get_goal(goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    try:
        from backend.orchestration.llm_factory import load_llm_config_from_settings

        llm_config = load_llm_config_from_settings()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"LLM not available: {e}",
        )

    checkpoints = await checkpoint_mgr.generate_checkpoints(goal, llm_config=llm_config)

    if checkpoints:
        goal.checkpoints = checkpoints
        await service.update_goal(goal)

    return GenerateCheckpointsOut(
        goal_id=goal_id,
        generated_count=len(checkpoints),
        checkpoints=[CheckpointOut.from_checkpoint(c) for c in checkpoints],
    )
