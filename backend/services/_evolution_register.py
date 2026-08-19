"""Lifespan entry for evolution task registration.

PR-C §5.1: Read config.yaml evolution.tasks.<name>.time/day as optional
overrides; default cron schedule if missing or invalid. Pure function —
no side effects beyond scheduler_service.register_evolution_task().
"""
import logging
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

# Default cron schedule — tuple is (minute, hour, day_of_week).
_DEFAULT_SCHEDULE: Dict[str, Tuple[str, str, str]] = {
    "daily_summary": ("0", "3", "*"),
    "memory_pruning": ("30", "3", "*"),
    "preference_learning": ("0", "2", "*"),
    "importance_reevaluation": ("0", "4", "0"),
    "memory_consolidation": ("30", "4", "0"),
}

_TIME_RE = re.compile(r"^([0-9]{1,2}):([0-9]{2})$")
_VALID_DAYS = {
    "*",
    "0-6",
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "mon",
    "tue",
    "wed",
    "thu",
    "fri",
    "sat",
    "sun",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}


def _parse_yaml_overrides(
    config_path: Optional[Path],
) -> Dict[str, Tuple[str, str, str]]:
    """Parse config.yaml → {task_name → (minute, hour, dow)}.

    Returns {} on missing file, malformed YAML, or no evolution section.
    Individual task parse errors are logged and skipped (callers fall
    back to _DEFAULT_SCHEDULE for that task).
    """
    if config_path is None or not config_path.is_file():
        return {}
    try:
        doc = yaml.safe_load(config_path.read_text("utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning("config.yaml 解析失败: %s — 使用默认 cron", exc)
        return {}
    if not isinstance(doc, dict):
        return {}
    evo = doc.get("evolution", {})
    if not isinstance(evo, dict):
        return {}
    tasks_cfg = evo.get("tasks", {})
    if not isinstance(tasks_cfg, dict):
        return {}

    overrides: Dict[str, Tuple[str, str, str]] = {}
    for name, cfg in tasks_cfg.items():
        if name not in _DEFAULT_SCHEDULE:
            continue
        if not isinstance(cfg, dict):
            continue
        time_str = cfg.get("time")
        day_str = cfg.get("day", "*")
        if time_str is None:
            continue
        m = _TIME_RE.match(str(time_str))
        if not m:
            logger.warning(
                "Evolution task %s 的 time='%s' 格式不合法(应为 HH:MM),跳过",
                name,
                time_str,
            )
            continue
        minute, hour = m.group(2), m.group(1)
        if int(minute) > 59 or int(hour) > 23:
            logger.warning(
                "Evolution task %s 的 time='%s' 越界,跳过", name, time_str
            )
            continue
        if str(day_str).lower() not in _VALID_DAYS:
            logger.warning(
                "Evolution task %s 的 day='%s' 非法,跳过", name, day_str
            )
            continue
        overrides[name] = (minute, hour, str(day_str).lower())
    return overrides


def _register_evolution_tasks(
    scheduler_service: "SchedulerService",  # type: ignore[name-defined]  # noqa: F821
    config_path: Optional[Path] = None,
) -> Dict[str, str]:
    """注册 5 个 evolution 任务到 scheduler_service。返回 name → cron 映射。

    行为:
    - 若 config_path 提供且存在 → 解析 YAML evolution.tasks.<name>.time/day
    - 若字段缺失或 YAML 不存在 → 用 _DEFAULT_SCHEDULE 兜底
    - YAML 解析失败 → log warning + 用默认值
    - 单个任务字段错 → log warning + 跳过该任务,继续注册其他
    """
    overrides = _parse_yaml_overrides(config_path)
    from backend.scheduler.evolution import create_evolution_tasks

    tasks = create_evolution_tasks({})
    registered: Dict[str, str] = {}
    for name, task in tasks.items():
        if name not in _DEFAULT_SCHEDULE:
            logger.warning("Unknown evolution task skipped: %s", name)
            continue
        minute, hour, dow = overrides.get(name, _DEFAULT_SCHEDULE[name])
        cron_expr = f"{minute} {hour} * * {dow}"
        try:
            scheduler_service.register_evolution_task(
                name=name, task=task, cron_expr=cron_expr
            )
            registered[name] = cron_expr
        except ValueError as exc:
            logger.warning("Evolution task %s 注册失败: %s", name, exc)
    return registered
