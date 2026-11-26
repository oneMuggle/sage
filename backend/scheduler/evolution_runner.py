"""进化任务执行包装（手动 / cron / 补跑共用）。

职责三件：

1. 运行状态登记 —— 经 ``EvolutionRunRegistry`` 记录 running / 阶段 / 终态，
   前端轮询 ``GET /scheduled/evolution/tasks`` 读取；
2. 进度回调注入 —— 把任务的 ``_report_progress`` 接到注册表 update；
3. 触发来源上下文 —— 任务内部写 evolution_log 时 ``trigger_type`` 取到
   manual / scheduled / catch_up，而不是一律 scheduled。

放在独立模块而不是 SchedulerService 方法里，是为了让 services/scheduler.py
守住 800 行架构棘轮，同时让手动触发线程与 APScheduler worker 线程共用
同一份执行语义。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def run_evolution_task(
    name: str,
    task: Any,
    trigger: str = "scheduled",
    run_id: str = "",
) -> Optional[Dict[str, Any]]:
    """执行进化任务并登记运行状态；返回任务统计，互斥命中或异常返回 None。

    ``run_id`` 由异步启动方（launch_evolution_task）预先登记后传入，
    保证 ``begin`` 与线程启动之间不被 cron 抢占；为空时本函数自行登记。
    """
    from backend.scheduler.evolution_log import (
        reset_evolution_trigger,
        set_evolution_trigger,
    )
    from backend.scheduler.evolution_run_registry import get_evolution_run_registry

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
    try:
        result = task.run()
    except Exception as exc:  # noqa: BLE001 — 单任务失败只记日志并落终态
        registry.finish(name, run_id, error=str(exc))
        logger.exception("Evolution task %s failed", name)
        return None
    else:
        registry.finish(name, run_id, result=result)
        logger.info("Evolution task %s completed: %s", name, result)
        return result
    finally:
        task.set_progress_reporter(None)
        reset_evolution_trigger(token)
