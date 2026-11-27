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

# 白名单 ORDER BY 表达式（list_todos 用；dict 查找，绝不把调用方字符串
# 拼进 SQL 标识符位）。
#   - ``due_at``：``(due_at IS NULL)`` 优先，让无日期行在升序时排最后；
#   - ``priority``：CASE 保证 high→medium→low，避免字典序错排。
SORT_EXPRS = {
    "due_at": "(due_at IS NULL), due_at",
    "priority": "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END",
    "created_at": "created_at",
}

# 手工排序（P1 拖拽排序）：先按所属层分组（顶层 parent_id 为 NULL → 0），
# 层内按 ``sort_order``，再用 ``id`` 兜底（旧行 sort_order 全为 0，靠 id
# 保持稳定的创建次序）。
# 三列都是真正的排序键 —— SQLite 的 ``ORDER BY a, b, c DESC`` 只把方向作用
# 于最后一列，所以方向必须逐列给出，不能像单列表达式那样只拼一个。
SORT_MANUAL_EXPRS = ("COALESCE(parent_id, 0)", "sort_order", "id")

# 允许的 ``sort_by`` 取值（router 的 Query pattern 与本文件共用这一份）。
SORT_KEYS = frozenset(SORT_EXPRS) | {"manual"}


def sort_expression(sort_by: str, sort_order: str = "asc") -> str:
    """返回 ORDER BY 片段（不含 ``ORDER BY`` 关键字）。

    单列表达式沿用「表达式 + 方向」的旧拼法（生成 SQL 与改动前逐字一致）；
    手工排序是三列表达式，方向逐列应用，否则升降序只影响最后一列。
    """
    direction = "DESC" if sort_order == "desc" else "ASC"
    if sort_by == "manual":
        return ", ".join(f"{col} {direction}" for col in SORT_MANUAL_EXPRS)
    return f"{SORT_EXPRS[sort_by]} {direction}"


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
    specialist_id: Optional[str] = None,
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

    if specialist_id:
        query += " AND specialist_id = ?"
        params.append(specialist_id)

    return query, params
