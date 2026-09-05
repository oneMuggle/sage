"""SQLite persistence for the unified orchestration event envelope."""

from __future__ import annotations

import json
import sqlite3
from typing import List, Optional

from backend.data.database import _SQLITE_LOCK, get_database
from backend.domain.orch_events import RunEvent


class OrchEventRepository:
    """Append-only event store backed by the shared database connection."""

    def __init__(self) -> None:
        self.db = get_database()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orch_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES orch_runs(run_id),
                    seq INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    task_id TEXT,
                    lane_id TEXT,
                    step_id TEXT,
                    agent_id TEXT,
                    occurred_at INTEGER NOT NULL,
                    producer TEXT NOT NULL,
                    producer_generation INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL,
                    visibility TEXT NOT NULL DEFAULT 'user',
                    command_id TEXT,
                    schema_version TEXT NOT NULL DEFAULT 'run-events@1.0',
                    UNIQUE(run_id, seq),
                    UNIQUE(command_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_orch_events_run_seq ON orch_events(run_id, seq)"
            )
            conn.commit()

    def append(self, event: RunEvent) -> None:
        entity = event.entity
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            conn.execute(
                """
                INSERT OR IGNORE INTO orch_events (
                    event_id, run_id, seq, event_type, task_id, lane_id, step_id,
                    agent_id, occurred_at, producer, producer_generation, payload,
                    visibility, command_id, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id, event.run_id, event.seq, event.event_type,
                    entity.get("task_id"), entity.get("lane_id"), entity.get("step_id"),
                    entity.get("agent_id"), event.occurred_at, event.producer,
                    event.producer_generation, json.dumps(event.payload, ensure_ascii=False),
                    event.visibility, event.command_id, event.schema_version,
                ),
            )
            conn.commit()

    def max_seq(self, run_id: str) -> int:
        row = self.db.get_connection().execute(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM orch_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return int(row["max_seq"])

    def list_runs(self) -> List[str]:
        """Return run IDs with persisted events."""
        rows = self.db.get_connection().execute(
            "SELECT DISTINCT run_id FROM orch_events ORDER BY run_id"
        ).fetchall()
        return [str(row["run_id"]) for row in rows]

    def get(self, event_id: str) -> Optional[RunEvent]:
        """Return a single event by its primary key, or None if not found."""
        row = self.db.get_connection().execute(
            "SELECT * FROM orch_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return self._row_to_event(row) if row else None

    def list_after(self, run_id: str, after_seq: int = 0, limit: int = 1000) -> List[RunEvent]:
        if after_seq < 0 or limit < 1:
            raise ValueError("after_seq must be non-negative and limit must be positive")
        rows = self.db.get_connection().execute(
            "SELECT * FROM orch_events WHERE run_id = ? AND seq > ? ORDER BY seq ASC LIMIT ?",
            (run_id, after_seq, limit),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> RunEvent:
        entity = {
            key: row[key]
            for key in ("task_id", "lane_id", "step_id", "agent_id")
            if row[key] is not None
        }
        return RunEvent(
            event_id=row["event_id"], run_id=row["run_id"], seq=row["seq"],
            event_type=row["event_type"], occurred_at=row["occurred_at"],
            producer=row["producer"], producer_generation=row["producer_generation"],
            entity=entity, payload=json.loads(row["payload"]),
            visibility=row["visibility"], schema_version=row["schema_version"],
            command_id=row["command_id"],
        )


__all__ = ["OrchEventRepository"]
