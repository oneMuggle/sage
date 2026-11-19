"""待办统计聚合：启动摘要与统计端点。

从 ``todo_service.py`` 拆出（800 行架构棘轮）。只读 ``todos`` 表，
时间语义与主服务一致：naive 本地 ISO8601。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Dict, List

if TYPE_CHECKING:
    from backend.services.todo_service import Todo

RowToTodo = Callable[[Any], Any]


def startup_summary(db: Any, row_to_todo: RowToTodo) -> Dict[str, Any]:
    """启动摘要：逾期 / 今日 / 未来 7 天 / 高优先级 / 计数。

    口径与 ``get_startup_summary`` 历史实现保持一致（naive 本地时间）。
    """
    now = datetime.now()
    today_end = now.replace(hour=23, minute=59, second=59)
    week_end = now + timedelta(days=7)
    now_iso = now.isoformat()
    today_end_iso = today_end.isoformat()
    week_end_iso = week_end.isoformat()

    conn = db.get_connection()

    overdue: List[Todo] = [
        row_to_todo(r)
        for r in conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND due_at IS NOT NULL AND due_at < ? "
            "ORDER BY due_at ASC",
            (now_iso,),
        ).fetchall()
    ]

    today: List[Todo] = [
        row_to_todo(r)
        for r in conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND due_at IS NOT NULL "
            "AND due_at >= ? AND due_at <= ? "
            "ORDER BY due_at ASC",
            (now_iso, today_end_iso),
        ).fetchall()
    ]

    upcoming: List[Todo] = [
        row_to_todo(r)
        for r in conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND due_at IS NOT NULL "
            "AND due_at > ? AND due_at <= ? "
            "ORDER BY due_at ASC",
            (today_end_iso, week_end_iso),
        ).fetchall()
    ]

    high_priority: List[Todo] = [
        row_to_todo(r)
        for r in conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND priority = 'high' "
            "ORDER BY due_at ASC"
        ).fetchall()
    ]

    total_pending = conn.execute(
        "SELECT COUNT(*) FROM todos WHERE status IN ('pending', 'in_progress')"
    ).fetchone()[0]

    total_completed_today = conn.execute(
        "SELECT COUNT(*) FROM todos "
        "WHERE status = 'completed' AND DATE(completed_at) = DATE(?)",
        (now_iso,),
    ).fetchone()[0]

    return {
        "overdue": overdue,
        "today": today,
        "upcoming": upcoming,
        "high_priority": high_priority,
        "total_pending": total_pending,
        "total_completed_today": total_completed_today,
    }


def todo_stats(db: Any) -> Dict[str, Any]:
    """统计端点：总数 / 状态分布 / 优先级分布 / 逾期 / 今日到期 / 今日完成。"""
    now = datetime.now()
    today_end = now.replace(hour=23, minute=59, second=59)
    now_iso = now.isoformat()
    today_end_iso = today_end.isoformat()

    conn = db.get_connection()

    total = conn.execute("SELECT COUNT(*) FROM todos").fetchone()[0]

    by_status = {
        row["status"]: row["n"]
        for row in conn.execute(
            "SELECT status, COUNT(*) AS n FROM todos GROUP BY status"
        ).fetchall()
    }

    by_priority = {
        row["priority"]: row["n"]
        for row in conn.execute(
            "SELECT priority, COUNT(*) AS n FROM todos GROUP BY priority"
        ).fetchall()
    }

    overdue = conn.execute(
        "SELECT COUNT(*) FROM todos "
        "WHERE status IN ('pending', 'in_progress') "
        "AND due_at IS NOT NULL AND due_at < ?",
        (now_iso,),
    ).fetchone()[0]

    due_today = conn.execute(
        "SELECT COUNT(*) FROM todos "
        "WHERE status IN ('pending', 'in_progress') "
        "AND due_at IS NOT NULL "
        "AND due_at >= ? AND due_at <= ?",
        (now_iso, today_end_iso),
    ).fetchone()[0]

    completed_today = conn.execute(
        "SELECT COUNT(*) FROM todos "
        "WHERE status = 'completed' AND DATE(completed_at) = DATE(?)",
        (now_iso,),
    ).fetchone()[0]

    return {
        "total": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "overdue": overdue,
        "due_today": due_today,
        "completed_today": completed_today,
    }


def completion_heatmap(db: Any, days: int = 91) -> Dict[str, Any]:
    """按日聚合完成数（GitHub 风格热力图，最近 ``days`` 天，含今天）。

    返回 ``{"days": [{"date": "YYYY-MM-DD", "count": n}, ...], "total": n, "max": n}``；
    区间内无完成记录的日期补 0，保证前端网格完整。
    """
    span = max(7, min(int(days), 366))
    today = datetime.now().date()
    start = today - timedelta(days=span - 1)

    conn = db.get_connection()
    rows = conn.execute(
        "SELECT DATE(completed_at) AS day, COUNT(*) AS n FROM todos "
        "WHERE status = 'completed' AND completed_at IS NOT NULL "
        "AND DATE(completed_at) >= ? GROUP BY day",
        (start.isoformat(),),
    ).fetchall()
    counts = {row["day"]: row["n"] for row in rows}

    series = []
    day = start
    while day <= today:
        key = day.isoformat()
        series.append({"date": key, "count": int(counts.get(key, 0))})
        day += timedelta(days=1)

    total = sum(item["count"] for item in series)
    max_count = max((item["count"] for item in series), default=0)
    return {"days": series, "total": total, "max": max_count}
