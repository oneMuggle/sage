"""循环待办：完成时生成下一实例。

``recurrence_rule`` 为 5 字段 cron（分 时 日 月 周）。用 APScheduler
``CronTrigger`` 计算下一次触发时间；无效规则 fail-open —— 只记录 warning，
绝不让完成操作本身失败。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from backend.services.todo_service import Todo

logger = logging.getLogger(__name__)


def spawn_next_recurrence(
    create_todo: Callable[..., Any], existing: Todo, now: datetime
) -> None:
    """为完成的循环待办创建下一实例（next due = cron 的下一次触发时间）。"""
    if not existing.is_recurring or not existing.recurrence_rule:
        return
    try:
        from apscheduler.triggers.cron import CronTrigger

        base = now
        if existing.due_at:
            try:
                base = max(datetime.fromisoformat(existing.due_at), now)
            except ValueError:
                base = now
        trigger = CronTrigger.from_crontab(existing.recurrence_rule)
        next_fire = trigger.get_next_fire_time(None, base)
        if next_fire is None:
            logger.warning(
                "循环待办 %s 的 cron=%r 没有下一次触发时间，跳过实例生成",
                existing.id,
                existing.recurrence_rule,
            )
            return
        if next_fire.tzinfo is not None:
            next_fire = next_fire.astimezone().replace(tzinfo=None)
        create_todo(
            title=existing.title,
            description=existing.description,
            due_at=next_fire.isoformat(),
            priority=existing.priority,
            project_tag=existing.project_tag,
            recurrence_rule=existing.recurrence_rule,
            parent_id=existing.parent_id,
            tags=existing.tags,
            reminder_offsets=existing.reminder_offsets,
        )
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        logger.warning(
            "循环待办 %s 生成下一实例失败（cron=%r）: %s",
            existing.id,
            existing.recurrence_rule,
            exc,
        )
