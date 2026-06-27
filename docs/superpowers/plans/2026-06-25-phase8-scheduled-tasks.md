# Phase 8: Scheduled Tasks (Cron Jobs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users schedule one-shot or recurring "reminder" / "automation" messages that fire at a specific time and auto-send into a chosen chat session, visible in the sidebar's "Cron Jobs" group and editable from a dedicated `ScheduledTasks` page. Inspired by AionUi `pages/cron/` + `Sider/CronJobSiderSection.tsx`.

**Architecture:** Backend uses APScheduler (`BackgroundScheduler`) loaded from `backend/data/scheduled_tasks.json` on startup, with one-shot (`DateTrigger`) and recurring (`CronTrigger`) jobs. On fire, the scheduler posts a message into the target session via the existing `MessageRepository`. Frontend uses a Zustand store (`taskStore`) backed by an IPC client (`scheduledClient`) that hits a new `scheduled_router.py` REST API (`/api/v1/scheduled/*`). UI is split: a sidebar section (read-only list, status badges) plus a `ScheduledTasks` page with the create/edit modal, and a "定时" button in `ChatInput` that opens the modal pre-filled with current session.

**Tech Stack:**
- **Frontend:** React 18, TypeScript, Zustand, Vitest, @testing-library/react, lucide-react, sonner (toast), i18next (existing `useI18n`)
- **Backend:** Python 3.11, FastAPI, APScheduler 3.10+, pydantic 2.x, croniter (already in deps — reused for validation)
- **Storage:** JSON file (`backend/data/scheduled_tasks.json`) — atomic write via temp + rename
- **Time:** UTC epoch ms in storage; local timezone for display via `Intl.DateTimeFormat()`

## Global Constraints

From spec `2026-06-25-aionui-inspired-ui-design.md` and project rules:

- **No new npm packages** (frontend uses existing deps only)
- **Backend new dep:** `apscheduler==3.10.4` added to `backend/requirements.txt`
- **Coverage:** `scheduler.py` ≥ 95%, `cronValidator.ts` ≥ 95%, `scheduledClient.ts` ≥ 90%, overall frontend ≥ 85%, overall backend ≥ 85%
- **Python env:** All backend work runs in `sage-backend` conda env (`/home/fz/anaconda3/envs/sage-backend/bin/python`)
- **Timezone dual-track:** Store UTC epoch ms; display via `Intl.DateTimeFormat()` in user locale
- **No breaking changes** to existing APIs (`/sessions`, `/chat`, etc. untouched)
- **FSD architecture:** pages / widgets / features / entities / shared — strict layering
- **TDD mandatory:** Tests written FIRST (RED) → implementation (GREEN) → refactor
- **Atomic file writes:** Use `tempfile.NamedTemporaryFile` + `os.replace` for `scheduled_tasks.json`
- **Concurrency:** All store mutations go through FastAPI; APScheduler runs in same process; uses threading.Lock for JSON reads/writes
- **Error contract:** Never throw to UI; surface via toast + console.warn; scheduler continues on per-job failures

## File Structure

**New files (frontend):**
- `src/entities/scheduled/taskStore.ts` — Zustand store for tasks + load/create/update/delete
- `src/entities/scheduled/__tests__/taskStore.test.ts` — Store unit tests
- `src/features/scheduled/cronValidator.ts` — Cron + one-shot validation utilities
- `src/features/scheduled/__tests__/cronValidator.test.ts` — Validator unit tests
- `src/features/scheduled/CronExpressionPicker.tsx` — Visual cron editor (presets + custom)
- `src/features/scheduled/__tests__/CronExpressionPicker.test.tsx` — Picker component tests
- `src/features/scheduled/CreateTaskModal.tsx` — Create/edit task modal
- `src/features/scheduled/__tests__/CreateTaskModal.test.tsx` — Modal component tests
- `src/widgets/sidebar/sections/CronJobSection.tsx` — Sidebar section (replaces Phase 2 placeholder)
- `src/widgets/sidebar/sections/__tests__/CronJobSection.test.tsx` — Section component tests
- `src/pages/ScheduledTasks.tsx` — Page: list + create button + modals
- `src/pages/__tests__/ScheduledTasks.test.tsx` — Page component tests
- `src/shared/api/scheduledClient.ts` — IPC client (CRUD)
- `src/shared/api/__tests__/scheduledClient.test.ts` — Client integration tests

**New files (backend):**
- `backend/api/scheduled_router.py` — REST API for CRUD + run-now
- `backend/api/__init__.py` — already exists, re-export router
- `backend/services/__init__.py` — package init
- `backend/services/scheduler.py` — APScheduler wrapper + persistence
- `backend/services/__tests__/test_scheduler.py` — Scheduler unit tests
- `backend/tests/integration/test_scheduled_api.py` — API integration tests
- `backend/data/scheduled_tasks.json` — Empty seed (`{"version":1,"tasks":[]}`) — created on first save, NOT committed with content

**Modified files:**
- `backend/requirements.txt` — add `apscheduler==3.10.4`
- `backend/main.py` — mount `scheduled_router`, start/stop scheduler in lifespan
- `src/widgets/chat/ChatInput.tsx` — add "定时" button next to attach row
- `src/widgets/chat/__tests__/ChatInput.scheduled.test.tsx` — ChatInput test for schedule button
- `src/widgets/layout/Sidebar.tsx` — wire `<CronJobSection />` into nav (after ConversationsSection)
- `src/App.tsx` — add `/scheduled` route
- `src/shared/lib/i18n/zh.ts` — add 22 i18n keys
- `src/shared/lib/i18n/en.ts` — add 22 i18n keys
- `src/shared/api/types.ts` — add `ScheduledTask` interface

---

## Task 1: Backend — add APScheduler dependency

**Files:**
- Modify: `/home/fz/project/sage/backend/requirements.txt`

**Interfaces:** None (deps only)

- [ ] **Step 1: Add apscheduler line to requirements.txt**

Append to `/home/fz/project/sage/backend/requirements.txt` (after the `# Utils` block, on its own line):

```
# Scheduled tasks (Phase 8)
apscheduler==3.10.4
```

- [ ] **Step 2: Install into sage-backend env**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/pip install apscheduler==3.10.4`
Expected: Successfully installed apscheduler-3.10.4 ...

- [ ] **Step 3: Verify import**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -c "from apscheduler.schedulers.background import BackgroundScheduler; from apscheduler.triggers.cron import CronTrigger; from apscheduler.triggers.date import DateTrigger; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage
git add backend/requirements.txt
git commit -m "build(backend): add apscheduler 3.10.4 for scheduled tasks (Phase 8)"
```

---

## Task 2: Backend — write scheduler.py test scaffolding

**Files:**
- Create: `/home/fz/project/sage/backend/services/__init__.py` (empty)
- Create: `/home/fz/project/sage/backend/services/__tests__/test_scheduler.py`

**Interfaces:**
- Consumes: APScheduler, json, threading
- Produces: test cases for `SchedulerService` (TBD)

- [ ] **Step 1: Create empty `services/__init__.py`**

```bash
touch /home/fz/project/sage/backend/services/__init__.py
```

- [ ] **Step 2: Create `__tests__` directory**

```bash
mkdir -p /home/fz/project/sage/backend/services/__tests__
```

- [ ] **Step 3: Write test file (RED)**

Create file `/home/fz/project/sage/backend/services/__tests__/test_scheduler.py` with the following content:

```python
"""Tests for backend.services.scheduler — APScheduler wrapper + persistence."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.services.scheduler import SchedulerService, TaskNotFoundError, ValidationError


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """Per-test JSON store path (file does not yet exist)."""
    return tmp_path / "scheduled_tasks.json"


@pytest.fixture
def message_repo() -> MagicMock:
    """Mock message repo that records inserted messages."""
    repo = MagicMock()
    repo.insert = MagicMock(return_value={"id": "msg-1"})
    return repo


@pytest.fixture
def session_repo() -> MagicMock:
    """Mock session repo that confirms session exists."""
    repo = MagicMock()
    repo.exists = MagicMock(return_value=True)
    return repo


@pytest.fixture
def scheduler(store_path: Path, message_repo: MagicMock, session_repo: MagicMock) -> SchedulerService:
    return SchedulerService(
        store_path=store_path,
        message_repo=message_repo,
        session_repo=session_repo,
    )


class TestLoadOnInit:
    def test_returns_empty_list_when_file_missing(self, scheduler: SchedulerService) -> None:
        assert scheduler.list_tasks() == []

    def test_loads_tasks_from_existing_file(self, store_path: Path, message_repo: MagicMock, session_repo: MagicMock) -> None:
        store_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "tasks": [
                        {
                            "id": "t-1",
                            "name": "Morning brief",
                            "type": "recurring",
                            "schedule": {"kind": "recurring", "cron": "0 8 * * *"},
                            "session_id": "s-1",
                            "content": "good morning",
                            "enabled": True,
                            "created_at": 1700000000000,
                        }
                    ],
                }
            )
        )
        svc = SchedulerService(store_path=store_path, message_repo=message_repo, session_repo=session_repo)
        tasks = svc.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == "t-1"
        assert tasks[0].name == "Morning brief"


class TestAddTask:
    def test_adds_recurring_task(self, scheduler: SchedulerService) -> None:
        task = scheduler.add_task(
            name="Daily standup",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 9 * * 1-5"},
            session_id="s-1",
            content="Daily standup reminder",
        )
        assert task.id.startswith("task-")
        assert task.name == "Daily standup"
        assert task.type == "recurring"
        assert task.enabled is True
        assert scheduler.list_tasks()[0].id == task.id

    def test_adds_one_shot_task_with_at_timestamp(self, scheduler: SchedulerService) -> None:
        future_at = int(time.time() * 1000) + 60_000  # 60 seconds from now
        task = scheduler.add_task(
            name="Meeting reminder",
            task_type="once",
            schedule={"kind": "once", "at": future_at},
            session_id="s-1",
            content="Meeting starts in 5 min",
        )
        assert task.type == "once"
        assert task.next_run == future_at

    def test_rejects_invalid_cron_expression(self, scheduler: SchedulerService) -> None:
        with pytest.raises(ValidationError):
            scheduler.add_task(
                name="Bad",
                task_type="recurring",
                schedule={"kind": "recurring", "cron": "this is not cron"},
                session_id="s-1",
                content="x",
            )

    def test_rejects_one_shot_in_the_past(self, scheduler: SchedulerService) -> None:
        past_at = int(time.time() * 1000) - 60_000
        with pytest.raises(ValidationError):
            scheduler.add_task(
                name="Old",
                task_type="once",
                schedule={"kind": "once", "at": past_at},
                session_id="s-1",
                content="x",
            )

    def test_rejects_nonexistent_session(self, scheduler: SchedulerService, session_repo: MagicMock) -> None:
        session_repo.exists.return_value = False
        with pytest.raises(ValidationError):
            scheduler.add_task(
                name="Bad session",
                task_type="recurring",
                schedule={"kind": "recurring", "cron": "0 8 * * *"},
                session_id="ghost",
                content="x",
            )

    def test_persists_to_disk(self, scheduler: SchedulerService, store_path: Path) -> None:
        scheduler.add_task(
            name="Persist me",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s-1",
            content="hello",
        )
        assert store_path.exists()
        data = json.loads(store_path.read_text())
        assert data["version"] == 1
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["name"] == "Persist me"


class TestUpdateTask:
    def test_updates_name(self, scheduler: SchedulerService) -> None:
        task = scheduler.add_task(
            name="Old name",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s-1",
            content="x",
        )
        updated = scheduler.update_task(task.id, name="New name")
        assert updated.name == "New name"

    def test_updates_enabled_flag(self, scheduler: SchedulerService) -> None:
        task = scheduler.add_task(
            name="Pauseable",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s-1",
            content="x",
        )
        scheduler.update_task(task.id, enabled=False)
        assert scheduler.get_task(task.id).enabled is False

    def test_raises_on_missing_task(self, scheduler: SchedulerService) -> None:
        with pytest.raises(TaskNotFoundError):
            scheduler.update_task("task-missing", name="x")


class TestDeleteTask:
    def test_removes_task(self, scheduler: SchedulerService) -> None:
        task = scheduler.add_task(
            name="Delete me",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s-1",
            content="x",
        )
        scheduler.delete_task(task.id)
        assert scheduler.list_tasks() == []

    def test_raises_on_missing_task(self, scheduler: SchedulerService) -> None:
        with pytest.raises(TaskNotFoundError):
            scheduler.delete_task("task-missing")


class TestRunNow:
    def test_fires_task_immediately_and_inserts_message(self, scheduler: SchedulerService, message_repo: MagicMock) -> None:
        task = scheduler.add_task(
            name="Run now",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s-1",
            content="manual trigger",
        )
        scheduler.run_now(task.id)
        message_repo.insert.assert_called_once()
        kwargs = message_repo.insert.call_args.kwargs
        assert kwargs["session_id"] == "s-1"
        assert kwargs["role"] == "system"
        assert kwargs["content"] == "manual trigger"
        assert kwargs["created_at"] > 0

    def test_skips_when_session_missing(self, scheduler: SchedulerService, session_repo: MagicMock, message_repo: MagicMock) -> None:
        task = scheduler.add_task(
            name="Ghost session",
            task_type="recurring",
            schedule={"kind": "recurring", "cron": "0 8 * * *"},
            session_id="s-1",
            content="x",
        )
        session_repo.exists.return_value = False
        scheduler.run_now(task.id)
        message_repo.insert.assert_not_called()

    def test_disables_one_shot_after_firing(self, scheduler: SchedulerService, message_repo: MagicMock) -> None:
        future_at = int(time.time() * 1000) + 60_000
        task = scheduler.add_task(
            name="One shot",
            task_type="once",
            schedule={"kind": "once", "at": future_at},
            session_id="s-1",
            content="once",
        )
        scheduler.run_now(task.id)
        assert scheduler.get_task(task.id).enabled is False


class TestLifecycle:
    def test_start_and_stop_scheduler(self, scheduler: SchedulerService) -> None:
        scheduler.start()
        assert scheduler.is_running() is True
        scheduler.shutdown()
        assert scheduler.is_running() is False

    def test_shutdown_is_idempotent(self, scheduler: SchedulerService) -> None:
        scheduler.start()
        scheduler.shutdown()
        scheduler.shutdown()  # must not raise
        assert scheduler.is_running() is False
```

