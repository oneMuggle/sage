"""Unit tests for TodoReminderScheduler."""
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from backend.scheduler.todo_reminder import (
    MAX_PENDING_NOTIFICATIONS,
    OVERDUE_REPEAT_HOURS,
    SCAN_INTERVAL_MINUTES,
    TodoReminderScheduler,
)

# The ``todo_service`` fixture lives in test_todo_service.py. Importing it
# registers it in this module's namespace, which is how pytest resolves
# fixtures — no duplicated fixture body, no conftest edit.
from backend.tests.unit.test_todo_service import todo_service  # noqa: F401


def _mock_service():
    """A ``MagicMock`` service whose scan methods return iterables.

    A bare ``MagicMock()`` attribute is **not** iterable, so
    ``_periodic_scan``'s ``for todo in ...`` would raise ``TypeError``
    inside the APScheduler job thread. APScheduler logs job exceptions
    rather than propagating them, so a bare mock does not fail the test —
    it just fills the log with a confusing traceback. Configuring the
    return values keeps the startup-scan tests honest and quiet.
    """
    svc = MagicMock()
    svc.refresh_effective_urgency.return_value = 0
    svc.get_unfired_24h_reminders.return_value = []
    svc.get_unfired_1h_reminders.return_value = []
    svc.get_overdue_todos.return_value = []
    return svc


@pytest.fixture()
def scheduler(todo_service):  # noqa: F811
    """Scheduler over a real ``TodoService``. APScheduler is never started
    here — tests call ``_periodic_scan`` directly to stay deterministic.
    """
    return TodoReminderScheduler(todo_service)


def test_start_registers_both_jobs():
    """start() must register both the periodic AND the startup scan.

    The startup scan is a one-shot ``DateTrigger(run_date=datetime.now())``:
    APScheduler runs it and then **removes it from the job store**, so
    asserting on ``get_jobs()`` after ``start()`` races against that removal
    (this is why the previous version of this test was flaky). Spying on
    ``add_job`` records what ``start()`` registered — the actual contract —
    with no race. ``test_start_runs_immediate_scan`` separately proves the
    startup job really does fire at once.
    """
    sched = TodoReminderScheduler(_mock_service())
    registered = []
    real_add_job = sched.scheduler.add_job

    def _spy(*args, **kwargs):
        registered.append(kwargs["id"])
        return real_add_job(*args, **kwargs)

    sched.scheduler.add_job = _spy
    try:
        sched.start()
    finally:
        sched.stop()

    assert "todo_periodic_scan" in registered
    assert "todo_startup_scan" in registered


def test_start_runs_immediate_scan():
    """The startup scan fires at once, not after a full interval.

    Ruling 11 #4: without it, a todo that came due while the app was closed
    waits up to 15 minutes for its first reminder. Proved by observing the
    scan's first side effect rather than by job-store presence (which the
    one-shot removal makes racy).
    """
    svc = _mock_service()
    sched = TodoReminderScheduler(svc)
    try:
        sched.start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not svc.refresh_effective_urgency.called:
            time.sleep(0.01)
        assert svc.refresh_effective_urgency.called
    finally:
        sched.stop()


def test_start_is_idempotent():
    """Calling start() twice must not raise and must not duplicate the
    periodic job.

    Asserts on the periodic job specifically, not on ``len(get_jobs())``:
    the startup one-shot is removed from the store as soon as it fires, so
    a count of 2 would race against that removal.
    """
    sched = TodoReminderScheduler(_mock_service())
    try:
        sched.start()
        sched.start()
        periodic = [
            j for j in sched.scheduler.get_jobs() if j.id == "todo_periodic_scan"
        ]
        assert len(periodic) == 1
    finally:
        sched.stop()


def test_stop_on_unstarted_is_safe():
    """stop() on a never-started scheduler must not raise — APScheduler's
    shutdown() raises SchedulerNotRunningError, the guard must intercept."""
    sched = TodoReminderScheduler(_mock_service())
    sched.stop()  # must not raise


