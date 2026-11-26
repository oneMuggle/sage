"""进化任务执行包装（手动 / cron / 补跑共用）。

职责：

1. 运行状态登记 —— 经 ``EvolutionRunRegistry`` 记录 running / 阶段 / 终态，
   前端轮询 ``GET /scheduled/evolution/tasks`` 读取；
2. 进度回调注入 —— 把任务的 ``_report_progress`` 接到注册表 update；
3. 取消检查注入 —— 任务在检查点查询注册表取消标志（协作式）；
4. 触发来源上下文 —— 任务内部写 evolution_log 时 ``trigger_type`` 取到
   manual / scheduled / catch_up，而不是一律 scheduled；
5. 完成通知 —— 仅手动触发的终态入队后台通知（Electron 转 OS 通知），
   cron / 补跑不打扰用户。

放在独立模块而不是 SchedulerService 方法里，是为了让 services/scheduler.py
守住 800 行架构棘轮，同时让手动触发线程与 APScheduler worker 线程共用
同一份执行语义。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: 进化任务中文名（通知标题用；与前端 TASK_LABELS 保持一致）。
EVOLUTION_TASK_LABELS: Dict[str, str] = {
    "memory_reflection": "记忆整理",
    "memory_pruning": "记忆修剪",
    "memory_consolidation": "记忆固化",
    "daily_summary": "每日摘要",
    "preference_learning": "偏好学习",
    "importance_reevaluation": "重要性重评估",
    "skill_consolidation": "技能巡检",
    "maintenance_catchup": "进化补跑",
}


def _result_summary(result: Optional[Dict[str, Any]]) -> str:
    """把终态统计压成一行通知正文（最多 4 项；游标是内部细节）。"""
    if not result:
        return ""
    parts = []
    for key, value in result.items():
        if key == "reflection_backlog_cursor_ms":
            continue
        parts.append(f"{key}: {value}")
        if len(parts) >= 4:
            break
    return "，".join(parts)


def _notify_manual_finish(name: str, trigger: str, state: str, summary: str) -> None:
    """手动触发的任务终态推一条通知（cron / 补跑不打扰用户）。"""
    if trigger != "manual":
        return
    try:
        from backend.services.background_notifications import (
            get_background_notification_queue,
        )

        get_background_notification_queue().push_evolution(
            name=name,
            label=EVOLUTION_TASK_LABELS.get(name, name),
            status=state,
            summary=summary,
        )
    except Exception:  # noqa: BLE001 — 通知是旁路，失败只记日志
        logger.debug("进化任务完成通知入队失败", exc_info=True)


def run_evolution_task(
    name: str,
    task: Any,
    trigger: str = "scheduled",
    run_id: str = "",
) -> Optional[Dict[str, Any]]:
    """执行进化任务并登记运行状态；返回任务统计，互斥命中或取消/异常返回 None。

    ``run_id`` 由异步启动方（launch_evolution_task）预先登记后传入，
    保证 ``begin`` 与线程启动之间不被 cron 抢占；为空时本函数自行登记。
    """
    from backend.scheduler.evolution import EvolutionTaskCancelled
    from backend.scheduler.evolution_log import (
        reset_evolution_trigger,
        set_evolution_trigger,
    )
    from backend.scheduler.evolution_run_registry import (
        get_evolution_run_registry,
        serialize_evolution_result,
    )

    registry = get_evolution_run_registry()
    if not run_id:
        run_id = registry.begin(name, trigger) or ""
        if not run_id:
            logger.info("Evolution task %s already running, skip duplicate run", name)
            return None

    token = set_evolution_trigger(trigger)
    task.set_progress_reporter(
        lambda phase, label, extra: registry.update(name, run_id, phase, label, extra)
    )
    task.set_cancel_check(lambda: registry.is_cancel_requested(name, run_id))
    try:
        result = task.run()
    except EvolutionTaskCancelled:
        registry.finish(name, run_id, cancelled=True)
        logger.info("Evolution task %s cancelled", name)
        _notify_manual_finish(name, trigger, "cancelled", "")
        return None
    except Exception as exc:  # noqa: BLE001 — 单任务失败只记日志并落终态
        registry.finish(name, run_id, error=str(exc))
        logger.exception("Evolution task %s failed", name)
        _notify_manual_finish(name, trigger, "failed", str(exc))
        return None
    else:
        registry.finish(name, run_id, result=result)
        logger.info("Evolution task %s completed: %s", name, result)
        _notify_manual_finish(
            name, trigger, "succeeded", _result_summary(serialize_evolution_result(result))
        )
        return result
    finally:
        task.set_progress_reporter(None)
        task.set_cancel_check(None)
        reset_evolution_trigger(token)