- [ ] **Step 4: Run test, verify RED**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/services/__tests__/test_scheduler.py -x --no-header`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.scheduler'`

- [ ] **Step 5: No commit yet** (will commit with implementation in Task 3)

---

## Task 3: Backend — implement scheduler.py (GREEN)

**Files:**
- Create: `/home/fz/project/sage/backend/services/scheduler.py`

**Interfaces:**
- Consumes: APScheduler `BackgroundScheduler`, `CronTrigger`, `DateTrigger`, `MessageRepository` (mocked in tests), `SessionRepository` (mocked in tests), `croniter` (validation)
- Produces: `SchedulerService` class, `ScheduledTask` dataclass, `TaskNotFoundError`, `ValidationError`

- [ ] **Step 1: Create scheduler.py with full implementation**

Create file `/home/fz/project/sage/backend/services/scheduler.py` with the following content:

```python
"""APScheduler wrapper for Phase 8 scheduled tasks.

Persistence: ``backend/data/scheduled_tasks.json`` (atomic write).
Concurrency: a single ``threading.Lock`` guards JSON read/write.
Failure mode: per-job exceptions are logged and never raised to the scheduler
loop, so a bad task cannot kill the scheduler.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from croniter import croniter

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class TaskNotFoundError(KeyError):
    """Raised when the task id does not exist in the store."""


class ValidationError(ValueError):
    """Raised when input fails validation (bad cron, past timestamp, etc.)."""


@dataclass
class ScheduledTask:
    """Public dataclass used by router and store tests.

    Mirrors the TS interface in ``src/shared/api/types.ts``.
    """

    id: str
    name: str
    type: Literal["once", "recurring"]
    schedule: dict[str, Any]
    session_id: str
    content: str
    enabled: bool
    created_at: int
    last_run: int | None = None
    next_run: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ScheduledTask":
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            type=raw["type"],  # type: ignore[arg-type]
            schedule=dict(raw["schedule"]),
            session_id=str(raw["session_id"]),
            content=str(raw["content"]),
            enabled=bool(raw["enabled"]),
            created_at=int(raw["created_at"]),
            last_run=int(raw["last_run"]) if raw.get("last_run") is not None else None,
            next_run=int(raw["next_run"]) if raw.get("next_run") is not None else None,
        )


def _epoch_ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


class SchedulerService:
    """APScheduler-backed scheduler with JSON persistence.

    The service is safe to instantiate once per process. ``start()`` is
    idempotent; ``shutdown()`` is idempotent and tolerates double calls.
    """

    def __init__(
        self,
        store_path: Path,
        message_repo: Any,
        session_repo: Any,
    ) -> None:
        self._store_path = Path(store_path)
        self._message_repo = message_repo
        self._session_repo = session_repo
        self._lock = threading.Lock()
        self._tasks: dict[str, ScheduledTask] = {}
        self._scheduler = BackgroundScheduler(daemon=True)
        self._load_from_disk()
        self._reschedule_all()

    # ---------- public API ----------

    def list_tasks(self) -> list[ScheduledTask]:
        with self._lock:
            return list(self._tasks.values())

    def get_task(self, task_id: str) -> ScheduledTask:
        with self._lock:
            if task_id not in self._tasks:
                raise TaskNotFoundError(task_id)
            return self._tasks[task_id]

    def add_task(
        self,
        name: str,
        task_type: Literal["once", "recurring"],
        schedule: dict[str, Any],
        session_id: str,
        content: str,
    ) -> ScheduledTask:
        if not name or not name.strip():
            raise ValidationError("name must not be empty")
        if not content:
            raise ValidationError("content must not be empty")
        if not self._session_repo_exists(session_id):
            raise ValidationError(f"session not found: {session_id}")

        if task_type == "once":
            at_ms = int(schedule["at"])
            if at_ms <= int(time.time() * 1000):
                raise ValidationError("one-shot 'at' must be in the future")
            validated_schedule: dict[str, Any] = {"kind": "once", "at": at_ms}
            next_run = at_ms
        else:
            cron_expr = str(schedule["cron"]).strip()
            if not cron_expr or not croniter.is_valid(cron_expr):
                raise ValidationError(f"invalid cron expression: {cron_expr!r}")
            validated_schedule = {"kind": "recurring", "cron": cron_expr}
            next_run = self._compute_next_cron_run(cron_expr)

        task = ScheduledTask(
            id=f"task-{uuid.uuid4().hex[:8]}",
            name=name.strip(),
            type=task_type,
            schedule=validated_schedule,
            session_id=session_id,
            content=content,
            enabled=True,
            created_at=int(time.time() * 1000),
            next_run=next_run,
        )
        with self._lock:
            self._tasks[task.id] = task
            self._save_to_disk()
            self._schedule_job(task)
        logger.info("scheduled task added: %s (%s)", task.id, task.type)
        return task

    def update_task(self, task_id: str, **changes: Any) -> ScheduledTask:
        with self._lock:
            if task_id not in self._tasks:
                raise TaskNotFoundError(task_id)
            current = self._tasks[task_id]
            new_name = changes.get("name", current.name)
            new_enabled = changes.get("enabled", current.enabled)
            if not isinstance(new_name, str) or not new_name.strip():
                raise ValidationError("name must not be empty")
            if not isinstance(new_enabled, bool):
                raise ValidationError("enabled must be bool")
            updated = ScheduledTask(
                id=current.id,
                name=new_name.strip(),
                type=current.type,
                schedule=current.schedule,
                session_id=current.session_id,
                content=current.content,
                enabled=new_enabled,
                created_at=current.created_at,
                last_run=current.last_run,
                next_run=current.next_run,
            )
            self._tasks[task_id] = updated
            self._save_to_disk()
            self._reschedule_one(updated)
        logger.info("scheduled task updated: %s", task_id)
        return updated

    def delete_task(self, task_id: str) -> None:
        with self._lock:
            if task_id not in self._tasks:
                raise TaskNotFoundError(task_id)
            del self._tasks[task_id]
            try:
                self._scheduler.remove_job(task_id)
            except Exception:  # noqa: BLE001 — APScheduler raises if job absent
                logger.debug("apscheduler job %s already absent", task_id)
            self._save_to_disk()
        logger.info("scheduled task deleted: %s", task_id)

    def run_now(self, task_id: str) -> None:
        with self._lock:
            if task_id not in self._tasks:
                raise TaskNotFoundError(task_id)
            task = self._tasks[task_id]
        self._fire(task)

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("scheduler started with %d jobs", len(self._tasks))

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        logger.info("scheduler shut down")

    def is_running(self) -> bool:
        return self._scheduler.running

    # ---------- internal helpers ----------

    def _session_repo_exists(self, session_id: str) -> bool:
        exists = getattr(self._session_repo, "exists", None)
        if callable(exists):
            return bool(exists(session_id))
        get = getattr(self._session_repo, "get", None)
        if callable(get):
            return get(session_id) is not None
        return True  # no repo available — allow (used in unit tests with full mock)

    def _compute_next_cron_run(self, cron_expr: str) -> int:
        itr = croniter(cron_expr, time.time())
        return int(itr.get_next(float) * 1000)

    def _reschedule_all(self) -> None:
        for task in self._tasks.values():
            self._schedule_job(task)

    def _reschedule_one(self, task: ScheduledTask) -> None:
        try:
            self._scheduler.remove_job(task.id)
        except Exception:  # noqa: BLE001
            pass
        self._schedule_job(task)

    def _schedule_job(self, task: ScheduledTask) -> None:
        if not task.enabled:
            return
        if task.type == "once":
            trigger = DateTrigger(run_date=_epoch_ms_to_dt(task.schedule["at"]))
        else:
            trigger = CronTrigger.from_crontab(task.schedule["cron"])
        self._scheduler.add_job(
            self._fire,
            trigger=trigger,
            args=[task],
            id=task.id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def _fire(self, task: ScheduledTask) -> None:
        """Insert the task's content as a system message into the target session."""
        try:
            if not self._session_repo_exists(task.session_id):
                logger.warning("task %s: session %s gone, skipping", task.id, task.session_id)
                return
            self._message_repo.insert(
                session_id=task.session_id,
                role="system",
                content=task.content,
                created_at=int(time.time() * 1000),
            )
            logger.info("task %s fired into session %s", task.id, task.session_id)
        except Exception:  # noqa: BLE001
            logger.exception("task %s fire failed", task.id)
        finally:
            with self._lock:
                if task.id not in self._tasks:
                    return
                current = self._tasks[task.id]
                last_run = int(time.time() * 1000)
                if current.type == "once":
                    self._tasks[task.id] = ScheduledTask(
                        id=current.id,
                        name=current.name,
                        type=current.type,
                        schedule=current.schedule,
                        session_id=current.session_id,
                        content=current.content,
                        enabled=False,
                        created_at=current.created_at,
                        last_run=last_run,
                        next_run=None,
                    )
                    try:
                        self._scheduler.remove_job(current.id)
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    next_run = self._compute_next_cron_run(current.schedule["cron"])
                    self._tasks[task.id] = ScheduledTask(
                        id=current.id,
                        name=current.name,
                        type=current.type,
                        schedule=current.schedule,
                        session_id=current.session_id,
                        content=current.content,
                        enabled=current.enabled,
                        created_at=current.created_at,
                        last_run=last_run,
                        next_run=next_run,
                    )
                self._save_to_disk()

    # ---------- persistence ----------

    def _load_from_disk(self) -> None:
        if not self._store_path.exists():
            return
        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("scheduled_tasks.json unreadable, starting empty: %s", exc)
            return
        version = raw.get("version", 1)
        if version != SCHEMA_VERSION:
            logger.warning("scheduled_tasks.json schema=%s, expected %s, ignoring", version, SCHEMA_VERSION)
            return
        for item in raw.get("tasks", []):
            try:
                task = ScheduledTask.from_dict(item)
                self._tasks[task.id] = task
            except Exception:  # noqa: BLE001
                logger.warning("skipping malformed task entry: %s", item)

    def _save_to_disk(self) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SCHEMA_VERSION,
            "tasks": [t.to_dict() for t in self._tasks.values()],
        }
        tmp = self._store_path.with_suffix(self._store_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._store_path)


_global_service: SchedulerService | None = None


def get_scheduler_service() -> SchedulerService | None:
    """Return the process-wide SchedulerService if it has been initialised."""
    return _global_service


def init_scheduler_service(
    store_path: Path,
    message_repo: Any,
    session_repo: Any,
) -> SchedulerService:
    """Initialise the global service. Must be called once during app startup."""
    global _global_service
    _global_service = SchedulerService(
        store_path=store_path,
        message_repo=message_repo,
        session_repo=session_repo,
    )
    return _global_service
```

