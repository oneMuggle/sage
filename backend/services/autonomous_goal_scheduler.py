"""
闲时自主目标执行系统 — 调度器集成

AutonomousGoalScheduler:
- 定期扫描 pending 目标
- 检查时间窗口
- 自动启动符合条件的目标
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from backend.domain.autonomous_goals import GoalStatus
from backend.services.goal_service import GoalService
from backend.services.time_window_manager import TimeWindowManager

logger = logging.getLogger(__name__)


class AutonomousGoalScheduler:
    """自主目标调度器

    职责：
    1. 定期扫描 pending 状态的目标
    2. 检查当前是否在目标配置的时间窗口内
    3. 如果条件满足，自动启动目标执行
    """

    def __init__(
        self,
        goal_service: Optional[GoalService] = None,
        time_window_manager: Optional[TimeWindowManager] = None,
    ) -> None:
        self.goal_service = goal_service or GoalService()
        self.time_window_mgr = time_window_manager or TimeWindowManager()

    async def check_and_start_pending_goals(self) -> int:
        """
        检查并启动所有符合条件的 pending 目标

        返回：本次启动的目标数量
        """
        # 获取所有 pending 状态的目标
        pending_goals = await self.goal_service.list_goals(
            status=GoalStatus.PENDING, limit=100
        )

        if not pending_goals:
            logger.debug("No pending autonomous goals found")
            return 0

        started_count = 0

        for goal in pending_goals:
            try:
                # 检查是否应该在当前时间执行
                if self.time_window_mgr.should_execute_now(goal):
                    logger.info(
                        f"Auto-starting goal {goal.id} ({goal.name}): "
                        "within time window"
                    )
                    await self.goal_service.start_execution(goal.id)
                    started_count += 1
                else:
                    logger.debug(
                        f"Goal {goal.id} ({goal.name}): not in time window, skipping"
                    )
            except Exception as e:
                logger.error(f"Failed to auto-start goal {goal.id}: {e}")
                continue

        if started_count > 0:
            logger.info(f"Auto-started {started_count} autonomous goal(s)")

        return started_count

    def register_to_scheduler(self, scheduler_service, cron_expr: str = "*/5 * * * *") -> None:
        """
        注册到 APScheduler

        Args:
            scheduler_service: SchedulerService 实例
            cron_expr: 检查频率，默认每 5 分钟
        """
        async def _check_goals():
            """定期任务回调"""
            try:
                await self.check_and_start_pending_goals()
            except Exception as e:
                logger.error(f"Autonomous goal scheduler check failed: {e}")

        # 使用 register_system_task 注册
        scheduler_service.register_system_task(
            name="autonomous_goals_checker",
            fn=lambda: asyncio.run(_check_goals()),
            cron_expr=cron_expr,
        )
        logger.info(f"Autonomous goal scheduler registered (cron: {cron_expr})")


# ─── 全局实例（可选） ───────────────────────────────────────────────────

_autonomous_scheduler: Optional[AutonomousGoalScheduler] = None


def get_autonomous_scheduler() -> AutonomousGoalScheduler:
    """获取全局调度器实例"""
    global _autonomous_scheduler
    if _autonomous_scheduler is None:
        _autonomous_scheduler = AutonomousGoalScheduler()
    return _autonomous_scheduler
