"""报告聚合引擎测试（P3）—— 双来源上下文 / 模板渲染 / LLM 降级。

覆盖：

- :func:`report_ai.build_report_context` —— 工作日志（只算已确认）+ 待办（按时间窗）
- :func:`report_ai.render_template` —— 无 LLM 时的确定性 Markdown
- :func:`report_ai.generate_with_fallback` —— 未配置 LLM 时降级模板，绝不空手

路由层的测试在 ``backend/tests/unit/api/test_report_router.py``。
"""
from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from backend.data.database import Database
from backend.services import report_ai
from backend.services.llm_endpoint import LLMNotConfiguredError
from backend.services.worklog_service import WorklogService

# 测试用的固定窗口（两端都含）。
PERIOD_START = "2026-11-20"
PERIOD_END = "2026-11-26"


@pytest.fixture()
def db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_report_ai.db"
        database = Database(db_path=str(db_path))
        database.init_db()
        yield database
        database.close()


@pytest.fixture()
def worklog_service(db):
    return WorklogService(db)


# ======================================================================
# 造数工具
# ======================================================================


def _insert_todo(
    db: Database,
    *,
    title: str,
    status: str = "pending",
    priority: str = "medium",
    due_at: Optional[str] = None,
    completed_at: Optional[str] = None,
    created_at: str = "2026-11-20T08:00:00",
) -> None:
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO todos (
            title, status, priority, due_at, completed_at,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            status,
            priority,
            due_at,
            completed_at,
            created_at,
            created_at,
        ),
    )
    conn.commit()