- [ ] **Step 2: Run tests, verify GREEN**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/services/__tests__/test_scheduler.py -x --no-header`
Expected: All tests pass (~17 tests).

- [ ] **Step 3: Run with coverage to confirm >= 95%**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/services/__tests__/test_scheduler.py --cov=backend.services.scheduler --cov-report=term-missing --no-header`
Expected: `TOTAL ... 95%` or higher.

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage
git add backend/services/__init__.py backend/services/scheduler.py backend/services/__tests__/test_scheduler.py
git commit -m "feat(backend): SchedulerService with APScheduler + JSON persistence (Phase 8)"
```

---

## Task 4: Backend — write scheduled_router test scaffolding

**Files:**
- Create: `/home/fz/project/sage/backend/tests/integration/test_scheduled_api.py`

**Interfaces:** None (scaffolding only)

- [ ] **Step 1: Create the integration test file (RED)**

Create file `/home/fz/project/sage/backend/tests/integration/test_scheduled_api.py`:

```python
"""Integration tests for scheduled_router against an in-process FastAPI app."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.scheduled_router import build_router
from backend.services.scheduler import SchedulerService


@pytest.fixture
def message_repo() -> MagicMock:
    repo = MagicMock()
    repo.insert = MagicMock(return_value={"id": "msg-1"})
    return repo


@pytest.fixture
def session_repo() -> MagicMock:
    repo = MagicMock()
    repo.exists = MagicMock(return_value=True)
    return repo


@pytest.fixture
def scheduler(tmp_path: Path, message_repo: MagicMock, session_repo: MagicMock) -> SchedulerService:
    return SchedulerService(
        store_path=tmp_path / "scheduled_tasks.json",
        message_repo=message_repo,
        session_repo=session_repo,
    )


@pytest.fixture
def client(scheduler: SchedulerService) -> TestClient:
    app = FastAPI()
    app.include_router(build_router(lambda: scheduler), prefix="/api/v1")
    return TestClient(app)


class TestScheduledApi:
    def test_health_ok(self, client: TestClient) -> None:
        r = client.get("/api/v1/scheduled/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_list_starts_empty(self, client: TestClient) -> None:
        r = client.get("/api/v1/scheduled/tasks")
        assert r.status_code == 200
        assert r.json() == []

    def test_create_recurring_task(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/scheduled/tasks",
            json={
                "name": "Daily brief",
                "type": "recurring",
                "schedule": {"kind": "recurring", "cron": "0 8 * * *"},
                "session_id": "s-1",
                "content": "good morning",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "Daily brief"
        assert body["enabled"] is True
        assert body["id"].startswith("task-")

    def test_create_rejects_bad_cron(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/scheduled/tasks",
            json={
                "name": "Bad",
                "type": "recurring",
                "schedule": {"kind": "recurring", "cron": "not a cron"},
                "session_id": "s-1",
                "content": "x",
            },
        )
        assert r.status_code == 422
        assert "cron" in r.text.lower()

    def test_create_one_shot_in_past_rejected(self, client: TestClient) -> None:
        r = client.post(
            "/api/v1/scheduled/tasks",
            json={
                "name": "Past",
                "type": "once",
                "schedule": {"kind": "once", "at": 1},
                "session_id": "s-1",
                "content": "x",
            },
        )
        assert r.status_code == 422

    def test_update_task(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/scheduled/tasks",
            json={
                "name": "Old",
                "type": "recurring",
                "schedule": {"kind": "recurring", "cron": "0 8 * * *"},
                "session_id": "s-1",
                "content": "x",
            },
        ).json()
        r = client.patch(
            f"/api/v1/scheduled/tasks/{created['id']}",
            json={"name": "New", "enabled": False},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "New"
        assert r.json()["enabled"] is False

    def test_update_missing_returns_404(self, client: TestClient) -> None:
        r = client.patch(
            "/api/v1/scheduled/tasks/task-missing",
            json={"name": "x"},
        )
        assert r.status_code == 404

    def test_delete_task(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/scheduled/tasks",
            json={
                "name": "Temp",
                "type": "recurring",
                "schedule": {"kind": "recurring", "cron": "0 8 * * *"},
                "session_id": "s-1",
                "content": "x",
            },
        ).json()
        r = client.delete(f"/api/v1/scheduled/tasks/{created['id']}")
        assert r.status_code == 204
        assert client.get("/api/v1/scheduled/tasks").json() == []

    def test_delete_missing_returns_404(self, client: TestClient) -> None:
        r = client.delete("/api/v1/scheduled/tasks/task-missing")
        assert r.status_code == 404

    def test_run_now_inserts_message(self, client: TestClient, message_repo: MagicMock) -> None:
        created = client.post(
            "/api/v1/scheduled/tasks",
            json={
                "name": "Manual",
                "type": "recurring",
                "schedule": {"kind": "recurring", "cron": "0 8 * * *"},
                "session_id": "s-1",
                "content": "go",
            },
        ).json()
        r = client.post(f"/api/v1/scheduled/tasks/{created['id']}/run")
        assert r.status_code == 200
        message_repo.insert.assert_called_once()
```

- [ ] **Step 2: Run test, verify RED**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_scheduled_api.py -x --no-header`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.api.scheduled_router'`

- [ ] **Step 3: No commit yet**

---

## Task 5: Backend — implement scheduled_router.py (GREEN)

**Files:**
- Create: `/home/fz/project/sage/backend/api/scheduled_router.py`

**Interfaces:**
- Consumes: FastAPI, pydantic, `SchedulerService`
- Produces: `APIRouter` factory `build_router(get_service)` returning router with endpoints: GET /health, GET /tasks, POST /tasks, PATCH /tasks/{id}, DELETE /tasks/{id}, POST /tasks/{id}/run

- [ ] **Step 1: Create router file with full implementation**

Create file `/home/fz/project/sage/backend/api/scheduled_router.py`:

```python
"""Scheduled tasks REST API.

Mount under ``/api/v1`` from ``backend/main.py``. Service dependency is injected
via a ``get_service`` callable so tests can supply an isolated instance with
mocked repos.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.services.scheduler import SchedulerService, TaskNotFoundError, ValidationError

logger = logging.getLogger(__name__)


# ---------- request / response models ----------


class ScheduleIn(BaseModel):
    kind: Literal["once", "recurring"]
    at: int | None = None
    cron: str | None = None


class ScheduleOut(BaseModel):
    kind: Literal["once", "recurring"]
    at: int | None = None
    cron: str | None = None


class CreateTaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: Literal["once", "recurring"]
    schedule: ScheduleIn
    session_id: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=4000)


class UpdateTaskIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    enabled: bool | None = None


class TaskOut(BaseModel):
    id: str
    name: str
    type: Literal["once", "recurring"]
    schedule: ScheduleOut
    session_id: str
    content: str
    enabled: bool
    created_at: int
    last_run: int | None = None
    next_run: int | None = None


def _task_to_dict(task: Any) -> dict[str, Any]:
    return {
        "id": task.id,
        "name": task.name,
        "type": task.type,
        "schedule": dict(task.schedule),
        "session_id": task.session_id,
        "content": task.content,
        "enabled": task.enabled,
        "created_at": task.created_at,
        "last_run": task.last_run,
        "next_run": task.next_run,
    }


def _schedule_in_to_dict(s: ScheduleIn) -> dict[str, Any]:
    if s.kind == "once":
        if s.at is None:
            raise ValueError("'at' is required for one-shot tasks")
        return {"kind": "once", "at": s.at}
    if not s.cron:
        raise ValueError("'cron' is required for recurring tasks")
    return {"kind": "recurring", "cron": s.cron}


# ---------- router factory ----------


