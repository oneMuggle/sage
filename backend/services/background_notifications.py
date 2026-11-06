"""后台任务完成通知队列（2026-11-06 Phase 1）。

BashSessionRegistry 的退出观察器在后台 shell 结束时把一条通知推入本队列；
Electron 主进程通过 ``GET /api/v1/scheduled/notifications/pending`` 排空并转成
OS 通知（与定时任务 / 待办提醒共用同一消费节奏）。

进程内实现（bounded deque），无持久化：后端重启后未消费的通知丢失是可接受
的降级 —— 后台 shell 本身也不跨重启存活。
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

#: 未消费通知上限（防止无消费者时内存无限增长）。
MAX_BACKGROUND_NOTIFICATIONS = 100


class BackgroundNotificationQueue:
    """线程安全的后台任务完成通知队列。"""

    def __init__(self, maxlen: int = MAX_BACKGROUND_NOTIFICATIONS) -> None:
        self._items: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(
        self,
        shell_id: str,
        command: str,
        exit_code: Optional[int],
        session_id: Optional[str] = None,
    ) -> None:
        """记录一条后台任务结束通知。"""
        compact = (command or "").strip().replace("\n", " ")[:60] or shell_id
        succeeded = exit_code == 0
        with self._lock:
            self._items.append(
                {
                    "kind": "background_task",
                    "shell_id": shell_id,
                    "session_id": session_id or "",
                    "status": "succeeded" if succeeded else "failed",
                    "exit_code": exit_code,
                    "title": (
                        f"✅ 后台任务完成：{compact}"
                        if succeeded
                        else f"❌ 后台任务失败：{compact}"
                    ),
                    "body": f"exit={exit_code if exit_code is not None else 'unknown'}",
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
        with self._lock:
            return len(self._items)


_global_queue: Optional[BackgroundNotificationQueue] = None


def get_background_notification_queue() -> BackgroundNotificationQueue:
    """进程级单例。"""
    global _global_queue
    if _global_queue is None:
        _global_queue = BackgroundNotificationQueue()
    return _global_queue
