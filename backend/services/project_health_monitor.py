"""项目健康监控器（2026-11-14 M1）。

确定性扫描活跃项目的里程碑逾期 / 阻塞情况，生成健康摘要；发现问题时
推入 ProjectHealthNotificationQueue，由 Electron 主进程 15s 轮询转成 OS 通知。

与 ProjectAdvisor 的分工：
- ProjectHealthMonitor：纯本地计算、零 LLM 成本，可高频调用（定时任务 / API 轮询）
- ProjectAdvisor：LLM 深度分析，30 分钟缓存，用户手动触发

Python 3.8 兼容：不使用 PEP 604 联合类型写法，也不使用内建泛型下标。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.services.project_health_notifications import (
    ProjectHealthNotificationQueue,
    get_project_health_notification_queue,
)

logger = logging.getLogger(__name__)

#: 逾期达到该天数时升级为 critical。
CRITICAL_OVERDUE_DAYS = 7

#: 同一项目同一级别的告警推送间隔（秒），避免定时任务高频轰炸。
NOTIFY_INTERVAL_SECONDS = 24 * 60 * 60

SEVERITY_OK = "ok"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

_SEVERITY_RANK = {SEVERITY_CRITICAL: 0, SEVERITY_WARNING: 1, SEVERITY_OK: 2}


@dataclass
class OverdueMilestone:
    """单条逾期里程碑。"""

    milestone_id: str
    title: str
    due_date: str
    days_overdue: int
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "milestone_id": self.milestone_id,
            "title": self.title,
            "due_date": self.due_date,
            "days_overdue": self.days_overdue,
            "status": self.status,
        }


@dataclass
class ProjectHealthSummary:
    """单个项目的健康摘要。"""

    project_id: str
    project_name: str
    severity: str
    total_milestones: int
    completed_milestones: int
    in_progress_milestones: int
    pending_milestones: int
    blocked_milestones: int
    project_stage: str = ""
    overdue: List[OverdueMilestone] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "severity": self.severity,
            "project_stage": self.project_stage,
            "total_milestones": self.total_milestones,
            "completed_milestones": self.completed_milestones,
            "in_progress_milestones": self.in_progress_milestones,
            "pending_milestones": self.pending_milestones,
            "blocked_milestones": self.blocked_milestones,
            "overdue": [o.to_dict() for o in self.overdue],
        }


class ProjectHealthMonitor:
    """扫描项目里程碑状态并生成健康摘要。"""

    def __init__(
        self,
        project_repo: Any = None,
        milestone_repo: Any = None,
        notification_queue: Optional[ProjectHealthNotificationQueue] = None,
        now_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self._project_repo = project_repo
        self._milestone_repo = milestone_repo
        self._queue = notification_queue
        self._now = now_fn or time.time
        # 节流表：key = "{project_id}:{severity}" -> 上次推送时间戳（秒）
        self._notified: Dict[str, float] = {}
        self._lock = threading.Lock()

    # ── 依赖懒加载（避免导入期初始化数据库） ─────────────────────────────

    @property
    def project_repo(self) -> Any:
        if self._project_repo is None:
            from backend.data.project_repo import ProjectRepository

            self._project_repo = ProjectRepository()
        return self._project_repo

    @property
    def milestone_repo(self) -> Any:
        if self._milestone_repo is None:
            from backend.data.project_milestone_repo import ProjectMilestoneRepository

            self._milestone_repo = ProjectMilestoneRepository()
        return self._milestone_repo

    @property
    def notification_queue(self) -> ProjectHealthNotificationQueue:
        if self._queue is None:
            self._queue = get_project_health_notification_queue()
        return self._queue

    # ── 扫描 ─────────────────────────────────────────────────────────────

    def summarize(
        self,
        project_id: str,
        today: Optional[str] = None,
        project: Any = None,
    ) -> Optional[ProjectHealthSummary]:
        """生成单个项目的健康摘要；项目不存在时返回 None。"""
        if project is None:
            project = self.project_repo.get(project_id)
        if project is None:
            return None

        today = today or time.strftime("%Y-%m-%d")
        milestones = self.milestone_repo.list_by_project(project_id)

        overdue: List[OverdueMilestone] = []
        completed = 0
        in_progress = 0
        pending = 0
        blocked = 0

        for m in milestones:
            if m.status == "completed":
                completed += 1
            elif m.status == "in_progress":
                in_progress += 1
            elif m.status == "blocked":
                blocked += 1
            else:
                pending += 1

            if m.due_date and m.status != "completed" and _parse_date(m.due_date) is not None:
                days = _days_between(m.due_date, today)
                if days <= 0:
                    continue
                overdue.append(
                    OverdueMilestone(
                        milestone_id=str(m.id),
                        title=m.title,
                        due_date=m.due_date,
                        days_overdue=days,
                        status=m.status,
                    )
                )

        overdue.sort(key=lambda o: o.days_overdue, reverse=True)
        max_overdue = overdue[0].days_overdue if overdue else 0
        if max_overdue >= CRITICAL_OVERDUE_DAYS:
            severity = SEVERITY_CRITICAL
        elif overdue or blocked:
            severity = SEVERITY_WARNING
        else:
            severity = SEVERITY_OK

        return ProjectHealthSummary(
            project_id=str(project.id),
            project_name=project.name,
            severity=severity,
            total_milestones=len(milestones),
            completed_milestones=completed,
            in_progress_milestones=in_progress,
            pending_milestones=pending,
            blocked_milestones=blocked,
            project_stage=project.project_stage or "",
            overdue=overdue,
        )

    def scan_all(
        self, limit: int = 100, today: Optional[str] = None,
    ) -> List[ProjectHealthSummary]:
        """扫描所有活跃项目，按严重程度降序返回。

        ``today`` 允许测试注入固定日期,避免随真实时间漂移触发断言;
        未传时回落到 ``time.strftime``。
        """
        today = today or time.strftime("%Y-%m-%d")
        summaries: List[ProjectHealthSummary] = []
        for project in self.project_repo.list(limit=limit):
            if (project.status or "active") != "active":
                continue
            summary = self.summarize(project.id, today=today, project=project)
            if summary is not None:
                summaries.append(summary)
        summaries.sort(
            key=lambda s: (_SEVERITY_RANK.get(s.severity, 9), -len(s.overdue))
        )
        return summaries

    # ── 通知推送 ─────────────────────────────────────────────────────────

    def push_alerts(self, summaries: List[ProjectHealthSummary]) -> int:
        """把 warning / critical 摘要推入通知队列；返回实际推送条数。"""
        pushed = 0
        now_ts = self._now()
        for summary in summaries:
            if summary.severity == SEVERITY_OK:
                continue
            key = f"{summary.project_id}:{summary.severity}"
            with self._lock:
                last = self._notified.get(key)
                if last is not None and now_ts - last < NOTIFY_INTERVAL_SECONDS:
                    continue
                self._notified[key] = now_ts

            title, body = _build_notification(summary)
            self.notification_queue.push(
                project_id=summary.project_id,
                project_name=summary.project_name,
                severity=summary.severity,
                title=title,
                body=body,
            )
            pushed += 1
        return pushed

    def scan_and_notify(self, limit: int = 100) -> Dict[str, Any]:
        """扫描 + 推送，返回本次扫描结果摘要（供 API / 调度器回报）。"""
        summaries = self.scan_all(limit=limit)
        pushed = self.push_alerts(summaries)
        return {
            "checked": len(summaries),
            "notified": pushed,
            "severities": {
                SEVERITY_CRITICAL: sum(
                    1 for s in summaries if s.severity == SEVERITY_CRITICAL
                ),
                SEVERITY_WARNING: sum(
                    1 for s in summaries if s.severity == SEVERITY_WARNING
                ),
                SEVERITY_OK: sum(1 for s in summaries if s.severity == SEVERITY_OK),
            },
        }

    def reset_throttle(self) -> None:
        """测试用：清空推送节流记录。"""
        with self._lock:
            self._notified.clear()


def _build_notification(summary: ProjectHealthSummary) -> Tuple[str, str]:
    """构造通知标题与正文。"""
    if summary.severity == SEVERITY_CRITICAL:
        longest = summary.overdue[0]
        return (
            f"项目逾期告警：{summary.project_name}",
            f"{len(summary.overdue)} 个里程碑逾期，最久 {longest.days_overdue} 天（{longest.title}）",
        )

    if summary.overdue:
        longest = summary.overdue[0]
        return (
            f"项目待关注：{summary.project_name}",
            f"{len(summary.overdue)} 个里程碑逾期，最久 {longest.days_overdue} 天（{longest.title}）",
        )

    return (
        f"项目待关注：{summary.project_name}",
        f"{summary.blocked_milestones} 个里程碑处于阻塞状态",
    )


def _parse_date(value: str) -> Optional[Any]:
    """解析 YYYY-MM-DD；无法解析时返回 None（调用方据此跳过该条）。"""
    try:
        from datetime import datetime

        return datetime.strptime(value, "%Y-%m-%d")  # noqa: DTZ007
    except (ValueError, TypeError):
        return None


def _days_between(date_a: str, date_b: str) -> int:
    """计算两个 YYYY-MM-DD 日期之间的天数差（b - a）。"""
    try:
        from datetime import datetime

        da = datetime.strptime(date_a, "%Y-%m-%d")  # noqa: DTZ007
        db = datetime.strptime(date_b, "%Y-%m-%d")  # noqa: DTZ007
        return (db - da).days
    except (ValueError, TypeError):
        return 0


__all__ = [
    "CRITICAL_OVERDUE_DAYS",
    "NOTIFY_INTERVAL_SECONDS",
    "OverdueMilestone",
    "ProjectHealthMonitor",
    "ProjectHealthSummary",
    "SEVERITY_CRITICAL",
    "SEVERITY_OK",
    "SEVERITY_WARNING",
]