def test_periodic_scan_fires_24h_reminder_and_latches(todo_service):  # noqa: F811
    """End-to-end scan over a real DB: 24 h todo fires, gets latched, does not
    fire on a second scan."""
    now = datetime.now()
    todo_service.create_todo(
        title="soon", due_at=(now + timedelta(hours=12)).isoformat()
    )

    sched = TodoReminderScheduler(todo_service)
    sched._periodic_scan()

    pending = sched.get_pending_notifications()
    assert len(pending) == 1
    assert pending[0]["title"] == "📋 待办提醒"
    assert "soon" in pending[0]["body"]

    # Second scan: 24 h latch is set, so no new notification.
    sched._periodic_scan()
    assert sched.get_pending_notifications() == []


def test_precise_trigger_fires_for_1h_todo(todo_service):  # noqa: F811
    now = datetime.now()
    todo_service.create_todo(
        title="very soon", due_at=(now + timedelta(minutes=45)).isoformat()
    )

    sched = TodoReminderScheduler(todo_service)
    try:
        sched.start()
        sched._periodic_scan()

        # ``_precise_job_ids`` maps todo_id → job_id (``Dict[int, str]``), so
        # the lookup key is the integer id, not the job-id string. Asserting
        # the value too proves the id was built as ``todo_precise_{id}``.
        assert sched._precise_job_ids.get(1) == "todo_precise_1"

        sched.get_pending_notifications()
        sched._fire_precise_reminder(1)
        precise = sched.get_pending_notifications()
        assert len(precise) == 1
        assert precise[0]["title"] == "⏰ 待办紧急"
        assert "即将到期" in precise[0]["body"]
    finally:
        sched.stop()


def test_overdue_throttle_announces_once_per_hour(todo_service):  # noqa: F811
    now = datetime.now()
    todo_service.create_todo(
        title="overdue", due_at=(now - timedelta(hours=1)).isoformat()
    )

    sched = TodoReminderScheduler(todo_service)
    sched._periodic_scan()
    assert len(sched.get_pending_notifications()) == 1

    sched._periodic_scan()
    assert sched.get_pending_notifications() == []


def test_overdue_prune_clears_old_claims(todo_service):  # noqa: F811
    now = datetime.now()
    todo_service.create_todo(
        title="overdue", due_at=(now - timedelta(hours=1)).isoformat()
    )

    sched = TodoReminderScheduler(todo_service)
    sched._periodic_scan()
    assert len(sched.get_pending_notifications()) == 1

    sched._overdue_notified_at = {
        k: now - timedelta(hours=OVERDUE_REPEAT_HOURS + 1)
        for k in sched._overdue_notified_at
    }
    sched._periodic_scan()
    assert len(sched.get_pending_notifications()) == 1


def test_get_pending_notifications_drains_queue():
    from unittest.mock import MagicMock

    sched = TodoReminderScheduler(MagicMock())
    sched._send_notification(title="A", body="B", urgency="normal")
    sched._send_notification(title="C", body="D", urgency="normal")
    assert len(sched.get_pending_notifications()) == 2
    assert sched.get_pending_notifications() == []


def test_notification_queue_is_bounded():
    from unittest.mock import MagicMock

    sched = TodoReminderScheduler(MagicMock())
    for i in range(MAX_PENDING_NOTIFICATIONS + 10):
        sched._send_notification(title=f"t{i}", body="b", urgency="normal")

    pending = sched.get_pending_notifications()
    assert len(pending) == MAX_PENDING_NOTIFICATIONS


def test_scan_interval_is_fifteen_minutes():
    """Spec §6.2 — the scan interval must be 15 minutes, not 5."""
    assert SCAN_INTERVAL_MINUTES == 15


def test_precise_lead_is_five_minutes():
    from backend.scheduler.todo_reminder import PRECISE_LEAD_MINUTES
    assert PRECISE_LEAD_MINUTES == 5
