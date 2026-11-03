"""Playbook share repository (2026-11-03).

Stores share tokens linking to playbook library entries. Each token grants
read-only access to the playbook spec for a limited time window.
"""

from __future__ import annotations

import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from backend.data.database import get_database

DEFAULT_EXPIRY_DAYS = 7


@dataclass
class PlaybookShare:
    id: str
    playbook_id: str
    token: str
    expires_at: int
    created_at: int

    @property
    def is_expired(self) -> bool:
        return int(time.time() * 1000) >= self.expires_at


def _row_to_share(row) -> PlaybookShare:  # noqa: ANN001 — sqlite3.Row
    return PlaybookShare(
        id=row["id"],
        playbook_id=row["playbook_id"],
        token=row["token"],
        expires_at=int(row["expires_at"]),
        created_at=int(row["created_at"]),
    )


class PlaybookShareRepository:
    def __init__(self) -> None:
        self.db = get_database()

    def create(
        self,
        playbook_id: str,
        *,
        expiry_days: int = DEFAULT_EXPIRY_DAYS,
    ) -> PlaybookShare:
        now_ms = int(time.time() * 1000)
        expires_ms = now_ms + expiry_days * 86_400_000
        share_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(16)
        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO playbook_shares (id, playbook_id, token, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (share_id, playbook_id, token, expires_ms, now_ms),
        )
        conn.commit()
        return PlaybookShare(
            id=share_id,
            playbook_id=playbook_id,
            token=token,
            expires_at=expires_ms,
            created_at=now_ms,
        )

    def get_by_token(self, token: str) -> Optional[PlaybookShare]:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM playbook_shares WHERE token = ?", (token,)
        ).fetchone()
        return None if row is None else _row_to_share(row)

    def delete(self, share_id: str) -> bool:
        conn = self.db.get_connection()
        cursor = conn.execute(
            "DELETE FROM playbook_shares WHERE id = ?", (share_id,)
        )
        conn.commit()
        return cursor.rowcount > 0


__all__ = [
    "DEFAULT_EXPIRY_DAYS",
    "PlaybookShare",
    "PlaybookShareRepository",
]