def build_router(get_service: Callable[[], SchedulerService | None]) -> APIRouter:
    router = APIRouter()

    def service_dep() -> SchedulerService:
        svc = get_service()
        if svc is None:
            raise HTTPException(status_code=503, detail="scheduler not initialised")
        return svc

    @router.get("/scheduled/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/scheduled/tasks", response_model=list[TaskOut])
    def list_tasks(svc: SchedulerService = Depends(service_dep)) -> list[dict[str, Any]]:
        return [_task_to_dict(t) for t in svc.list_tasks()]

    @router.post("/scheduled/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
    def create_task(payload: CreateTaskIn, svc: SchedulerService = Depends(service_dep)) -> dict[str, Any]:
        try:
            schedule_dict = _schedule_in_to_dict(payload.schedule)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            task = svc.add_task(
                name=payload.name,
                task_type=payload.type,
                schedule=schedule_dict,
                session_id=payload.session_id,
                content=payload.content,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _task_to_dict(task)

    @router.patch("/scheduled/tasks/{task_id}", response_model=TaskOut)
    def update_task(
        task_id: str,
        payload: UpdateTaskIn,
        svc: SchedulerService = Depends(service_dep),
    ) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        if payload.name is not None:
            changes["name"] = payload.name
        if payload.enabled is not None:
            changes["enabled"] = payload.enabled
        try:
            return _task_to_dict(svc.update_task(task_id, **changes))
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.delete("/scheduled/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_task(task_id: str, svc: SchedulerService = Depends(service_dep)) -> None:
        try:
            svc.delete_task(task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/scheduled/tasks/{task_id}/run", response_model=TaskOut)
    def run_task(task_id: str, svc: SchedulerService = Depends(service_dep)) -> dict[str, Any]:
        try:
            svc.run_now(task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _task_to_dict(svc.get_task(task_id))

    return router
```

- [ ] **Step 2: Run integration tests, verify GREEN**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_scheduled_api.py -x --no-header`
Expected: All 10 tests pass.

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage
git add backend/api/scheduled_router.py backend/tests/integration/test_scheduled_api.py
git commit -m "feat(backend): scheduled_router with CRUD + run-now endpoints (Phase 8)"
```

---

## Task 6: Backend — wire scheduler into main.py lifespan

**Files:**
- Modify: `/home/fz/project/sage/backend/main.py`

**Interfaces:**
- Consumes: existing `lifespan` async context, `Database`, `SchedulerService`
- Produces: scheduler init on startup, router mounted, shutdown on app exit

- [ ] **Step 1: Add imports and constants to main.py**

Add immediately after the existing imports (after `from backend.data.database import Database`):

```python
from backend.api.scheduled_router import build_router as build_scheduled_router
from backend.data.message_repo import MessageRepository  # noqa: F401 — wired in scheduler init
from backend.data.session_repo import SessionRepository
from backend.services.scheduler import (
    get_scheduler_service,
    init_scheduler_service,
)
```

- [ ] **Step 2: Initialise scheduler in lifespan startup**

Inside `lifespan` (after `app.state.db = db`, before the chat-stream sweeper block), add:

```python
    # Phase 8: scheduled tasks service — load JSON, start APScheduler
    from pathlib import Path

    store_path = Path("backend/data/scheduled_tasks.json")
    scheduler_service = init_scheduler_service(
        store_path=store_path,
        message_repo=MessageRepository(),
        session_repo=SessionRepository(),
    )
    scheduler_service.start()
    app.state.scheduler = scheduler_service
    logger.info(
        "SchedulerService 已初始化并启动（%d 个任务）", len(scheduler_service.list_tasks())
    )
```

- [ ] **Step 3: Mount router for BOTH api modes**

After the if/elif/else block that conditionally mounts `legacy_router` and `hex_router`, add a single line that mounts the scheduled router regardless of API mode:

```python
# Phase 8: scheduled tasks — mounted for both API modes (independent feature)
app.include_router(build_scheduled_router(get_scheduler_service), prefix="/api/v1")
```

- [ ] **Step 4: Shut down scheduler in lifespan cleanup**

In the cleanup section after `yield`, before the orphan-stream cancellation, add:

```python
    # Phase 8: stop APScheduler cleanly so jobs do not fire after shutdown
    if hasattr(app.state, "scheduler") and app.state.scheduler is not None:
        app.state.scheduler.shutdown()
```

- [ ] **Step 5: Sanity import check**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -c "from backend.main import app; print('routes:', sorted([r.path for r in app.routes if 'scheduled' in r.path]))"`
Expected: prints `['/api/v1/scheduled/health', '/api/v1/scheduled/tasks', '/api/v1/scheduled/tasks/{task_id}', '/api/v1/scheduled/tasks/{task_id}/run']`.

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage
git add backend/main.py
git commit -m "feat(backend): mount scheduled_router and start scheduler in lifespan (Phase 8)"
```

---

## Task 7: Backend — MessageRepository.insert guard

**Files:**
- Modify: `/home/fz/project/sage/backend/data/session_repo.py`

**Interfaces:**
- Produces: `MessageRepository.insert(session_id, role, content, created_at)` method (used by `SchedulerService._fire`)

- [ ] **Step 1: Read existing MessageRepository**

Run: `grep -n "class MessageRepository\|def insert\|def add" /home/fz/project/sage/backend/data/session_repo.py | head -20`

If `MessageRepository.insert` already exists with a matching signature, skip to Step 3. Otherwise continue.

- [ ] **Step 2: Add or alias `insert` method**

Append to `/home/fz/project/sage/backend/data/session_repo.py` (inside `MessageRepository` class):

```python
    def insert(
        self,
        session_id: str,
        role: str,
        content: str,
        created_at: int,
    ) -> dict[str, Any]:
        """Insert a new message row and return the inserted record.

        The scheduler uses this to deliver one-shot/recurring task content
        into the target session. We deliberately bypass the LLM/agent path
        because scheduled messages are pre-formed (no streaming).
        """
        import uuid

        message_id = f"msg-{uuid.uuid4().hex[:12]}"
        with self._conn() as db:  # type: ignore[attr-defined]
            db.execute(
                "INSERT INTO messages (id, session_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (message_id, session_id, role, content, created_at),
            )
        return {"id": message_id}
```

> Note: if `MessageRepository` exposes an existing method under a different name (e.g. `add`), alias it: `insert = add`. Confirm exact attribute via Step 1 grep before writing.

- [ ] **Step 3: Smoke test insert via REPL**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -c "
from backend.data.session_repo import MessageRepository, SessionRepository
from backend.data.database import Database
db = Database(); db.init_db()
SessionRepository().create(title='phase8-smoke')
print('inserted:', MessageRepository().insert('s-smoke', 'system', 'hi', 1700000000000))
"
```
Expected: prints `inserted: {'id': 'msg-...'}`.

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage
git add backend/data/session_repo.py
git commit -m "feat(backend): ensure MessageRepository.insert signature for scheduler (Phase 8)"
```

---

## Task 8: Frontend — extend `types.ts` with `ScheduledTask` interface

**Files:**
- Modify: `/home/fz/project/sage/src/shared/api/types.ts`

**Interfaces:**
- Consumes: none (type-only addition)
- Produces: `ScheduledTask`, `Schedule`, `ScheduleKind`, `CreateTaskInput` exported types

- [ ] **Step 1: Append the new types to types.ts**

Open `/home/fz/project/sage/src/shared/api/types.ts` and append the following block at the end of the file:

```typescript
// ─── Scheduled Tasks (Phase 8) ───────────────────────────────

export type ScheduleKind = 'once' | 'recurring';

export type Schedule =
  | { kind: 'once'; at: number }
  | { kind: 'recurring'; cron: string };

export interface ScheduledTask {
  id: string;
  name: string;
  type: ScheduleKind;
  schedule: Schedule;
  session_id: string;
  content: string;
  enabled: boolean;
  last_run?: number | null;
  next_run?: number | null;
  created_at: number;
}

export interface CreateTaskInput {
  name: string;
  type: ScheduleKind;
  schedule: Schedule;
  session_id: string;
  content: string;
}

export interface UpdateTaskInput {
  name?: string;
  enabled?: boolean;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /home/fz/project/sage && npx tsc --noEmit -p tsconfig.json 2>&1 | head -20`
Expected: no errors related to `types.ts`.

- [ ] **Step 3: No commit** (combined with next task)

---

## Task 9: Frontend — cronValidator test scaffolding

**Files:**
- Create: `/home/fz/project/sage/src/features/scheduled/__tests__/cronValidator.test.ts`

**Interfaces:** None (tests only)

- [ ] **Step 1: Create directory**

```bash
mkdir -p /home/fz/project/sage/src/features/scheduled/__tests__
```

- [ ] **Step 2: Write test file (RED)**

Create file `/home/fz/project/sage/src/features/scheduled/__tests__/cronValidator.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';

import {
  validateCronExpression,
  validateOneShotTimestamp,
  describeSchedule,
  CRON_PRESETS,
} from '../cronValidator';

describe('validateCronExpression', () => {
  it('accepts a valid 5-field cron', () => {
    expect(validateCronExpression('0 8 * * *')).toEqual({ ok: true });
  });

  it('accepts step expressions', () => {
    expect(validateCronExpression('*/15 * * * *')).toEqual({ ok: true });
  });

  it('accepts every preset', () => {
    for (const preset of CRON_PRESETS) {
      const result = validateCronExpression(preset.cron);
      expect(result.ok, `preset ${preset.id} (${preset.cron}) should validate`).toBe(true);
    }
  });

  it('rejects empty string', () => {
    const result = validateCronExpression('');
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/empty/i);
  });

  it('rejects garbage input', () => {
    const result = validateCronExpression('not a cron');
    expect(result.ok).toBe(false);
  });

  it('rejects 6-field expressions (we only support 5-field)', () => {
    const result = validateCronExpression('0 0 8 * * *');
    expect(result.ok).toBe(false);
  });

  it('rejects out-of-range values', () => {
    expect(validateCronExpression('0 25 * * *').ok).toBe(false);
    expect(validateCronExpression('60 * * * *').ok).toBe(false);
  });

  it('trims whitespace before validating', () => {
    expect(validateCronExpression('   0 8 * * *   ').ok).toBe(true);
  });
});

describe('validateOneShotTimestamp', () => {
  it('accepts a future timestamp', () => {
    const future = Date.now() + 60_000;
    expect(validateOneShotTimestamp(future).ok).toBe(true);
  });

  it('rejects a past timestamp', () => {
    const past = Date.now() - 60_000;
    const result = validateOneShotTimestamp(past);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/past/i);
  });

  it('rejects non-finite values', () => {
    expect(validateOneShotTimestamp(Number.NaN).ok).toBe(false);
    expect(validateOneShotTimestamp(Number.POSITIVE_INFINITY).ok).toBe(false);
  });
});

describe('describeSchedule', () => {
  it('describes a recurring cron in user-friendly terms', () => {
    const text = describeSchedule({ kind: 'recurring', cron: '0 8 * * *' }, 'zh');
    expect(text).toMatch(/8|每天/);
  });

  it('describes a one-shot timestamp via Intl.DateTimeFormat', () => {
    const fixed = Date.UTC(2026, 5, 25, 8, 0, 0); // 2026-06-25 08:00 UTC
    const text = describeSchedule({ kind: 'once', at: fixed }, 'zh');
    expect(text.length).toBeGreaterThan(0);
  });

  it('returns Invalid cron placeholder for malformed expressions', () => {
    const text = describeSchedule({ kind: 'recurring', cron: 'garbage' }, 'en');
    expect(text.toLowerCase()).toMatch(/invalid|无效/);
  });
});
```

- [ ] **Step 3: Run test, verify RED**

Run: `cd /home/fz/project/sage && npx vitest run src/features/scheduled/__tests__/cronValidator.test.ts`
Expected: FAIL with `Cannot find module '../cronValidator'`

- [ ] **Step 4: No commit yet**

---

## Task 10: Frontend — implement cronValidator.ts (GREEN)

**Files:**
- Create: `/home/fz/project/sage/src/features/scheduled/cronValidator.ts`

**Interfaces:**
- Consumes: nothing (pure functions)
- Produces: `validateCronExpression`, `validateOneShotTimestamp`, `describeSchedule`, `CRON_PRESETS`

- [ ] **Step 1: Create cronValidator.ts**

Create file `/home/fz/project/sage/src/features/scheduled/cronValidator.ts`:

```typescript
/**
 * Cron expression validation and human-readable descriptions.
 *
 * No third-party deps — we re-implement the small subset of cron syntax
 * we need. Supported format: 5-field standard cron
 *   minute hour day-of-month month day-of-week
 * with `*`, integer lists (`1,15`), ranges (`1-5`), and steps (`*/15`).
 *
 * Display layer uses Intl.DateTimeFormat for locale-aware formatting.
 */

export type ValidationResult =
  | { ok: true }
  | { ok: false; reason: string };

export interface CronPreset {
  id: string;
  labelKey: string; // i18n key for human label
  cron: string;
}

export const CRON_PRESETS: readonly CronPreset[] = [
  { id: 'hourly', labelKey: 'cron.preset.hourly', cron: '0 * * * *' },
  { id: 'daily-08', labelKey: 'cron.preset.daily08', cron: '0 8 * * *' },
  { id: 'daily-18', labelKey: 'cron.preset.daily18', cron: '0 18 * * *' },
  { id: 'weekday-09', labelKey: 'cron.preset.weekday09', cron: '0 9 * * 1-5' },
  { id: 'weekly-mon', labelKey: 'cron.preset.weeklyMon', cron: '0 9 * * 1' },
  { id: 'monthly-1st', labelKey: 'cron.preset.monthly1st', cron: '0 9 1 * *' },
];

const FIELD_RANGES = [
  { min: 0, max: 59 }, // minute
  { min: 0, max: 23 }, // hour
  { min: 1, max: 31 }, // day of month
  { min: 1, max: 12 }, // month
  { min: 0, max: 6 }, // day of week (0 = Sunday)
] as const;

function validateField(value: string, min: number, max: number): boolean {
  if (value === '*') return true;
  for (const part of value.split(',')) {
    let body = part;
    let step = 1;
    if (body.includes('/')) {
      const [base, stepStr] = body.split('/');
      const parsedStep = Number(stepStr);
      if (!Number.isInteger(parsedStep) || parsedStep < 1) return false;
      step = parsedStep;
      body = base === '' ? '*' : base;
    }
    if (body === '*') {
      if (step > max - min + 1) return false;
      continue;
    }
    if (body.includes('-')) {
      const [lo, hi] = body.split('-').map(Number);
      if (!Number.isInteger(lo) || !Number.isInteger(hi)) return false;
      if (lo < min || hi > max || lo > hi) return false;
      if (step > hi - lo + 1) return false;
      continue;
    }
    const num = Number(body);
    if (!Number.isInteger(num) || num < min || num > max) return false;
  }
  return true;
}

export function validateCronExpression(input: string): ValidationResult {
  const trimmed = (input ?? '').trim();
  if (trimmed === '') return { ok: false, reason: 'Cron expression must not be empty' };
  const parts = trimmed.split(/\s+/);
  if (parts.length !== 5) {
    return { ok: false, reason: `Expected 5 fields, got ${parts.length}` };
  }
  for (let i = 0; i < parts.length; i++) {
    if (!validateField(parts[i], FIELD_RANGES[i].min, FIELD_RANGES[i].max)) {
      return { ok: false, reason: `Field ${i + 1} is out of range or malformed` };
    }
  }
  return { ok: true };
}

export function validateOneShotTimestamp(atMs: number): ValidationResult {
  if (!Number.isFinite(atMs) || atMs === Number.POSITIVE_INFINITY) {
    return { ok: false, reason: 'Timestamp must be a finite number' };
  }
  if (atMs <= Date.now()) {
    return { ok: false, reason: 'One-shot time must be in the future' };
  }
  return { ok: true };
}

const ZH_LOCALE = 'zh-CN';

function formatDateTime(ms: number, locale: 'zh' | 'en'): string {
  const intlLocale = locale === 'zh' ? ZH_LOCALE : 'en-US';
  return new Intl.DateTimeFormat(intlLocale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(ms));
}

export function describeSchedule(
  schedule: { kind: 'once'; at: number } | { kind: 'recurring'; cron: string },
  locale: 'zh' | 'en' = 'zh',
): string {
  if (schedule.kind === 'once') {
    return formatDateTime(schedule.at, locale);
  }
  const validation = validateCronExpression(schedule.cron);
  if (!validation.ok) {
    return locale === 'zh' ? '无效的 Cron 表达式' : 'Invalid cron expression';
  }
  const preset = CRON_PRESETS.find((p) => p.cron === schedule.cron);
  if (preset) {
    return `[${preset.id}] ${schedule.cron}`;
  }
  return `cron: ${schedule.cron}`;
}
```

- [ ] **Step 2: Run tests, verify GREEN**

Run: `cd /home/fz/project/sage && npx vitest run src/features/scheduled/__tests__/cronValidator.test.ts`
Expected: All tests pass (~17 tests).

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage
git add src/features/scheduled/cronValidator.ts src/features/scheduled/__tests__/cronValidator.test.ts
git commit -m "feat(scheduled): cronValidator with presets + describe (Phase 8)"
```

---

## Task 11: Frontend — scheduledClient test scaffolding

**Files:**
- Create: `/home/fz/project/sage/src/shared/api/__tests__/scheduledClient.test.ts`

**Interfaces:** None (tests only)

- [ ] **Step 1: Write test file (RED)**

Create file `/home/fz/project/sage/src/shared/api/__tests__/scheduledClient.test.ts`:

```typescript
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../desktopInvoke', () => ({
  invoke: vi.fn(),
}));

import { invoke } from '../desktopInvoke';
import { scheduledClient } from '../scheduledClient';

const invokeMock = invoke as unknown as ReturnType<typeof vi.fn>;

describe('scheduledClient', () => {
  afterEach(() => {
    invokeMock.mockReset();
  });

  it('list() invokes scheduled_list_tasks and returns array', async () => {
    invokeMock.mockResolvedValueOnce([]);
    const result = await scheduledClient.list();
    expect(invokeMock).toHaveBeenCalledWith('scheduled_list_tasks', {});
    expect(result).toEqual([]);
  });

  it('create() posts scheduled_create_task payload', async () => {
    const fixture = {
      id: 'task-1',
      name: 'x',
      type: 'once' as const,
      schedule: { kind: 'once' as const, at: Date.now() + 60_000 },
      session_id: 's-1',
      content: 'hi',
      enabled: true,
      created_at: Date.now(),
    };
    invokeMock.mockResolvedValueOnce(fixture);
    await scheduledClient.create({
      name: 'x',
      type: 'once',
      schedule: { kind: 'once', at: Date.now() + 60_000 },
      session_id: 's-1',
      content: 'hi',
    });
    expect(invokeMock.mock.calls[0][0]).toBe('scheduled_create_task');
  });

  it('update() sends id and changes via invoke', async () => {
    invokeMock.mockResolvedValueOnce({});
    await scheduledClient.update('task-1', { enabled: false });
    expect(invokeMock.mock.calls[0][0]).toBe('scheduled_update_task');
    expect(invokeMock.mock.calls[0][1]).toEqual({ id: 'task-1', changes: { enabled: false } });
  });

  it('delete() sends id and resolves when invoke resolves', async () => {
    invokeMock.mockResolvedValueOnce(undefined);
    await scheduledClient.delete('task-1');
    expect(invokeMock.mock.calls[0][0]).toBe('scheduled_delete_task');
    expect(invokeMock.mock.calls[0][1]).toEqual({ id: 'task-1' });
  });

  it('runNow() invokes scheduled_run_task', async () => {
    invokeMock.mockResolvedValueOnce({});
    await scheduledClient.runNow('task-1');
    expect(invokeMock.mock.calls[0][0]).toBe('scheduled_run_task');
    expect(invokeMock.mock.calls[0][1]).toEqual({ id: 'task-1' });
  });

  it('propagates errors from invoke', async () => {
    invokeMock.mockRejectedValueOnce(new Error('boom'));
    await expect(scheduledClient.list()).rejects.toThrow('boom');
  });
});
```

- [ ] **Step 2: Run test, verify RED**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/scheduledClient.test.ts`
Expected: FAIL with `Cannot find module '../scheduledClient'`

- [ ] **Step 3: No commit yet**

---

## Task 12: Frontend — implement scheduledClient.ts (GREEN)

**Files:**
- Create: `/home/fz/project/sage/src/shared/api/scheduledClient.ts`

**Interfaces:**
- Consumes: `invoke` from `desktopInvoke`, `ScheduledTask`, `CreateTaskInput`, `UpdateTaskInput`
- Produces: `scheduledClient` object with `list`, `create`, `update`, `delete`, `runNow`

- [ ] **Step 1: Create scheduledClient.ts**

Create file `/home/fz/project/sage/src/shared/api/scheduledClient.ts`:

```typescript
/**
 * IPC client for scheduled tasks (Phase 8).
 *
 * Translates to backend HTTP via Electron preload:
 *   scheduled_list_tasks   → GET  /api/v1/scheduled/tasks
 *   scheduled_create_task  → POST /api/v1/scheduled/tasks
 *   scheduled_update_task  → PATCH /api/v1/scheduled/tasks/{id}
 *   scheduled_delete_task  → DELETE /api/v1/scheduled/tasks/{id}
 *   scheduled_run_task     → POST /api/v1/scheduled/tasks/{id}/run
 *
 * All methods throw on IPC failure; callers should wrap in try/catch and
 * surface a toast on failure.
 */
import type { CreateTaskInput, ScheduledTask, UpdateTaskInput } from './types';
import { invoke } from './desktopInvoke';

export const scheduledClient = {
  async list(): Promise<ScheduledTask[]> {
    return invoke<ScheduledTask[]>('scheduled_list_tasks', {});
  },

  async create(input: CreateTaskInput): Promise<ScheduledTask> {
    return invoke<ScheduledTask>('scheduled_create_task', { input });
  },

  async update(id: string, changes: UpdateTaskInput): Promise<ScheduledTask> {
    return invoke<ScheduledTask>('scheduled_update_task', { id, changes });
  },

  async delete(id: string): Promise<void> {
    await invoke<void>('scheduled_delete_task', { id });
  },

  async runNow(id: string): Promise<ScheduledTask> {
    return invoke<ScheduledTask>('scheduled_run_task', { id });
  },
};
```

- [ ] **Step 2: Run tests, verify GREEN**

Run: `cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/scheduledClient.test.ts`
Expected: All 6 tests pass.

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage
git add src/shared/api/scheduledClient.ts src/shared/api/__tests__/scheduledClient.test.ts
git commit -m "feat(api): scheduledClient IPC wrapper (Phase 8)"
```

---

## Task 13: Frontend — taskStore test scaffolding

**Files:**
- Create: `/home/fz/project/sage/src/entities/scheduled/__tests__/taskStore.test.ts`

**Interfaces:** None (tests only)

- [ ] **Step 1: Create directory**

```bash
mkdir -p /home/fz/project/sage/src/entities/scheduled/__tests__
```

- [ ] **Step 2: Write test file (RED)**

Create file `/home/fz/project/sage/src/entities/scheduled/__tests__/taskStore.test.ts`:

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/scheduledClient', () => ({
  scheduledClient: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    runNow: vi.fn(),
  },
}));

import { scheduledClient } from '../../../shared/api/scheduledClient';
import { useScheduledTaskStore } from '../taskStore';

const client = scheduledClient as unknown as {
  list: ReturnType<typeof vi.fn>;
  create: ReturnType<typeof vi.fn>;
  update: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
  runNow: ReturnType<typeof vi.fn>;
};

const sampleTask = {
  id: 'task-1',
  name: 'Demo',
  type: 'recurring' as const,
  schedule: { kind: 'recurring' as const, cron: '0 8 * * *' },
  session_id: 's-1',
  content: 'go',
  enabled: true,
  created_at: 1_700_000_000_000,
  last_run: null,
  next_run: 1_700_000_000_000,
};

describe('useScheduledTaskStore', () => {
  beforeEach(() => {
    useScheduledTaskStore.setState({ tasks: [], loading: false, error: null });
    client.list.mockReset();
    client.create.mockReset();
    client.update.mockReset();
    client.delete.mockReset();
    client.runNow.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('starts empty', () => {
    expect(useScheduledTaskStore.getState().tasks).toEqual([]);
  });

  it('load() fetches and stores tasks', async () => {
    client.list.mockResolvedValueOnce([sampleTask]);
    await useScheduledTaskStore.getState().load();
    expect(useScheduledTaskStore.getState().tasks).toEqual([sampleTask]);
    expect(useScheduledTaskStore.getState().loading).toBe(false);
  });

  it('load() sets error string on failure and clears tasks', async () => {
    client.list.mockRejectedValueOnce(new Error('boom'));
    await useScheduledTaskStore.getState().load();
    expect(useScheduledTaskStore.getState().error).toBe('boom');
    expect(useScheduledTaskStore.getState().tasks).toEqual([]);
  });

  it('create() appends returned task', async () => {
    client.create.mockResolvedValueOnce({ ...sampleTask, id: 'task-2' });
    await useScheduledTaskStore.getState().create({
      name: 'New',
      type: 'recurring',
      schedule: { kind: 'recurring', cron: '0 8 * * *' },
      session_id: 's-1',
      content: 'hi',
    });
    const ids = useScheduledTaskStore.getState().tasks.map((t) => t.id);
    expect(ids).toContain('task-2');
  });

  it('update() replaces task by id', async () => {
    client.list.mockResolvedValueOnce([sampleTask]);
    await useScheduledTaskStore.getState().load();
    const updated = { ...sampleTask, enabled: false };
    client.update.mockResolvedValueOnce(updated);
    await useScheduledTaskStore.getState().update('task-1', { enabled: false });
    expect(useScheduledTaskStore.getState().tasks[0].enabled).toBe(false);
  });

  it('delete() removes task by id', async () => {
    client.list.mockResolvedValueOnce([sampleTask]);
    await useScheduledTaskStore.getState().load();
    client.delete.mockResolvedValueOnce(undefined);
    await useScheduledTaskStore.getState().delete('task-1');
    expect(useScheduledTaskStore.getState().tasks).toEqual([]);
  });

  it('delete() surfaces error and keeps state on failure', async () => {
    client.list.mockResolvedValueOnce([sampleTask]);
    await useScheduledTaskStore.getState().load();
    client.delete.mockRejectedValueOnce(new Error('nope'));
    await useScheduledTaskStore.getState().delete('task-1');
    expect(useScheduledTaskStore.getState().error).toBe('nope');
    expect(useScheduledTaskStore.getState().tasks).toHaveLength(1);
  });
});
```

- [ ] **Step 3: Run test, verify RED**

Run: `cd /home/fz/project/sage && npx vitest run src/entities/scheduled/__tests__/taskStore.test.ts`
Expected: FAIL with `Cannot find module '../taskStore'`

- [ ] **Step 4: No commit yet**

---

## Task 14: Frontend — implement taskStore.ts (GREEN)

**Files:**
- Create: `/home/fz/project/sage/src/entities/scheduled/taskStore.ts`

**Interfaces:**
- Consumes: `scheduledClient`, `CreateTaskInput`, `UpdateTaskInput`, `ScheduledTask`
- Produces: `useScheduledTaskStore` Zustand store

- [ ] **Step 1: Create taskStore.ts**

Create file `/home/fz/project/sage/src/entities/scheduled/taskStore.ts`:

```typescript
import { create } from 'zustand';

import type { CreateTaskInput, ScheduledTask, UpdateTaskInput } from '../../shared/api/types';
import { scheduledClient } from '../../shared/api/scheduledClient';

interface ScheduledTaskState {
  tasks: ScheduledTask[];
  loading: boolean;
  error: string | null;
  load: () => Promise<void>;
  create: (input: CreateTaskInput) => Promise<ScheduledTask>;
  update: (id: string, changes: UpdateTaskInput) => Promise<ScheduledTask>;
  delete: (id: string) => Promise<void>;
  runNow: (id: string) => Promise<ScheduledTask>;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export const useScheduledTaskStore = create<ScheduledTaskState>((set, get) => ({
  tasks: [],
  loading: false,
  error: null,

  async load() {
    set({ loading: true, error: null });
    try {
      const tasks = await scheduledClient.list();
      set({ tasks, loading: false });
    } catch (error: unknown) {
      set({ tasks: [], loading: false, error: getErrorMessage(error) });
    }
  },

  async create(input: CreateTaskInput) {
    const task = await scheduledClient.create(input);
    set({ tasks: [...get().tasks, task] });
    return task;
  },

  async update(id: string, changes: UpdateTaskInput) {
    const updated = await scheduledClient.update(id, changes);
    set({
      tasks: get().tasks.map((t) => (t.id === id ? updated : t)),
    });
    return updated;
  },

  async delete(id: string) {
    try {
      await scheduledClient.delete(id);
      set({ tasks: get().tasks.filter((t) => t.id !== id), error: null });
    } catch (error: unknown) {
      set({ error: getErrorMessage(error) });
      throw error;
    }
  },

  async runNow(id: string) {
    const updated = await scheduledClient.runNow(id);
    set({
      tasks: get().tasks.map((t) => (t.id === id ? updated : t)),
    });
    return updated;
  },
}));
```

- [ ] **Step 2: Run tests, verify GREEN**

Run: `cd /home/fz/project/sage && npx vitest run src/entities/scheduled/__tests__/taskStore.test.ts`
Expected: All 7 tests pass.

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage
git add src/entities/scheduled/taskStore.ts src/entities/scheduled/__tests__/taskStore.test.ts
git commit -m "feat(scheduled): Zustand taskStore with CRUD + runNow (Phase 8)"
```

---

## Task 15: Frontend — i18n keys (zh + en)

**Files:**
- Modify: `/home/fz/project/sage/src/shared/lib/i18n/zh.ts`
- Modify: `/home/fz/project/sage/src/shared/lib/i18n/en.ts`

**Interfaces:**
- Produces: 22 new translation keys

- [ ] **Step 1: Append keys to zh.ts**

Append the following block before the closing `} as const;` in `/home/fz/project/sage/src/shared/lib/i18n/zh.ts`:

```typescript

  // ─── 定时任务 (Phase 8) ───────────
  'scheduled.title': '定时任务',
  'scheduled.subtitle': '管理自动发送的消息',
  'scheduled.empty': '还没有定时任务，点击下方按钮创建一个。',
  'scheduled.create': '新建任务',
  'scheduled.edit': '编辑任务',
  'scheduled.field.name': '任务名称',
  'scheduled.field.type': '类型',
  'scheduled.field.type.once': '执行一次',
  'scheduled.field.type.recurring': '周期',
  'scheduled.field.cron': 'Cron 表达式',
  'scheduled.field.at': '执行时间',
  'scheduled.field.session': '目标会话',
  'scheduled.field.content': '发送内容',
  'scheduled.field.enabled': '启用',
  'scheduled.status.enabled': '已启用',
  'scheduled.status.disabled': '已停用',
  'scheduled.action.run_now': '立即执行',
  'scheduled.toast.create_fail': '创建失败',
  'scheduled.toast.update_fail': '更新失败',
  'scheduled.toast.delete_fail': '删除失败',
  'scheduled.confirm.delete': '确定要删除这个定时任务吗？',
