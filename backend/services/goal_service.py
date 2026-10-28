"""
闲时自主目标执行系统 — 目标服务

GoalService: 目标生命周期管理、多轮执行、完成度审查、智能降级
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.data.goal_repository import GoalRepository
from backend.domain.autonomous_goals import (
    DegradationLevel,
    ExecutionBudget,
    ExecutionRound,
    Goal,
    GoalStatus,
    TimeWindow,
)
from backend.domain.execution_conditions import (
    ExecutionCondition,
    TriggerMode,
)
from backend.services.checkpoint_manager import CheckpointManager, CheckpointReport
from backend.services.time_window_manager import TimeWindowManager

logger = logging.getLogger(__name__)


class GoalService:
    """目标生命周期管理器"""

    def __init__(
        self,
        goal_repository: Optional[GoalRepository] = None,
        checkpoint_manager: Optional[CheckpointManager] = None,
        time_window_manager: Optional[TimeWindowManager] = None,
    ) -> None:
        self.goal_repo = goal_repository or GoalRepository()
        self.checkpoint_mgr = checkpoint_manager or CheckpointManager()
        self.time_window_mgr = time_window_manager or TimeWindowManager()

    # ─── CRUD ───────────────────────────────────────────────────────

    async def create_goal(
        self,
        name: str,
        description: str,
        time_window: Optional[TimeWindow] = None,
        budget: Optional[ExecutionBudget] = None,
        session_id: Optional[str] = None,
        trigger_mode: TriggerMode = TriggerMode.IMMEDIATE,
        execution_conditions: Optional[List[ExecutionCondition]] = None,
    ) -> Goal:
        """创建新目标

        Args:
            name: 目标名称
            description: 目标描述
            time_window: 时间窗口配置
            budget: 执行预算
            session_id: 关联会话 ID
            trigger_mode: 触发模式（立即 / 条件）
            execution_conditions: 执行条件列表（CONDITIONAL 模式使用）
        """
        goal = Goal(
            id=f"goal_{uuid.uuid4().hex[:12]}",
            name=name,
            description=description,
            status=GoalStatus.PENDING,
            session_id=session_id,
            time_window=time_window or TimeWindow(),
            budget=budget or ExecutionBudget(),
            trigger_mode=trigger_mode,
            execution_conditions=execution_conditions or [],
        )

        created = self.goal_repo.create(goal)
        logger.info(f"Created goal: {created.id} ({created.name})")
        return created

    async def get_goal(self, goal_id: str) -> Optional[Goal]:
        """获取目标详情"""
        return self.goal_repo.get(goal_id)

    async def list_goals(
        self,
        status: Optional[GoalStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Goal]:
        """获取目标列表"""
        return self.goal_repo.list_all(status=status, limit=limit, offset=offset)

    async def update_goal(self, goal: Goal) -> Goal:
        """更新目标"""
        return self.goal_repo.update(goal)

    async def delete_goal(self, goal_id: str) -> bool:
        """删除目标"""
        return self.goal_repo.delete(goal_id)

    # ─── 执行控制 ──────────────────────────────────────────────────

    async def start_execution(self, goal_id: str) -> Goal:
        """
        启动目标执行

        1. 检查目标状态（必须 PENDING 或 PAUSED）
        2. 检查时间窗口（如果不在闲时，等待或立即执行）
        3. 启动执行循环
        """
        goal = self.goal_repo.get(goal_id)
        if not goal:
            raise ValueError(f"Goal not found: {goal_id}")

        if goal.status not in (GoalStatus.PENDING, GoalStatus.PAUSED):
            raise ValueError(
                f"Cannot start goal in status {goal.status.value}. "
                f"Expected PENDING or PAUSED."
            )

        # 更新状态
        goal.status = GoalStatus.RUNNING
        goal.started_at = datetime.utcnow()  # noqa: DTZ003
        self.goal_repo.update(goal)

        # 启动执行循环（异步）
        asyncio.create_task(self._execute_loop(goal_id))

        logger.info(f"Started execution for goal: {goal_id}")
        return goal

    async def pause_execution(self, goal_id: str) -> Goal:
        """暂停目标执行"""
        goal = self.goal_repo.get(goal_id)
        if not goal:
            raise ValueError(f"Goal not found: {goal_id}")

        if goal.status != GoalStatus.RUNNING:
            raise ValueError(f"Cannot pause goal in status {goal.status.value}")

        goal.status = GoalStatus.PAUSED
        self.goal_repo.update(goal)

        logger.info(f"Paused execution for goal: {goal_id}")
        return goal

    async def cancel_execution(self, goal_id: str) -> Goal:
        """取消目标执行"""
        goal = self.goal_repo.get(goal_id)
        if not goal:
            raise ValueError(f"Goal not found: {goal_id}")

        goal.status = GoalStatus.CANCELLED
        goal.completed_at = datetime.utcnow()  # noqa: DTZ003
        self.goal_repo.update(goal)

        logger.info(f"Cancelled execution for goal: {goal_id}")
        return goal

    # ─── 执行循环 ──────────────────────────────────────────────────

    async def _execute_loop(self, goal_id: str) -> None:
        """
        主执行循环

        while not terminated:
          1. 时间窗口检查
          2. 执行一轮
          3. 检查点验证
          4. 完成度审查
          5. 决策：继续/停止/降级
        """
        goal = self.goal_repo.get(goal_id)
        if not goal:
            logger.error(f"Goal {goal_id} not found in execute_loop")
            return

        try:
            while await self._should_continue(goal):
                # 1. 时间窗口检查
                if not self.time_window_mgr.should_execute_now(goal):
                    next_time = self.time_window_mgr.get_next_execution_time(goal)
                    wait_seconds = (next_time - datetime.utcnow()).total_seconds()  # noqa: DTZ003

                    logger.info(
                        f"Goal {goal_id}: outside time window, "
                        f"waiting {wait_seconds:.0f}s until {next_time}"
                    )
                    goal.status = GoalStatus.PAUSED
                    self.goal_repo.update(goal)

                    # 等待到下次执行时间（最多等 1 小时，避免长睡眠）
                    await asyncio.sleep(min(wait_seconds, 3600))

                    # 重新加载目标（可能被用户修改）
                    goal = self.goal_repo.get(goal_id)
                    if not goal or goal.status == GoalStatus.CANCELLED:
                        break

                    goal.status = GoalStatus.RUNNING
                    self.goal_repo.update(goal)
                    continue

                # 2. 执行一轮
                round_result = await self.execute_round(goal_id)

                # 重新加载目标
                goal = self.goal_repo.get(goal_id)
                if not goal:
                    break

                goal.rounds.append(round_result)
                goal.current_round += 1
                goal.total_tokens_used += round_result.tokens_used

                # 3. 检查点验证
                checkpoint_report = await self.checkpoint_mgr.verify_all(goal.checkpoints)
                goal.completion_percentage = checkpoint_report.progress_percentage

                # 4. 完成度审查（Phase 3: LLM 审查）
                is_complete = await self._review_completion(goal, checkpoint_report)

                if is_complete:
                    goal.status = GoalStatus.COMPLETED
                    goal.completed_at = datetime.utcnow()  # noqa: DTZ003
                    self.goal_repo.update(goal)
                    logger.info(f"Goal {goal_id} completed at round {goal.current_round}")
                    break

                # 5. 保存进度
                self.goal_repo.update(goal)

                # 6. 短暂间隔（避免过快循环）
                await asyncio.sleep(5)

        except Exception as e:
            logger.error(f"Goal {goal_id} execution failed: {e}")
            goal = self.goal_repo.get(goal_id)
            if goal:
                goal.status = GoalStatus.FAILED
                goal.last_error = str(e)
                goal.completed_at = datetime.utcnow()  # noqa: DTZ003
                await self._apply_degradation(goal, e)
                self.goal_repo.update(goal)

    async def _should_continue(self, goal: Goal) -> bool:
        """判断是否应该继续执行"""
        # 状态检查
        if goal.status in (GoalStatus.COMPLETED, GoalStatus.FAILED, GoalStatus.CANCELLED):
            return False

        # 预算检查
        if goal.current_round >= goal.budget.max_rounds:
            logger.info(f"Goal {goal.id}: max rounds reached ({goal.budget.max_rounds})")
            return False

        if goal.started_at:
            elapsed_hours = (datetime.utcnow() - goal.started_at).total_seconds() / 3600  # noqa: DTZ003
            if elapsed_hours >= goal.budget.max_hours:
                logger.info(
                    f"Goal {goal.id}: max hours reached "
                    f"({elapsed_hours:.1f} >= {goal.budget.max_hours})"
                )
                return False

        if goal.total_tokens_used >= goal.budget.max_tokens:
            logger.info(
                f"Goal {goal.id}: max tokens reached "
                f"({goal.total_tokens_used} >= {goal.budget.max_tokens})"
            )
            return False

        return True

    async def execute_round(self, goal_id: str) -> ExecutionRound:
        """
        执行一轮迭代

        1. 使用 Planner 分解目标为任务
        2. 执行任务（复用编排系统）
        3. 记录执行结果
        """
        from pathlib import Path

        from backend.data.database import get_database
        from backend.orchestration.llm_factory import load_llm_config_from_settings
        from backend.orchestration.models import RecoveryPolicy, TaskPacket
        from backend.orchestration.planner import Planner
        from backend.orchestration.subagent_runner import SubagentRunner
        from backend.orchestration.task_registry import TaskRegistry
        from backend.orchestration.team_registry import TeamRegistry

        goal = self.goal_repo.get(goal_id)
        if not goal:
            raise ValueError(f"Goal not found: {goal_id}")

        round_number = goal.current_round + 1
        started_at = datetime.utcnow()  # noqa: DTZ003

        logger.info(f"Goal {goal_id}: starting round {round_number}")

        tasks_executed = 0
        tasks_succeeded = 0
        tasks_failed = 0
        tokens_used = 0
        error_message = None

        try:
            # 1. 初始化编排系统注册表
            task_registry = TaskRegistry()
            team_registry = TeamRegistry()

            # 2. 使用 Planner 分解目标
            planner = Planner(
                task_registry=task_registry,
                team_registry=team_registry,
                auto_configure=True,
            )

            # 构建上下文（包含前一轮的反馈信息）
            context = {
                "source": "autonomous_goal",
                "goal_id": goal.id,
                "round_number": round_number,
                "previous_rounds": len(goal.rounds),
                "completion_percentage": goal.completion_percentage,
            }

            plan = await planner.decompose_request(goal.description, context=context)

            logger.info(
                f"Goal {goal_id} round {round_number}: "
                f"decomposed into {len(plan.tasks)} tasks"
            )

            # 3. 执行任务（复用编排系统的 LaneExecutor 模式）
            llm_config = load_llm_config_from_settings()
            data_dir = Path(get_database().db_path).parent
            scratch_root = data_dir / "scratch" / f"goal-{goal.id}"
            scratch_root.mkdir(parents=True, exist_ok=True)

            # 为每个 task 创建 lane 并执行
            execution_results = []

            for task in plan.tasks:
                tasks_executed += 1

                # 设置 task packet
                task_dir = scratch_root / task.task_id
                task_dir.mkdir(parents=True, exist_ok=True)
                task.packet = TaskPacket(
                    objective=task.description,
                    recovery_policy=RecoveryPolicy(on_failure="retry", max_retries=2),
                )
                task.parameters["goal"] = task.description
                task.parameters["scratch_dir"] = str(task_dir)
                task_registry.repo.update(task)

                # 创建 SubagentRunner 并执行
                interrupt_event = asyncio.Event()
                agent_runner = SubagentRunner(
                    llm_config,
                    interrupt_event=interrupt_event,
                    session_id=goal.session_id,
                )

                try:
                    task_registry.mark_running(task.task_id)
                    result = await agent_runner(task, agent_id="default")

                    if result.get("status") == "succeeded":
                        tasks_succeeded += 1
                        execution_results.append({
                            "task_id": task.task_id,
                            "status": "succeeded",
                            "output": result.get("output", "")[:500],
                        })
                    else:
                        tasks_failed += 1
                        execution_results.append({
                            "task_id": task.task_id,
                            "status": "failed",
                            "error": result.get("error", "unknown"),
                        })

                except Exception as task_error:
                    tasks_failed += 1
                    task_registry.mark_failed(task.task_id, error=str(task_error))
                    execution_results.append({
                        "task_id": task.task_id,
                        "status": "failed",
                        "error": str(task_error),
                    })

            # 估算 token 消耗（简单启发式：每任务约 1000 tokens）
            tokens_used = tasks_executed * 1000

            checkpoints_verified = sum(1 for c in goal.checkpoints if c.verified)

            logger.info(
                f"Goal {goal_id} round {round_number} complete: "
                f"{tasks_succeeded}/{tasks_executed} tasks succeeded"
            )

            return ExecutionRound(
                round_number=round_number,
                started_at=started_at,
                completed_at=datetime.utcnow(),  # noqa: DTZ003
                tasks_executed=tasks_executed,
                tasks_succeeded=tasks_succeeded,
                tasks_failed=tasks_failed,
                tokens_used=tokens_used,
                checkpoints_verified=checkpoints_verified,
                degradation_level=goal.degradation_level,
                error_message=error_message,
                llm_review=plan.reasoning[:500] if plan.reasoning else None,
            )

        except Exception as e:
            logger.error(f"Goal {goal_id} round {round_number} failed: {e}")
            return ExecutionRound(
                round_number=round_number,
                started_at=started_at,
                completed_at=datetime.utcnow(),  # noqa: DTZ003
                tasks_executed=tasks_executed,
                tasks_succeeded=tasks_succeeded,
                tasks_failed=tasks_failed + 1,
                tokens_used=tokens_used,
                degradation_level=goal.degradation_level,
                error_message=str(e),
            )

    async def _review_completion(
        self,
        goal: Goal,
        checkpoint_report: CheckpointReport,
    ) -> bool:
        """
        审查完成度

        基础逻辑：
        - 检查点全部通过 → 完成
        - 完成度 >= 95% → 完成
        - 否则 → 未完成

        Phase 3 增强：如果有 LLM，可以用 LLM 做最终判断
        """
        # 基础版：检查点全部通过即完成
        if checkpoint_report.total > 0 and checkpoint_report.passed == checkpoint_report.total:
            logger.info(f"Goal {goal.id}: all checkpoints passed, marking as complete")
            return True

        # 完成度超过 95% 也视为完成（允许少量检查点失败）
        if checkpoint_report.progress_percentage >= 95.0:
            logger.info(
                f"Goal {goal.id}: completion {checkpoint_report.progress_percentage:.1f}% >= 95%, "
                "marking as complete"
            )
            return True

        return False

    async def review_completion_with_llm(
        self,
        goal: Goal,
        checkpoint_report: CheckpointReport,
        llm_config: Optional[object] = None,
    ) -> dict:
        """
        使用 LLM 审查目标完成度

        返回:
            {
                "is_complete": bool,
                "confidence": float (0-1),
                "reasoning": str,
                "suggestions": List[str],
            }
        """
        if llm_config is None:
            # 回退到基础版
            is_complete = await self._review_completion(goal, checkpoint_report)
            return {
                "is_complete": is_complete,
                "confidence": checkpoint_report.progress_percentage / 100.0,
                "reasoning": f"基础判断：{checkpoint_report.passed}/{checkpoint_report.total} 检查点通过",
                "suggestions": [],
            }

        # 构建审查 prompt
        failed_checkpoints = [
            r for r in checkpoint_report.results if not r.passed
        ]

        prompt = f"""## 目标审查

