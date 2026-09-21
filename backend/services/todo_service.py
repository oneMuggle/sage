"""Todo service — business logic for personal task management"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

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
        now = datetime.now(timezone.utc).isoformat()  # noqa: UP017 — py38 兼容
        is_recurring = 1 if recurrence_rule else 0

        # Auto-link project
        project_id = self._auto_link_project(project_tag) if project_tag else None

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

    def update_todo(self, todo_id: int, **fields) -> Todo:
        """Update todo fields.

        Only keys in ``_UPDATABLE_FIELDS`` are honoured; ``None`` values are
        dropped, i.e. ``None`` means "leave unchanged" rather than "clear".
        """
        updates = {k: v for k, v in fields.items() if k in _UPDATABLE_FIELDS and v is not None}

        if not updates:
            return self.get_todo(todo_id)

        # Auto-link project if project_tag changed
        if updates.get("project_tag"):
            updates["project_id"] = self._auto_link_project(updates["project_tag"])

        updates["updated_at"] = datetime.now(timezone.utc).isoformat()  # noqa: UP017 — py38 兼容

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
