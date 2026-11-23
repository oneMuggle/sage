"""编排 run 终态 / 审批等待通知队列（M4.3a, 2026-11-23）。

M4 第 3 条要求"编排 run 结束/失败/等待审批发系统通知（沿用后台任务通知通道）"。
本模块是那条通道上的第六路队列：run 终态由 ``_finalize_orch_run`` 推入，
审批等待由 ``SubagentEventSink`` 推入；Electron 主进程通过
``GET /api/v1/scheduled/notifications/pending`` 排空并转成 OS 通知。

进程内实现（bounded deque），无持久化：后端重启后未消费的通知丢失是可接受的
降级 —— 编排 run 本身也不跨重启存活。与 ``background_notifications`` 同构。

载荷字段（前端 ``PendingNotificationItem`` 对齐）：

- ``kind``: ``orch_run_completed`` / ``orch_run_failed`` / ``orch_run_cancelled`` /
  ``orch_run_awaiting_approval``
- ``run_id`` / ``task_id`` / ``session_id``: 点击跳转的深链锚点
- ``status`` / ``title`` / ``body`` / ``created_at``
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: 未消费通知上限（防止无消费者时内存无限增长）。
MAX_ORCH_RUN_NOTIFICATIONS = 100

#: 摘要截断上限（正文再长也只带这么多字进通知）。
SUMMARY_MAX_CHARS = 120

#: 状态 → (通知标题前缀, kind)
_STATUS_TITLES: Dict[str, Tuple[str, str]] = {
    "completed": ("✅ 编排运行完成", "orch_run_completed"),
    "failed": ("❌ 编排运行失败", "orch_run_failed"),
    "cancelled": ("🚫 编排运行已取消", "orch_run_cancelled"),
    "awaiting_approval": ("⏸ 编排任务等待审批", "orch_run_awaiting_approval"),
}


class OrchRunNotificationQueue:
    """线程安全的编排 run 通知队列。"""

    def __init__(self, maxlen: int = MAX_ORCH_RUN_NOTIFICATIONS) -> None:
        self._items: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(
        self,
        run_id: str,
        status: str,
        *,
        session_id: str = "",
        task_id: str = "",
        title: str = "",
        body: str = "",
    ) -> None:
        """记录一条编排 run 通知。"""
        prefix, kind = _STATUS_TITLES.get(status, ("ℹ️ 编排运行更新", "orch_run_updated"))
        with self._lock:
            self._items.append(
                {
                    "kind": kind,
                    "run_id": run_id,
                    "task_id": task_id,
                    "session_id": session_id or "",
                    "status": status,
                    "title": title or f"{prefix}：{run_id}",
                    "body": body or "",
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


_global_queue: Optional[OrchRunNotificationQueue] = None


def get_orch_run_notification_queue() -> OrchRunNotificationQueue:
    """进程级单例。"""
    global _global_queue
    if _global_queue is None:
        _global_queue = OrchRunNotificationQueue()
    return _global_queue


def resolve_session_id(run_id: str) -> str:
    """按 run_id 查 ``orch_runs.session_id``；查不到返回空串。

    让事件发布方（子代理 sink 等）无需自带 session_id —— 编排 run 的会话
    归属只有 ``orch_runs`` 表知道。查库失败按空串降级，不抛。
    """
    if not run_id:
        return ""
    try:
        from backend.data.orch_run_repo import OrchRunRepository

        run = OrchRunRepository().get(run_id)
        if run is None:
            return ""
        return run.session_id or ""
    except Exception as exc:  # noqa: BLE001 — 通知降级不影响主流
        logger.debug("解析 run session_id 失败 (%s): %s", run_id, exc)
        return ""


def push_run_notification(
    run_id: str,
    status: str,
    *,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    title: Optional[str] = None,
    body: Optional[str] = None,
) -> None:
    """推一条编排 run 通知（自身吞错 —— 通知失败不影响主流）。

    ``session_id`` 缺省时按 run_id 反查 ``orch_runs``。
    """
    if not run_id:
        return
    try:
        resolved = session_id if session_id is not None else resolve_session_id(run_id)
        get_orch_run_notification_queue().push(
            run_id,
            status,
            session_id=resolved or "",
            task_id=task_id or "",
            title=title or "",
            body=body or "",
        )
    except Exception as exc:  # noqa: BLE001 — 通知降级不影响主流
        logger.debug("推送编排 run 通知失败 (%s): %s", run_id, exc)


def summarize_for_notification(text: Optional[str]) -> str:
    """把 run 摘要压成一行、限长，供通知正文使用。"""
    if not text:
        return ""
    compact = " ".join(str(text).split())
    if len(compact) <= SUMMARY_MAX_CHARS:
        return compact
    return compact[: SUMMARY_MAX_CHARS - 1] + "…"


__all__ = [
    "MAX_ORCH_RUN_NOTIFICATIONS",
    "OrchRunNotificationQueue",
    "SUMMARY_MAX_CHARS",
    "get_orch_run_notification_queue",
    "push_run_notification",
    "resolve_session_id",
    "summarize_for_notification",
]
