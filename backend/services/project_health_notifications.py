"""项目健康告警通知队列（2026-11-14 M1）。

与 BackgroundNotificationQueue / GoalNotificationQueue 同构：进程内 bounded
deque + threading.Lock，无持久化。Electron 主进程通过
``GET /api/v1/scheduled/notifications/pending`` 的 ``project_health`` 键排空。

为什么不复用 background_tasks：该键语义是"后台 Bash 任务"，混入项目健康
告警会污染既有消费方。

Python 3.8 兼容：本文件将被 cherry-pick 到 release/win7 分支，不使用 PEP 604
联合类型写法，也不使用内建泛型下标。
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

#: 未消费通知上限（防止无消费者时内存无限增长）。
MAX_PROJECT_HEALTH_NOTIFICATIONS = 100


class ProjectHealthNotificationQueue:
    """线程安全的项目健康告警队列。"""

    def __init__(self, maxlen: int = MAX_PROJECT_HEALTH_NOTIFICATIONS) -> None:
        self._items: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(
        self,
        project_id: str,
        project_name: str,
        severity: str,
        title: str,
        body: str,
    ) -> None:
        """记录一条项目健康告警。"""
        with self._lock:
            self._items.append(
                {
                    "kind": "project_health",
                    "project_id": str(project_id),
                    "project_name": project_name,
                    "severity": severity,
                    "title": title,
                    "body": body,
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


_queue: Optional[ProjectHealthNotificationQueue] = None
_queue_lock = threading.Lock()


def get_project_health_notification_queue() -> ProjectHealthNotificationQueue:
    """进程级单例。"""
    global _queue
    with _queue_lock:
        if _queue is None:
            _queue = ProjectHealthNotificationQueue()
        return _queue


def reset_project_health_notification_queue() -> None:
    """测试用：丢弃单例。"""
    global _queue
    with _queue_lock:
        _queue = None


__all__ = [
    "MAX_PROJECT_HEALTH_NOTIFICATIONS",
    "ProjectHealthNotificationQueue",
    "get_project_health_notification_queue",
    "reset_project_health_notification_queue",
]
