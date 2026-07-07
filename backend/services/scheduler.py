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
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

try:  # pragma: no cover — py3.11+ runtime branch
    from datetime import UTC as _UTC  # type: ignore[attr-defined]
except ImportError:  # py3.10 fallback
    from datetime import timedelta

    _UTC = timezone(timedelta(0))

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
    schedule: Dict[str, Any]
    session_id: str
    content: str
    enabled: bool
    created_at: int
    last_run: Optional[int] = None
    next_run: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> ScheduledTask:
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
    return datetime.fromtimestamp(ms / 1000, tz=_UTC)


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
        self._tasks: Dict[str, ScheduledTask] = {}
        self._scheduler = BackgroundScheduler(daemon=True)
        self._load_from_disk()
        self._reschedule_all()

    # ---------- public API ----------

    def list_tasks(self) -> List[ScheduledTask]:
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
        schedule: Dict[str, Any],
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
            validated_schedule: Dict[str, Any] = {"kind": "once", "at": at_ms}
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
        suppress(Exception, self._scheduler.remove_job, task.id)
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
                self._record_run(task)
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
        self._record_run(task)

    def _record_run(self, task: ScheduledTask) -> None:
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
                suppress(Exception, self._scheduler.remove_job, current.id)
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
            logger.warning(
                "scheduled_tasks.json schema=%s, expected %s, ignoring", version, SCHEMA_VERSION
            )
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


_global_service: Optional[SchedulerService] = None


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
