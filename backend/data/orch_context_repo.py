"""SQLite persistence for ``orch_context_messages`` (steering context).

Stores follow-up messages the parent agent / user appends to a running task.
Each message has a lifecycle ``pending -> delivered -> acknowledged`` (or
``rejected``). The executor polls ``list_pending`` at the next boundary to
consume newly injected context.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

from backend.data.database import _SQLITE_LOCK, get_database


@dataclass
class ContextMessage:
    """A single appended context message."""

    context_id: str
    run_id: str
    task_id: str
    source: str  # "user" | "parent_agent" | "system"
    message_type: str  # constraint | clarification | additional_context | correction | priority_update | reference
    content_redacted: str
    apply_mode: str  # next_boundary | new_followup
    expected_task_revision: Optional[int]
    created_at: int
    created_by: Optional[str]
    status: str = "pending"
    applied_at: Optional[int] = None
    applied_step_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "context_id": self.context_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "source": self.source,
            "message_type": self.message_type,
            "content_redacted": self.content_redacted,
            "apply_mode": self.apply_mode,
            "expected_task_revision": self.expected_task_revision,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "status": self.status,
            "applied_at": self.applied_at,
            "applied_step_id": self.applied_step_id,
        }


_CONTENT_MAX_BYTES = 8 * 1024  # 8 KB per-message cap (plan §3.7)
_VALID_SOURCES = {"user", "parent_agent", "system"}
_VALID_MESSAGE_TYPES = {
    "constraint",
    "clarification",
    "additional_context",
    "correction",
    "priority_update",
    "reference",
}
_VALID_APPLY_MODES = {"next_boundary", "new_followup"}


class OrchestrationContextError(ValueError):
    """Raised when context input fails validation."""


class OrchestrationContextRepository:
    """CRUD + lifecycle management for steering context messages.

    Schema ownership note: the authoritative DDL lives in
    ``backend/data/database.py`` (``orch_context_messages``). This class
    assumes the table + indexes already exist and only performs CRUD.
    """

    def __init__(self) -> None:
        self.db = get_database()

    # ------------------------------------------------------------------ creation

    def create(
        self,
        *,
        run_id: str,
        task_id: str,
        source: str,
        message_type: str,
        content_redacted: str,
        apply_mode: str = "next_boundary",
        expected_task_revision: Optional[int] = None,
        created_by: Optional[str] = None,
    ) -> ContextMessage:
        """Validate + persist a new context message. Returns the row."""
        self._validate(
            source=source,
            message_type=message_type,
            content_redacted=content_redacted,
            apply_mode=apply_mode,
        )
        context_id = f"ctx-{uuid.uuid4().hex[:16]}"
        created_at = int(time.time() * 1000)
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            conn.execute(
                """
                INSERT INTO orch_context_messages (
                    context_id, run_id, task_id, source, message_type,
                    content_redacted, apply_mode, expected_task_revision,
                    created_at, created_by, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    context_id, run_id, task_id, source, message_type,
                    content_redacted, apply_mode, expected_task_revision,
                    created_at, created_by,
                ),
            )
            conn.commit()
        return ContextMessage(
            context_id=context_id,
            run_id=run_id,
            task_id=task_id,
            source=source,
            message_type=message_type,
            content_redacted=content_redacted,
            apply_mode=apply_mode,
            expected_task_revision=expected_task_revision,
            created_at=created_at,
            created_by=created_by,
            status="pending",
        )

    def _validate(
        self,
        *,
        source: str,
        message_type: str,
        content_redacted: str,
        apply_mode: str,
    ) -> None:
        if source not in _VALID_SOURCES:
            raise OrchestrationContextError(f"invalid source: {source}")
        if message_type not in _VALID_MESSAGE_TYPES:
            raise OrchestrationContextError(f"invalid message_type: {message_type}")
        if apply_mode not in _VALID_APPLY_MODES:
            raise OrchestrationContextError(f"invalid apply_mode: {apply_mode}")
        if not content_redacted or not content_redacted.strip():
            raise OrchestrationContextError("content_redacted is empty")
        if len(content_redacted.encode("utf-8")) > _CONTENT_MAX_BYTES:
            raise OrchestrationContextError(
                f"content_redacted exceeds {_CONTENT_MAX_BYTES} byte limit"
            )

    # -------------------------------------------------------------------- reads

    def get(self, context_id: str) -> Optional[ContextMessage]:
        row = self.db.get_connection().execute(
            """
            SELECT context_id, run_id, task_id, source, message_type,
                   content_redacted, apply_mode, expected_task_revision,
                   created_at, created_by, status, applied_at, applied_step_id
            FROM orch_context_messages WHERE context_id = ?
            """,
            (context_id,),
        ).fetchone()
        return self._row_to_message(row) if row else None

    def list_pending(
        self,
        task_id: str,
        apply_mode: Optional[str] = None,
    ) -> List[ContextMessage]:
        """All pending messages for ``task_id``, oldest first.

        ``apply_mode`` filters to a specific delivery class (e.g. only
        ``next_boundary``). Without it, returns every pending message.
        """
        if apply_mode:
            rows = self.db.get_connection().execute(
                """
                SELECT context_id, run_id, task_id, source, message_type,
                       content_redacted, apply_mode, expected_task_revision,
                       created_at, created_by, status, applied_at, applied_step_id
                FROM orch_context_messages
                WHERE task_id = ? AND status = 'pending' AND apply_mode = ?
                ORDER BY created_at ASC
                """,
                (task_id, apply_mode),
            ).fetchall()
        else:
            rows = self.db.get_connection().execute(
                """
                SELECT context_id, run_id, task_id, source, message_type,
                       content_redacted, apply_mode, expected_task_revision,
                       created_at, created_by, status, applied_at, applied_step_id
                FROM orch_context_messages
                WHERE task_id = ? AND status = 'pending'
                ORDER BY created_at ASC
                """,
                (task_id,),
            ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def list_for_task(self, task_id: str) -> List[ContextMessage]:
        """All messages for a task (any status), newest first."""
        rows = self.db.get_connection().execute(
            """
            SELECT context_id, run_id, task_id, source, message_type,
                   content_redacted, apply_mode, expected_task_revision,
                   created_at, created_by, status, applied_at, applied_step_id
            FROM orch_context_messages
            WHERE task_id = ?
            ORDER BY created_at DESC
            """,
            (task_id,),
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    # ---------------------------------------------------------------- lifecycle

    def mark_delivered(
        self,
        context_id: str,
        *,
        applied_step_id: Optional[str] = None,
    ) -> bool:
        """``pending`` → ``delivered``. Returns True iff a row transitioned."""
        return self._transition(context_id, "pending", "delivered", applied_step_id)

    def mark_acknowledged(self, context_id: str) -> bool:
        """``delivered`` → ``acknowledged``."""
        return self._transition(context_id, "delivered", "acknowledged", None)

    def mark_rejected(self, context_id: str) -> bool:
        """``pending`` | ``delivered`` → ``rejected``."""
        now_ms = int(time.time() * 1000)
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            cur = conn.execute(
                """
                UPDATE orch_context_messages
                SET status = 'rejected', applied_at = ?
                WHERE context_id = ? AND status IN ('pending', 'delivered')
                """,
                (now_ms, context_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def _transition(
        self,
        context_id: str,
        from_status: str,
        to_status: str,
        applied_step_id: Optional[str],
    ) -> bool:
        now_ms = int(time.time() * 1000)
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            cur = conn.execute(
                """
                UPDATE orch_context_messages
                SET status = ?, applied_at = ?, applied_step_id = ?
                WHERE context_id = ? AND status = ?
                """,
                (to_status, now_ms, applied_step_id, context_id, from_status),
            )
            conn.commit()
            return cur.rowcount > 0

    # -------------------------------------------------------------------- helpers

    @staticmethod
    def _row_to_message(row) -> ContextMessage:
        return ContextMessage(
            context_id=row["context_id"],
            run_id=row["run_id"],
            task_id=row["task_id"],
            source=row["source"],
            message_type=row["message_type"],
            content_redacted=row["content_redacted"],
            apply_mode=row["apply_mode"],
            expected_task_revision=row["expected_task_revision"],
            created_at=row["created_at"],
            created_by=row["created_by"],
            status=row["status"],
            applied_at=row["applied_at"],
            applied_step_id=row["applied_step_id"],
        )


__all__ = [
    "ContextMessage",
    "OrchestrationContextError",
    "OrchestrationContextRepository",
]
