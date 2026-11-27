"""报告存档服务与模型映射测试（P3）。

覆盖：

- :class:`ReportService` —— 存档 / 列表 / 详情 / 计数
- :func:`row_to_report` —— 行到模型的映射与脏数据降级
- 关键不变量：**报告是快照**（落库后内容不再随工作日志变化）

路由层的测试在 ``backend/tests/unit/api/test_report_router.py``。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.data.database import Database
from backend.services.report_models import Report, row_to_report
from backend.services.report_service import ReportService


@pytest.fixture()
def report_service():
    """ReportService backed by a throwaway SQLite file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_report_service.db"
        db = Database(db_path=str(db_path))
        db.init_db()

        service = ReportService(db)

        yield service

        db.close()


# ======================================================================
# 模型映射
# ======================================================================


def _row(**overrides):
    base = {
        "id": 1,
        "title": "日报 · 2026-11-27",
        "report_type": "daily",
        "period_start": "2026-11-27",
        "period_end": "2026-11-27",
        "content": "# 日报\n\n## 完成\n- 写了报告服务",
        "stats_json": '{"ai_generated": true}',
        "created_at": "2026-11-27T14:32:05.123456",
        "updated_at": "2026-11-27T14:32:05.123456",
    }
    base.update(overrides)
    return base


def test_row_to_report_decodes_stats_json():
    report = row_to_report(_row())

    assert isinstance(report, Report)
    assert report.id == 1
    assert report.report_type == "daily"
    assert report.stats == {"ai_generated": True}


def test_row_to_report_downgrades_broken_stats_json():
    report = row_to_report(_row(stats_json="{not json"))

    assert report.stats is None


def test_row_to_report_ignores_non_dict_stats():
    report = row_to_report(_row(stats_json="[1, 2]"))

    assert report.stats is None


def test_row_to_report_without_stats_column():
    row = _row()
    row.pop("stats_json")

    assert row_to_report(row).stats is None


# ======================================================================
# 存档
# ======================================================================


def test_create_report_roundtrip(report_service):
    created = report_service.create_report(
        title="日报 · 2026-11-27",
        report_type="daily",
        period_start="2026-11-27",
        period_end="2026-11-27",
        content="# 日报",
        stats={"ai_generated": False},
    )

    assert created.id > 0
    assert created.stats == {"ai_generated": False}

    fetched = report_service.get_report(created.id)
    assert fetched is not None
    assert fetched.content == "# 日报"
    assert fetched.stats == {"ai_generated": False}


def test_create_report_generates_default_title(report_service):
    daily = report_service.create_report(
        title="  ",
        report_type="daily",
        period_start="2026-11-27",
        period_end="2026-11-27",
        content="# 日报",
    )
    weekly = report_service.create_report(
        title=None,
        report_type="weekly",
        period_start="2026-11-20",
        period_end="2026-11-27",
        content="# 周报",
    )

    assert daily.title == "日报 · 2026-11-27"
    assert weekly.title == "周报 · 2026-11-20 ~ 2026-11-27"


def test_create_report_rejects_inverted_period(report_service):
    with pytest.raises(ValueError, match="period_start"):
        report_service.create_report(
            title=None,
            report_type="daily",
            period_start="2026-11-27",
            period_end="2026-11-20",
            content="# 日报",
        )


def test_create_report_rejects_invalid_date(report_service):
    with pytest.raises(ValueError, match="invalid date"):
        report_service.create_report(
            title=None,
            report_type="daily",
            period_start="not-a-date",
            period_end="2026-11-27",
            content="# 日报",
        )


def test_create_report_rejects_invalid_type(report_service):
    with pytest.raises(ValueError, match="invalid report_type"):
        report_service.create_report(
            title=None,
            report_type="monthly",
            period_start="2026-11-27",
            period_end="2026-11-27",
            content="# 月报",
        )


def test_create_report_rejects_empty_content(report_service):
    with pytest.raises(ValueError, match="content must not be empty"):
        report_service.create_report(
            title=None,
            report_type="daily",
            period_start="2026-11-27",
            period_end="2026-11-27",
            content="   ",
        )


def test_create_report_normalises_long_period_strings(report_service):
    created = report_service.create_report(
        title=None,
        report_type="daily",
        period_start="2026-11-27T09:00:00",
        period_end="2026-11-27",
        content="# 日报",
    )

    assert created.period_start == "2026-11-27"


def test_failed_create_leaves_no_row(report_service):
    with pytest.raises(ValueError, match="period_start"):
        report_service.create_report(
            title=None,
            report_type="daily",
            period_start="2026-11-28",
            period_end="2026-11-27",
            content="# 日报",
        )

    assert report_service.count_reports() == 0


# ======================================================================
# 查询
# ======================================================================


def test_list_reports_is_newest_first(report_service):
    first = report_service.create_report(
        title="A",
        report_type="daily",
        period_start="2026-11-25",
        period_end="2026-11-25",
        content="# A",
    )
    second = report_service.create_report(
        title="B",
        report_type="daily",
        period_start="2026-11-26",
        period_end="2026-11-26",
        content="# B",
    )

    items = report_service.list_reports()

    assert [item.id for item in items] == [second.id, first.id]


def test_list_reports_filters_by_type(report_service):
    report_service.create_report(
        title="D",
        report_type="daily",
        period_start="2026-11-27",
        period_end="2026-11-27",
        content="# D",
    )
    report_service.create_report(
        title="W",
        report_type="weekly",
        period_start="2026-11-20",
        period_end="2026-11-27",
        content="# W",
    )

    daily = report_service.list_reports(report_type="daily")
    weekly = report_service.list_reports(report_type="weekly")

    assert len(daily) == 1
    assert daily[0].report_type == "daily"
    assert len(weekly) == 1
    assert weekly[0].report_type == "weekly"
    assert report_service.count_reports(report_type="daily") == 1
    assert report_service.count_reports() == 2


def test_list_reports_paginates(report_service):
    for index in range(5):
        report_service.create_report(
            title=f"R{index}",
            report_type="daily",
            period_start="2026-11-27",
            period_end="2026-11-27",
            content=f"# R{index}",
        )

    page = report_service.list_reports(limit=2, offset=1)

    assert len(page) == 2
    assert report_service.count_reports() == 5


def test_get_report_returns_none_for_missing(report_service):
    assert report_service.get_report(999) is None


def test_report_content_is_a_snapshot(report_service):
    """报告落库后不再随其它数据变化 —— 复盘看的是当时的结论。"""
    created = report_service.create_report(
        title="日报 · 2026-11-27",
        report_type="daily",
        period_start="2026-11-27",
        period_end="2026-11-27",
        content="# 日报\n\n- 当时只做完了这一件事",
        stats={"ai_generated": False},
    )

    fetched = report_service.get_report(created.id)

    assert fetched is not None
    assert "当时只做完了这一件事" in fetched.content
    assert fetched.stats == {"ai_generated": False}
