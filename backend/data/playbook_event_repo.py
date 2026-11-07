"""Playbook event repository (2026-11-02).

Stores lightweight telemetry events for playbook usage — bind/unbind, audit,
actions apply, stage confirm, imports, exports, library operations, batch
moves. Events are best-effort: failures are logged but never propagated, so
the main playbook flow is unaffected by telemetry issues.

Events are local-only and never uploaded. They power the "recent activity"
view inside the playbook card and future analytics.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.data.database import get_database

logger = logging.getLogger(__name__)

# Events are bounded per project to keep the table small.
MAX_EVENTS_PER_PROJECT = 500

# Allowed event types — typos are silently ignored (logged).
ALLOWED_EVENTS = frozenset(
    {
        "bind",
        "unbind",
        "audit",
        "audit_ai",
        "author",
        "actions_apply",
        "stage_confirm",
        "import",
        "export_json",
        "export_md",
        "export_agents",
        "export_wiki",
        "library_save",
        "library_delete",
        "library_export",
        "batch_move",
        "undo_batch_move",
        "cleanup_rules",
        "rules_ai_apply",
        "exemption_grant",
        "exemption_revoke",
        "manual_complete",
        "update_state",
    }
)


@dataclass(frozen=True)
class PlaybookEvent:
    id: int
    project_id: str
    event: str
    stage: Optional[str]
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: int = 0


def _row_to_event(row) -> PlaybookEvent:
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except (TypeError, ValueError):
        payload = {}
    return PlaybookEvent(
        id=int(row["id"]),
        project_id=row["project_id"],
        event=row["event"],
        stage=row["stage"],
        payload=payload if isinstance(payload, dict) else {},
        created_at=int(row["created_at"]),
    )


class PlaybookEventRepository:
    """Best-effort local event recorder for playbook usage."""

    def __init__(self) -> None:
        self.db = get_database()

    def record(
        self,
        project_id: str,
        event: str,
        *,
        stage: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        """Record an event. Returns the inserted id, or None on failure.

        Failures are caught and logged — telemetry must never break the main
        playbook flow.
        """
        if event not in ALLOWED_EVENTS:
            logger.debug("playbook event type %r not in allowlist; skipping", event)
            return None
        if not project_id:
            return None
        payload_json = "{}"
        if payload:
            try:
                payload_json = json.dumps(payload, ensure_ascii=False)
            except (TypeError, ValueError):
                payload_json = "{}"
        now_ms = int(time.time() * 1000)
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO playbook_events "
                "(project_id, event, stage, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(project_id),
                    event,
                    (str(stage)[:128] if stage is not None else None),
                    payload_json,
                    now_ms,
                ),
            )
            event_id = cursor.lastrowid
            # Bounded retention per project.
            cursor.execute(
                "DELETE FROM playbook_events WHERE project_id = ? AND id NOT IN "
                "(SELECT id FROM playbook_events "
                "WHERE project_id = ? ORDER BY created_at DESC LIMIT ?)",
                (str(project_id), str(project_id), MAX_EVENTS_PER_PROJECT),
            )
            conn.commit()
            return event_id
        except Exception:  # pragma: no cover - best effort
            logger.warning("failed to record playbook event", exc_info=True)
            return None

    def list_recent(
        self, project_id: str, *, limit: int = 50
    ) -> List[PlaybookEvent]:
        if not project_id:
            return []
        limit = max(1, min(limit, 200))
        try:
            conn = self.db.get_connection()
            rows = conn.execute(
                "SELECT * FROM playbook_events WHERE project_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (str(project_id), limit),
            ).fetchall()
            return [_row_to_event(row) for row in rows]
        except Exception:  # pragma: no cover - best effort
            logger.warning("failed to list playbook events", exc_info=True)
            return []

    def aggregate(
        self, project_id: Optional[str] = None, *, days: int = 30
    ) -> Dict[str, int]:
        """Return event counts keyed by event name within the time window."""
        days = max(1, min(days, 365))
        cutoff_ms = int((time.time() - days * 86400) * 1000)
        try:
            conn = self.db.get_connection()
            if project_id:
                rows = conn.execute(
                    "SELECT event, COUNT(*) AS n FROM playbook_events "
                    "WHERE project_id = ? AND created_at >= ? "
                    "GROUP BY event",
                    (str(project_id), cutoff_ms),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT event, COUNT(*) AS n FROM playbook_events "
                    "WHERE created_at >= ? GROUP BY event",
                    (cutoff_ms,),
                ).fetchall()
            return {row["event"]: int(row["n"]) for row in rows}
        except Exception:  # pragma: no cover - best effort
            logger.warning("failed to aggregate playbook events", exc_info=True)
            return {}


def record_playbook_event(
    project_id: str,
    event: str,
    *,
    stage: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Module-level convenience wrapper (lazy-constructs the repo)."""
    return PlaybookEventRepository().record(
        project_id, event, stage=stage, payload=payload
    )


__all__ = [
    "ALLOWED_EVENTS",
    "MAX_EVENTS_PER_PROJECT",
    "PlaybookEvent",
    "PlaybookEventRepository",
    "record_playbook_event",
]
