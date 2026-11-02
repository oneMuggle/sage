"""Playbook snapshot repository (2026-10-31).

Each project binds a complete snapshot of a playbook spec, so upgrading a
built-in playbook never silently changes an existing project's behaviour.
Only the newest snapshot is ``active``; older versions remain for diffing.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.data.database import get_database
from backend.data.project_repo import ProjectRepository
from backend.services.playbook_spec import normalize_playbook, spec_hash

logger = logging.getLogger(__name__)

MAX_SNAPSHOTS_PER_PROJECT = 20


@dataclass
class PlaybookSnapshot:
    """One project-bound playbook snapshot."""

    id: str
    project_id: str
    version: int
    source: str
    parent_id: Optional[str]
    spec: Dict[str, Any]
    spec_hash: str
    created_at: int
    active: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "version": self.version,
            "source": self.source,
            "parent_id": self.parent_id,
            "spec": self.spec,
            "spec_hash": self.spec_hash,
            "created_at": self.created_at,
            "active": self.active,
        }


def _row_to_snapshot(row) -> Optional[PlaybookSnapshot]:  # noqa: ANN001 — sqlite3.Row
    try:
        spec = json.loads(row["spec_json"])
    except (TypeError, ValueError):
        logger.warning("playbook snapshot %s has invalid spec_json", row["id"])
        return None
    return PlaybookSnapshot(
        id=row["id"],
        project_id=row["project_id"],
        version=int(row["version"]),
        source=row["source"],
        parent_id=row["parent_id"],
        spec=spec,
        spec_hash=row["spec_hash"],
        created_at=int(row["created_at"]),
        active=bool(row["active"]),
    )


class PlaybookRepository:
    """CRUD for project playbook snapshots and the project's playbook state."""

    def __init__(self) -> None:
        self.db = get_database()

    def get_active(self, project_id: str) -> Optional[PlaybookSnapshot]:
        conn = self.db.get_connection()
        row = conn.execute(
            """
            SELECT * FROM project_playbooks
            WHERE project_id = ? AND active = 1
            ORDER BY version DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        return None if row is None else _row_to_snapshot(row)

    def list_versions(self, project_id: str, limit: int = MAX_SNAPSHOTS_PER_PROJECT) -> List[PlaybookSnapshot]:
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT * FROM project_playbooks
            WHERE project_id = ?
            ORDER BY version DESC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
        snapshots = [_row_to_snapshot(row) for row in rows]
        return [item for item in snapshots if item is not None]

    def create_snapshot(
        self,
        project_id: str,
        spec: Dict[str, Any],
        *,
        source: str = "custom",
        parent_id: Optional[str] = None,
    ) -> PlaybookSnapshot:
        normalized = normalize_playbook(spec)
        digest = spec_hash(normalized)
        conn = self.db.get_connection()
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT MAX(version) AS max_version FROM project_playbooks WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        version = int((row["max_version"] if row is not None else 0) or 0) + 1
        now_ms = int(time.time() * 1000)
        snapshot_id = str(uuid.uuid4())
        cursor.execute(
            "UPDATE project_playbooks SET active = 0 WHERE project_id = ?",
            (project_id,),
        )
        cursor.execute(
            """
            INSERT INTO project_playbooks
                (id, project_id, version, source, parent_id, spec_json, spec_hash, created_at, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                snapshot_id,
                project_id,
                version,
                str(source or "custom"),
                parent_id,
                json.dumps(normalized, ensure_ascii=False),
                digest,
                now_ms,
            ),
        )
        # Keep only the newest MAX_SNAPSHOTS_PER_PROJECT versions.
        cursor.execute(
            "DELETE FROM project_playbooks WHERE project_id = ? AND version <= ?",
            (project_id, version - MAX_SNAPSHOTS_PER_PROJECT),
        )
        conn.commit()
        return PlaybookSnapshot(
            id=snapshot_id,
            project_id=project_id,
            version=version,
            source=str(source or "custom"),
            parent_id=parent_id,
            spec=normalized,
            spec_hash=digest,
            created_at=now_ms,
            active=True,
        )

    def delete_snapshot(self, project_id: str, snapshot_id: str) -> bool:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM project_playbooks WHERE project_id = ? AND id = ?",
            (project_id, snapshot_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def unbind(self, project_id: str) -> int:
        """Deactivate all snapshots for a project (history is kept)."""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE project_playbooks SET active = 0 WHERE project_id = ? AND active = 1",
            (project_id,),
        )
        conn.commit()
        return cursor.rowcount

    def get_state(self, project_id: str) -> Dict[str, Any]:
        project = ProjectRepository().get(project_id)
        if project is None or not project.playbook_state:
            return {}
        try:
            state = json.loads(project.playbook_state)
        except (TypeError, ValueError):
            logger.warning("project %s has invalid playbook_state", project_id)
            return {}
        return state if isinstance(state, dict) else {}

    def update_state(self, project_id: str, state: Dict[str, Any]) -> bool:
        payload = json.dumps(state or {}, ensure_ascii=False)
        return ProjectRepository().update_playbook_state(project_id, payload)


__all__ = [
    "MAX_SNAPSHOTS_PER_PROJECT",
    "PlaybookRepository",
    "PlaybookSnapshot",
]