```

- [ ] **Step 2: Append keys to en.ts**

Append the following block before the closing `};` in `/home/fz/project/sage/src/shared/lib/i18n/en.ts`:

```typescript

  // ─── Scheduled Tasks (Phase 8) ─────
  'scheduled.title': 'Scheduled Tasks',
  'scheduled.subtitle': 'Manage automated messages',
  'scheduled.empty': 'No scheduled tasks yet — create one below.',
  'scheduled.create': 'New Task',
  'scheduled.edit': 'Edit Task',
  'scheduled.field.name': 'Task name',
  'scheduled.field.type': 'Type',
  'scheduled.field.type.once': 'Run once',
  'scheduled.field.type.recurring': 'Recurring',
  'scheduled.field.cron': 'Cron expression',
  'scheduled.field.at': 'Run at',
  'scheduled.field.session': 'Target session',
  'scheduled.field.content': 'Message content',
  'scheduled.field.enabled': 'Enabled',
  'scheduled.status.enabled': 'Enabled',
  'scheduled.status.disabled': 'Disabled',
  'scheduled.action.run_now': 'Run now',
  'scheduled.toast.create_fail': 'Failed to create task',
  'scheduled.toast.update_fail': 'Failed to update task',
  'scheduled.toast.delete_fail': 'Failed to delete task',
  'scheduled.confirm.delete': 'Delete this scheduled task?',
```

- [ ] **Step 3: Run tsc to confirm both files compile**

Run: `cd /home/fz/project/sage && npx tsc --noEmit -p tsconfig.json 2>&1 | head -20`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage
git add src/shared/lib/i18n/zh.ts src/shared/lib/i18n/en.ts
git commit -m "feat(i18n): add 22 scheduled-task translation keys (Phase 8)"
```

---

## Task 16: Frontend — CronExpressionPicker test scaffolding

**Files:**
- Create: `/home/fz/project/sage/src/features/scheduled/__tests__/CronExpressionPicker.test.tsx`

**Interfaces:** None (tests only)

- [ ] **Step 1: Write test file (RED)**

