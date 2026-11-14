"""Unit tests for the periodic project health scheduler (2026-11-14 M3)."""

from __future__ import annotations

from typing import Any, List

import pytest

from backend.services.project_health_monitor import (
    SEVERITY_CRITICAL,
    SEVERITY_OK,
    SEVERITY_WARNING,
    ProjectHealthSummary,
)
from backend.services.project_health_scheduler import (
    DEFAULT_CRON,
    TASK_NAME,
    ProjectHealthScheduler,
    get_project_health_scheduler,
)


def _summary(project_id: str, severity: str) -> ProjectHealthSummary:
    return ProjectHealthSummary(
        project_id=project_id,
        project_name="示例课题",
        severity=severity,
        total_milestones=3,
        completed_milestones=1,
        in_progress_milestones=1,
        pending_milestones=1,
        blocked_milestones=0,
        project_stage="实施",
    )


class FakeMonitor:
    def __init__(self, summaries: List[ProjectHealthSummary], pushed: int = 0) -> None:
        self.summaries = summaries
        self.pushed = pushed
        self.scan_limit: Any = None
        self.push_calls: List[List[ProjectHealthSummary]] = []

    def scan_all(self, limit: int = 100) -> List[ProjectHealthSummary]:
        self.scan_limit = limit
        return self.summaries

    def push_alerts(self, summaries: List[ProjectHealthSummary]) -> int:
        self.push_calls.append(summaries)
        return self.pushed


class FailingMonitor(FakeMonitor):
    def scan_all(self, limit: int = 100) -> List[ProjectHealthSummary]:
        raise RuntimeError("database unavailable")


def test_check_all_projects_builds_report() -> None:
    monitor = FakeMonitor(
        [
            _summary("p1", SEVERITY_CRITICAL),
            _summary("p2", SEVERITY_WARNING),
            _summary("p3", SEVERITY_OK),
            _summary("p4", SEVERITY_WARNING),
        ],
        pushed=2,
    )
    scheduler = ProjectHealthScheduler(monitor=monitor, limit=50)

    report = scheduler.check_all_projects()

    assert monitor.scan_limit == 50
    assert monitor.push_calls == [monitor.summaries]
    assert report.checked == 4
    assert report.notified == 2
    assert report.severities == {
        SEVERITY_CRITICAL: 1,
        SEVERITY_WARNING: 2,
        SEVERITY_OK: 1,
    }
    assert [item["project_id"] for item in report.projects] == ["p1", "p2", "p3", "p4"]
    assert report.projects[0]["severity"] == SEVERITY_CRITICAL
    assert isinstance(report.checked_at, float)


def test_run_check_returns_serializable_dict() -> None:
    monitor = FakeMonitor([_summary("p1", SEVERITY_WARNING)], pushed=1)
    scheduler = ProjectHealthScheduler(monitor=monitor)

    payload = scheduler.run_check()

    assert payload["checked"] == 1
    assert payload["notified"] == 1
    assert payload["severities"][SEVERITY_WARNING] == 1
    assert payload["projects"][0]["project_name"] == "示例课题"
    assert "error" not in payload


def test_run_check_swallows_failures() -> None:
    scheduler = ProjectHealthScheduler(monitor=FailingMonitor([]))

    assert scheduler.run_check() == {"error": True}
    assert scheduler.latest_report() is None


def test_latest_report_tracks_last_run() -> None:
    monitor = FakeMonitor([_summary("p1", SEVERITY_OK)])
    scheduler = ProjectHealthScheduler(monitor=monitor)

    assert scheduler.latest_report() is None
    first = scheduler.check_all_projects()
    assert scheduler.latest_report() is first


def test_register_to_scheduler_uses_system_task() -> None:
    calls: List[dict] = []

    class FakeSchedulerService:
        def register_system_task(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    scheduler = ProjectHealthScheduler(monitor=FakeMonitor([]))
    scheduler.register_to_scheduler(FakeSchedulerService())

    assert len(calls) == 1
    assert calls[0]["name"] == TASK_NAME
    assert calls[0]["cron_expr"] == DEFAULT_CRON
    assert calls[0]["fn"] == scheduler.run_check


def test_get_project_health_scheduler_is_singleton() -> None:
    assert get_project_health_scheduler() is get_project_health_scheduler()


def test_monitor_property_is_lazy() -> None:
    scheduler = ProjectHealthScheduler()

    assert scheduler.monitor is not None
    assert scheduler.monitor is scheduler.monitor


@pytest.mark.parametrize("severity", [SEVERITY_OK, SEVERITY_WARNING, SEVERITY_CRITICAL])
def test_severity_counts(severity: str) -> None:
    scheduler = ProjectHealthScheduler(monitor=FakeMonitor([_summary("p1", severity)]))

    report = scheduler.check_all_projects()

    assert report.severities[severity] == 1
    assert sum(report.severities.values()) == 1
