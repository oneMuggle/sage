"""
闲时自主目标执行系统 — 时间窗口管理器

TimeWindowManager: 判断当前是否在闲时窗口，应用定价规则
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Optional

from backend.domain.autonomous_goals import Goal, PricingTier, TimeWindow

logger = logging.getLogger(__name__)


class TimeWindowManager:
    """时间窗口与定价管理器"""

    def __init__(self, default_timezone: str = "Asia/Shanghai") -> None:
        self.default_timezone = default_timezone

    def is_off_peak(
        self,
        time_window: TimeWindow,
        now: Optional[datetime] = None,
    ) -> bool:
        """
        判断当前是否在闲时窗口

        逻辑：
        1. 检查是否为节假日 → 全天闲时
        2. 检查是否为周末且 weekends_off_peak=True → 全天闲时
        3. 检查当前时间是否在 off_peak_start ~ off_peak_end 之间
        """
        if now is None:
            now = datetime.now()

        # 1. 节假日检查
        date_str = now.strftime("%Y-%m-%d")
        if date_str in time_window.holidays:
            logger.debug(f"Date {date_str} is a holiday, treating as off-peak")
            return True

        # 2. 周末检查 (5=Saturday, 6=Sunday)
        if time_window.weekends_off_peak and now.weekday() >= 5:
            logger.debug(f"Weekend day {now.weekday()}, treating as off-peak")
            return True

        # 3. 时间段检查
        current_time = now.time()
        start_time = self._parse_time(time_window.off_peak_start)
        end_time = self._parse_time(time_window.off_peak_end)

        # 处理跨午夜的情况（如 22:00-06:00）
        if start_time > end_time:
            # 跨午夜：22:00-23:59 或 00:00-06:00
            is_off_peak = current_time >= start_time or current_time <= end_time
        else:
            # 同一天内：如 01:00-05:00
            is_off_peak = start_time <= current_time <= end_time

        logger.debug(
            f"Time check: current={current_time}, "
            f"range=[{start_time}, {end_time}], "
            f"is_off_peak={is_off_peak}"
        )
        return is_off_peak

    def get_pricing_tier(
        self,
        time_window: TimeWindow,
        now: Optional[datetime] = None,
    ) -> PricingTier:
        """
        获取当前时段的定价等级

        定价规则：
        - 闲时窗口内 → OFF_PEAK (0.5x)
        - 接近闲时（06:00-09:00, 18:00-22:00）→ STANDARD (0.7x)
        - 其他时间 → PEAK (1.0x)
        """
        if now is None:
            now = datetime.now()

        # 闲时窗口内
        if self.is_off_peak(time_window, now):
            return PricingTier.OFF_PEAK

        # 判断是否为"平峰"时段
        current_hour = now.hour
        if 6 <= current_hour < 9 or 18 <= current_hour < 22:
            return PricingTier.STANDARD

        # 其他时间为高峰
        return PricingTier.PEAK

    def should_execute_now(
        self,
        goal: Goal,
        now: Optional[datetime] = None,
    ) -> bool:
        """
        判断目标是否应该在当前时刻执行

        逻辑：
        1. 检查是否在目标配置的时间窗口内
        2. 检查定价等级是否符合要求
        3. 检查是否有足够的预算
        """
        if now is None:
            now = datetime.now()

        # 1. 时间窗口检查
        if not self.is_off_peak(goal.time_window, now):
            logger.info(f"Goal {goal.id}: not in off-peak window")
            return False

        # 2. 定价等级检查
        current_tier = self.get_pricing_tier(goal.time_window, now)
        tier_priority = {
            PricingTier.OFF_PEAK: 0,
            PricingTier.STANDARD: 1,
            PricingTier.PEAK: 2,
            PricingTier.DYNAMIC: 3,
        }

        if tier_priority[current_tier] > tier_priority[goal.time_window.min_pricing_tier]:
            logger.info(
                f"Goal {goal.id}: current tier {current_tier.value} "
                f"exceeds minimum {goal.time_window.min_pricing_tier.value}"
            )
            return False

        # 3. 预算检查
        if goal.current_round >= goal.budget.max_rounds:
            logger.info(f"Goal {goal.id}: max rounds reached ({goal.budget.max_rounds})")
            return False

        if goal.started_at:
            elapsed_hours = (now - goal.started_at).total_seconds() / 3600
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

        logger.info(f"Goal {goal.id}: should execute now")
        return True

    def get_next_execution_time(
        self,
        goal: Goal,
        now: Optional[datetime] = None,
    ) -> datetime:
        """
        计算下次执行时间

        如果当前在闲时，返回现在。
        如果当前不在闲时，返回下一个闲时开始时间。
        """
        if now is None:
            now = datetime.now()

        if self.is_off_peak(goal.time_window, now):
            return now

        # 计算下一个闲时开始时间
        start_time = self._parse_time(goal.time_window.off_peak_start)

        # 如果今天还没到闲时开始时间
        if now.time() < start_time:
            next_time = now.replace(
                hour=start_time.hour,
                minute=start_time.minute,
                second=0,
                microsecond=0,
            )
        else:
            # 否则是明天的闲时开始时间
            next_time = now.replace(
                hour=start_time.hour,
                minute=start_time.minute,
                second=0,
                microsecond=0,
            ) + timedelta(days=1)

        # 检查是否为节假日或周末（如果是且 weekends_off_peak=True，则全天可执行）
        while not self.is_off_peak(goal.time_window, next_time):
            next_time += timedelta(days=1)
            # 重置时间为闲时开始时间
            next_time = next_time.replace(
                hour=start_time.hour,
                minute=start_time.minute,
                second=0,
                microsecond=0,
            )

        logger.info(f"Next execution time for goal {goal.id}: {next_time}")
        return next_time

    def _parse_time(self, time_str: str) -> time:
        """解析时间字符串（HH:MM 格式）"""
        parts = time_str.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid time format: {time_str}, expected HH:MM")
        return time(int(parts[0]), int(parts[1]))