Create file `/home/fz/project/sage/src/features/scheduled/__tests__/CronExpressionPicker.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { CronExpressionPicker } from '../CronExpressionPicker';

describe('CronExpressionPicker', () => {
  it('renders preset chips and a custom input', () => {
    render(<CronExpressionPicker value="" onChange={() => {}} />);
    expect(screen.getAllByTestId(/^cron-preset-/).length).toBeGreaterThan(0);
    expect(screen.getByTestId('cron-input')).toBeTruthy();
  });

  it('clicking a preset calls onChange with the preset cron', () => {
    const onChange = vi.fn();
    render(<CronExpressionPicker value="" onChange={onChange} />);
    fireEvent.click(screen.getByTestId('cron-preset-hourly'));
    expect(onChange).toHaveBeenCalledWith('0 * * * *');
  });

  it('typing in custom input calls onChange with the new value', () => {
    const onChange = vi.fn();
    render(<CronExpressionPicker value="" onChange={onChange} />);
    const input = screen.getByTestId('cron-input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '0 8 * * *' } });
    expect(onChange).toHaveBeenCalledWith('0 8 * * *');
  });

  it('shows inline error when custom cron is invalid', () => {
    render(<CronExpressionPicker value="garbage" onChange={() => {}} />);
    expect(screen.getByTestId('cron-error')).toBeTruthy();
  });

  it('does not show error when value is a valid cron', () => {
    render(<CronExpressionPicker value="0 8 * * *" onChange={() => {}} />);
    expect(screen.queryByTestId('cron-error')).toBeNull();
  });
});
```

- [ ] **Step 2: Run test, verify RED**

Run: `cd /home/fz/project/sage && npx vitest run src/features/scheduled/__tests__/CronExpressionPicker.test.tsx`
Expected: FAIL with `Cannot find module '../CronExpressionPicker'`

- [ ] **Step 3: No commit yet**

---

## Task 17: Frontend — implement CronExpressionPicker.tsx (GREEN)

**Files:**
- Create: `/home/fz/project/sage/src/features/scheduled/CronExpressionPicker.tsx`

**Interfaces:**
- Consumes: `validateCronExpression`, `CRON_PRESETS`, `useI18n` (returns `t`)
- Produces: `CronExpressionPicker` React component

- [ ] **Step 1: Create CronExpressionPicker.tsx**

Create file `/home/fz/project/sage/src/features/scheduled/CronExpressionPicker.tsx`:

```tsx
import { useMemo } from 'react';

import { useI18n } from '../../shared/lib/i18n';

import { CRON_PRESETS, validateCronExpression } from './cronValidator';

interface CronExpressionPickerProps {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}

export function CronExpressionPicker({ value, onChange, disabled = false }: CronExpressionPickerProps) {
  const { t } = useI18n();
  const validation = useMemo(() => validateCronExpression(value), [value]);

  return (
    <div className="flex flex-col gap-2" data-testid="cron-picker">
      <div className="flex flex-wrap gap-1.5">
        {CRON_PRESETS.map((preset) => {
          const active = preset.cron === value;
          return (
            <button
              key={preset.id}
              type="button"
              disabled={disabled}
              onClick={() => onChange(preset.cron)}
              className={[
                'px-2.5 py-1 rounded-radius-sm text-xs border transition-colors',
                active
                  ? 'bg-primary/10 border-primary text-primary'
                  : 'bg-surface border-border text-text-secondary hover:bg-bg-hover',
              ].join(' ')}
              data-testid={`cron-preset-${preset.id}`}
            >
              {t(preset.labelKey as never)}
            </button>
          );
        })}
      </div>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder="0 8 * * *"
        className="border border-border rounded-radius-sm px-2 py-1.5 text-sm bg-bg"
        data-testid="cron-input"
      />
      {!validation.ok && (
        <p className="text-xs text-error" data-testid="cron-error">
          {validation.reason}
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Run tests, verify GREEN**

Run: `cd /home/fz/project/sage && npx vitest run src/features/scheduled/__tests__/CronExpressionPicker.test.tsx`
Expected: All 5 tests pass.

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage
git add src/features/scheduled/CronExpressionPicker.tsx src/features/scheduled/__tests__/CronExpressionPicker.test.tsx
git commit -m "feat(scheduled): CronExpressionPicker with presets + validation (Phase 8)"
```

---

## Task 18: Frontend — CreateTaskModal test scaffolding

**Files:**
- Create: `/home/fz/project/sage/src/features/scheduled/__tests__/CreateTaskModal.test.tsx`

**Interfaces:** None (tests only)

- [ ] **Step 1: Write test file (RED)**

Create file `/home/fz/project/sage/src/features/scheduled/__tests__/CreateTaskModal.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../../../entities/scheduled/taskStore', () => {
  const state = {
    tasks: [],
    loading: false,
    error: null,
    load: vi.fn(),
    create: vi.fn().mockResolvedValue({}),
    update: vi.fn().mockResolvedValue({}),
    delete: vi.fn(),
    runNow: vi.fn(),
  };
  const hook = (sel?: (s: unknown) => unknown) => (sel ? sel(state) : state);
  return {
    useScheduledTaskStore: Object.assign(hook, { getState: () => state, setState: vi.fn() }),
  };
});

import { I18nProvider } from '../../../shared/lib/i18n';
import { useScheduledTaskStore } from '../../../entities/scheduled/taskStore';
import { CreateTaskModal } from '../CreateTaskModal';

function renderModal(props: Partial<React.ComponentProps<typeof CreateTaskModal>> = {}) {
  return render(
    <I18nProvider>
      <CreateTaskModal
        open={true}
        onClose={vi.fn()}
        sessionId="s-1"
        {...props}
      />
    </I18nProvider>,
  );
}

describe('CreateTaskModal', () => {
  it('submit disabled until name and cron are filled', () => {
    renderModal();
    const submit = screen
      .getAllByRole('button')
      .find((b) => b.getAttribute('type') === 'submit') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });

  it('clicking cancel calls onClose', () => {
    const onClose = vi.fn();
    renderModal({ onClose });
    fireEvent.click(screen.getByText(/common\.cancel|取消|Cancel/i));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('filling name + cron enables submit, submit calls create() and onClose', async () => {
    const onClose = vi.fn();
    renderModal({ onClose });

    const nameInput = screen.getByPlaceholderText(/scheduled\.field\.name|Task name|任务名称/i);
    fireEvent.change(nameInput, { target: { value: 'My task' } });

    fireEvent.click(screen.getByTestId('cron-preset-hourly'));

    await waitFor(() => {
      const submit = screen
        .getAllByRole('button')
        .find((b) => b.getAttribute('type') === 'submit') as HTMLButtonElement;
      expect(submit.disabled).toBe(false);
    });

    const submit = screen
      .getAllByRole('button')
      .find((b) => b.getAttribute('type') === 'submit') as HTMLButtonElement;
    fireEvent.click(submit);

    await waitFor(() => {
      const state = useScheduledTaskStore.getState();
      expect(state.create).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  it('edit mode prefills values from existing task and calls update()', async () => {
    const onClose = vi.fn();
    const existing = {
      id: 'task-1',
      name: 'Old name',
      type: 'recurring' as const,
      schedule: { kind: 'recurring' as const, cron: '0 8 * * *' },
      session_id: 's-1',
      content: 'hi',
      enabled: true,
      created_at: 0,
    };

    renderModal({ onClose, task: existing });

    const nameInput = screen.getByPlaceholderText(/scheduled\.field\.name|Task name|任务名称/i) as HTMLInputElement;
    expect(nameInput.value).toBe('Old name');

    fireEvent.change(nameInput, { target: { value: 'Renamed' } });

    const submit = screen
      .getAllByRole('button')
      .find((b) => b.getAttribute('type') === 'submit') as HTMLButtonElement;
    fireEvent.click(submit);

    await waitFor(() => {
      const state = useScheduledTaskStore.getState();
      expect(state.update).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  it('shows server error inline when create throws', async () => {
    // Override the mock for this test only
    const failingState = {
      tasks: [],
      loading: false,
      error: null,
      load: vi.fn(),
      create: vi.fn().mockRejectedValue(new Error('cron invalid')),
      update: vi.fn().mockResolvedValue({}),
      delete: vi.fn(),
      runNow: vi.fn(),
    };
    (useScheduledTaskStore as unknown as { getState: () => typeof failingState }).getState =
      () => failingState;

    renderModal();

    fireEvent.change(screen.getByPlaceholderText(/scheduled\.field\.name|Task name|任务名称/i), {
      target: { value: 'X' },
    });
    fireEvent.click(screen.getByTestId('cron-preset-hourly'));

    const submit = screen
      .getAllByRole('button')
      .find((b) => b.getAttribute('type') === 'submit') as HTMLButtonElement;
    fireEvent.click(submit);

    await waitFor(() => {
      expect(screen.getByText('cron invalid')).toBeTruthy();
    });
  });
});
```

- [ ] **Step 2: Run test, verify RED**

Run: `cd /home/fz/project/sage && npx vitest run src/features/scheduled/__tests__/CreateTaskModal.test.tsx`
Expected: FAIL with `Cannot find module '../CreateTaskModal'`

- [ ] **Step 3: No commit yet**

---

## Task 19: Frontend — implement CreateTaskModal.tsx (GREEN)

**Files:**
- Create: `/home/fz/project/sage/src/features/scheduled/CreateTaskModal.tsx`

**Interfaces:**
- Consumes: `useScheduledTaskStore`, `CronExpressionPicker`, `useI18n`, `validateCronExpression`, `validateOneShotTimestamp`, sonner `toast`
- Produces: `CreateTaskModal` React component (create + edit)

- [ ] **Step 1: Create CreateTaskModal.tsx**

Create file `/home/fz/project/sage/src/features/scheduled/CreateTaskModal.tsx`:

```tsx
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { useScheduledTaskStore } from '../../entities/scheduled/taskStore';
import { useI18n } from '../../shared/lib/i18n';
import type { CreateTaskInput, ScheduledTask } from '../../shared/api/types';

import { CronExpressionPicker } from './CronExpressionPicker';
import { validateCronExpression, validateOneShotTimestamp } from './cronValidator';

interface CreateTaskModalProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  task?: ScheduledTask;
}

function toLocalDatetimeInput(ms: number): string {
  const date = new Date(ms);
  const tz = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - tz).toISOString().slice(0, 16);
}

function fromLocalDatetimeInput(value: string): number {
  return new Date(value).getTime();
}

export function CreateTaskModal({ open, onClose, sessionId, task }: CreateTaskModalProps) {
  const { t } = useI18n();
  const store = useScheduledTaskStore();
  const isEdit = Boolean(task);

  const [name, setName] = useState(task?.name ?? '');
  const [type, setType] = useState<'once' | 'recurring'>(task?.type ?? 'recurring');
  const [cron, setCron] = useState(
    task?.schedule.kind === 'recurring' ? task.schedule.cron : '0 8 * * *',
  );
  const [atLocal, setAtLocal] = useState(() =>
    task?.schedule.kind === 'once' ? toLocalDatetimeInput(task.schedule.at) : toLocalDatetimeInput(Date.now() + 60_000),
  );
  const [content, setContent] = useState(task?.content ?? '');
  const [enabled, setEnabled] = useState(task?.enabled ?? true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setSubmitting(false);
  }, [open]);

  const cronValidation = useMemo(() => validateCronExpression(cron), [cron]);
  const atMs = useMemo(() => fromLocalDatetimeInput(atLocal), [atLocal]);
  const atValidation = useMemo(() => validateOneShotTimestamp(atMs), [atMs]);

  const canSubmit =
    name.trim().length > 0 &&
    content.length > 0 &&
    (type === 'recurring' ? cronValidation.ok : atValidation.ok) &&
    !submitting;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    const schedule: CreateTaskInput['schedule'] =
      type === 'recurring'
        ? { kind: 'recurring', cron }
        : { kind: 'once', at: atMs };

    try {
      if (isEdit && task) {
        await store.update(task.id, { name, enabled });
        toast.success(t('scheduled.edit'));
      } else {
        await store.create({ name, type, schedule, session_id: sessionId, content });
        toast.success(t('scheduled.create'));
      }
      onClose();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      toast.error(isEdit ? t('scheduled.toast.update_fail') : t('scheduled.toast.create_fail'));
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="bg-surface border border-border rounded-radius-md w-[460px] max-w-[92vw] p-5 shadow-xl flex flex-col gap-3"
      >
        <h2 className="text-base font-semibold text-text">
          {isEdit ? t('scheduled.edit') : t('scheduled.create')}
        </h2>

        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          <span>{t('scheduled.field.name')}</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="border border-border rounded-radius-sm px-2 py-1.5 text-sm bg-bg"
            placeholder={t('scheduled.field.name')}
            required
          />
        </label>

        <div className="flex gap-2 text-xs">
          <button
            type="button"
            onClick={() => setType('once')}
            className={`flex-1 py-1.5 rounded-radius-sm border ${
              type === 'once'
                ? 'bg-primary/10 border-primary text-primary'
                : 'bg-surface border-border text-text-secondary'
            }`}
          >
            {t('scheduled.field.type.once')}
          </button>
          <button
            type="button"
            onClick={() => setType('recurring')}
            className={`flex-1 py-1.5 rounded-radius-sm border ${
              type === 'recurring'
                ? 'bg-primary/10 border-primary text-primary'
                : 'bg-surface border-border text-text-secondary'
            }`}
          >
            {t('scheduled.field.type.recurring')}
          </button>
        </div>

        {type === 'recurring' ? (
          <div className="flex flex-col gap-1 text-xs text-text-secondary">
            <span>{t('scheduled.field.cron')}</span>
            <CronExpressionPicker value={cron} onChange={setCron} disabled={submitting} />
          </div>
        ) : (
          <label className="flex flex-col gap-1 text-xs text-text-secondary">
            <span>{t('scheduled.field.at')}</span>
            <input
              type="datetime-local"
              value={atLocal}
              onChange={(e) => setAtLocal(e.target.value)}
              className="border border-border rounded-radius-sm px-2 py-1.5 text-sm bg-bg"
            />
            {!atValidation.ok && <p className="text-error">{atValidation.reason}</p>}
          </label>
        )}

        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          <span>{t('scheduled.field.content')}</span>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={3}
            className="border border-border rounded-radius-sm px-2 py-1.5 text-sm bg-bg resize-none"
          />
        </label>

        <label className="flex items-center gap-2 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          <span>{t('scheduled.field.enabled')}</span>
        </label>

        {error && (
          <p className="text-xs text-error" role="alert">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover rounded-radius-sm"
          >
            {t('common.cancel')}
          </button>
          <button
            type="submit"
            disabled={!canSubmit}
            className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm disabled:opacity-50"
          >
            {isEdit ? t('common.save') : t('scheduled.create')}
          </button>
        </div>
      </form>
    </div>
  );
}
```

