"""闲时目标完成 / 失败通知队列（2026-11-09）。

与 BackgroundNotificationQueue 同构：进程内 bounded deque + threading.Lock，
无持久化。Electron 主进程通过
``GET /api/v1/scheduled/notifications/pending`` 的 ``goal_notifications`` 键排空。

为什么不复用 background_notifications：``background_tasks`` 键的语义是
"后台 Bash 任务"，混入目标通知会污染既有消费方（spec §7.2）。

Python 3.8 兼容：本文件将被 cherry-pick 到 release/win7 分支，
不使用 PEP 604 联合类型写法，也不使用内建泛型下标。
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

#: 未消费通知上限（防止无消费者时内存无限增长）。
MAX_GOAL_NOTIFICATIONS = 100

#: 触发通知的目标终态（对应 GoalStatus.COMPLETED / GoalStatus.FAILED）。
_TERMINAL_STATUSES = ("completed", "failed")


class GoalNotificationQueue:
    """线程安全的目标终态通知队列。"""

    def __init__(self, maxlen: int = MAX_GOAL_NOTIFICATIONS) -> None:
        self._items: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(self, goal: Any) -> None:
        """记录一条目标终态通知；非终态忽略。"""
        status = getattr(goal.status, "value", goal.status)
        if status not in _TERMINAL_STATUSES:
            return

        name = (getattr(goal, "name", "") or goal.id).strip()[:60]
        succeeded = status == "completed"
        error = getattr(goal, "last_error", None)

        with self._lock:
            self._items.append(
                {
                    "kind": "goal",
                    "goal_id": str(goal.id),
                    "status": "succeeded" if succeeded else "failed",
                    "title": (
                        f"✅ 闲时目标完成：{name}" if succeeded else f"❌ 闲时目标失败：{name}"
                    ),
                    "body": (error or "").strip()[:200],
                    "created_at": datetime.now().isoformat(),
                }
            )

    def drain(self) -> List[Dict[str, Any]]:
        """排空并返回全部通知。"""
        with self._lock:
            items = list(self._items)
            self._items.clear()
            return items

    def size(self) -> int:
        """当前未消费通知数（诊断用）。"""
        with self._lock:
            return len(self._items)


_queue: Optional[GoalNotificationQueue] = None
_queue_lock = threading.Lock()


def get_goal_notification_queue() -> GoalNotificationQueue:
    """进程级单例。"""
    global _queue
    with _queue_lock:
        if _queue is None:
            _queue = GoalNotificationQueue()
        return _queue


def reset_goal_notification_queue() -> None:
    """测试用：丢弃单例。"""
    global _queue
    with _queue_lock:
        _queue = None
