"""进化任务补跑与空闲门控（2026-11-17）。

桌面应用并非 7x24 在线：默认 cron 落在凌晨 02:00–05:30，应用关闭或系统
睡眠时任务直接错过，APScheduler 的 ``misfire_grace_time=300`` 也不会在
下次启动时补跑。本模块负责：

1. 读取 ``evolution_log`` 中每类任务上次成功/跳过的执行时间；
2. 与任务节奏（日报 26h / 周报 8d）比较，得到逾期任务；
3. 启动后延迟执行一次，并注册每 30 分钟的系统任务持续检查；
4. 重任务（记忆反思/固化/技能巡检）只在用户深度空闲时执行，避免抢资源。

设计约束：

* 只补跑“逾期”任务，不做全量重跑；
* 模块级锁 + 每任务 running 集合，避免补跑自身重入；
* 任务失败不抛出到调用方，只记日志。
"""

# ruff: noqa: UP045 — release/win7 需保持 Python 3.8 可解析的类型注解

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

from backend.domain.execution_conditions import IdleLevel
from backend.memory.time_utils import now_ms, seconds_to_ms
from backend.scheduler.evolution_log import record_evolution_log

logger = logging.getLogger(__name__)

#: 日报类任务节奏（略大于 24h，容许几分钟的 cron 漂移）
DAILY_CADENCE_SECONDS = 26 * 3600
#: 周报类任务节奏（略大于 7 天）
WEEKLY_CADENCE_SECONDS = 8 * 24 * 3600

#: 任务 → 节奏。未知任务按日报处理。
CADENCE_SECONDS: Dict[str, int] = {
    "daily_summary": DAILY_CADENCE_SECONDS,
    "memory_pruning": DAILY_CADENCE_SECONDS,
    "preference_learning": DAILY_CADENCE_SECONDS,
    "importance_reevaluation": WEEKLY_CADENCE_SECONDS,
    "memory_consolidation": WEEKLY_CADENCE_SECONDS,
    "skill_consolidation": WEEKLY_CADENCE_SECONDS,
    "memory_reflection": WEEKLY_CADENCE_SECONDS,
}

#: 重任务：可能调用 LLM / 扫描大量记忆，要求用户深度空闲
HEAVY_TASKS = frozenset({"memory_reflection", "memory_consolidation", "skill_consolidation"})

#: 视为“任务已正常完成/明确跳过”的日志状态
_COMPLETED_STATUSES = ("success", "skipped")

#: 失败后至少间隔 1 小时再补跑，避免每 30 分钟反复重试
FAILURE_RETRY_INTERVAL_MS = 60 * 60 * 1000

#: 启动后延迟执行补跑，避免和启动阶段的服务初始化抢资源
STARTUP_DELAY_SECONDS = 90

_maintenance_lock = threading.Lock()
_running: Set[str] = set()
_started = False


