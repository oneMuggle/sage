"""APScheduler wrapper for Phase 8 scheduled tasks.

Persistence: SQLite ``scheduled_tasks`` table via
:class:`ScheduledTaskRepository` when a :class:`Database` is supplied. Legacy
JSON (``${SAGE_USER_DATA_DIR}/scheduled_tasks.json`` in packaged mode, else
``backend/data/scheduled_tasks.json``) is still honoured when no ``db`` is
passed, and is imported once on the first SQLite-backed startup.
Concurrent write safety: a single ``threading.Lock`` guards the in-memory task
map; SQLite access serialises on the shared ``_SQLITE_LOCK``.
Failure mode: per-job exceptions are logged and never raised to the
scheduler loop, so a bad task cannot kill the scheduler.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from contextlib import suppress
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Deque, Dict, List, Literal, Optional

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

from backend.domain.scheduler import (
    RunOutcome,
    ScheduledTask,
    ScheduledTaskNotFoundError,
    ScheduledTaskValidationError,
    TaskRunner,
)
from backend.services.scheduler_repository import ScheduledTaskRepository
from backend.utils.timezones import local_timezone

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

#: Undrained desktop notifications are capped so a missing consumer cannot leak memory.
MAX_PENDING_NOTIFICATIONS = 100


TaskNotFoundError = ScheduledTaskNotFoundError
ValidationError = ScheduledTaskValidationError

__all__ = [
    "MAX_PENDING_NOTIFICATIONS",
    "SCHEMA_VERSION",
    "RunOutcome",
    "ScheduledTask",
    "SchedulerService",
    "TaskNotFoundError",
    "TaskRunner",
    "ValidationError",
    "get_scheduler_service",
    "init_scheduler_service",
]


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
        db: Any = None,
    ) -> None:
        self._store_path = Path(store_path)
        self._message_repo = message_repo
        self._session_repo = session_repo
        self._lock = threading.Lock()
        self._tasks: Dict[str, ScheduledTask] = {}
        self._running = set()
        # Desktop-notification payloads for fired tasks. Electron drains this
        # via the pending-notifications endpoint; nothing here is persisted.
        self._pending_notifications: Deque[Dict[str, Any]] = deque(
            maxlen=MAX_PENDING_NOTIFICATIONS
        )
        # 显式设置本地时区, 让 cron/interval 触发时间与日志、趋势图一致
        # (2026-11-03). 不设置时 APScheduler 用其内部默认 (系统本地),
        # 但行为依赖 tzlocal 是否可用, 显式传入更稳.
        self._scheduler = BackgroundScheduler(daemon=True, timezone=local_timezone())
        self._evolution_tasks: Dict[str, "BaseEvolutionTask"] = {}  # noqa: UP037
        self._repository = ScheduledTaskRepository(db) if db is not None else None
        # 注入的任务执行器（由 main.py lifespan 装配后调用 ``set_executor``
        # 填入）。为 ``None`` 时 ``_fire`` 降级到 ``deliver`` 行为，保证启动
        # 顺序不影响基础功能。
        self._executor: Optional[TaskRunner] = None
        if self._repository is None:
            self._load_from_disk()
        else:
            self._migrate_from_json()
            self._load_from_repo()
        self._reschedule_all()

    def set_executor(self, runner: Optional[TaskRunner]) -> None:
        """注入任务执行器（由 ``main.py`` 装配期调用）。

        ``runner`` 必须是同步可调用对象，由调度线程直接调用；内部负责把
        异步的 ``ChatService.run_turn_tracked`` 桥接到主事件循环并返回
        ``RunOutcome``。传 ``None`` 清除注入（仅测试使用）。
        """
        self._executor = runner

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
        # Legacy service callers omit kind; normalize it from task_type while
        # still rejecting an explicit mismatch. REST ScheduleIn requires kind.
        if task_type not in ("once", "recurring") or schedule.get("kind", task_type) != task_type:
            raise ValidationError("type must match schedule.kind")
        if task_type == "once":
            try:
                at_ms = int(schedule["at"])
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValidationError("one-shot 'at' must be a timestamp") from exc
            if require_future and at_ms <= int(time.time() * 1000):
                raise ValidationError("one-shot 'at' must be in the future")
            # 2026-09-19: 上界校验。此前只查下限，超出 datetime 可表示范围
            # 的 at（如 1e17 ms）会先被持久化、再在 _schedule_job 抛
            # ValueError —— 任务留在磁盘上但调度失败，且重启时
            # _reschedule_all 抛同一异常导致 SchedulerService 构造失败
            # （后端起不来）。必须在落盘前拦下。
            try:
                _epoch_ms_to_dt(at_ms)
            except (ValueError, OverflowError, OSError) as exc:
                raise ValidationError("one-shot 'at' is out of the representable date range") from exc
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
        try:
            if schedule.get("kind") == "once":
                return schedule["at"]
            return self._compute_next_cron_run(schedule["cron"])
        except (ValueError, KeyError, TypeError):
            # 2026-09-19: 磁盘脏数据（损坏 cron / 缺字段）不得阻断启动。
            # _record_run 会经此计算 next_run；若在此抛异常，_reschedule_all
            # 的逐条容错会被击穿 —— croniter 的 CroniterBadCronError 继承
            # ValueError，会一路穿透 __init__ 使后端起不来。
            logger.warning("cannot compute next run for %r", schedule, exc_info=True)
            return None

    def add_task(
        self,
        name: str,
        task_type: Literal["once", "recurring"],
        schedule: Dict[str, Any],
        session_id: str,
        content: str,
        enabled: bool = True,
        max_runs: Optional[int] = None,
        mode: Literal["execute", "deliver"] = "execute",
    ) -> ScheduledTask:
        if not name or not name.strip():
            raise ValidationError("name must not be empty")
        if not content or not content.strip():
            raise ValidationError("content must not be empty")
        if not isinstance(enabled, bool):
            raise ValidationError("enabled must be bool")
        if max_runs is not None and (isinstance(max_runs, bool) or not isinstance(max_runs, int) or max_runs < 1):
            raise ValidationError("max_runs must be a positive integer")
        if mode not in ("execute", "deliver"):
            raise ValidationError("mode must be 'execute' or 'deliver'")
        if not self._session_repo_exists(session_id):
            raise ValidationError(f"session not found: {session_id}")
        validated_schedule = self._validate_schedule(task_type, schedule)
        task = ScheduledTask(
            id=f"task-{uuid.uuid4().hex[:8]}", name=name.strip(), type=task_type,
            schedule=validated_schedule, session_id=session_id, content=content,
            enabled=enabled, created_at=int(time.time() * 1000),
            next_run=self._next_run_for(validated_schedule, enabled),
            max_runs=max_runs, mode=mode,
        )
        with self._lock:
            self._tasks[task.id] = task
            self._persist(task)
            self._schedule_job(task)
        logger.info("scheduled task added: %s (%s, mode=%s)", task.id, task.type, task.mode)
        return task

    def update_task(self, task_id: str, **changes: Any) -> ScheduledTask:
        with self._lock:
            if task_id not in self._tasks:
                raise TaskNotFoundError(task_id)
            if task_id in self._running:
                raise ValidationError("task is running; retry editing after it finishes")
            current = self._tasks[task_id]
            allowed = {"name", "enabled", "type", "schedule", "content", "session_id", "max_runs", "mode"}
            if set(changes) - allowed:
                raise ValidationError("unknown task field")
            new_name = changes.get("name", current.name)
            new_enabled = changes.get("enabled", current.enabled)
            new_content = changes.get("content", current.content)
            new_session = changes.get("session_id", current.session_id)
            new_type = changes.get("type", current.type)
            schedule = changes.get("schedule", current.schedule)
            new_max_runs = changes.get("max_runs", current.max_runs)
            new_mode = changes.get("mode", current.mode)
            if not isinstance(new_name, str) or not new_name.strip():
                raise ValidationError("name must not be empty")
            if not isinstance(new_content, str) or not new_content.strip():
                raise ValidationError("content must not be empty")
            if not isinstance(new_enabled, bool):
                raise ValidationError("enabled must be bool")
            if new_max_runs is not None and (isinstance(new_max_runs, bool) or not isinstance(new_max_runs, int) or new_max_runs < 1):
                raise ValidationError("max_runs must be a positive integer")
            if new_mode not in ("execute", "deliver"):
                raise ValidationError("mode must be 'execute' or 'deliver'")
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
                max_runs=new_max_runs, mode=new_mode,
            )
            self._tasks[task_id] = updated
            self._persist(updated)
            self._reschedule_one(updated)
        logger.info("scheduled task updated: %s", task_id)
        return updated

    def delete_task(self, task_id: str, expected_session_id: Optional[str] = None) -> None:
        """删除任务。``expected_session_id`` 非空时在同一把锁内校验归属，
        不匹配则抛 ``ValidationError`` —— 供 LLM 工具原子地"只删本会话任务"，
        避免先 get_task 校验、再 delete_task 之间的 TOCTOU 窗口（前端 UI 可
        在该窗口把任务迁移到别的会话）。"""
        with self._lock:
            if task_id not in self._tasks:
                raise TaskNotFoundError(task_id)
            if expected_session_id is not None and self._tasks[task_id].session_id != expected_session_id:
                raise ValidationError("task does not belong to the expected session")
            del self._tasks[task_id]
            try:
                self._scheduler.remove_job(task_id)
            except Exception:  # noqa: BLE001 — APScheduler raises if job absent
                logger.debug("apscheduler job %s already absent", task_id)
            self._persist_delete(task_id)
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
        cron_expr: str | None = None,
        *,
        hour: int | None = None,
        minute: int | None = None,
        day_of_week: str | None = None,
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

    def run_evolution_task_now(self, name: str) -> Dict[str, Any] | None:
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
        # 2026-09-19: 单条坏任务不得阻断启动。磁盘上可能留有旧版本写入的
        # 不可调度条目（如超出 datetime 范围的 once 'at'）；此前
        # _schedule_job 抛出的异常会一路穿透 __init__，使 SchedulerService
        # 构造失败 → 后端起不来，且用户无从下手（须手删 JSON）。现在逐条
        # 容错：失败的那条标记为 missed 使 UI 可见，其余正常登记。
        for task in list(self._tasks.values()):
            try:
                self._schedule_job(task)
            except Exception:  # noqa: BLE001 — 隔离单条脏数据
                logger.exception("task %s: scheduling failed, marking missed", task.id)
                self._record_run(task, error="invalid: task could not be scheduled")

    def _reschedule_one(self, task: ScheduledTask) -> None:
        with suppress(JobLookupError):
            self._scheduler.remove_job(task.id)
        self._schedule_job(task)

    def _schedule_job(self, task: ScheduledTask) -> None:
        if not task.enabled:
            return
        if task.type == "once":
            run_dt = _epoch_ms_to_dt(task.schedule["at"])
            # 2026-09 修复: 后端停机跨过触发点的一次性任务 —— APScheduler
            # misfire 会静默跳过, 任务停留 enabled 且 next_run 是过去值,
            # 提醒永久丢失且 UI 无法察觉。重启登记时已过期的直接记为
            # missed, 用户在任务列表能看到失败原因并可手动重跑。
            if run_dt.timestamp() * 1000 <= time.time() * 1000:
                logger.warning(
                    "task %s: one-shot 触发点 (%s) 已在停机期间错过, 标记 missed",
                    task.id,
                    run_dt.isoformat(),
                )
                # 2026-09-19 安全审查修复: 去掉外层 `with self._lock:` —
                # _record_run 内部自行获锁（scheduler.py:480），threading.Lock
                # 不可重入，嵌套获锁会死锁。触发场景：后端重启时磁盘上有
                # 已过期的一次性任务，_schedule_job 在 __init__ 的
                # _reschedule_all 中被调用，导致后端永久挂起。
                self._record_run(task, error="missed: backend was down at fire time")
                return
            trigger = DateTrigger(run_date=run_dt)
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
        outcome_message_id: Optional[str] = None
        outcome_duration_ms: Optional[int] = None
        try:
            if not self._session_repo_exists(task.session_id):
                error = "Target session no longer exists. Select a valid session before retrying."
            elif task.mode == "execute":
                if self._executor is None:
                    # 启动期 ChatService 尚未装配：降级到 deliver，保证用户提醒
                    # 不丢（方案 §3.8）。
                    logger.warning(
                        "task %s is mode='execute' but no executor injected; "
                        "degrading to deliver",
                        task.id,
                    )
                    self._message_repo.insert(
                        session_id=task.session_id, role="system", content=task.content,
                        created_at=int(time.time() * 1000),
                    )
                else:
                    outcome = self._executor(task)
                    outcome_message_id = outcome.message_id
                    outcome_duration_ms = outcome.duration_ms
                    if outcome.status == "failed":
                        error = outcome.error or "Execution failed"
                    else:
                        logger.info(
                            "task %s executed in %dms (message=%s)",
                            task.id, outcome.duration_ms, outcome.message_id,
                        )
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
                self._record_run(
                    task, error,
                    message_id=outcome_message_id, duration_ms=outcome_duration_ms,
                )
            finally:
                with self._lock:
                    self._running.discard(task.id)
                self._push_notification(task, error)

    def _push_notification(self, task: ScheduledTask, error: Optional[str]) -> None:
        """Queue a desktop-notification payload for this fire (best effort).

        Delivery is Electron's job: the main process drains
        ``GET /api/v1/scheduled/notifications/pending`` on a timer and posts
        an OS notification, gated by the user's notification preferences.
        """
        body = (error or task.content or "")[:120]
        with self._lock:
            self._pending_notifications.append(
                {
                    "kind": "scheduled_task",
                    "task_id": task.id,
                    "task_name": task.name,
                    "session_id": task.session_id,
                    "status": "failed" if error else "succeeded",
                    "title": (
                        f"❌ 定时任务失败：{task.name}"
                        if error
                        else f"✅ 定时任务已完成：{task.name}"
                    ),
                    "body": body,
                    "created_at": datetime.now().isoformat(),
                }
            )

    def drain_pending_notifications(self) -> List[Dict[str, Any]]:
        """Drain and return queued desktop-notification payloads."""
        with self._lock:
            pending = list(self._pending_notifications)
            self._pending_notifications.clear()
            return pending

    def _record_run(
        self,
        task: ScheduledTask,
        error: Optional[str] = None,
        *,
        message_id: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        with self._lock:
            if task.id not in self._tasks:
                return
            current = self._tasks[task.id]
            now = int(time.time() * 1000)
            # Failed one-shots are paused, NOT completed. No automatic replay:
            # a failed response can be ambiguous after a successful commit.
            new_run_count = current.run_count if error else current.run_count + 1
            budget_reached = (
                error is None
                and current.max_runs is not None
                and new_run_count >= current.max_runs
            )
            enabled = (current.enabled and not budget_reached) if current.type == "recurring" else False
            self._tasks[task.id] = replace(
                current, enabled=enabled,
                last_attempt=now, last_status="failed" if error else "succeeded",
                last_error=error, last_run=current.last_run if error else now,
                next_run=self._next_run_for(current.schedule, enabled),
                run_count=new_run_count,
                last_result_message_id=message_id,
                last_duration_ms=duration_ms,
            )
            if current.type == "once" or budget_reached:
                with suppress(JobLookupError):
                    self._scheduler.remove_job(current.id)
            self._persist(self._tasks[task.id])

    # ---------- persistence ----------

    def _persist(self, task: ScheduledTask) -> None:
        """Write one task through to durable storage."""
        if self._repository is not None:
            self._repository.upsert(task.to_dict())
        else:
            self._save_to_disk()

    def _persist_delete(self, task_id: str) -> None:
        if self._repository is not None:
            self._repository.delete(task_id)
        else:
            self._save_to_disk()

    def _load_from_repo(self) -> None:
        assert self._repository is not None
        for item in self._repository.list_all():
            try:
                task = ScheduledTask.from_dict(item)
                self._tasks[task.id] = task
            except Exception:  # noqa: BLE001 — 单条坏数据不得阻断启动
                logger.warning("skipping malformed scheduled_tasks row: %s", item)

    def _migrate_from_json(self) -> None:
        """Import the legacy JSON store once, then leave it in place as backup.

        Idempotent: the ``scheduler_migrations`` row is the marker, not table
        emptiness — a user who deletes every task would otherwise have them
        resurrected from the stale JSON on the next restart.
        """
        assert self._repository is not None
        source = str(self._store_path)
        if self._repository.has_migrated(source) or not self._store_path.exists():
            return
        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("scheduled_tasks.json unreadable, starting empty: %s", exc)
            self._repository.mark_migrated(source, 0, int(time.time() * 1000))
            return
        if raw.get("version", 1) != SCHEMA_VERSION:
            logger.warning(
                "scheduled_tasks.json schema=%s, expected %s, ignoring",
                raw.get("version", 1), SCHEMA_VERSION,
            )
            self._repository.mark_migrated(source, 0, int(time.time() * 1000))
            return
        importable: List[Dict[str, Any]] = []
        for item in raw.get("tasks", []):
            try:
                ScheduledTask.from_dict(item)
            except Exception:  # noqa: BLE001
                logger.warning("skipping malformed task entry: %s", item)
                continue
            importable.append(item)
        imported = self._repository.bulk_upsert(importable)
        self._repository.mark_migrated(source, imported, int(time.time() * 1000))
        logger.info("migrated %d scheduled tasks from JSON to SQLite", imported)

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
    db: Any = None,
) -> SchedulerService:
    """Initialise the global service. Must be called once during app startup."""
    global _global_service
    _global_service = SchedulerService(
        store_path=store_path,
        message_repo=message_repo,
        session_repo=session_repo,
        db=db,
    )
    return _global_service
