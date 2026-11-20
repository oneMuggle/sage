"""ProjectHealthMonitor 单元测试（2026-11-14 M1）。

覆盖：严重等级判定、逾期计数、阻塞计数、节流推送、scan_all 排序。
全部使用内存 fake repo，不触碰真实数据库。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pytest

from backend.services.project_health_monitor import (
    CRITICAL_OVERDUE_DAYS,
    NOTIFY_INTERVAL_SECONDS,
    SEVERITY_CRITICAL,
    SEVERITY_OK,
    SEVERITY_WARNING,
    ProjectHealthMonitor,
)
from backend.services.project_health_notifications import ProjectHealthNotificationQueue


@dataclass
class FakeProject:
    id: str
    name: str
    status: str = "active"
    project_stage: str = ""


@dataclass
class FakeMilestone:
    id: str
    title: str
    due_date: Optional[str] = None
    status: str = "pending"


class FakeProjectRepo:
    def __init__(self, projects: List[FakeProject]) -> None:
        self._projects = {p.id: p for p in projects}

    def get(self, project_id: str) -> Optional[FakeProject]:
        return self._projects.get(project_id)

    def list(self, limit: int = 100, offset: int = 0) -> List[FakeProject]:
        return list(self._projects.values())[offset : offset + limit]


class FakeMilestoneRepo:
    def __init__(self, by_project: dict) -> None:
        self._by_project = by_project

    def list_by_project(self, project_id: str) -> List[FakeMilestone]:
        return list(self._by_project.get(project_id, []))


def make_monitor(projects: List[FakeProject], milestones: dict, now: float = 1000.0):
    queue = ProjectHealthNotificationQueue()
    monitor = ProjectHealthMonitor(
        project_repo=FakeProjectRepo(projects),
        milestone_repo=FakeMilestoneRepo(milestones),
        notification_queue=queue,
        now_fn=lambda: now,
    )
    return monitor, queue


# ── summarize ────────────────────────────────────────────────────────────


def test_summarize_returns_ok_when_no_overdue_or_blocked():
    monitor, _ = make_monitor(
        [FakeProject(id="p1", name="Alpha")],
        {
            "p1": [
                FakeMilestone(id="m1", title="Done", due_date="2026-01-01", status="completed")
            ]
        },
    )
    summary = monitor.summarize("p1", today="2026-11-14")
    assert summary is not None
    assert summary.severity == SEVERITY_OK
    assert summary.completed_milestones == 1
    assert summary.overdue == []


def test_summarize_returns_warning_for_small_overdue():
    monitor, _ = make_monitor(
        [FakeProject(id="p1", name="Alpha")],
        {
            "p1": [
                FakeMilestone(id="m1", title="Late", due_date="2026-11-12", status="in_progress")
            ]
        },
    )
    summary = monitor.summarize("p1", today="2026-11-14")
    assert summary is not None
    assert summary.severity == SEVERITY_WARNING
    assert len(summary.overdue) == 1
    assert summary.overdue[0].days_overdue == 2
    assert summary.overdue[0].milestone_id == "m1"


def test_summarize_returns_critical_when_overdue_exceeds_threshold():
    # 10 天 > CRITICAL_OVERDUE_DAYS(7)
    monitor, _ = make_monitor(
        [FakeProject(id="p1", name="Alpha")],
        {
            "p1": [
                FakeMilestone(id="m1", title="Very Late", due_date="2026-11-04", status="pending")
            ]
        },
    )
    summary = monitor.summarize("p1", today="2026-11-14")
    assert summary is not None
    assert summary.severity == SEVERITY_CRITICAL
    assert summary.overdue[0].days_overdue == 10


def test_summarize_returns_warning_for_blocked_without_overdue():
    monitor, _ = make_monitor(
        [FakeProject(id="p1", name="Alpha")],
        {
            "p1": [
                FakeMilestone(id="m1", title="Stuck", due_date="2026-12-31", status="blocked")
            ]
        },
    )
    summary = monitor.summarize("p1", today="2026-11-14")
    assert summary is not None
    assert summary.severity == SEVERITY_WARNING
    assert summary.blocked_milestones == 1
    assert summary.overdue == []


def test_summarize_returns_none_for_unknown_project():
    monitor, _ = make_monitor([], {})
    assert monitor.summarize("missing", today="2026-11-14") is None


def test_summarize_ignores_completed_milestones_even_if_past_due():
    monitor, _ = make_monitor(
        [FakeProject(id="p1", name="Alpha")],
        {
            "p1": [
                FakeMilestone(
                    id="m1", title="Done Late", due_date="2026-01-01", status="completed"
                )
            ]
        },
    )
    summary = monitor.summarize("p1", today="2026-11-14")
    assert summary is not None
    assert summary.severity == SEVERITY_OK
    assert summary.overdue == []


def test_overdue_sorted_by_days_desc():
    monitor, _ = make_monitor(
        [FakeProject(id="p1", name="Alpha")],
        {
            "p1": [
                FakeMilestone(id="m1", title="Short", due_date="2026-11-13", status="pending"),
                FakeMilestone(id="m2", title="Long", due_date="2026-11-01", status="pending"),
            ]
        },
    )
    summary = monitor.summarize("p1", today="2026-11-14")
    assert summary is not None
    assert [o.milestone_id for o in summary.overdue] == ["m2", "m1"]


# ── scan_all ─────────────────────────────────────────────────────────────


def test_scan_all_skips_non_active_projects():
    monitor, _ = make_monitor(
        [
            FakeProject(id="p1", name="Active"),
            FakeProject(id="p2", name="Archived", status="archived"),
        ],
        {"p1": [], "p2": []},
    )
    summaries = monitor.scan_all()
    assert [s.project_id for s in summaries] == ["p1"]


def test_scan_all_sorts_critical_before_warning_before_ok():
    monitor, _ = make_monitor(
        [
            FakeProject(id="ok", name="OK"),
            FakeProject(id="warn", name="Warn"),
            FakeProject(id="crit", name="Crit"),
        ],
        {
            "ok": [],
            "warn": [FakeMilestone(id="mw", title="W", due_date="2026-11-17", status="pending")],
            "crit": [FakeMilestone(id="mc", title="C", due_date="2026-10-01", status="pending")],
        },
    )
    # 注入固定日期，避免真实日历漂移。在 today=2026-11-20 下：
    # - crit: 2026-10-01 逾期 50 天 → CRITICAL
    # - warn: 2026-11-17 逾期 3 天 → WARNING（3 < CRITICAL_OVERDUE_DAYS=7）
    # - ok: 无里程碑 → OK
    summaries = monitor.scan_all(today="2026-11-20")
    assert [s.project_id for s in summaries] == ["crit", "warn", "ok"]


# ── push_alerts 节流 ─────────────────────────────────────────────────────


def test_push_alerts_skips_ok_summaries():
    monitor, queue = make_monitor([FakeProject(id="p1", name="Alpha")], {"p1": []})
    summary = monitor.summarize("p1", today="2026-11-14")
    assert summary is not None
    assert monitor.push_alerts([summary]) == 0
    assert queue.size() == 0


def test_push_alerts_emits_warning_once_then_throttles():
    monitor, queue = make_monitor(
        [FakeProject(id="p1", name="Alpha")],
        {"p1": [FakeMilestone(id="m1", title="Late", due_date="2026-11-12", status="pending")]},
        now=1000.0,
    )
    summary = monitor.summarize("p1", today="2026-11-14")
    assert summary is not None

    assert monitor.push_alerts([summary]) == 1
    items = queue.drain()
    assert len(items) == 1
    assert items[0]["kind"] == "project_health"
    assert items[0]["project_id"] == "p1"
    assert items[0]["severity"] == SEVERITY_WARNING
    assert "Alpha" in items[0]["title"]

    # 同一时间窗口内再推 → 节流，不重复
    assert monitor.push_alerts([summary]) == 0
    assert queue.drain() == []


def test_push_alerts_re_emits_after_interval():
    clock = {"now": 1000.0}
    queue = ProjectHealthNotificationQueue()
    monitor = ProjectHealthMonitor(
        project_repo=FakeProjectRepo([FakeProject(id="p1", name="Alpha")]),
        milestone_repo=FakeMilestoneRepo(
            {"p1": [FakeMilestone(id="m1", title="Late", due_date="2026-11-12", status="pending")]}
        ),
        notification_queue=queue,
        now_fn=lambda: clock["now"],
    )
    summary = monitor.summarize("p1", today="2026-11-14")
    assert summary is not None
    assert monitor.push_alerts([summary]) == 1
    queue.drain()

    clock["now"] += NOTIFY_INTERVAL_SECONDS + 1
    assert monitor.push_alerts([summary]) == 1
    assert len(queue.drain()) == 1


def test_push_alerts_critical_and_warning_use_separate_throttle_keys():
    monitor, queue = make_monitor(
        [FakeProject(id="p1", name="Alpha")],
        {
            "p1": [
                FakeMilestone(id="m1", title="Very Late", due_date="2026-10-01", status="pending")
            ]
        },
        now=1000.0,
    )
    critical = monitor.summarize("p1", today="2026-11-14")
    assert critical is not None
    assert critical.severity == SEVERITY_CRITICAL

    # 手工构造同项目的 warning 摘要，验证 key 与 critical 分离
    warning = monitor.summarize("p1", today="2026-11-14")
    assert warning is not None
    warning.severity = SEVERITY_WARNING
    warning.overdue = warning.overdue[:1]

    pushed = monitor.push_alerts([critical, warning])
    assert pushed == 2
    assert queue.size() == 2


# ── scan_and_notify ──────────────────────────────────────────────────────


def test_scan_and_notify_returns_counts():
    monitor, queue = make_monitor(
        [FakeProject(id="p1", name="Alpha"), FakeProject(id="p2", name="Beta")],
        {
            "p1": [FakeMilestone(id="m1", title="Late", due_date="2026-10-01", status="pending")],
            "p2": [],
        },
    )
    result = monitor.scan_and_notify()
    assert result["checked"] == 2
    assert result["notified"] == 1
    assert result["severities"][SEVERITY_CRITICAL] == 1
    assert result["severities"][SEVERITY_WARNING] == 0
    assert result["severities"][SEVERITY_OK] == 1
    assert len(queue.drain()) == 1


# ── 边界 ────────────────────────────────────────────────────────────────


def test_summarize_skips_malformed_due_date():
    monitor, _ = make_monitor(
        [FakeProject(id="p1", name="Alpha")],
        {"p1": [FakeMilestone(id="m1", title="Bad", due_date="0000-00-00", status="pending")]},
    )
    # 无法解析的日期不应产生"逾期 0 天"的告警，直接跳过
    summary = monitor.summarize("p1", today="2026-11-14")
    assert summary is not None
    assert summary.overdue == []
    assert summary.severity == SEVERITY_OK


def test_critical_threshold_is_seven_days():
    assert CRITICAL_OVERDUE_DAYS == 7


@pytest.mark.parametrize(
    ("due_date", "expected_severity"),
    [
        ("2026-11-08", SEVERITY_WARNING),  # 6 天
        ("2026-11-07", SEVERITY_CRITICAL),  # 7 天，达到阈值
    ],
)
def test_severity_threshold_boundary(due_date: str, expected_severity: str):
    monitor, _ = make_monitor(
        [FakeProject(id="p1", name="Alpha")],
        {"p1": [FakeMilestone(id="m1", title="X", due_date=due_date, status="pending")]},
    )
    summary = monitor.summarize("p1", today="2026-11-14")
    assert summary is not None
    assert summary.severity == expected_severity
