"""
闲时延迟执行系统 — 条件评估引擎

ConditionEvaluator 评估 ExecutionCondition 是否满足。
支持多条件 AND 语义：所有条件都满足才返回 True。

条件类型处理：
- IDLE: 查询 IdleDetector 空闲时长
- TIME_WINDOW: 委托 TimeWindowManager
- RESOURCE: 系统资源检查（当前乐观默认，无 psutil）
- NO_ACTIVE_TASKS: 检查是否有 RUNNING 状态的 Goal
- MANUAL: 永不自动满足（需用户手动触发）
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from backend.domain.execution_conditions import (
    ConditionType,
    ExecutionCondition,
)

if TYPE_CHECKING:
    from backend.services.goal_service import GoalService
    from backend.services.idle_detector import IdleDetector
    from backend.services.time_window_manager import TimeWindowManager

logger = logging.getLogger(__name__)


class ConditionEvaluator:
    """条件评估引擎

    评估 ExecutionCondition 是否满足，支持多条件 AND 语义。
    """

    def __init__(
        self,
        idle_detector: IdleDetector,
        time_window_manager: TimeWindowManager,
        goal_service: Optional[GoalService] = None,
    ) -> None:
        self._idle_detector = idle_detector
        self._time_window_manager = time_window_manager
        self._goal_service = goal_service

    def evaluate(
        self,
        condition: ExecutionCondition,
        now: Optional[datetime] = None,
    ) -> bool:
        """评估单个条件是否满足

        Args:
            condition: 要评估的执行条件
            now: 当前时间（测试用）

        Returns:
            True = 条件满足，False = 条件不满足
        """
        ct = condition.type
        params = condition.params

        if ct == ConditionType.IDLE:
            return self._evaluate_idle(params)
        elif ct == ConditionType.TIME_WINDOW:
            return self._evaluate_time_window(params, now)
        elif ct == ConditionType.RESOURCE:
            return self._evaluate_resource(params)
        elif ct == ConditionType.NO_ACTIVE_TASKS:
            return self._evaluate_no_active_tasks()
        elif ct == ConditionType.MANUAL:
            return False  # 手动触发永不自动满足
        else:
            logger.warning(f"Unknown condition type: {ct}, treating as unsatisfied")
            return False

    def evaluate_all(
        self,
        conditions: List[ExecutionCondition],
        now: Optional[datetime] = None,
    ) -> bool:
        """评估所有条件（AND 语义）

        空条件列表 → True（无约束 = 可执行）

        Args:
            conditions: 条件列表
            now: 当前时间（测试用）

        Returns:
            True = 所有条件都满足
        """
        if not conditions:
            return True

        for condition in conditions:
            if not self.evaluate(condition, now):
                logger.debug(
                    f"Condition {condition.type.value} not satisfied, "
                    f"blocking execution"
                )
                return False

        logger.debug(f"All {len(conditions)} conditions satisfied")
        return True

    def evaluate_with_details(
        self,
        conditions: List[ExecutionCondition],
        now: Optional[datetime] = None,
    ) -> dict:
        """评估所有条件并返回详细信息（用于 API 响应）

        Returns:
            {
                "all_satisfied": bool,
                "conditions": [
                    {"type": "idle", "satisfied": True, "detail": "..."},
                    ...
                ]
            }
        """
        if not conditions:
            return {"all_satisfied": True, "conditions": []}

        results = []
        all_ok = True

        for condition in conditions:
            satisfied = self.evaluate(condition, now)
            if not satisfied:
                all_ok = False

            results.append({
                "type": condition.type.value,
                "params": condition.params,
                "satisfied": satisfied,
                "detail": self._get_condition_detail(condition),
            })

        return {"all_satisfied": all_ok, "conditions": results}

    # ─── 私有评估方法 ──────────────────────────────────────────────

    def _evaluate_idle(self, params: dict) -> bool:
        """评估空闲条件"""
        min_idle_minutes = params.get("min_idle_minutes", 15)
        current_idle = self._idle_detector.get_idle_minutes()
        return current_idle >= min_idle_minutes

    def _evaluate_time_window(
        self,
        params: dict,
        now: Optional[datetime] = None,
    ) -> bool:
        """评估时间窗口条件

        复用 TimeWindowManager.is_off_peak()。
        构造一个临时 TimeWindow 对象。
        """
        from backend.domain.autonomous_goals import TimeWindow

        start = params.get("start", "22:00")
        end = params.get("end", "06:00")

        tw = TimeWindow(
            off_peak_start=start,
            off_peak_end=end,
            weekends_off_peak=params.get("weekends_off_peak", True),
            holidays=params.get("holidays", []),
        )

        return self._time_window_manager.is_off_peak(tw, now)

    def _evaluate_resource(self, params: dict) -> bool:
        """评估资源条件

        当前无 psutil 依赖，使用乐观默认（返回 True）。
        未来可接入 psutil.cpu_percent() / psutil.virtual_memory()。
        """
        # 乐观默认：假设资源充足。接入 psutil 后改为读取
        # cpu_percent() / virtual_memory().percent 并与 params 阈值比较。
        return True

    def _evaluate_no_active_tasks(self) -> bool:
        """评估无活动任务条件

        检查是否有 RUNNING 状态的 Goal。
        如果 goal_service 未注入，乐观返回 True。
        """
        if self._goal_service is None:
            return True  # 未注入时乐观默认

        try:
            running_goals = [
                g for g in self._goal_service.list_goals()
                if g.status.value == "running"
            ]
            return len(running_goals) == 0
        except Exception:
            logger.warning("Failed to check running goals, assuming none")
            return True

    def _get_condition_detail(self, condition: ExecutionCondition) -> str:
        """获取条件当前的详细状态描述"""
        ct = condition.type

        if ct == ConditionType.IDLE:
            min_idle = condition.params.get("min_idle_minutes", 15)
            current = self._idle_detector.get_idle_minutes()
            return f"空闲 {current:.1f} 分钟 / 需要 {min_idle} 分钟"

        elif ct == ConditionType.TIME_WINDOW:
            start = condition.params.get("start", "22:00")
            end = condition.params.get("end", "06:00")
            return f"时间窗口 {start}-{end}"

        elif ct == ConditionType.RESOURCE:
            return "资源检查（当前乐观默认）"

        elif ct == ConditionType.NO_ACTIVE_TASKS:
            return self._describe_active_tasks()

        elif ct == ConditionType.MANUAL:
            return "需用户手动触发"

        return "未知条件"

    def _describe_active_tasks(self) -> str:
        """描述当前运行中目标数量"""
        if self._goal_service is None:
            return "未配置 goal_service（乐观默认）"
        try:
            running = len([
                g for g in self._goal_service.list_goals()
                if g.status.value == "running"
            ])
            return f"运行中目标数: {running}"
        except Exception:
            return "检查失败（乐观默认）"
