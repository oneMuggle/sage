"""周期性项目健康检查调度器（2026-11-14 M3）。

把 ProjectHealthMonitor 的确定性扫描挂到 SchedulerService 的系统任务上，
每天定时扫描活跃项目，并把 warning / critical 摘要推入桌面通知队列。

与 ProjectHealthMonitor 的分工：本模块只负责调度与报告汇总，扫描与节流
逻辑完全复用 monitor，不重复实现。

Python 3.8 兼容：不使用 PEP 604 联合类型写法，也不使用内建泛型下标。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.services.project_health_monitor import (
    SEVERITY_CRITICAL,
    SEVERITY_OK,
    SEVERITY_WARNING,
    ProjectHealthMonitor,
    ProjectHealthSummary,
)

logger = logging.getLogger(__name__)

#: 默认每天 09:00 扫描一次。
DEFAULT_CRON = "0 9 * * *"

#: 单次扫描的项目上限，避免项目极多时长时间占用调度线程。
DEFAULT_LIMIT = 100

#: 在 SchedulerService 中的系统任务名。
TASK_NAME = "project_health_check"


@dataclass
class HealthReport:
    """一次全量健康检查的结果。"""

    checked: int
    notified: int
    severities: Dict[str, int] = field(default_factory=dict)
    projects: List[Dict[str, Any]] = field(default_factory=list)
    checked_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checked": self.checked,
            "notified": self.notified,
            "severities": dict(self.severities),
            "projects": list(self.projects),
            "checked_at": self.checked_at,
        }


class ProjectHealthScheduler:
    """把健康扫描注册为 SchedulerService 的周期系统任务。"""

    def __init__(
        self,
        monitor: Optional[ProjectHealthMonitor] = None,
        limit: int = DEFAULT_LIMIT,
    ) -> None:
        self._monitor = monitor
        self._limit = limit
        self._last_report: Optional[HealthReport] = None

    @property
    def monitor(self) -> ProjectHealthMonitor:
        if self._monitor is None:
            self._monitor = ProjectHealthMonitor()
        return self._monitor

    def check_all_projects(self) -> HealthReport:
        """扫描所有活跃项目并推送告警，返回本次报告。"""
        summaries: List[ProjectHealthSummary] = self.monitor.scan_all(limit=self._limit)
        notified = self.monitor.push_alerts(summaries)
        report = HealthReport(
            checked=len(summaries),
            notified=notified,
            severities={
                SEVERITY_CRITICAL: sum(
                    1 for s in summaries if s.severity == SEVERITY_CRITICAL
                ),
                SEVERITY_WARNING: sum(
                    1 for s in summaries if s.severity == SEVERITY_WARNING
                ),
                SEVERITY_OK: sum(1 for s in summaries if s.severity == SEVERITY_OK),
            },
            projects=[s.to_dict() for s in summaries],
            checked_at=time.time(),
        )
        self._last_report = report
        return report

    def run_check(self) -> Dict[str, Any]:
        """调度器回调：失败只记日志，不打断后续周期。"""
        try:
            report = self.check_all_projects()
        except Exception:  # noqa: BLE001 - 调度线程不能因单次失败退出
            logger.exception("项目健康定时检查失败")
            return {"error": True}
        logger.info(
            "项目健康定时检查完成：%d 个项目，%d 条通知",
            report.checked,
            report.notified,
        )
        return report.to_dict()

    def latest_report(self) -> Optional[HealthReport]:
        """最近一次检查报告（进程内缓存，供 API / 看板展示）。"""
        return self._last_report

    def register_to_scheduler(
        self,
        scheduler_service: Any,
        cron_expr: str = DEFAULT_CRON,
    ) -> None:
        """注册到 SchedulerService（默认每天 09:00）。"""
        scheduler_service.register_system_task(
            name=TASK_NAME,
            fn=self.run_check,
            cron_expr=cron_expr,
        )
        logger.info("项目健康定时检查已注册（cron: %s）", cron_expr)


_global_scheduler: Optional[ProjectHealthScheduler] = None


def get_project_health_scheduler() -> ProjectHealthScheduler:
    """获取进程级调度器实例。"""
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = ProjectHealthScheduler()
    return _global_scheduler


__all__ = [
    "DEFAULT_CRON",
    "DEFAULT_LIMIT",
    "HealthReport",
    "ProjectHealthScheduler",
    "TASK_NAME",
    "get_project_health_scheduler",
]
