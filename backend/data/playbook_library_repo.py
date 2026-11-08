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
        meta = _spec_meta(self.spec)
        tags = meta.get("tags")
        tags = tags if isinstance(tags, list) else []
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
            "description": str(self.spec.get("description") or ""),
            "tags": [str(tag) for tag in tags],
        }


def _spec_meta(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Return the spec's ``meta`` dict, tolerating legacy / hand-edited rows."""
    meta = spec.get("meta")
    return meta if isinstance(meta, dict) else {}


def _matches_query(item: LibraryPlaybook, tokens: List[str]) -> bool:
    """True when every casefolded token appears in name, description or tags."""
    tags = _spec_meta(item.spec).get("tags")
    tags = tags if isinstance(tags, list) else []
    haystacks = [
        item.name or "",
        str(item.spec.get("description") or ""),
        " ".join(str(tag) for tag in tags),
    ]
    folded = " ".join(haystacks).casefold()
    return all(token in folded for token in tokens)


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

    def list(
        self, limit: int = MAX_LIBRARY_ITEMS, *, q: str = ""
    ) -> List[LibraryPlaybook]:
        """Return library items, optionally filtered by a search query.

        The query matches name / description / tags (case-insensitive
        substring); multi-word queries require every token to match.
        """
        conn = self.db.get_connection()
        rows = conn.execute(
            "SELECT * FROM playbook_library ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        items = [_row_to_library(row) for row in rows]
        results = [item for item in items if item is not None]
        tokens = [token.casefold() for token in q.split() if token.strip()]
        if not tokens:
            return results
        return [item for item in results if _matches_query(item, tokens)]

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

    def update_metadata(
        self,
        library_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[LibraryPlaybook]:
        """Update display metadata (name / description / tags) in place.

        ``spec_hash`` is deliberately left untouched: it identifies the
        imported source spec, so metadata edits must not change that identity
        (otherwise re-importing the same source would create a duplicate).

        Returns the updated entry, or None when it does not exist.
        """
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM playbook_library WHERE id = ?", (library_id,)
        ).fetchone()
        if row is None:
            return None
        try:
            spec = json.loads(row["spec_json"])
        except (TypeError, ValueError):
            logger.warning("library playbook %s has invalid spec_json", library_id)
            return None
        if not isinstance(spec, dict):
            return None
        meta = _spec_meta(spec)
        if description is not None:
            spec["description"] = str(description).strip()
        if tags is not None:
            meta["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]
        spec["meta"] = meta
        new_name = str(name).strip() if name is not None else row["name"]
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE playbook_library SET name = ?, spec_json = ? WHERE id = ?",
            (new_name, json.dumps(spec, ensure_ascii=False), library_id),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM playbook_library WHERE id = ?", (library_id,)
        ).fetchone()
        return None if updated is None else _row_to_library(updated)

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