- [ ] **Step 2: Run tests, verify GREEN**

Run: `cd /home/fz/project/sage && npx vitest run src/features/scheduled/__tests__/CreateTaskModal.test.tsx`
Expected: All 5 tests pass.

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage
git add src/features/scheduled/CreateTaskModal.tsx src/features/scheduled/__tests__/CreateTaskModal.test.tsx
git commit -m "feat(scheduled): CreateTaskModal with create + edit modes (Phase 8)"
```

---

## Task 20: Frontend — CronJobSection test scaffolding

**Files:**
- Create: `/home/fz/project/sage/src/widgets/sidebar/sections/__tests__/CronJobSection.test.tsx`

**Interfaces:** None (tests only)

- [ ] **Step 1: Create directories**

```bash
mkdir -p /home/fz/project/sage/src/widgets/sidebar/sections/__tests__
```

- [ ] **Step 2: Write test file (RED)**

Create file `/home/fz/project/sage/src/widgets/sidebar/sections/__tests__/CronJobSection.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../../../entities/scheduled/taskStore', () => {
  const state = {
    tasks: [],
    loading: false,
    error: null,
    load: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    runNow: vi.fn(),
  };
  const hook = (sel?: (s: unknown) => unknown) => (sel ? sel(state) : state);
  return {
    useScheduledTaskStore: Object.assign(hook, { getState: () => state }),
  };
});

import { CronJobSection } from '../CronJobSection';

describe('CronJobSection', () => {
  it('renders the section title and empty hint when no tasks', () => {
    render(
      <MemoryRouter>
        <CronJobSection />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('cron-section')).toBeTruthy();
    expect(screen.getByText(/scheduled\.title|定时任务|Scheduled/i)).toBeTruthy();
  });

  it('renders a link to the /scheduled page', () => {
    render(
      <MemoryRouter>
        <CronJobSection />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: /scheduled\.create|新建任务|New Task/i })).toBeTruthy();
  });

  it('shows an error indicator when store reports error', () => {
    const errorState = {
      tasks: [],
      loading: false,
      error: 'scheduler offline',
      load: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
      runNow: vi.fn(),
    };
    (require('../../../entities/scheduled/taskStore').useScheduledTaskStore as unknown as {
      getState: () => typeof errorState;
    }).getState = () => errorState;
    // Re-render — component reads store via getState for error indicator
    render(
      <MemoryRouter>
        <CronJobSection />
      </MemoryRouter>,
    );
    // Title still renders
    expect(screen.getByTestId('cron-section')).toBeTruthy();
  });
});
```

- [ ] **Step 3: Run test, verify RED**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/sidebar/sections/__tests__/CronJobSection.test.tsx`
Expected: FAIL with `Cannot find module '../CronJobSection'`

- [ ] **Step 4: No commit yet**

---

## Task 21: Frontend — implement CronJobSection.tsx (GREEN)

**Files:**
- Create: `/home/fz/project/sage/src/widgets/sidebar/sections/CronJobSection.tsx`

**Interfaces:**
- Consumes: `useScheduledTaskStore`, `useI18n`, lucide-react icons
- Produces: `CronJobSection` React component (sidebar group)

- [ ] **Step 1: Create CronJobSection.tsx**

Create file `/home/fz/project/sage/src/widgets/sidebar/sections/CronJobSection.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { CalendarClock, Loader2, AlertCircle, Plus } from 'lucide-react';
import { Link } from 'react-router-dom';

import { useScheduledTaskStore } from '../../../entities/scheduled/taskStore';
import { useI18n } from '../../../shared/lib/i18n';
import { describeSchedule } from '../../../features/scheduled/cronValidator';

export function CronJobSection() {
  const { t, locale } = useI18n();
  const tasks = useScheduledTaskStore((s) => s.tasks);
  const error = useScheduledTaskStore((s) => s.error);
  const load = useScheduledTaskStore((s) => s.load);
  const loading = useScheduledTaskStore((s) => s.loading);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mt-3 px-2" data-testid="cron-section">
      <div className="flex items-center justify-between px-1 py-1.5">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted hover:text-text-secondary"
        >
          <CalendarClock className="w-3.5 h-3.5" />
          <span>{t('scheduled.title')}</span>
          <span className="ml-1 text-text-secondary">{tasks.length}</span>
        </button>
        <Link
          to="/scheduled"
          title={t('scheduled.create')}
          aria-label={t('scheduled.create')}
          className="w-5 h-5 flex items-center justify-center rounded text-muted hover:text-text hover:bg-bg-hover"
        >
          <Plus className="w-3.5 h-3.5" />
        </Link>
      </div>

      {error && (
        <div className="flex items-center gap-1 px-2 py-1 text-[11px] text-error" data-testid="cron-error">
          <AlertCircle className="w-3 h-3" />
          <span>paused</span>
        </div>
      )}

      {!collapsed && (
        <ul className="flex flex-col" data-testid="cron-task-list">
          {tasks.length === 0 && !error && (
            <li className="text-[11px] text-muted px-2 py-1 italic">{t('scheduled.empty')}</li>
          )}
          {tasks.slice(0, 6).map((task) => (
            <li
              key={task.id}
              className="group flex items-center justify-between gap-2 px-2 py-1 rounded-radius-sm hover:bg-bg-hover"
            >
              <div className="flex flex-col min-w-0">
                <span className="text-xs text-text truncate">{task.name}</span>
                <span className="text-[10px] text-muted truncate">
                  {describeSchedule(task.schedule, locale as 'zh' | 'en')}
                </span>
              </div>
              <span
                className={[
                  'text-[10px] px-1.5 py-0.5 rounded-full flex-shrink-0',
                  task.enabled
                    ? 'bg-success/10 text-success'
                    : 'bg-muted/20 text-muted',
                ].join(' ')}
              >
                {task.enabled ? t('scheduled.status.enabled') : t('scheduled.status.disabled')}
              </span>
            </li>
          ))}
        </ul>
      )}

      {tasks.length > 6 && (
        <Link
          to="/scheduled"
          className="block px-2 py-1 text-[11px] text-primary hover:underline"
        >
          View all ({tasks.length})
        </Link>
      )}

      {loading && (
        <div className="px-2 py-1">
          <Loader2 className="w-3 h-3 animate-spin text-muted" />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Run tests, verify GREEN**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/sidebar/sections/__tests__/CronJobSection.test.tsx`
Expected: All 3 tests pass.

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage
git add src/widgets/sidebar/sections/CronJobSection.tsx src/widgets/sidebar/sections/__tests__/CronJobSection.test.tsx
git commit -m "feat(sidebar): CronJobSection with status badges and link to page (Phase 8)"
```

---

## Task 22: Frontend — ScheduledTasks page test scaffolding

**Files:**
- Create: `/home/fz/project/sage/src/pages/__tests__/ScheduledTasks.test.tsx`

**Interfaces:** None (tests only)

- [ ] **Step 1: Write test file (RED)**

Create file `/home/fz/project/sage/src/pages/__tests__/ScheduledTasks.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../../entities/scheduled/taskStore', () => {
  const state = {
    tasks: [],
    loading: false,
    error: null,
    load: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    runNow: vi.fn(),
  };
  const hook = (sel?: (s: unknown) => unknown) => (sel ? sel(state) : state);
  return {
    useScheduledTaskStore: Object.assign(hook, { getState: () => state }),
  };
});

import { I18nProvider } from '../../shared/lib/i18n';
import { ScheduledTasks } from '../ScheduledTasks';