### 目标信息
- 名称: {goal.name}
- 描述: {goal.description}
- 当前轮次: {goal.current_round}
- 完成度: {checkpoint_report.progress_percentage:.1f}%

### 检查点验证结果
- 总计: {checkpoint_report.total}
- 通过: {checkpoint_report.passed}
- 失败: {checkpoint_report.failed}

### 失败检查点详情
"""
        for r in failed_checkpoints[:10]:  # 最多列出 10 个
            prompt += f"- {r.checkpoint_id}: {r.actual_value} (期望: {r.expected_value})\n"
            if r.error_message:
                prompt += f"  错误: {r.error_message}\n"

        prompt += """
### 历史轮次摘要
"""
        for r in goal.rounds[-3:]:  # 最近 3 轮
            prompt += (
                f"- 轮次 {r.round_number}: {r.tasks_succeeded}/{r.tasks_executed} 任务成功"
            )
            if r.error_message:
                prompt += f" (错误: {r.error_message})"
            prompt += "\n"

        prompt += """
请判断目标是否已完成，并给出建议。返回 JSON 格式:
```json
{
  "is_complete": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "判断理由",
  "suggestions": ["建议1", "建议2"]
}
```
"""

        try:
            llm_client = llm_config.create_client()
            response = await llm_client.chat_completion(
                model=llm_config.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个任务完成度审查专家。根据检查点验证结果和历史执行情况判断目标是否已完成。只返回 JSON。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=1000,
            )

            content = response.choices[0].message.content
            if not content:
                return {
                    "is_complete": await self._review_completion(goal, checkpoint_report),
                    "confidence": 0.5,
                    "reasoning": "LLM 返回空内容，回退到基础判断",
                    "suggestions": [],
                }

            # 解析 JSON
            import json
            import re

            json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", content, re.DOTALL)
            if json_match:
                content = json_match.group(1)

            array_match = re.search(r"\{.*\}", content, re.DOTALL)
            if array_match:
                content = array_match.group(0)

            result = json.loads(content)

            return {
                "is_complete": result.get("is_complete", False),
                "confidence": result.get("confidence", 0.5),
                "reasoning": result.get("reasoning", ""),
                "suggestions": result.get("suggestions", []),
            }

        except Exception as e:
            logger.error(f"review_completion_with_llm failed: {e}")
            is_complete = await self._review_completion(goal, checkpoint_report)
            return {
                "is_complete": is_complete,
                "confidence": checkpoint_report.progress_percentage / 100.0,
                "reasoning": f"LLM 审查失败 ({e})，回退到基础判断",
                "suggestions": [],
            }

    async def _apply_degradation(self, goal: Goal, error: Exception) -> None:
        """
        智能降级处理

        策略：
        1. 第一次失败 -> 降级模型（Phase 3 实现）
        2. 第二次失败 -> 简化任务（Phase 3 实现）
        3. 第三次失败 -> 停止
        """
        # 统计连续失败次数
        consecutive_failures = 0
        for round_result in reversed(goal.rounds):
            if round_result.error_message:
                consecutive_failures += 1
            else:
                break

        logger.info(
            f"Goal {goal.id}: {consecutive_failures} consecutive failures, "
            "applying degradation"
        )

        if consecutive_failures == 1:
            # 第一次失败：降级模型（预留）
            goal.degradation_level = DegradationLevel.MODEL_DOWNGRADE
            logger.info("Degradation: model downgrade")

        elif consecutive_failures == 2:
            # 第二次失败：简化任务（预留）
            goal.degradation_level = DegradationLevel.TASK_SIMPLIFY
            logger.info("Degradation: task simplify")

        else:
            # 第三次失败：停止
            goal.degradation_level = DegradationLevel.STOPPED
            goal.status = GoalStatus.FAILED
            goal.completed_at = datetime.utcnow()  # noqa: DTZ003
            logger.warning(
                f"Goal {goal.id}: {consecutive_failures} consecutive failures, stopping"
            )

    # ─── 辅助方法 ──────────────────────────────────────────────────

    async def get_execution_report(self, goal_id: str) -> Dict[str, Any]:
        """生成执行报告"""
        goal = self.goal_repo.get(goal_id)
        if not goal:
            raise ValueError(f"Goal not found: {goal_id}")

        total_rounds = len(goal.rounds)
        total_tasks = sum(r.tasks_executed for r in goal.rounds)
        total_succeeded = sum(r.tasks_succeeded for r in goal.rounds)
        total_failed = sum(r.tasks_failed for r in goal.rounds)
        total_tokens = goal.total_tokens_used

        duration_hours = 0.0
        if goal.started_at and goal.completed_at:
            duration_hours = (goal.completed_at - goal.started_at).total_seconds() / 3600

        return {
            "goal_id": goal.id,
            "goal_name": goal.name,
            "status": goal.status.value,
            "total_rounds": total_rounds,
            "total_tasks": total_tasks,
            "tasks_succeeded": total_succeeded,
            "tasks_failed": total_failed,
            "total_tokens_used": total_tokens,
            "completion_percentage": goal.completion_percentage,
            "duration_hours": duration_hours,
            "degradation_level": goal.degradation_level.value,
            "last_error": goal.last_error,
            "rounds": [r.to_dict() for r in goal.rounds],
        }
