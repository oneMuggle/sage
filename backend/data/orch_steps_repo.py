"""SQLite persistence for orchestration step state."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import List, Optional

from backend.data.database import _SQLITE_LOCK, get_database


@dataclass(frozen=True)
class OrchStep:
    step_id: str
    run_id: str
    task_id: str
    name: str
    status: str = "pending"
    sequence: int = 0
    kind: str = ""
    input_summary: Optional[str] = None
    output_preview: Optional[str] = None
    tool_name: Optional[str] = None
    error_code: Optional[str] = None
    retry_count: int = 0
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    created_at: int = 0


class OrchStepRepository:
    """SQLite-backed step state repository."""

    def __init__(self) -> None:
        self.db = get_database()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orch_steps (
                    step_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES orch_runs(run_id),
                    task_id TEXT NOT NULL REFERENCES orch_tasks(task_id),
                    sequence INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_summary TEXT,
                    output_preview TEXT,
                    tool_name TEXT,
                    error_code TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    started_at INTEGER,
                    finished_at INTEGER,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_orch_steps_run_seq ON orch_steps(run_id, sequence)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_orch_steps_task_seq ON orch_steps(task_id, sequence)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_orch_steps_task_status ON orch_steps(task_id, status)"
            )
            conn.commit()

    def upsert(self, step: OrchStep) -> None:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            conn.execute(
                """
                INSERT INTO orch_steps (
                    step_id, run_id, task_id, sequence, kind, name, status,
                    input_summary, output_preview, tool_name, error_code,
                    retry_count, started_at, finished_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(step_id) DO UPDATE SET
                    run_id=excluded.run_id, task_id=excluded.task_id,
                    sequence=excluded.sequence, kind=excluded.kind,
                    name=excluded.name, status=excluded.status,
                    input_summary=excluded.input_summary,
                    output_preview=excluded.output_preview,
                    tool_name=excluded.tool_name, error_code=excluded.error_code,
                    retry_count=excluded.retry_count, started_at=excluded.started_at,
                    finished_at=excluded.finished_at
                """,
                (
                    step.step_id, step.run_id, step.task_id, step.sequence, step.kind,
                    step.name, step.status, step.input_summary, step.output_preview,
                    step.tool_name, step.error_code, step.retry_count, step.started_at,
                    step.finished_at, step.created_at,
                ),
            )
            conn.commit()

    def get(self, step_id: str) -> Optional[OrchStep]:
        row = self.db.get_connection().execute(
            "SELECT * FROM orch_steps WHERE step_id = ?", (step_id,)
        ).fetchone()
        return self._row_to_step(row) if row else None

    def list_by_task(self, task_id: str) -> List[OrchStep]:
        rows = self.db.get_connection().execute(
            "SELECT * FROM orch_steps WHERE task_id = ? ORDER BY sequence ASC", (task_id,)
        ).fetchall()
        return [self._row_to_step(row) for row in rows]

    @staticmethod
    def _row_to_step(row: sqlite3.Row) -> OrchStep:
        return OrchStep(
            step_id=row["step_id"], run_id=row["run_id"], task_id=row["task_id"],
            name=row["name"], status=row["status"], sequence=row["sequence"],
            kind=row["kind"], input_summary=row["input_summary"],
            output_preview=row["output_preview"], tool_name=row["tool_name"],
            error_code=row["error_code"], retry_count=row["retry_count"],
            started_at=row["started_at"], finished_at=row["finished_at"],
            created_at=row["created_at"],
        )


__all__ = ["OrchStep", "OrchStepRepository"]
