"""Todo service — business logic for personal task management"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, List, Optional

from pydantic import BaseModel

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
    }
)


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
        recurrence_rule: Optional[str] = None
    ) -> Todo:
        """Create a new todo and return the persisted row."""
        now = datetime.now().isoformat()
        is_recurring = 1 if recurrence_rule else 0

        # Auto-link project
        project_id = self._auto_link_project(project_tag) if project_tag else None

        # Normalize due_at: naive pass-through, tz-aware → naive local
        if due_at is not None:
            due_at = _to_local_naive_iso(due_at)

        conn = self.db.get_connection()
        cursor = conn.execute(
            """INSERT INTO todos
               (title, description, due_at, priority, project_tag, project_id,
                is_recurring, recurrence_rule, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, description, due_at, priority, project_tag, project_id,
             is_recurring, recurrence_rule, now, now)
        )
        todo_id = cursor.lastrowid
        conn.commit()

        created = self.get_todo(todo_id)
        if created is None:
            raise RuntimeError(f"todo {todo_id} vanished immediately after insert")
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
        offset: int = 0
    ) -> List[Todo]:
        """List todos with optional filters."""
        query = "SELECT * FROM todos WHERE 1=1"
        params = []

        if status and status != "all":
            query += " AND status = ?"
            params.append(status)
        elif not include_completed:
            query += " AND status IN ('pending', 'in_progress')"

        if project_tag:
            query += " AND project_tag = ?"
            params.append(project_tag)

        if priority:
            query += " AND priority = ?"
            params.append(priority)

        query += " ORDER BY due_at ASC, created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        conn = self.db.get_connection()
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        return [self._row_to_todo(row) for row in rows]

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

        if not updates:
            return self.get_todo(todo_id)

        # Auto-link / clear project when project_tag changed (None clears both)
        if "project_tag" in updates:
            project_tag = updates["project_tag"]
            updates["project_id"] = (
                self._auto_link_project(project_tag) if project_tag else None
            )

        # Normalize due_at: naive pass-through, tz-aware → naive local
        if updates.get("due_at") is not None:
            updates["due_at"] = _to_local_naive_iso(updates["due_at"])

        updates["updated_at"] = datetime.now().isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [todo_id]

        conn = self.db.get_connection()
        conn.execute(
            f"UPDATE todos SET {set_clause} WHERE id = ?", values
        )
        conn.commit()

        return self.get_todo(todo_id)

    def delete_todo(self, todo_id: int) -> bool:
        """Delete todo by ID. Returns True if a row was removed."""
        conn = self.db.get_connection()
        cursor = conn.execute(
            "DELETE FROM todos WHERE id = ?", (todo_id,)
        )
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted

    # --- state changes ---

    def complete_todo(self, todo_id: int) -> Optional[Todo]:
        """Mark a todo as completed.

        Sets ``status='completed'`` and stamps ``completed_at`` and
        ``updated_at`` to the current local time. Returns the refreshed
        :class:`Todo`, or ``None`` if ``todo_id`` does not exist (mirrors
        :meth:`update_todo` semantics).
        """
        existing = self.get_todo(todo_id)
        if existing is None:
            return None

        now = datetime.now().isoformat()
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE todos SET status = 'completed', completed_at = ?, "
            "updated_at = ? WHERE id = ?",
            (now, now, todo_id),
        )
        conn.commit()
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

    def get_startup_summary(self) -> dict:
        """Aggregate counts for the startup dashboard notification.

        Keys:
        - ``overdue`` — pending/in_progress, ``due_at < now``
        - ``today`` — pending/in_progress, ``now <= due_at <= end_of_today``
        - ``upcoming`` — pending/in_progress, ``end_of_today < due_at <= now + 7d``
        - ``high_priority`` — pending/in_progress, ``priority = 'high'``
        - ``total_pending`` — count of pending/in_progress
        - ``total_completed_today`` — completed where
          ``DATE(completed_at) = DATE(now)``
        """
        now = datetime.now()
        today_end = now.replace(hour=23, minute=59, second=59)
        week_end = now + timedelta(days=7)
        now_iso = now.isoformat()
        today_end_iso = today_end.isoformat()
        week_end_iso = week_end.isoformat()

        conn = self.db.get_connection()

        cursor = conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND due_at IS NOT NULL AND due_at < ? "
            "ORDER BY due_at ASC",
            (now_iso,),
        )
        overdue = [self._row_to_todo(r) for r in cursor.fetchall()]

        cursor = conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND due_at IS NOT NULL "
            "AND due_at >= ? AND due_at <= ? "
            "ORDER BY due_at ASC",
            (now_iso, today_end_iso),
        )
        today = [self._row_to_todo(r) for r in cursor.fetchall()]

        cursor = conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND due_at IS NOT NULL "
            "AND due_at > ? AND due_at <= ? "
            "ORDER BY due_at ASC",
            (today_end_iso, week_end_iso),
        )
        upcoming = [self._row_to_todo(r) for r in cursor.fetchall()]

        cursor = conn.execute(
            "SELECT * FROM todos "
            "WHERE status IN ('pending', 'in_progress') "
            "AND priority = 'high' "
            "ORDER BY due_at ASC"
        )
        high_priority = [self._row_to_todo(r) for r in cursor.fetchall()]

        cursor = conn.execute(
            "SELECT COUNT(*) FROM todos "
            "WHERE status IN ('pending', 'in_progress')"
        )
        total_pending = cursor.fetchone()[0]

        cursor = conn.execute(
            "SELECT COUNT(*) FROM todos "
            "WHERE status = 'completed' AND DATE(completed_at) = DATE(?)",
            (now_iso,),
        )
        total_completed_today = cursor.fetchone()[0]

        return {
            "overdue": overdue,
            "today": today,
            "upcoming": upcoming,
            "high_priority": high_priority,
            "total_pending": total_pending,
            "total_completed_today": total_completed_today,
        }


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
        table cannot silently shift the model's fields.
        """
        data = {name: row[name] for name in _TODO_MODEL_FIELDS}
        data["is_recurring"] = bool(data["is_recurring"])

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
