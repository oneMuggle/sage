"""Playbook library repository (2026-10-31).

Stores imported/shared playbook specs independently of any project. Entries
are deduplicated by canonical spec hash so re-importing the same file does not
create duplicates.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from backend.data.database import get_database
from backend.services.playbook_spec import normalize_playbook, spec_hash

logger = logging.getLogger(__name__)

MAX_LIBRARY_ITEMS = 100


@dataclass
class LibraryPlaybook:
    id: str
    name: str
    source: str
    spec: Dict[str, Any]
    spec_hash: str
    created_at: int

    def summary(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "spec_hash": self.spec_hash,
            "created_at": self.created_at,
            "stage_count": len(self.spec.get("stages") or []),
            "directories": [
                item.get("path") for item in self.spec.get("directory_layout") or []
            ],
        }


def _row_to_library(row) -> Optional[LibraryPlaybook]:  # noqa: ANN001 — sqlite3.Row
    try:
        spec = json.loads(row["spec_json"])
    except (TypeError, ValueError):
        logger.warning("library playbook %s has invalid spec_json", row["id"])
        return None
    return LibraryPlaybook(
        id=row["id"],
        name=row["name"],
        source=row["source"],
        spec=spec,
        spec_hash=row["spec_hash"],
        created_at=int(row["created_at"]),
    )


class PlaybookLibraryRepository:
    def __init__(self) -> None:
        self.db = get_database()

    def list(self, limit: int = MAX_LIBRARY_ITEMS) -> List[LibraryPlaybook]:
        conn = self.db.get_connection()
        rows = conn.execute(
            "SELECT * FROM playbook_library ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        items = [_row_to_library(row) for row in rows]
        return [item for item in items if item is not None]

    def get(self, library_id: str) -> Optional[LibraryPlaybook]:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM playbook_library WHERE id = ?", (library_id,)
        ).fetchone()
        return None if row is None else _row_to_library(row)

    def save(
        self, spec: Dict[str, Any], *, source: str = "imported"
    ) -> Tuple[LibraryPlaybook, bool]:
        normalized = normalize_playbook(spec)
        digest = spec_hash(normalized)
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM playbook_library WHERE spec_hash = ?", (digest,)
        ).fetchone()
        if row is not None:
            existing = _row_to_library(row)
            if existing is not None:
                return existing, False
        now_ms = int(time.time() * 1000)
        library_id = str(uuid.uuid4())
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO playbook_library
                (id, name, source, spec_json, spec_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                library_id,
                str(normalized.get("name") or "未命名规程")[:200],
                str(source or "imported")[:128],
                json.dumps(normalized, ensure_ascii=False),
                digest,
                now_ms,
            ),
        )
        # Keep the library bounded; oldest entries are removed.
        cursor.execute(
            "DELETE FROM playbook_library WHERE id NOT IN "
            "(SELECT id FROM playbook_library ORDER BY created_at DESC LIMIT ?)",
            (MAX_LIBRARY_ITEMS,),
        )
        conn.commit()
        return (
            LibraryPlaybook(
                id=library_id,
                name=str(normalized.get("name") or "未命名规程"),
                source=str(source or "imported"),
                spec=normalized,
                spec_hash=digest,
                created_at=now_ms,
            ),
            True,
        )

    def delete(self, library_id: str) -> bool:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM playbook_library WHERE id = ?", (library_id,))
        conn.commit()
        return cursor.rowcount > 0


__all__ = [
    "MAX_LIBRARY_ITEMS",
    "LibraryPlaybook",
    "PlaybookLibraryRepository",
]
