"""待办状态的单一真相源：状态词表 + 行内三态循环 + 完成时间戳副作用。

前端行内圆形按钮的三态循环（未开始 → 进行中 → 已完成 → 未开始）与后端
状态词表共用这一份定义，避免前后端各写一套字符串而悄悄漂移。

``cancelled`` 是终态：不参与三态循环，只能通过显式的「取消」动作进入。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

PENDING = "pending"
IN_PROGRESS = "in_progress"
COMPLETED = "completed"
CANCELLED = "cancelled"

# 全部合法状态。后端 ``UpdateTodoIn.status`` 的 pattern 与本表保持一致。
STATUSES = (PENDING, IN_PROGRESS, COMPLETED, CANCELLED)

# 活跃状态：未完成且未取消。待办列表默认只展示这两类。
ACTIVE_STATUSES = (PENDING, IN_PROGRESS)

# 行内三态循环顺序。
CYCLE_ORDER = (PENDING, IN_PROGRESS, COMPLETED)


def next_cycle_status(status: str) -> Optional[str]:
    """返回三态循环的下一个状态。

    不在循环内（``cancelled``）返回 ``None``，调用方据此隐藏循环入口。
    """
    if status not in CYCLE_ORDER:
        return None
    index = CYCLE_ORDER.index(status)
    return CYCLE_ORDER[(index + 1) % len(CYCLE_ORDER)]


def completion_timestamp(status: str, now: datetime) -> Optional[str]:
    """状态变更时 ``completed_at`` 的新值。

    完成态打上当前时间戳；其余状态（未开始 / 进行中 / 已取消）返回
    ``None`` 表示清空 —— 重开一条已完成的待办必须同时清掉完成时间，
    否则统计里的「已完成」永远带着一个陈旧的完成时刻。
    """
    if status == COMPLETED:
        return now.isoformat()
    return None


def is_active(status: str) -> bool:
    """待办是否处于「未完成且未取消」的活跃态。"""
    return status in ACTIVE_STATUSES


def apply_completion_stamp(updates: Dict[str, Any], now: datetime) -> None:
    """把状态变更的 ``completed_at`` 副作用写进 ``updates``（就地修改）。

    ``completed_at`` 不在待办服务的可写字段白名单里 —— 调用方不能直接写
    这一列，这里是唯一入口。``updates`` 里没有 ``status`` 键时什么都不做。
    """
    if "status" in updates:
        updates["completed_at"] = completion_timestamp(updates["status"], now)
