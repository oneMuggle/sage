"""APScheduler wrapper for Phase 8 scheduled tasks.

Persistence: ``${SAGE_USER_DATA_DIR}/scheduled_tasks.json`` in packaged
mode (env set by Electron at spawn → per-user ``<userData>``); falls back
to ``backend/data/scheduled_tasks.json`` in dev / tests when env is unset.
Concurrent write safety: a single ``threading.Lock`` guards JSON read/write.
Failure mode: per-job exceptions are logged and never raised to the
scheduler loop, so a bad task cannot kill the scheduler.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional

if TYPE_CHECKING:
    from backend.scheduler.evolution import BaseEvolutionTask

try:  # pragma: no cover — py3.11+ runtime branch
    from datetime import (
        UTC as _UTC,  # type: ignore[attr-defined]  # py38: guarded (ImportError fallback below)
    )
except ImportError:  # py3.10 fallback
    from datetime import timedelta

    _UTC = timezone(timedelta(0))

from apscheduler.jobstores.base import JobLookupError
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
    last_attempt: Optional[int] = None
    last_status: str = "never"
    last_error: Optional[str] = None

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
            last_attempt=raw.get("last_attempt"),
            last_status=str(raw.get("last_status", "succeeded" if raw.get("last_run") else "never")),
            last_error=raw.get("last_error"),
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
        self._running = set()
        self._scheduler = BackgroundScheduler(daemon=True)
        self._evolution_tasks: Dict[str, "BaseEvolutionTask"] = {}  # noqa: UP037
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

    def _validate_schedule(self, task_type: str, schedule: Dict[str, Any], require_future: bool = True) -> Dict[str, Any]:
        if task_type not in ("once", "recurring") or schedule.get("kind") != task_type:
            raise ValidationError("type must match schedule.kind")
        if task_type == "once":
            try:
                at_ms = int(schedule["at"])
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValidationError("one-shot 'at' must be a timestamp") from exc
            if require_future and at_ms <= int(time.time() * 1000):
                raise ValidationError("one-shot 'at' must be in the future")
            return {"kind": "once", "at": at_ms}
        cron_expr = str(schedule.get("cron") or "").strip()
        try:
            CronTrigger.from_crontab(cron_expr)
        except (ValueError, TypeError) as exc:
            raise ValidationError("invalid five-field cron expression") from exc
        if not croniter.is_valid(cron_expr):
            raise ValidationError("invalid cron expression")
        return {"kind": "recurring", "cron": cron_expr}

    def _next_run_for(self, schedule: Dict[str, Any], enabled: bool) -> Optional[int]:
        if not enabled:
            return None
        return schedule["at"] if schedule["kind"] == "once" else self._compute_next_cron_run(schedule["cron"])

    def add_task(
        self,
        name: str,
        task_type: Literal["once", "recurring"],
        schedule: Dict[str, Any],
        session_id: str,
        content: str,
        enabled: bool = True,
    ) -> ScheduledTask:
        if not name or not name.strip():
            raise ValidationError("name must not be empty")
        if not content or not content.strip():
            raise ValidationError("content must not be empty")
        if not isinstance(enabled, bool):
            raise ValidationError("enabled must be bool")
        if not self._session_repo_exists(session_id):
            raise ValidationError(f"session not found: {session_id}")
        validated_schedule = self._validate_schedule(task_type, schedule)
        task = ScheduledTask(
            id=f"task-{uuid.uuid4().hex[:8]}", name=name.strip(), type=task_type,
            schedule=validated_schedule, session_id=session_id, content=content,
            enabled=enabled, created_at=int(time.time() * 1000),
            next_run=self._next_run_for(validated_schedule, enabled),
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
            if task_id in self._running:
                raise ValidationError("task is running; retry editing after it finishes")
            current = self._tasks[task_id]
            allowed = {"name", "enabled", "type", "schedule", "content", "session_id"}
            if set(changes) - allowed:
                raise ValidationError("unknown task field")
            new_name = changes.get("name", current.name)
            new_enabled = changes.get("enabled", current.enabled)
            new_content = changes.get("content", current.content)
            new_session = changes.get("session_id", current.session_id)
            new_type = changes.get("type", current.type)
            schedule = changes.get("schedule", current.schedule)
            if not isinstance(new_name, str) or not new_name.strip():
                raise ValidationError("name must not be empty")
            if not isinstance(new_content, str) or not new_content.strip():
                raise ValidationError("content must not be empty")
            if not isinstance(new_enabled, bool):
                raise ValidationError("enabled must be bool")
            if new_session != current.session_id and not self._session_repo_exists(new_session):
                raise ValidationError(f"session not found: {new_session}")
            if not isinstance(schedule, dict):
                raise ValidationError("schedule must be an object")
            schedule_changed = new_type != current.type or schedule != current.schedule
            validated = self._validate_schedule(
                new_type, schedule,
                require_future=schedule_changed or (new_enabled and not current.enabled),
            )
            updated = replace(
                current, name=new_name.strip(), enabled=new_enabled, type=new_type,
                schedule=validated, content=new_content, session_id=new_session,
                next_run=self._next_run_for(validated, new_enabled),
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

    # ---------- evolution tasks (PR-C §5.1) ----------

    def register_evolution_task(
        self,
        name: str,
        task: "BaseEvolutionTask",  # noqa: UP037
        cron_expr: Optional[str] = None,
        *,
        hour: Optional[int] = None,
        minute: Optional[int] = None,
        day_of_week: Optional[str] = None,
    ) -> None:
        """注册一个 evolution 任务到 BackgroundScheduler (不写 JSON 持久化)。

        cron_expr (5-field, e.g. "0 3 * * *") 与 hour+minute+(day_of_week)
        二选一;同时传 → ValueError。job_id 固定 "evolution/<name>",
        replace_existing=True 允许测试重跑。
        """
        if cron_expr and (hour is not None or minute is not None):
            raise ValueError(
                "register_evolution_task: cron_expr 与 hour/minute 互斥"
            )
        if not cron_expr and (hour is None or minute is None):
            raise ValueError(
                "register_evolution_task: 必须传 cron_expr 或 hour+minute"
            )
        if cron_expr:
            expr = cron_expr
        else:
            dow = day_of_week if day_of_week is not None else "*"
            expr = f"{minute} {hour} * * {dow}"
        trigger = CronTrigger.from_crontab(expr)
        self._scheduler.add_job(
            lambda: self._fire_evolution(name, task),
            trigger=trigger,
            id=f"evolution/{name}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        self._evolution_tasks[name] = task
        logger.info("Evolution task registered: %s (%s)", name, expr)

    def register_system_task(self, name: str, fn, cron_expr: str) -> None:
        """注册一个系统维护任务（R19-B: SQLite 自动备份等）。

        与 register_evolution_task 的区别：回调是任意可调用对象而非
        BaseEvolutionTask，job_id 前缀 ``system/``。同样不写 JSON 持久化，
        replace_existing 允许重启后重注册。
        """
        trigger = CronTrigger.from_crontab(cron_expr)
        self._scheduler.add_job(
            fn,
            trigger=trigger,
            id=f"system/{name}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=600,
        )
        logger.info("System task registered: %s (%s)", name, cron_expr)

    def trigger_evolution_task(self, name: str) -> bool:
        """同步触发一个 evolution 任务(运维/手动用)。"""
        task = self._evolution_tasks.get(name)
        if task is None:
            return False
        self._fire_evolution(name, task)
        return True

    def run_evolution_task_now(self, name: str) -> Optional[Dict[str, Any]]:
        """同步运行一个 evolution 任务并返回其统计结果(手动触发 API 用, R17-B)。

        与 trigger_evolution_task 的区别:任务返回值(如 MemoryConsolidationTask
        的 {promoted, decayed, total})透传给调用方,而不是只进日志。
        未注册返回 None;任务内部异常记日志后返回 None(与 _fire_evolution 语义一致)。
        """
        task = self._evolution_tasks.get(name)
        if task is None:
            return None
        try:
            return task.run()
        except Exception:
            logger.exception("Evolution task %s failed", name)
            return None

    def get_evolution_task_names(self) -> List[str]:
        """已注册的 evolution 任务名列表。"""
        return list(self._evolution_tasks.keys())

    def _fire_evolution(self, name: str, task: "BaseEvolutionTask") -> None:  # noqa: UP037
        """APScheduler 触发的实际执行函数。"""
        try:
            result = task.run()
            logger.info("Evolution task %s completed: %s", name, result)
        except Exception:
            logger.exception("Evolution task %s failed", name)

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
        with suppress(JobLookupError):
            self._scheduler.remove_job(task.id)
        self._schedule_job(task)

    def _schedule_job(self, task: ScheduledTask) -> None:
        if not task.enabled:
            return
        if task.type == "once":
            trigger = DateTrigger(run_date=_epoch_ms_to_dt(task.schedule["at"]))
        else:
            trigger = CronTrigger.from_crontab(task.schedule["cron"])
        self._scheduler.add_job(
            self._fire_scheduled,
            trigger=trigger,
            args=[task],
            id=task.id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def _fire_scheduled(self, task: ScheduledTask) -> None:
        """Ignore stale queued callbacks; explicit manual attempts stay separate."""
        with self._lock:
            current = self._tasks.get(task.id)
            if current is None or not current.enabled or current.schedule != task.schedule:
                return
        try:
            self._fire(current)
        except ValidationError:
            logger.info("task %s already running; skip overlapping automatic callback", task.id)

    def _fire(self, task: ScheduledTask) -> None:
        """Record delivery success separately from failures; never blindly retry."""
        with self._lock:
            if task.id in self._running:
                raise ValidationError("task is already running")
            if task.id not in self._tasks:
                return
            self._running.add(task.id)
        error = None
        try:
            if not self._session_repo_exists(task.session_id):
                error = "Target session no longer exists. Select a valid session before retrying."
            else:
                self._message_repo.insert(
                    session_id=task.session_id, role="system", content=task.content,
                    created_at=int(time.time() * 1000),
                )
                logger.info("task %s fired into session %s", task.id, task.session_id)
        except Exception:  # noqa: BLE001 — failed delivery is persisted and shown in UI
            logger.exception("task %s fire failed", task.id)
            error = "Delivery failed. Check the target session and backend logs before retrying."
        finally:
            try:
                self._record_run(task, error)
            finally:
                with self._lock:
                    self._running.discard(task.id)

    def _record_run(self, task: ScheduledTask, error: Optional[str] = None) -> None:
        with self._lock:
            if task.id not in self._tasks:
                return
            current = self._tasks[task.id]
            now = int(time.time() * 1000)
            # Failed one-shots are paused, NOT completed. No automatic replay:
            # a failed response can be ambiguous after a successful commit.
            enabled = current.enabled if current.type == "recurring" else False
            self._tasks[task.id] = replace(
                current, enabled=enabled,
                last_attempt=now, last_status="failed" if error else "succeeded",
                last_error=error, last_run=current.last_run if error else now,
                next_run=self._next_run_for(current.schedule, enabled),
            )
            if current.type == "once":
                with suppress(JobLookupError):
                    self._scheduler.remove_job(current.id)
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


def get_scheduler_service() -> Optional[SchedulerService]:
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