def _insert_worklog(
    db: Database,
    *,
    content: str,
    kind: str = "progress",
    status: str = "confirmed",
    session_id: Optional[str] = "sess-1",
    created_at: str = "2026-11-21T09:00:00",
) -> None:
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO work_logs (
            session_id, content, kind, source_type, status,
            created_at, updated_at
        ) VALUES (?, ?, ?, 'manual', ?, ?, ?)
        """,
        (session_id, content, kind, status, created_at, created_at),
    )
    conn.commit()


# ======================================================================
# 工作日志侧
# ======================================================================


def test_worklog_section_counts_only_confirmed(db, worklog_service):
    _insert_worklog(db, content="确认过的活", status="confirmed")
    _insert_worklog(db, content="待确认的候选", status="pending")
    _insert_worklog(db, content="被否决的候选", status="dismissed")

    section = report_ai._worklog_section(
        worklog_service, PERIOD_START, PERIOD_END
    )

    assert section["total"] == 1
    assert [item["content"] for item in section["items"]] == ["确认过的活"]


def test_worklog_section_is_window_scoped(db, worklog_service):
    _insert_worklog(db, content="窗内", created_at="2026-11-21T09:00:00")
    _insert_worklog(db, content="窗外", created_at="2026-11-01T09:00:00")

    section = report_ai._worklog_section(
        worklog_service, PERIOD_START, PERIOD_END
    )

    assert [item["content"] for item in section["items"]] == ["窗内"]


def test_worklog_section_window_end_includes_whole_day(db, worklog_service):
    """``period_end`` 当天整日都算在内。"""
    _insert_worklog(db, content="当天深夜", created_at="2026-11-26T23:30:00")

    section = report_ai._worklog_section(
        worklog_service, PERIOD_START, PERIOD_END
    )

    assert section["total"] == 1


def test_worklog_section_zero_fills_kinds(db, worklog_service):
    section = report_ai._worklog_section(
        worklog_service, PERIOD_START, PERIOD_END
    )

    assert section["by_kind"] == {
        "progress": 0,
        "done": 0,
        "blocker": 0,
        "next": 0,
    }
    assert section["items"] == []


def test_worklog_section_without_service_is_empty():
    section = report_ai._worklog_section(None, PERIOD_START, PERIOD_END)

    assert section["total"] == 0
    assert section["items"] == []
    assert section["sessions"] == 0


def test_digest_for_period_matches_section(db, worklog_service):
    _insert_worklog(db, content="一条")

    digest = report_ai.digest_for_period(
        worklog_service, period_start=PERIOD_START, period_end=PERIOD_END
    )

    assert digest["total"] == 1


def test_digest_for_period_without_service():
    digest = report_ai.digest_for_period(
        None, period_start=PERIOD_START, period_end=PERIOD_END
    )

    assert digest["total"] == 0


# ======================================================================
# 待办侧
# ======================================================================


def test_todo_section_scopes_completed_by_window(db):
    _insert_todo(
        db,
        title="窗内完成",
        status="completed",
        completed_at="2026-11-22T17:00:00",
    )
    _insert_todo(
        db,
        title="窗外完成",
        status="completed",
        completed_at="2026-11-02T17:00:00",
    )

    section = report_ai._todo_section(db, PERIOD_START, PERIOD_END)

    assert section["completed"] == ["窗内完成"]
    assert section["completed_count"] == 1


def test_todo_section_counts_completed_beyond_list_limit(db):
    for index in range(25):
        _insert_todo(
            db,
            title=f"完成 {index}",
            status="completed",
            completed_at="2026-11-22T17:00:00",
        )

    section = report_ai._todo_section(db, PERIOD_START, PERIOD_END)

    assert len(section["completed"]) == report_ai.MAX_TODO_TITLES
    assert section["completed_count"] == 25


def test_todo_section_ignores_completed_without_timestamp(db):
    """状态是 completed 但没有 completed_at —— 不算「这段时间完成的」。"""
    _insert_todo(db, title="状态完成但无时间", status="completed")

    section = report_ai._todo_section(db, PERIOD_START, PERIOD_END)

    assert section["completed"] == []
    assert section["completed_count"] == 0


def test_todo_section_lists_high_priority_pending(db):
    _insert_todo(db, title="高优先级", priority="high")
    _insert_todo(db, title="普通优先级", priority="medium")
    _insert_todo(
        db, title="已完成的高优先级", priority="high", status="completed"
    )

    section = report_ai._todo_section(db, PERIOD_START, PERIOD_END)

    assert section["pending_high"] == ["高优先级"]


def test_todo_section_lists_overdue(db):
    yesterday = (datetime.now() - timedelta(days=1)).isoformat()
    future = (datetime.now() + timedelta(days=30)).isoformat()
    _insert_todo(db, title="已过期", due_at=yesterday)
    _insert_todo(db, title="还没到期", due_at=future)
    _insert_todo(db, title="无截止日")

    section = report_ai._todo_section(db, PERIOD_START, PERIOD_END)

    assert section["overdue"] == ["已过期"]


def test_todo_section_pending_count_covers_both_open_states(db):
    _insert_todo(db, title="未开始", status="pending")
    _insert_todo(db, title="进行中", status="in_progress")
    _insert_todo(db, title="已完成", status="completed")

    section = report_ai._todo_section(db, PERIOD_START, PERIOD_END)

    assert section["pending_count"] == 2


# ======================================================================
# 上下文组装
# ======================================================================


def test_build_report_context_shape(db, worklog_service):
    _insert_worklog(db, content="写完了报告服务", kind="done")
    _insert_todo(
        db,
        title="接上后端",
        status="completed",
        completed_at="2026-11-22T17:00:00",
    )

    context = report_ai.build_report_context(
        db=db,
        worklog_service=worklog_service,
        report_type="daily",
        period_start=PERIOD_START,
        period_end=PERIOD_END,
    )

    assert context["report_type"] == "daily"
    assert context["period_start"] == PERIOD_START
    assert context["period_end"] == PERIOD_END
    assert context["worklogs"]["total"] == 1
    assert context["todos"]["completed"] == ["接上后端"]


def test_build_report_context_is_read_only(db, worklog_service):
    _insert_worklog(db, content="一条")
    before = worklog_service.count_worklogs()

    report_ai.build_report_context(
        db=db,
        worklog_service=worklog_service,
        report_type="daily",
        period_start=PERIOD_START,
        period_end=PERIOD_END,
    )

    assert worklog_service.count_worklogs() == before


# ======================================================================
# 模板渲染
# ======================================================================


def _context(report_type: str = "daily") -> Dict[str, Any]:
    return {
        "report_type": report_type,
        "period_start": PERIOD_START,
        "period_end": PERIOD_END,
        "worklogs": {
            "total": 2,
            "by_kind": {"progress": 1, "done": 1, "blocker": 0, "next": 0},
            "sessions": 1,
            "items": [
                {"kind": "done", "content": "写完了报告服务", "created_at": ""},
                {"kind": "progress", "content": "在写测试", "created_at": ""},
            ],
        },
        "todos": {
            "completed": ["接上后端"],
            "completed_count": 1,
            "pending_high": ["补文档"],
            "overdue": [],
            "pending_count": 3,
        },
    }


def test_render_template_daily_sections():
    text = report_ai.render_template(_context("daily"))

    assert "# 日报 · 11 月 20 日" in text
    assert "## 完成" in text
    assert "## 进展" in text
    assert "## 阻塞与风险" in text
    assert "## 下一步" in text
    assert "- 写完了报告服务" in text
    assert "- 在写测试" in text


def test_render_template_weekly_sections():
    text = report_ai.render_template(_context("weekly"))

    assert "# 周报 · 11 月 20 日 ~ 11 月 26 日" in text
    assert "## 完成情况" in text
    assert "## 进展概览" in text
    assert "## 下周建议" in text
    assert "- 接上后端" in text


def test_render_template_weekly_suggests_backlog():
    text = report_ai.render_template(_context("weekly"))

    assert "补文档" in text


def test_render_template_has_stats_block():
    text = report_ai.render_template(_context("daily"))

    assert "## 统计" in text
    assert "工作日志 2 条" in text
    assert "待办完成 1 条" in text


def test_render_template_marks_empty_sections():
    context = _context("daily")
    context["worklogs"]["items"] = []
    context["worklogs"]["total"] = 0
    context["worklogs"]["by_kind"] = {
        "progress": 0,
        "done": 0,
        "blocker": 0,
        "next": 0,
    }

    text = report_ai.render_template(context)

    assert "- （无）" in text


# ======================================================================
# LLM 生成与降级
# ======================================================================


class _FakeClient:
    """最小 LLM 客户端替身。"""

    def __init__(self, text: str = "") -> None:
        self.text = text
        self.prompts: List[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.text


def test_generate_with_fallback_uses_llm_text(monkeypatch):
    client = _FakeClient("## 完成\n- 归纳出来的内容")
    monkeypatch.setattr(report_ai, "_client", lambda: client)

    text, ai_generated = _run(report_ai.generate_with_fallback(_context()))

    assert ai_generated is True
    assert text == "## 完成\n- 归纳出来的内容"


def test_generate_with_fallback_prompt_carries_both_sources(monkeypatch):
    client = _FakeClient("内容")
    monkeypatch.setattr(report_ai, "_client", lambda: client)

    _run(report_ai.generate_with_fallback(_context()))

    prompt = client.prompts[0]
    assert "写完了报告服务" in prompt
    assert "接上后端" in prompt


def test_generate_with_fallback_falls_back_without_llm(monkeypatch):
    def _boom() -> Any:
        raise LLMNotConfiguredError("LLM 未配置")

    monkeypatch.setattr(report_ai, "_client", _boom)

    text, ai_generated = _run(report_ai.generate_with_fallback(_context()))

    assert ai_generated is False
    assert "# 日报 · 11 月 20 日" in text
    assert "- 写完了报告服务" in text


def test_generate_with_fallback_falls_back_on_empty_output(monkeypatch):
    monkeypatch.setattr(report_ai, "_client", lambda: _FakeClient("   "))

    text, ai_generated = _run(report_ai.generate_with_fallback(_context()))

    assert ai_generated is False
    assert "# 日报" in text


def test_generate_report_raises_when_llm_missing(monkeypatch):
    def _boom() -> Any:
        raise LLMNotConfiguredError("LLM 未配置")

    monkeypatch.setattr(report_ai, "_client", _boom)

    with pytest.raises(LLMNotConfiguredError):
        _run(report_ai.generate_report(_context()))


# ======================================================================
# 时间窗默认值
# ======================================================================


def test_today_period_is_today():
    start, end = report_ai.today_period()

    assert start == end
    assert start == datetime.now().strftime("%Y-%m-%d")


def test_week_period_spans_seven_days():
    start, end = report_ai.week_period()

    # 报告时间窗按本地日历日切分 —— naive 是有意为之。
    start_date = datetime.strptime(start, "%Y-%m-%d")  # noqa: DTZ007
    end_date = datetime.strptime(end, "%Y-%m-%d")  # noqa: DTZ007
    assert (end_date - start_date).days == 6
    assert end == datetime.now().strftime("%Y-%m-%d")


def _run(coro):
    """在同步测试里跑协程。"""
    return asyncio.run(coro)
