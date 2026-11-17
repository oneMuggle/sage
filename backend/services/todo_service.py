"""Todo service — business logic for personal task management"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.services import (
    todo_export,
    todo_filters,
    todo_fts,
    todo_recurrence,
    todo_stats,
    todo_tags,
)

logger = logging.getLogger(__name__)


def _to_local_naive_iso(value: str) -> str:
    """Normalize an ISO8601 string to naive local time.

    - Naive input: passed through unchanged.
    - Offset-aware input: converted to local time and the tzinfo is dropped.
    - ``...Z`` suffix: accepted (canonical ``Date.toISOString()`` output; py3.10
      ``datetime.fromisoformat`` does not parse it natively, so we rewrite it
      to ``+00:00`` first — this matches the project convention in
      ``backend/model_catalog/schemas.py:146``).
    """
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.isoformat()


# ``todos`` columns that map onto :class:`Todo`, in model-field order.
# Deliberately excludes ``reminder_24h_fired`` / ``reminder_1h_fired`` — those
# are bookkeeping columns owned by the reminder scheduler, not model fields.
_TODO_MODEL_FIELDS = (
    "id",
    "title",
    "description",
    "status",
    "priority",
    "effective_urgency",
    "due_at",
    "completed_at",
    "project_tag",
    "project_id",
    "tags",
    "is_recurring",
    "recurrence_rule",
    "parent_id",
    "created_at",
    "updated_at",
)

# Columns ``update_todo`` is allowed to write. Used to build the SET clause, so
# it doubles as the SQL-identifier whitelist — no caller-supplied key ever
# reaches the query unvalidated.
_UPDATABLE_FIELDS = frozenset(
    {
        "title",
        "description",
        "due_at",
        "priority",
        "project_tag",
        "status",
        "recurrence_rule",
        "parent_id",
        "tags",
    }
)

# Whitelisted ORDER BY expressions for :meth:`TodoService.list_todos`. Used as a
# dict lookup so no caller-supplied string ever reaches SQL as an identifier.
#   - ``due_at``: ``(due_at IS NULL)`` first so undated todos sort LAST when
#     ascending — SQLite's bare ``due_at ASC`` puts NULLs first, which reads
#     backwards to a user.
#   - ``priority``: a CASE is required; lexicographic ASC gives
#     ``high, low, medium``.
# Deliberately no secondary tiebreaker key: the spec documents one sort key, and
# a hidden secondary key makes ``sort_order=desc`` behave inconsistently.
_SORT_EXPRS = {
    "due_at": "(due_at IS NULL), due_at",
    "priority": "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END",
    "created_at": "created_at",
}


class Todo(BaseModel):
    """Todo item model"""
    id: int
    title: str
    description: Optional[str] = None
    status: str  # pending / in_progress / completed / cancelled
    priority: str  # high / medium / low
    effective_urgency: Optional[str] = None  # critical / urgent / normal
    due_at: Optional[str] = None  # ISO8601
    completed_at: Optional[str] = None
    project_tag: Optional[str] = None
    project_id: Optional[str] = None  # TEXT — projects.id is a hex/uuid string
    tags: List[str] = Field(default_factory=list)
    is_recurring: bool = False
    recurrence_rule: Optional[str] = None
    parent_id: Optional[int] = None
    created_at: str
    updated_at: str


class TodoService:
    """Business logic for todo management"""

    def __init__(self, db):
        self.db = db

    def create_todo(
        self,
        title: str,
        description: Optional[str] = None,
        due_at: Optional[str] = None,
        priority: str = "medium",
        project_tag: Optional[str] = None,
        recurrence_rule: Optional[str] = None,
        parent_id: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> Todo:
        """Create a new todo and return the persisted row.

        ``parent_id`` 将新行挂到父待办下（最多两级）：父行必须存在且本身是顶层。
        ``tags`` 为多标签（去重、上限 10 个、单标签 ≤32 字符）。
        """
        now = datetime.now().isoformat()
        is_recurring = 1 if recurrence_rule else 0

        if parent_id is not None:
            parent = self.get_todo(parent_id)
            if parent is None:
                raise ValueError(f"parent todo {parent_id} not found")
            if parent.parent_id is not None:
                raise ValueError("subtask depth exceeds 2 levels")

        # Auto-link project
        project_id = self._auto_link_project(project_tag) if project_tag else None

        # Normalize due_at: naive pass-through, tz-aware → naive local
        if due_at is not None:
            due_at = _to_local_naive_iso(due_at)

        conn = self.db.get_connection()
        cursor = conn.execute(
            """INSERT INTO todos
               (title, description, due_at, priority, project_tag, project_id,
                tags, is_recurring, recurrence_rule, parent_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, description, due_at, priority, project_tag, project_id,
             todo_tags.dump_tags(tags), is_recurring, recurrence_rule, parent_id, now, now)
        )
        todo_id = cursor.lastrowid
        conn.commit()

        created = self.get_todo(todo_id)
        if created is None:
            raise RuntimeError(f"todo {todo_id} vanished immediately after insert")
        todo_fts.upsert_todo_fts(
            self.db, created.id, created.title, created.description
        )
        return created

    def get_todo(self, todo_id: int) -> Optional[Todo]:
        """Get todo by ID, or None if it does not exist."""
        conn = self.db.get_connection()
        cursor = conn.execute(
            "SELECT * FROM todos WHERE id = ?", (todo_id,)
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_todo(row)

    def list_todos(
        self,
        status: Optional[str] = None,
        project_tag: Optional[str] = None,
        priority: Optional[str] = None,
        include_completed: bool = False,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "due_at",
        sort_order: str = "asc",
        q: Optional[str] = None,
        tag: Optional[str] = None,
        view: Optional[str] = None,
    ) -> List[Todo]:
        """List todos with optional filters.

        ``q`` 为全文搜索关键词（标题/描述），FTS5 优先、LIKE 降级。
        ``tag`` 为多标签精确过滤；``view`` 为智能视图（all/today/week/completed）。

        ``sort_by`` is a dict-key lookup into ``_SORT_EXPRS`` — no caller-
        supplied string reaches SQL as an identifier.  An unsupported key
        raises :class:`KeyError`; the router validates before this is
        reachable (see ``todo_router.py``).  ``sort_order`` collapses
        everything that is not ``"desc"`` to ``ASC`` — also validated by
        the router.

        Sorting happens **before** ``LIMIT``/``OFFSET``.
        """
        query = "SELECT * FROM todos WHERE 1=1"
        params: List[Any] = []

        query, params = todo_filters.apply_common_filters(
            query,
            params,
            status=status,
            project_tag=project_tag,
            priority=priority,
            include_completed=include_completed,
            tag=tag,
            view=view,
        )

        query, params = todo_fts.apply_search_filter(self.db, query, params, q)

        sort_expr = _SORT_EXPRS[sort_by]
        direction = "DESC" if sort_order == "desc" else "ASC"
        query += f" ORDER BY {sort_expr} {direction} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        conn = self.db.get_connection()
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        return [self._row_to_todo(row) for row in rows]

    def count_todos(
        self,
        status: Optional[str] = None,
        project_tag: Optional[str] = None,
        priority: Optional[str] = None,
        include_completed: bool = False,
        q: Optional[str] = None,
        tag: Optional[str] = None,
        view: Optional[str] = None,
    ) -> int:
        """Count todos matching the same filters list_todos applies.

        Both share :meth:`_apply_common_filters` — if they ever diverged,
        ``total`` would stop being the match count and clients would render
        wrong pagination.
        """
        query = "SELECT COUNT(*) FROM todos WHERE 1=1"
        params: List[Any] = []

        query, params = todo_filters.apply_common_filters(
            query,
            params,
            status=status,
            project_tag=project_tag,
            priority=priority,
            include_completed=include_completed,
            tag=tag,
            view=view,
        )

        query, params = todo_fts.apply_search_filter(self.db, query, params, q)

        conn = self.db.get_connection()
        return int(conn.execute(query, params).fetchone()[0])

    def list_tags(self) -> List[Dict[str, Any]]:
        """聚合全部待办的多标签及使用次数（按次数降序、名称升序）。"""
        conn = self.db.get_connection()
        rows = conn.execute(
            "SELECT tags FROM todos WHERE tags IS NOT NULL"
        ).fetchall()
        return todo_tags.aggregate_tag_counts(rows)

    def update_todo(self, todo_id: int, **fields) -> Optional[Todo]:
        """Update todo fields.

        * Key **absent** from ``fields``: column is untouched.
        * Key present with a non-``None`` value: column is set to that value.
        * Key present with an explicit ``None``: nullable column is cleared.
        * ``title`` cannot be cleared (``NOT NULL`` in the schema); explicit
          ``None`` raises :class:`ValueError` rather than an opaque SQL error.

        Returns ``None`` if ``todo_id`` does not exist.
        """
        updates = {k: v for k, v in fields.items() if k in _UPDATABLE_FIELDS}

        # ``title`` is NOT NULL in the schema — reject ``None`` explicitly so
        # callers see a clear Python-level error instead of a SQLite
        # ``IntegrityError`` from deep in the stack.
        if updates.get("title") is None and "title" in updates:
            raise ValueError("title is NOT NULL and cannot be cleared")

        # parent_id 变更校验：禁止自引用、只允许挂在顶层行下、有子任务的行
        # 不能变成子任务（否则形成三级层级）。显式 None 允许清除父子关系。
        if "parent_id" in updates and updates["parent_id"] is not None:
            new_parent_id = updates["parent_id"]
            if new_parent_id == todo_id:
                raise ValueError("a todo cannot be its own parent")
            parent = self.get_todo(new_parent_id)
            if parent is None:
                raise ValueError(f"parent todo {new_parent_id} not found")
            if parent.parent_id is not None:
                raise ValueError("subtask depth exceeds 2 levels")
            conn = self.db.get_connection()
            has_children = conn.execute(
                "SELECT 1 FROM todos WHERE parent_id = ? LIMIT 1", (todo_id,)
            ).fetchone()
            if has_children is not None:
                raise ValueError("a todo with subtasks cannot become a subtask")

        if not updates:
            return self.get_todo(todo_id)

        # Auto-link / clear project when project_tag changed (None clears both)
        if "project_tag" in updates:
            project_tag = updates["project_tag"]
            updates["project_id"] = (
                self._auto_link_project(project_tag) if project_tag else None
            )

        # 多标签：清洗后序列化；显式 None / 空列表都清空为 NULL。
        if "tags" in updates:
            updates["tags"] = todo_tags.dump_tags(updates["tags"])

        # Normalize due_at: naive pass-through, tz-aware → naive local
        if updates.get("due_at") is not None:
            updates["due_at"] = _to_local_naive_iso(updates["due_at"])

        # A new due_at or status redefines this todo's reminder schedule, so
        # both latches reset — otherwise a rescheduled or reopened todo would
        # never remind again. The keys below are literal Python strings, not
        # caller input.
        if "due_at" in updates or "status" in updates:
            updates["reminder_24h_fired"] = 0
            updates["reminder_1h_fired"] = 0

        updates["updated_at"] = datetime.now().isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [todo_id]

        conn = self.db.get_connection()
        conn.execute(
            f"UPDATE todos SET {set_clause} WHERE id = ?", values
        )
        conn.commit()

        updated = self.get_todo(todo_id)
        if updated is not None and ("title" in updates or "description" in updates):
            todo_fts.upsert_todo_fts(
                self.db, updated.id, updated.title, updated.description
            )
        return updated

    def delete_todo(self, todo_id: int) -> bool:
        """Delete todo by ID. Returns True if a row was removed."""
        conn = self.db.get_connection()
        cursor = conn.execute(
            "DELETE FROM todos WHERE id = ?", (todo_id,)
        )
        deleted = cursor.rowcount > 0
        conn.commit()
        if deleted:
            todo_fts.delete_todo_fts(self.db, todo_id)
        return deleted

    # --- state changes ---

    def complete_todo(self, todo_id: int) -> Optional[Todo]:
        """Mark a todo as completed.

        Sets ``status='completed'`` and stamps ``completed_at`` and
        ``updated_at`` to the current local time. Returns the refreshed
        :class:`Todo`, or ``None`` if ``todo_id`` does not exist (mirrors
        :meth:`update_todo` semantics).

        循环待办（``recurrence_rule`` 为 5 字段 cron）在完成时自动创建下一
        实例；cron 非法不影响本次完成（fail-open，仅告警）。
        """
        existing = self.get_todo(todo_id)
        if existing is None:
            return None

        now = datetime.now()
        now_iso = now.isoformat()
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE todos SET status = 'completed', completed_at = ?, "
            "updated_at = ? WHERE id = ?",
            (now_iso, now_iso, todo_id),
        )
        conn.commit()
        todo_recurrence.spawn_next_recurrence(self.create_todo, existing, now)
        return self.get_todo(todo_id)

    def cancel_todo(self, todo_id: int) -> bool:
        """Mark a todo as cancelled. Returns True if a row was updated."""
        now = datetime.now().isoformat()
        conn = self.db.get_connection()
        cursor = conn.execute(
            "UPDATE todos SET status = 'cancelled', updated_at = ? "
            "WHERE id = ?",
            (now, todo_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    # --- urgency ---

    @staticmethod
    def _compute_urgency(due_at_str: Optional[str], priority: str,
                         now: datetime) -> str:
        """Return the effective_urgency value for a single todo row.

        Rules:
        - ``due_at`` NULL → ``"normal"``.
        - ``hours_until_due < 1`` → ``"critical"``.
        - ``hours_until_due < 24`` → ``"urgent"``.
        - else → ``"normal"``.
        - Upgrade: ``priority == "high"`` and ``hours_until_due < 24`` →
          ``"critical"``.
        """
        if not due_at_str:
            return "normal"

        due_at = datetime.fromisoformat(due_at_str)
        hours_until_due = (due_at - now).total_seconds() / 3600

        if hours_until_due < 1:
            urgency = "critical"
        elif hours_until_due < 24:
            urgency = "urgent"
        else:
            urgency = "normal"

        if priority == "high" and hours_until_due < 24:
            urgency = "critical"

        return urgency

    def refresh_effective_urgency(self) -> int:
        """Recalculate ``effective_urgency`` for all pending/in_progress todos.

        Returns the number of rows updated.
        """
        now = datetime.now()
        now_iso = now.isoformat()

        conn = self.db.get_connection()
        cursor = conn.execute(
            "SELECT id, due_at, priority FROM todos "
            "WHERE status IN ('pending', 'in_progress')"
        )
        rows = cursor.fetchall()

        for row in rows:
            urgency = self._compute_urgency(row["due_at"], row["priority"], now)
            conn.execute(
                "UPDATE todos SET effective_urgency = ?, updated_at = ? "
                "WHERE id = ?",
                (urgency, now_iso, row["id"]),
            )

        conn.commit()
        return len(rows)

    # --- query helpers ---

    def get_due_soon_todos(self, within_seconds: int) -> List[Todo]:
        """Pending/in_progress todos due within ``within_seconds`` from now.

        Past-due items are excluded — those belong to :meth:`get_overdue_todos`.
        """
        now = datetime.now()
        cutoff = now + timedelta(seconds=within_seconds)

        conn = self.db.get_connection()
        cursor = conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND due_at IS NOT NULL "
            "AND due_at > ? AND due_at <= ? "
            "ORDER BY due_at ASC",
            (now.isoformat(), cutoff.isoformat()),
        )
        rows = cursor.fetchall()

        return [self._row_to_todo(row) for row in rows]

    def get_overdue_todos(self) -> List[Todo]:
        """Pending/in_progress todos past their due_at."""
        now = datetime.now().isoformat()

        conn = self.db.get_connection()
        cursor = conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND due_at IS NOT NULL AND due_at < ? "
            "ORDER BY due_at ASC",
            (now,),
        )
        rows = cursor.fetchall()

        return [self._row_to_todo(row) for row in rows]

    # --- reminder bookkeeping ---
    #
    # The ``reminder_*_fired`` columns are one-shot latches: a reminder is
    # sent at most once per todo per horizon. ``TodoReminderScheduler``
    # owns the *when*; this service owns the *columns*. Writes here do
    # **not** bump ``updated_at`` — they are bookkeeping, not content
    # changes.

    def get_unfired_24h_reminders(self) -> List[Todo]:
        """Pending/in_progress todos due within 24 h whose 24 h latch is 0."""
        now = datetime.now()
        cutoff = now + timedelta(hours=24)
        conn = self.db.get_connection()
        cursor = conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND due_at IS NOT NULL "
            "AND due_at > ? AND due_at <= ? "
            "AND reminder_24h_fired = 0 "
            "ORDER BY due_at ASC",
            (now.isoformat(), cutoff.isoformat()),
        )
        return [self._row_to_todo(r) for r in cursor.fetchall()]

    def mark_24h_fired(self, todo_id: int) -> None:
        """Latch the 24 h reminder. Does not bump ``updated_at``."""
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE todos SET reminder_24h_fired = 1 WHERE id = ?",
            (todo_id,),
        )
        conn.commit()

    def get_unfired_1h_reminders(self) -> List[Todo]:
        """Pending/in_progress todos due within 1 h whose 1 h latch is 0."""
        now = datetime.now()
        cutoff = now + timedelta(hours=1)
        conn = self.db.get_connection()
        cursor = conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND due_at IS NOT NULL "
            "AND due_at > ? AND due_at <= ? "
            "AND reminder_1h_fired = 0 "
            "ORDER BY due_at ASC",
            (now.isoformat(), cutoff.isoformat()),
        )
        return [self._row_to_todo(r) for r in cursor.fetchall()]

    def mark_1h_fired(self, todo_id: int) -> None:
        """Latch the 1 h reminder. Does not bump ``updated_at``."""
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE todos SET reminder_1h_fired = 1 WHERE id = ?",
            (todo_id,),
        )
        conn.commit()

    def get_startup_summary(self) -> dict:
        """启动摘要（逾期/今日/未来 7 天/高优先级/计数）。口径见 todo_stats。"""
        return todo_stats.startup_summary(self.db, self._row_to_todo)

    def get_todo_stats(self) -> dict:
        """统计端点（总数/状态分布/优先级分布/逾期/今日到期/今日完成）。"""
        return todo_stats.todo_stats(self.db)

    # --- batch operations ---

    def complete_many(self, ids: List[int]) -> Dict[str, Any]:
        """批量完成。返回 ``{completed, missing}``；缺失 id 不影响其余行。"""
        completed = 0
        missing: List[int] = []
        for todo_id in ids:
            if self.complete_todo(todo_id) is None:
                missing.append(todo_id)
            else:
                completed += 1
        return {"completed": completed, "missing": missing}

    def delete_many(self, ids: List[int]) -> int:
        """批量删除，返回实际删除行数。"""
        deleted = 0
        for todo_id in ids:
            if self.delete_todo(todo_id):
                deleted += 1
        return deleted

    # --- export ---

    def export_todos(self, include_completed: bool, fmt: str) -> Dict[str, str]:
        """导出为 JSON / Markdown。返回 ``{filename, format, content}``。"""
        todos = self.list_todos(
            status="all" if include_completed else None,
            include_completed=include_completed,
            limit=1000000,
            sort_by="due_at",
            sort_order="asc",
        )
        return todo_export.build_export(todos, fmt)

    def _auto_link_project(self, project_tag: str) -> Optional[str]:
        """Auto-link project_tag to a ``projects`` row, returning its TEXT id."""
        if not project_tag:
            return None

        conn = self.db.get_connection()

        # Exact match first
        cursor = conn.execute(
            "SELECT id FROM projects WHERE name = ? LIMIT 1",
            (project_tag,)
        )
        row = cursor.fetchone()

        if row:
            return row["id"]

        # Fuzzy match (LIKE)
        cursor = conn.execute(
            "SELECT id FROM projects WHERE name LIKE ? LIMIT 1",
            (f"%{project_tag}%",)
        )
        row = cursor.fetchone()

        return row["id"] if row else None

    def _row_to_todo(self, row) -> Todo:
        """Convert a ``todos`` row to a Todo model.

        Maps by column *name* rather than position, so adding a column to the
        table cannot silently shift the model's fields. ``tags`` 存 JSON 数组
        字符串，坏数据降级为空列表（不阻塞列表渲染）。
        """
        data = {name: row[name] for name in _TODO_MODEL_FIELDS}
        data["is_recurring"] = bool(data["is_recurring"])
        data["tags"] = todo_tags.parse_tags(data.get("tags"))

        return Todo(**data)


# ---------- process-wide singleton ----------

_global_service: Optional[TodoService] = None


def get_todo_service() -> Optional[TodoService]:
    """Return the process-wide TodoService if it has been initialised."""
    return _global_service


def init_todo_service(db: Any) -> TodoService:
    """Initialise the global service. Must be called once during app startup."""
    global _global_service
    _global_service = TodoService(db)
    return _global_service