def _latest_log(db: Any, name: str) -> Optional[Dict[str, Any]]:
    """该任务最近一条 evolution_log（任意状态）。"""
    try:
        row = (
            db.get_connection()
            .execute(
                """
            SELECT status, created_at
            FROM evolution_log
            WHERE evolution_type = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
                [name],
            )
            .fetchone()
        )
    except Exception as exc:  # noqa: BLE001 — 读日志失败按“无记录”处理
        logger.warning("evolution maintenance: 读取最近日志失败(%s): %s", name, exc)
        return None
    if row is None:
        return None
    return {"status": row["status"], "created_at": row["created_at"]}


def _latest_completed_log(db: Any, name: str) -> Optional[Dict[str, Any]]:
    """该任务最近一条“成功/跳过”的 evolution_log。"""
    placeholders = ",".join("?" for _ in _COMPLETED_STATUSES)
    try:
        row = (
            db.get_connection()
            .execute(
                f"""
            SELECT status, created_at
            FROM evolution_log
            WHERE evolution_type = ? AND status IN ({placeholders})
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
                [name, *_COMPLETED_STATUSES],
            )
            .fetchone()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("evolution maintenance: 读取完成日志失败(%s): %s", name, exc)
        return None
    if row is None:
        return None
    return {"status": row["status"], "created_at": row["created_at"]}


def compute_overdue_tasks(
    db: Any,
    scheduler_service: Any,
    *,
    now_ms_value: Optional[int] = None,
    cadence: Optional[Dict[str, int]] = None,
) -> List[str]:
    """返回当前逾期的 evolution 任务名列表。

    判定规则：

    * 从未有 success/skipped 记录 → 逾期；
    * 最近 success/skipped 距今超过任务节奏 → 逾期；
    * 最近一次尝试是失败、且失败发生在 1 小时内 → 暂缓重试。
    """
    now_value = now_ms() if now_ms_value is None else int(now_ms_value)
    cadence_map = cadence or CADENCE_SECONDS
    try:
        names = list(scheduler_service.get_evolution_task_names())
    except Exception:  # noqa: BLE001 — 调度器不可用时不猜任务清单
        logger.warning("evolution maintenance: 读取任务清单失败", exc_info=True)
        return []

    overdue: List[str] = []
    for name in names:
        latest = _latest_log(db, name)
        if latest is not None and latest.get("status") == "failed":
            failed_at_ms = seconds_to_ms(latest.get("created_at")) or 0
            if now_value - failed_at_ms < FAILURE_RETRY_INTERVAL_MS:
                continue
        completed = _latest_completed_log(db, name)
        if completed is None:
            overdue.append(name)
            continue
        completed_at_ms = seconds_to_ms(completed.get("created_at")) or 0
        interval_ms = int(cadence_map.get(name, DAILY_CADENCE_SECONDS)) * 1000
        if now_value - completed_at_ms >= interval_ms:
            overdue.append(name)
    return overdue


def _default_idle_check() -> bool:
    """默认空闲判定：深度空闲（>30 分钟无操作）才允许重任务。"""
    try:
        from backend.services.idle_detector import (  # noqa: PLC0415 — 延迟导入避免循环依赖
            get_idle_detector,
        )

        return get_idle_detector().is_idle_at_least(IdleLevel.DEEP)
    except Exception:  # noqa: BLE001 — headless/测试环境无检测器时放行
        return True


def run_overdue_tasks(
    scheduler_service: Any,
    db: Any,
    *,
    idle_check: Optional[Callable[[], bool]] = None,
    now_ms_value: Optional[int] = None,
    max_tasks: Optional[int] = None,
) -> List[str]:
    """执行逾期任务；返回实际执行的任务名列表。

    重任务在 ``idle_check()`` 为 False 时跳过（留待下一次检查）。
    """
    if not _maintenance_lock.acquire(blocking=False):
        logger.debug("evolution maintenance: 已有补跑在执行，跳过本轮")
        return []
    try:
        overdue = compute_overdue_tasks(db, scheduler_service, now_ms_value=now_ms_value)
        check_idle = idle_check or _default_idle_check
        executed: List[str] = []
        failed: List[str] = []
        for name in overdue:
            if max_tasks is not None and len(executed) >= max_tasks:
                break
            if name in _running:
                continue
            if name in HEAVY_TASKS:
                try:
                    if not check_idle():
                        logger.info("evolution maintenance: 用户忙碌，暂缓重任务 %s", name)
                        continue
                except Exception:  # noqa: BLE001 — 空闲检测异常时放行
                    logger.warning(
                        "evolution maintenance: 空闲检测失败，放行 %s", name, exc_info=True
                    )
            _running.add(name)
            try:
                result = scheduler_service.run_evolution_task_now(name)
                if result is None:
                    failed.append(name)
                    logger.warning("evolution maintenance: 任务 %s 执行失败", name)
                else:
                    executed.append(name)
                    logger.info("evolution maintenance: 补跑 %s 完成: %s", name, result)
            except Exception:  # noqa: BLE001 — 单任务失败不阻断其余
                failed.append(name)
                logger.exception("evolution maintenance: 补跑 %s 异常", name)
            finally:
                _running.discard(name)

        if executed or failed:
            record_evolution_log(
                db,
                evolution_type="maintenance_catchup",
                description=(
                    f"进化任务补跑: 执行 {len(executed)} 个"
                    f"{('，失败 ' + ', '.join(failed)) if failed else ''}"
                ),
                status="success" if not failed else "failed",
                error_message=", ".join(failed) if failed else None,
                trigger_type="catch_up",
                metrics={"executed": executed, "failed": failed, "overdue": overdue},
            )
        return executed
    finally:
        _maintenance_lock.release()


def start_maintenance(
    scheduler_service: Any,
    db: Any,
    *,
    startup_delay_seconds: int = STARTUP_DELAY_SECONDS,
) -> None:
    """注册补跑系统任务，并在启动后延迟执行一次。幂等。"""
    global _started
    with _maintenance_lock:
        if _started:
            return
        _started = True

    try:
        scheduler_service.register_system_task(
            "evolution-catchup",
            lambda: run_overdue_tasks(scheduler_service, db),
            "7,37 * * * *",
        )
    except Exception:  # noqa: BLE001 — 注册失败不影响启动
        logger.exception("evolution maintenance: 注册周期检查失败（忽略）")

    def _delayed_run() -> None:
        time.sleep(max(0, int(startup_delay_seconds)))
        try:
            run_overdue_tasks(scheduler_service, db)
        except Exception:  # noqa: BLE001 — 启动补跑失败只记日志
            logger.exception("evolution maintenance: 启动补跑失败（忽略）")

    threading.Thread(target=_delayed_run, name="evolution-catchup-startup", daemon=True).start()
    logger.info(
        "evolution maintenance: 已启动（启动后 %ss 补跑 + 每 30 分钟检查）",
        startup_delay_seconds,
    )


def reset_maintenance_state() -> None:
    """仅测试用：重置模块级启动/运行状态。"""
    global _started
    with _maintenance_lock:
        _started = False
        _running.clear()


__all__ = [
    "CADENCE_SECONDS",
    "DAILY_CADENCE_SECONDS",
    "HEAVY_TASKS",
    "WEEKLY_CADENCE_SECONDS",
    "compute_overdue_tasks",
    "reset_maintenance_state",
    "run_overdue_tasks",
    "start_maintenance",
]
