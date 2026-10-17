"""SQLite persistence for scheduled tasks, replacing ``scheduled_tasks.json``.

Rows use the same dict contract as :meth:`ScheduledTask.to_dict`, so a
JSON→SQLite migration is a pure format change and the repository carries no
dependency on the dataclass (which would otherwise import back into
``backend.services.scheduler`` and form a cycle).

All access goes through the shared ``_SQLITE_LOCK`` and the application's
WAL-mode connection, so no extra locking is needed here.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from backend.data.database import _SQLITE_LOCK, Database

logger = logging.getLogger(__name__)

_COLUMNS = (
    "id", "name", "type", "schedule", "session_id", "content", "enabled",
    "created_at", "last_run", "next_run", "last_attempt", "last_status",
    "last_error", "run_count", "max_runs",
)

# ``schedule`` is stored as JSON text; every other column maps 1:1.
_JSON_COLUMNS = frozenset({"schedule"})


class ScheduledTaskRepository:
    def __init__(self, db: Database):
        self.db = db

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            if conn.in_transaction:
                raise RuntimeError("scheduled tasks require an idle database connection")
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @staticmethod
    def _encode(task: Dict[str, Any]) -> Dict[str, Any]:
        row = {column: task.get(column) for column in _COLUMNS}
        for column in _JSON_COLUMNS:
            row[column] = json.dumps(row[column], ensure_ascii=False)
        row["enabled"] = 1 if row["enabled"] else 0
        return row

    @staticmethod
    def _decode(row: Any) -> Dict[str, Any]:
        task = {column: row[column] for column in _COLUMNS}
        for column in _JSON_COLUMNS:
            task[column] = json.loads(task[column])
        task["enabled"] = bool(task["enabled"])
        return task

    def count(self) -> int:
        with _SQLITE_LOCK:
            row = self.db.get_connection().execute(
                "SELECT COUNT(*) AS n FROM scheduled_tasks"
            ).fetchone()
        return int(row["n"])

    def list_all(self) -> List[Dict[str, Any]]:
        with _SQLITE_LOCK:
            rows = self.db.get_connection().execute(
                "SELECT * FROM scheduled_tasks ORDER BY created_at, id"
            ).fetchall()
        return [self._decode(row) for row in rows]

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        with _SQLITE_LOCK:
            row = self.db.get_connection().execute(
                "SELECT * FROM scheduled_tasks WHERE id=?", (task_id,)
            ).fetchone()
        return self._decode(row) if row else None

    def _upsert_sql(self) -> str:
        placeholders = ", ".join("?" for _ in _COLUMNS)
        assignments = ", ".join(f"{c}=excluded.{c}" for c in _COLUMNS if c != "id")
        return (
            f"INSERT INTO scheduled_tasks ({', '.join(_COLUMNS)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {assignments}"
        )

    def upsert(self, task: Dict[str, Any]) -> None:
        values = self._encode(task)
        with self._transaction() as conn:
            conn.execute(self._upsert_sql(), tuple(values[c] for c in _COLUMNS))

    def bulk_upsert(self, tasks: List[Dict[str, Any]]) -> int:
        """Write a whole batch in one transaction (used by the JSON migration)."""
        rows = [self._encode(task) for task in tasks]
        if not rows:
            return 0
        statement = self._upsert_sql()
        with self._transaction() as conn:
            conn.executemany(
                statement, [tuple(row[c] for c in _COLUMNS) for row in rows]
            )
        return len(rows)

    def delete(self, task_id: str) -> bool:
        with self._transaction() as conn:
            cursor = conn.execute("DELETE FROM scheduled_tasks WHERE id=?", (task_id,))
            return cursor.rowcount > 0

    def has_migrated(self, source: str) -> bool:
        with _SQLITE_LOCK:
            row = self.db.get_connection().execute(
                "SELECT 1 FROM scheduler_migrations WHERE source=?", (source,)
            ).fetchone()
        return row is not None

    def mark_migrated(self, source: str, imported: int, now_ms: int) -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO scheduler_migrations (source, migrated_at, imported) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(source) DO UPDATE SET "
                "migrated_at=excluded.migrated_at, imported=excluded.imported",
                (source, now_ms, imported),
            )
