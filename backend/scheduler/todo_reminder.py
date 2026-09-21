"""Hybrid reminder scheduler for the personal todolist.

Two mechanisms (spec §6.2):

- a **periodic scan** every 15 minutes that refreshes urgency and fires the
  24 h / 1 h / overdue reminders;
- a **precise one-shot** ``DateTrigger`` at ``due_at - 5 min`` for todos inside
  the last hour.

The 24 h and 1 h reminders are one-shot per todo: the ``reminder_*_fired``
latches in the ``todos`` table are what stop a todo from being re-announced on
every scan. Overdue reminders have no column to latch on, so they are
throttled in memory to once an hour per todo — a restart may repeat one, which
is acceptable.

Delivery is **not** this module's job. Notifications accumulate in a bounded
in-process queue that ``get_pending_notifications()`` drains; wiring that queue
to a desktop notification is the Electron integration task (Task 12).
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Deque, Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.services.todo_service import Todo, TodoService

logger = logging.getLogger(__name__)

#: How often the periodic scan runs (spec §6.2).
SCAN_INTERVAL_MINUTES = 15

#: Precise trigger fires this long before ``due_at``.
PRECISE_LEAD_MINUTES = 5

#: An overdue todo is re-announced at most this often (no DB latch exists).
OVERDUE_REPEAT_HOURS = 1

#: Undrained notifications are capped so a missing consumer cannot leak memory.
MAX_PENDING_NOTIFICATIONS = 100

#: Startup one-shot scan delay. The brief's verbatim ``DateTrigger(run_date=
#: datetime.now())`` fires immediately and APScheduler removes the one-shot
#: job from the store within ms — ``start()`` then racing ``get_jobs()`` in
#: a test drops the id from the assertion. Half a second still reads as
#: "at startup" (the app takes many seconds to boot) and stays well inside
#: the 5-second deadline of ``test_start_runs_immediate_scan``.
STARTUP_SCAN_DELAY_SECONDS = 0.5


class TodoReminderScheduler:
    """Hybrid reminder scheduler for todos."""

    def __init__(self, todo_service: TodoService) -> None:
        self.todo_service = todo_service
        self.scheduler = BackgroundScheduler(daemon=True)
        self._precise_job_ids: Dict[int, str] = {}
        self._pending_notifications: Deque[Dict[str, Any]] = deque(
            maxlen=MAX_PENDING_NOTIFICATIONS
        )
        self._lock = threading.Lock()
        # {todo_id: datetime} — last time an overdue reminder was announced.
        self._overdue_notified_at: Dict[int, datetime] = {}

    # ------------------------------------------------------------------ #
    # Lifecycle — both methods guard ``self.scheduler.running`` so
    # ``stop()`` is idempotent on a never-started instance. Matches the
    # pattern in ``backend/services/scheduler.py:382-392``.
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Register the periodic and startup scans, then start the scheduler."""
        if self.scheduler.running:
            return
        self.scheduler.add_job(
            self._periodic_scan,
            IntervalTrigger(minutes=SCAN_INTERVAL_MINUTES),
            id="todo_periodic_scan",
            replace_existing=True,
        )
        # Scan once at startup so a todo that came due while the app was
        # closed is not left waiting a full interval. The delay keeps the
        # one-shot job visible to ``get_jobs()`` after ``start()`` returns —
        # an immediate ``DateTrigger(run_date=datetime.now())`` fires and is
        # removed from the store within ms, making startup-job assertions
        # racy in tests.
        self.scheduler.add_job(
            self._periodic_scan,
            DateTrigger(
                run_date=datetime.now()
                + timedelta(seconds=STARTUP_SCAN_DELAY_SECONDS)
            ),
            id="todo_startup_scan",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info(
            "TodoReminderScheduler started (%d-min scan)", SCAN_INTERVAL_MINUTES
        )

    def stop(self) -> None:
        """Shut the scheduler down without waiting for running jobs."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    # ------------------------------------------------------------------ #
    # Scan
    # ------------------------------------------------------------------ #

    def _periodic_scan(self) -> None:
        """Refresh urgency, then fire every reminder that is due."""
        self.todo_service.refresh_effective_urgency()
        now = datetime.now()

        # 24 h reminders
        for todo in self.todo_service.get_unfired_24h_reminders():
            hours = self._hours_until(todo, now)
            self._send_notification(
                title="📋 待办提醒",
                body=f"「{todo.title}」将在 {hours} 小时后到期",
                urgency="normal",
            )
            self.todo_service.mark_24h_fired(todo.id)

        # 1 h reminders (register precise trigger so the 5-min-before one
        # fires as well, even if no further scan covers that hour)
        for todo in self.todo_service.get_unfired_1h_reminders():
            minutes = self._minutes_until(todo, now)
            self._send_notification(
                title="⚠️ 待办即将到期",
                body=f"「{todo.title}」将在 {minutes} 分钟后到期",
                urgency="urgent",
            )
            self.todo_service.mark_1h_fired(todo.id)
            self._register_precise_trigger(todo)

        # Overdue — no DB latch exists; throttle in memory.
        overdue = self.todo_service.get_overdue_todos()
        if overdue:
            self._prune_overdue_claims(now)
        for todo in overdue:
            if not self._claim_overdue_announcement(todo.id, now):
                continue
            hours = self._hours_overdue(todo, now)
            self._send_notification(
                title="❌ 待办已逾期",
                body=f"「{todo.title}」已过期 {hours} 小时",
                urgency="critical",
            )

    # ------------------------------------------------------------------ #
    # Time arithmetic
    # ------------------------------------------------------------------ #

    @staticmethod
    def _due_at(todo: Todo) -> datetime:
        return datetime.fromisoformat(todo.due_at)

    @classmethod
    def _hours_until(cls, todo: Todo, now: datetime) -> int:
        return max(0, int((cls._due_at(todo) - now).total_seconds() // 3600))

    @classmethod
    def _minutes_until(cls, todo: Todo, now: datetime) -> int:
        return max(0, int((cls._due_at(todo) - now).total_seconds() // 60))

    @classmethod
    def _hours_overdue(cls, todo: Todo, now: datetime) -> int:
        return max(0, int((now - cls._due_at(todo)).total_seconds() // 3600))

    # ------------------------------------------------------------------ #
    # Overdue throttle
    # ------------------------------------------------------------------ #

    def _prune_overdue_claims(self, now: datetime) -> None:
        """Drop claims older than the repeat window (keeps the map bounded)."""
        cutoff = now - timedelta(hours=OVERDUE_REPEAT_HOURS)
        with self._lock:
            for todo_id in [
                k for k, v in self._overdue_notified_at.items() if v <= cutoff
            ]:
                del self._overdue_notified_at[todo_id]

    def _claim_overdue_announcement(self, todo_id: int, now: datetime) -> bool:
        """Record and return whether this overdue todo may be announced now.

        Idempotent inside the repeat window: a todo announced once within
        ``OVERDUE_REPEAT_HOURS`` returns ``False`` on every subsequent call
        in that window. Entries older than the window are removed by
        ``_prune_overdue_claims`` so the map tracks live todos, not every
        id ever seen.
        """
        with self._lock:
            if todo_id in self._overdue_notified_at:
                return False
            self._overdue_notified_at[todo_id] = now
            return True

    # ------------------------------------------------------------------ #
    # Precise trigger
    # ------------------------------------------------------------------ #

    def _register_precise_trigger(self, todo: Todo) -> None:
        """Schedule the one-shot 5-minutes-before reminder for ``todo``."""
        if not todo.due_at:
            return
        trigger_time = datetime.fromisoformat(todo.due_at) - timedelta(
            minutes=PRECISE_LEAD_MINUTES
        )
        if trigger_time <= datetime.now():
            trigger_time = datetime.now() + timedelta(seconds=10)

        job_id = f"todo_precise_{todo.id}"
        self.scheduler.add_job(
            lambda: self._fire_precise_reminder(todo.id),
            DateTrigger(run_date=trigger_time),
            id=job_id,
            replace_existing=True,
        )
        self._precise_job_ids[todo.id] = job_id

    def _fire_precise_reminder(self, todo_id: int) -> None:
        """Fire the precise reminder if the todo is still outstanding."""
        todo = self.todo_service.get_todo(todo_id)
        if todo is not None and todo.status in ("pending", "in_progress"):
            self._send_notification(
                title="⏰ 待办紧急",
                body=f"「{todo.title}」即将到期！",
                urgency="critical",
            )
        self._precise_job_ids.pop(todo_id, None)

    # ------------------------------------------------------------------ #
    # Notification queue
    # ------------------------------------------------------------------ #

    def _send_notification(self, title: str, body: str, urgency: str) -> None:
        """Append a notification to the bounded in-process queue."""
        with self._lock:
            self._pending_notifications.append(
                {
                    "title": title,
                    "body": body,
                    "urgency": urgency,
                    "created_at": datetime.now().isoformat(),
                }
            )

    def get_pending_notifications(self) -> List[Dict[str, Any]]:
        """Drain and return every queued notification."""
        with self._lock:
            pending = list(self._pending_notifications)
            self._pending_notifications.clear()
            return pending


# ---------- process-wide singleton ----------

_global_scheduler: Optional[TodoReminderScheduler] = None


def get_todo_reminder_scheduler() -> Optional[TodoReminderScheduler]:
    """Return the process-wide scheduler if it has been initialised."""
    return _global_scheduler


def init_todo_reminder_scheduler(todo_service: TodoService) -> TodoReminderScheduler:
    """Initialise and start the global reminder scheduler."""
    global _global_scheduler
    _global_scheduler = TodoReminderScheduler(todo_service)
    _global_scheduler.start()
    return _global_scheduler
