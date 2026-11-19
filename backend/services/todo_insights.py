"""待办洞察（阶段 3）：推迟提醒与拖延统计。

从 ``todo_service.py`` 拆出（800 行架构棘轮）。两个函数都通过传入的
service / db 工作，避免反向依赖：
- :func:`snooze_todo` 需要 ``service.get_todo`` / ``service.update_todo``；
- :func:`most_snoozed` 只需要 db 与行→模型转换器。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, List, Optional

if TYPE_CHECKING:
    from backend.services.todo_service import Todo

logger = logging.getLogger(__name__)

MAX_SNOOZE_MINUTES = 7 * 24 * 60


def snooze_todo(service: Any, todo_id: int, minutes: int) -> Optional[Todo]:
    """推迟提醒：``due_at`` 后移 N 分钟（无 due_at 时从当前时间起算），
    ``snooze_count`` 自增。返回刷新后的 Todo；不存在返回 None。

    ``update_todo`` 内对 due_at 变更会重置 24h/1h 提醒 latch 与自定义
    提醒书签，因此 snooze 后提醒会按新时间重新触发。
    """
    todo = service.get_todo(todo_id)
    if todo is None:
        return None
    clamped = max(1, min(int(minutes), MAX_SNOOZE_MINUTES))
    now = datetime.now()
    base = now
    if todo.due_at:
        try:
            base = max(datetime.fromisoformat(todo.due_at), now)
        except ValueError:
            base = now
    new_due = (base + timedelta(minutes=clamped)).isoformat()

    conn = service.db.get_connection()
    conn.execute(
        "UPDATE todos SET snooze_count = COALESCE(snooze_count, 0) + 1 "
        "WHERE id = ?",
        (todo_id,),
    )
    conn.commit()
    return service.update_todo(todo_id, due_at=new_due)


def most_snoozed(
    db: Any, row_to_todo: Callable[[Any], Any], limit: int = 5
) -> List[Todo]:
    """被推迟次数最多的未完成待办（≥2 次），周回顾智能建议用。"""
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT * FROM todos "
        "WHERE status IN ('pending', 'in_progress') "
        "AND COALESCE(snooze_count, 0) >= 2 "
        "ORDER BY snooze_count DESC, updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [row_to_todo(row) for row in rows]
