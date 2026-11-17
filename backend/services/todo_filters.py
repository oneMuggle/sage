"""待办列表的共用过滤片段（list / count 单一真相源）。

``view`` 智能视图优先于 ``status``：
- ``today``：今日到期（pending/in_progress，due_at 在今日区间内）
- ``week``：未来 7 天内到期（含已逾期，due_at 非空）
- ``completed``：已完成
- ``all``：未完成全部（pending/in_progress）
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, List, Optional

# ``view`` 智能视图白名单；router 负责 GET 参数的模式校验。
VIEWS = frozenset({"all", "today", "week", "completed"})


def apply_common_filters(
    query: str,
    params: List[Any],
    *,
    status: Optional[str],
    project_tag: Optional[str],
    priority: Optional[str],
    include_completed: bool,
    tag: Optional[str],
    view: Optional[str],
    now: Optional[datetime] = None,
) -> tuple:
    """在 ``query`` 后追加 WHERE 片段并同步 ``params``，返回二元组。"""
    if view and view in VIEWS:
        current = now or datetime.now()
        if view == "today":
            day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = current.replace(hour=23, minute=59, second=59)
            query += (
                " AND status IN ('pending', 'in_progress') "
                "AND due_at IS NOT NULL AND due_at >= ? AND due_at <= ?"
            )
            params.extend([day_start.isoformat(), day_end.isoformat()])
        elif view == "week":
            query += (
                " AND status IN ('pending', 'in_progress') "
                "AND due_at IS NOT NULL AND due_at <= ?"
            )
            params.append((current + timedelta(days=7)).isoformat())
        elif view == "completed":
            query += " AND status = 'completed'"
        else:  # all
            query += " AND status IN ('pending', 'in_progress')"
    elif status and status != "all":
        query += " AND status = ?"
        params.append(status)
    elif not (include_completed or status == "all"):
        query += " AND status IN ('pending', 'in_progress')"

    if project_tag:
        query += " AND project_tag = ?"
        params.append(project_tag)

    if priority:
        query += " AND priority = ?"
        params.append(priority)

    if tag:
        query += " AND tags LIKE ?"
        params.append(f'%"{tag.strip()}"%')

    return query, params
