"""
闲时延迟执行系统 — 用户空闲检测器

通过 Electron IPC 接收前端上报的用户活动事件，
维护最后活跃时间戳，提供空闲等级判断。

三级空闲：
- none:  用户活跃（< 5 分钟无操作）
- short: 短暂空闲（5-30 分钟）→ 可执行轻任务
- deep:  深度空闲（> 30 分钟）→ 可执行重任务
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from backend.domain.execution_conditions import IdleLevel

logger = logging.getLogger(__name__)

# 空闲阈值（秒）
_SHORT_IDLE_SECONDS = 300     # 5 分钟
_DEEP_IDLE_SECONDS = 1800     # 30 分钟


class IdleDetector:
    """用户空闲检测器

    线程安全：所有操作都在单线程 asyncio 事件循环中执行，
    无需加锁。last_activity_ts 是单调递增的时间戳。
    """

    def __init__(
        self,
        short_idle_seconds: int = _SHORT_IDLE_SECONDS,
        deep_idle_seconds: int = _DEEP_IDLE_SECONDS,
    ) -> None:
        self._short_idle_seconds = short_idle_seconds
        self._deep_idle_seconds = deep_idle_seconds
        # 初始化为当前时间（启动时视为"刚活跃"）
        self._last_activity_ts: float = time.monotonic()
        self._last_activity_epoch: float = time.time()

    def report_activity(self, epoch_ts: Optional[float] = None) -> None:
        """报告用户活动

        Args:
            epoch_ts: 活动的 epoch 时间戳。
                      None 则使用当前时间。
        """
        ts = epoch_ts if epoch_ts is not None else time.time()
        self._last_activity_epoch = ts
        self._last_activity_ts = time.monotonic()
        logger.debug(f"User activity reported at epoch={ts:.0f}")

    def get_idle_seconds(self) -> float:
        """获取当前空闲时长（秒）"""
        return time.monotonic() - self._last_activity_ts

    def get_idle_minutes(self) -> float:
        """获取当前空闲时长（分钟）"""
        return self.get_idle_seconds() / 60.0

    def get_idle_level(self) -> IdleLevel:
        """判断当前空闲等级"""
        idle = self.get_idle_seconds()

        if idle >= self._deep_idle_seconds:
            return IdleLevel.DEEP
        elif idle >= self._short_idle_seconds:
            return IdleLevel.SHORT
        else:
            return IdleLevel.NONE

    def is_idle_at_least(self, level: IdleLevel) -> bool:
        """检查是否至少达到指定空闲等级"""
        current = self.get_idle_level()
        order = {IdleLevel.NONE: 0, IdleLevel.SHORT: 1, IdleLevel.DEEP: 2}
        return order[current] >= order[level]

    def get_last_activity_epoch(self) -> float:
        """获取最后活跃时间的 epoch 时间戳"""
        return self._last_activity_epoch

    def get_status(self) -> dict:
        """获取空闲状态摘要（用于 API 响应）"""
        return {
            "idle_level": self.get_idle_level().value,
            "idle_seconds": round(self.get_idle_seconds(), 1),
            "idle_minutes": round(self.get_idle_minutes(), 1),
            "last_activity_epoch": round(self._last_activity_epoch, 0),
            "short_idle_threshold": self._short_idle_seconds,
            "deep_idle_threshold": self._deep_idle_seconds,
        }


# ─── 全局单例 ────────────────────────────────────────────────────────

_idle_detector: Optional[IdleDetector] = None


def get_idle_detector() -> IdleDetector:
    """获取全局 IdleDetector 实例"""
    global _idle_detector
    if _idle_detector is None:
        _idle_detector = IdleDetector()
    return _idle_detector


def init_idle_detector(
    short_idle_seconds: int = _SHORT_IDLE_SECONDS,
    deep_idle_seconds: int = _DEEP_IDLE_SECONDS,
) -> IdleDetector:
    """初始化全局 IdleDetector（在 backend/main.py lifespan 中调用）"""
    global _idle_detector
    _idle_detector = IdleDetector(
        short_idle_seconds=short_idle_seconds,
        deep_idle_seconds=deep_idle_seconds,
    )
    logger.info(
        f"IdleDetector initialized: short={short_idle_seconds}s, deep={deep_idle_seconds}s"
    )
    return _idle_detector