describe('ScheduledTasks page', () => {
  it('renders title and Create button', () => {
    render(
      <MemoryRouter>
        <I18nProvider>
          <ScheduledTasks />
        </I18nProvider>
      </MemoryRouter>,
    );
    expect(screen.getByText(/scheduled\.title|定时任务|Scheduled/i)).toBeTruthy();
    expect(screen.getByText(/scheduled\.create/i)).toBeTruthy();
  });

  it('clicking Create opens the modal', () => {
    render(
      <MemoryRouter>
        <I18nProvider>
          <ScheduledTasks />
        </I18nProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByText(/scheduled\.create/i));
    expect(screen.getByRole('dialog')).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test, verify RED**

Run: `cd /home/fz/project/sage && npx vitest run src/pages/__tests__/ScheduledTasks.test.tsx`
Expected: FAIL with `Cannot find module '../ScheduledTasks'`

- [ ] **Step 3: No commit yet**

---

## Task 23: Frontend — implement ScheduledTasks.tsx page (GREEN)

**Files:**
- Create: `/home/fz/project/sage/src/pages/ScheduledTasks.tsx`

**Interfaces:**
- Consumes: `useScheduledTaskStore`, `useI18n`, `CreateTaskModal`, lucide-react icons
- Produces: `ScheduledTasks` page component

- [ ] **Step 1: Create ScheduledTasks.tsx**

Create file `/home/fz/project/sage/src/pages/ScheduledTasks.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Plus, Trash2, Play, Edit3 } from 'lucide-react';
import { toast } from 'sonner';

import { CreateTaskModal } from '../features/scheduled/CreateTaskModal';
import { useScheduledTaskStore } from '../entities/scheduled/taskStore';
import { useI18n } from '../shared/lib/i18n';
import { describeSchedule } from '../features/scheduled/cronValidator';
import type { ScheduledTask } from '../shared/api/types';

export function ScheduledTasks() {
  const { t, locale } = useI18n();
  const { tasks, load, delete: deleteTask, runNow, update } = useScheduledTaskStore();
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<ScheduledTask | undefined>(undefined);

  useEffect(() => {
    void load();
  }, [load]);

  const handleDelete = async (id: string) => {
    if (!window.confirm(t('scheduled.confirm.delete'))) return;
    try {
      await deleteTask(id);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`${t('scheduled.toast.delete_fail')}: ${message}`);
    }
  };

  const handleRunNow = async (id: string) => {
    try {
      await runNow(id);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(message);
    }
  };

  const handleToggleEnabled = async (task: ScheduledTask) => {
    try {
      await update(task.id, { enabled: !task.enabled });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(message);
    }
  };

  return (
    <div className="flex flex-col h-full p-6 gap-4 overflow-y-auto">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-text">{t('scheduled.title')}</h1>
          <p className="text-xs text-text-secondary">{t('scheduled.subtitle')}</p>
        </div>
        <button
          type="button"
          onClick={() => {
            setEditing(undefined);
            setCreateOpen(true);
          }}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary/90"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>{t('scheduled.create')}</span>
        </button>
      </header>

      {tasks.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-text-secondary text-sm">
          {t('scheduled.empty')}
        </div>
      ) : (
        <ul className="flex flex-col gap-2" data-testid="task-list">
          {tasks.map((task) => (
            <li
              key={task.id}
              className="flex items-center justify-between gap-3 p-3 bg-surface border border-border rounded-radius-md"
            >
              <div className="flex flex-col min-w-0 flex-1">
                <span className="text-sm font-medium text-text truncate">{task.name}</span>
                <span className="text-xs text-text-secondary truncate">
                  {describeSchedule(task.schedule, locale as 'zh' | 'en')}
                </span>
                <span className="text-[10px] text-muted">session: {task.session_id}</span>
              </div>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                <button
                  type="button"
                  onClick={() => handleToggleEnabled(task)}
                  className={[
                    'px-2 py-1 text-[11px] rounded-full',
                    task.enabled
                      ? 'bg-success/10 text-success'
                      : 'bg-muted/20 text-muted',
                  ].join(' ')}
                >
                  {task.enabled ? t('scheduled.status.enabled') : t('scheduled.status.disabled')}
                </button>
                <button
                  type="button"
                  onClick={() => handleRunNow(task.id)}
                  title={t('scheduled.action.run_now')}
                  className="w-7 h-7 flex items-center justify-center rounded-radius-sm text-text-secondary hover:bg-bg-hover"
                >
                  <Play className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditing(task);
                    setCreateOpen(true);
                  }}
                  title={t('scheduled.edit')}
                  className="w-7 h-7 flex items-center justify-center rounded-radius-sm text-text-secondary hover:bg-bg-hover"
                >
                  <Edit3 className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(task.id)}
                  title={t('common.delete')}
                  className="w-7 h-7 flex items-center justify-center rounded-radius-sm text-error hover:bg-error/10"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <CreateTaskModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        sessionId="default"
        task={editing}
      />
    </div>
  );
}
```

- [ ] **Step 2: Run tests, verify GREEN**

Run: `cd /home/fz/project/sage && npx vitest run src/pages/__tests__/ScheduledTasks.test.tsx`
Expected: All 2 tests pass.

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage
git add src/pages/ScheduledTasks.tsx src/pages/__tests__/ScheduledTasks.test.tsx
git commit -m "feat(pages): ScheduledTasks page with list + CRUD actions (Phase 8)"
```

---

## Task 24: Frontend — wire CronJobSection into Sidebar and add /scheduled route

**Files:**
- Modify: `/home/fz/project/sage/src/widgets/layout/Sidebar.tsx`
- Modify: `/home/fz/project/sage/src/App.tsx`

**Interfaces:** None (composition only)

- [ ] **Step 1: Add `CronJobSection` import and render in Sidebar**

In `/home/fz/project/sage/src/widgets/layout/Sidebar.tsx`, add the import after the existing imports:

```typescript
import { CronJobSection } from './sidebar/sections/CronJobSection';
```

Then, just before the closing `</nav>` (right after `<VirtualSessionList ... />`), insert:

```tsx
        <CronJobSection />
```

- [ ] **Step 2: Add `/scheduled` route in App.tsx**

In `/home/fz/project/sage/src/App.tsx`, add the import:

```typescript
import { ScheduledTasks } from './pages/ScheduledTasks';
```

And add a new `<Route>` line right after the `<Route path="skills" ... />`:

```tsx
        <Route path="scheduled" element={<ScheduledTasks />} />
```

- [ ] **Step 3: Run tsc to verify**

Run: `cd /home/fz/project/sage && npx tsc --noEmit -p tsconfig.json 2>&1 | head -20`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage
git add src/widgets/layout/Sidebar.tsx src/App.tsx
git commit -m "feat(routing): wire CronJobSection into sidebar and add /scheduled route (Phase 8)"
```

---

## Task 25: Frontend — add "定时" button to ChatInput

**Files:**
- Modify: `/home/fz/project/sage/src/widgets/chat/ChatInput.tsx`
- Create: `/home/fz/project/sage/src/widgets/chat/__tests__/ChatInput.scheduled.test.tsx`

**Interfaces:**
- Consumes: existing `ChatInputProps`, lucide-react `Clock` icon
- Produces: optional `onSchedule` callback prop and a "定时" button

- [ ] **Step 1: Write ChatInput scheduled test (RED)**

Create file `/home/fz/project/sage/src/widgets/chat/__tests__/ChatInput.scheduled.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { ChatInput } from '../ChatInput';

describe('ChatInput scheduled button', () => {
  it('renders schedule button when onSchedule is provided', () => {
    render(<ChatInput onSend={vi.fn()} onSchedule={vi.fn()} />);
    expect(screen.getByTitle(/定时/i)).toBeTruthy();
  });

  it('clicking schedule button invokes onSchedule', () => {
    const onSchedule = vi.fn();
    render(<ChatInput onSend={vi.fn()} onSchedule={onSchedule} />);
    fireEvent.click(screen.getByTitle(/定时/i));
    expect(onSchedule).toHaveBeenCalledTimes(1);
  });

  it('does not render schedule button when onSchedule is undefined', () => {
    render(<ChatInput onSend={vi.fn()} />);
    expect(screen.queryByTitle(/定时/i)).toBeNull();
  });
});
```

- [ ] **Step 2: Run test, verify RED**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ChatInput.scheduled.test.tsx`
Expected: FAIL — "Title 定时" element not found.

- [ ] **Step 3: Modify ChatInput.tsx**

Add to the import block at the top:

```typescript
import { Send, Square, Image, Paperclip, BookOpen, Clock } from 'lucide-react';
```

Add to the `ChatInputProps` interface (after `onClear?`):

```typescript
  onSchedule?: () => void;
```

Destructure the new prop in the component signature:

```typescript
export function ChatInput({
  onSend,
  onInterrupt,
  onClear,
  onSchedule,
  isLoading = false,
  disabled = false,
  placeholder = '输入消息...',
}: ChatInputProps) {
```

Inside the icon row (the `<div className="flex items-center gap-1 flex-shrink-0">`), add a new button next to the knowledge button:

```tsx
              {onSchedule && (
                <button
                  className="w-7 h-7 flex items-center justify-center rounded-radius-sm hover:bg-bg-hover text-muted hover:text-text transition-colors"
                  title="定时"
                  onClick={onSchedule}
                >
                  <Clock className="w-4 h-4" />
                </button>
              )}
```

- [ ] **Step 4: Run tests, verify GREEN**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ChatInput.scheduled.test.tsx`
Expected: All 3 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage
git add src/widgets/chat/ChatInput.tsx src/widgets/chat/__tests__/ChatInput.scheduled.test.tsx
git commit -m "feat(chat): add optional onSchedule button to ChatInput (Phase 8)"
```

---

## Task 26: Frontend — coverage verification + final build

**Files:** No new files; this is a verification gate.

**Interfaces:** None

- [ ] **Step 1: Run frontend coverage for the new modules**

Run:
```bash
cd /home/fz/project/sage && npx vitest run \
  src/features/scheduled/__tests__/cronValidator.test.ts \
  src/shared/api/__tests__/scheduledClient.test.ts \
  src/entities/scheduled/__tests__/taskStore.test.ts \
  src/features/scheduled/__tests__/CronExpressionPicker.test.tsx \
  src/features/scheduled/__tests__/CreateTaskModal.test.tsx \
  src/widgets/sidebar/sections/__tests__/CronJobSection.test.tsx \
  src/pages/__tests__/ScheduledTasks.test.tsx \
  src/widgets/chat/__tests__/ChatInput.scheduled.test.tsx \
  --coverage --coverage.reporter=text-summary
```

Expected: all suites pass; per-file coverage `cronValidator` and `scheduledClient` >= 90%.

- [ ] **Step 2: Run backend coverage for scheduler + scheduled API**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/services/__tests__/test_scheduler.py \
  backend/tests/integration/test_scheduled_api.py \
  --cov=backend.services.scheduler --cov=backend.api.scheduled_router \
  --cov-report=term-missing --no-header
```

Expected: `scheduler.py` >= 95%; `scheduled_router.py` >= 90%; overall >= 85%.

- [ ] **Step 3: Build frontend**

Run: `cd /home/fz/project/sage && npm run build`
Expected: build succeeds with no TypeScript errors.

- [ ] **Step 4: Backend import sanity**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -c "from backend.main import app; print(sorted([r.path for r in app.routes if 'scheduled' in r.path]))"`
Expected: prints list with `/api/v1/scheduled/health`, `/api/v1/scheduled/tasks`, `/api/v1/scheduled/tasks/{task_id}`, etc.

- [ ] **Step 5: No commit** (verification only)

---

## Task 27: E2E smoke test (manual verification)

**Files:** None (verification only)

**Interfaces:** None

- [ ] **Step 1: Start backend**

Run:
```bash
cd /home/fz/project/sage && \
  /home/fz/anaconda3/envs/sage-backend/bin/python backend/main.py
```

Expected: server starts, logs include `SchedulerService 已初始化并启动（0 个任务）`.

- [ ] **Step 2: Create a one-shot task via curl (30s in future)**

Run:
```bash
FUTURE=$(($(date +%s%3N) + 30000))
curl -X POST http://127.0.0.1:8765/api/v1/scheduled/tasks \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"smoke\",\"type\":\"once\",\"schedule\":{\"kind\":\"once\",\"at\":$FUTURE},\"session_id\":\"s-smoke\",\"content\":\"hello from scheduler\"}"
```

Expected: `201 Created` with a task body.

- [ ] **Step 3: Wait 35s, then list tasks and verify message**

Run:
```bash
sleep 35
curl -s http://127.0.0.1:8765/api/v1/scheduled/tasks | python -m json.tool
```

Expected: the task is present with `enabled: false`, `last_run` populated, and the message is in the session (query the SQLite DB or `/api/v1/sessions/s-smoke/messages`).

- [ ] **Step 4: Start frontend and verify ScheduledTasks page**

Run:
```bash
cd /home/fz/project/sage && npm run dev
```

Open `http://localhost:1420/scheduled`. Expected: page renders, list shows the completed task with disabled badge.

- [ ] **Step 5: No commit** (verification only — no code changes)

---

## Task 28: Final docs

**Files:**
- Create: `/home/fz/project/sage/docs/technical/08-scheduled-tasks.md`

**Interfaces:** None

- [ ] **Step 1: Verify docs/technical exists**

Run: `ls /home/fz/project/sage/docs/technical/ 2>/dev/null | head`
Expected: directory exists. If not, run `mkdir -p /home/fz/project/sage/docs/technical`.

- [ ] **Step 2: Write the technical chapter**

Create file `/home/fz/project/sage/docs/technical/08-scheduled-tasks.md`:

```markdown
# 08 — Scheduled Tasks (Phase 8)

## Overview

Backend-driven scheduler that fires one-shot or recurring messages into
target chat sessions. UI exposes create/edit/delete/run-now via the
`/scheduled` page and a sidebar group.

## Architecture

- Backend: APScheduler `BackgroundScheduler` in `backend/services/scheduler.py`,
  mounted in `backend/api/scheduled_router.py` under `/api/v1/scheduled/*`.
  Persistence: `backend/data/scheduled_tasks.json` (atomic write).
- Frontend: Zustand store in `src/entities/scheduled/taskStore.ts`, IPC via
  `src/shared/api/scheduledClient.ts`. UI in `src/pages/ScheduledTasks.tsx`
  and `src/widgets/sidebar/sections/CronJobSection.tsx`.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/scheduled/health` | Liveness check |
| GET | `/api/v1/scheduled/tasks` | List all tasks |
| POST | `/api/v1/scheduled/tasks` | Create |
| PATCH | `/api/v1/scheduled/tasks/{id}` | Update name/enabled |
| DELETE | `/api/v1/scheduled/tasks/{id}` | Delete |
| POST | `/api/v1/scheduled/tasks/{id}/run` | Run now |

## Storage

JSON file with schema `{ "version": 1, "tasks": [...] }`. Each task carries
`id, name, type, schedule, session_id, content, enabled, created_at,
last_run?, next_run?`. Writes use `tempfile` + `os.replace` (atomic).

## Timezone

All timestamps stored as UTC epoch milliseconds. Frontend displays via
`Intl.DateTimeFormat` in user locale.

## Error handling

- Bad cron: HTTP 422 with reason.
- Past `at`: HTTP 422.
- Missing session: HTTP 422.
- Missing task: HTTP 404.
- Per-job failure: logged, scheduler continues.

## Tests

| Module | Coverage target |
| --- | --- |
| `backend/services/scheduler.py` | >= 95% |
| `backend/api/scheduled_router.py` | >= 90% |
| `src/features/scheduled/cronValidator.ts` | >= 95% |
| `src/shared/api/scheduledClient.ts` | >= 90% |
| Overall | >= 85% |
```

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage
git add docs/technical/08-scheduled-tasks.md
git commit -m "docs(technical): add Phase 8 scheduled-tasks chapter"
```

---

## Definition of Done

Phase 8 is complete when:

1. `backend/services/scheduler.py` and `backend/api/scheduled_router.py`
   exist, all their tests are green, and per-file coverage targets are met.
2. APScheduler starts in `backend/main.py` lifespan and shuts down cleanly.
3. Frontend `cronValidator.ts`, `scheduledClient.ts`, `taskStore.ts`,
   `CronExpressionPicker.tsx`, `CreateTaskModal.tsx`, `CronJobSection.tsx`,
   and `ScheduledTasks.tsx` exist with tests passing.
4. `/scheduled` route is reachable from the sidebar, and the sidebar
   `CronJobSection` shows tasks with status badges.
5. `ChatInput` exposes an opt-in `onSchedule` callback (button visible
   only when the parent provides the prop).
6. Manual smoke test (Task 27) creates a one-shot task that fires and
   inserts a message into the target session.
7. `docs/technical/08-scheduled-tasks.md` is committed.

## Risks & Mitigations

| Risk | Mitigation |
| --- | --- |
| APScheduler double-fire | `max_instances=1` + `coalesce=True` on every job |
| One-shot past-time acceptance | Validator rejects in both client (`validateOneShotTimestamp`) and server (`add_task`) |
| Cross-thread JSON corruption | `threading.Lock` around all reads/writes |
| Lost tasks on crash mid-write | Atomic temp + replace; partial file never reaches final path |
| Frontend display in user TZ | `Intl.DateTimeFormat` with explicit locale |
