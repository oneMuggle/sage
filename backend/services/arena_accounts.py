"""Arena account pool: SQLite storage with Fernet-encrypted credentials.

State machine:
  available -> reserved -> available (on release)
  available -> degraded (on first failure)
  degraded  -> available (on release, resets count)
  degraded  -> disabled (when failure_count reaches threshold)
  *         -> destroyed (on soft_delete)
  disabled  -> available (on manual enable_account)
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


class AccountState(Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    DESTROYED = "destroyed"


#: Default failure threshold before account is auto-disabled
DEFAULT_FAILURE_THRESHOLD = 3


_SCHEMA = """
CREATE TABLE IF NOT EXISTS arena_accounts (
    id              TEXT PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_enc    BLOB NOT NULL,
    state           TEXT NOT NULL DEFAULT 'available',
    last_used_at    TEXT,
    failure_count   INTEGER NOT NULL DEFAULT 0,
    isolated_at     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_arena_accounts_state
    ON arena_accounts(state);
"""


class ArenaAccountService:
    """Thread-safe account pool backed by SQLite."""

    def __init__(
        self,
        db_path: str,
        encryption_key: bytes,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    ):
        self._db_path = db_path
        self._fernet = Fernet(encryption_key)
        self._failure_threshold = failure_threshold
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- CRUD -------------------------------------------------------------

    def create_account(
        self, email: str, password: str, notes: Optional[str] = None
    ) -> Dict:
        with self._lock:
            now = datetime.utcnow().isoformat(timespec="seconds")
            account_id = str(uuid.uuid4())
            password_enc = self._fernet.encrypt(password.encode("utf-8"))
            try:
                self._conn.execute(
                    """
                    INSERT INTO arena_accounts
                    (id, email, password_enc, state, failure_count,
                     created_at, updated_at, notes)
                    VALUES (?, ?, ?, 'available', 0, ?, ?, ?)
                    """,
                    (account_id, email, password_enc, now, now, notes),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as e:
                raise ValueError(f"email {email!r} already exists") from e
            return {
                "id": account_id,
                "email": email,
                "state": AccountState.AVAILABLE.value,
                "failure_count": 0,
                "created_at": now,
            }

    def list_accounts(self, state: Optional[AccountState] = None) -> List[Dict]:
        with self._lock:
            if state is not None:
                rows = self._conn.execute(
                    "SELECT id FROM arena_accounts WHERE state = ? ORDER BY created_at",
                    (state.value,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id FROM arena_accounts ORDER BY created_at"
                ).fetchall()
            return [self.get_account(r[0]) for r in rows if self.get_account(r[0])]

    def get_account(self, account_id: str) -> Optional[Dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, email, password_enc, state, last_used_at, "
                "failure_count, isolated_at, created_at, updated_at, notes "
                "FROM arena_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "email": row[1],
                "password": self._fernet.decrypt(row[2]).decode("utf-8"),
                "state": row[3],
                "last_used_at": row[4],
                "failure_count": row[5],
                "isolated_at": row[6],
                "created_at": row[7],
                "updated_at": row[8],
                "notes": row[9],
            }

    # -- Scheduling -------------------------------------------------------

    def reserve_account(self) -> Optional[Dict]:
        """Pick the available account with oldest last_used_at (LRU)."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id FROM arena_accounts
                WHERE state = 'available'
                ORDER BY
                    CASE WHEN last_used_at IS NULL THEN 1 ELSE 0 END,
                    last_used_at ASC
                LIMIT 1
                """,
            ).fetchone()
            if row is None:
                return None
            now = datetime.utcnow().isoformat(timespec="seconds")
            self._conn.execute(
                "UPDATE arena_accounts SET state = 'reserved', "
                "last_used_at = ?, updated_at = ? WHERE id = ?",
                (now, now, row[0]),
            )
            self._conn.commit()
            return self.get_account(row[0])

    def release_account(self, account_id: str) -> None:
        with self._lock:
            now = datetime.utcnow().isoformat(timespec="seconds")
            self._conn.execute(
                "UPDATE arena_accounts SET state = 'available', "
                "failure_count = 0, updated_at = ? WHERE id = ?",
                (now, account_id),
            )
            self._conn.commit()

    def record_failure(self, account_id: str, reason: str) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT failure_count FROM arena_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            if row is None:
                return
            new_count = row[0] + 1
            new_state = "degraded"
            isolated_at = None
            if new_count >= self._failure_threshold:
                new_state = "disabled"
                isolated_at = datetime.utcnow().isoformat(timespec="seconds")
            now = datetime.utcnow().isoformat(timespec="seconds")
            self._conn.execute(
                "UPDATE arena_accounts SET state = ?, failure_count = ?, "
                "isolated_at = ?, updated_at = ? WHERE id = ?",
                (new_state, new_count, isolated_at, now, account_id),
            )
            self._conn.commit()
            logger.info(
                "arena account %s failure recorded: count=%d state=%s reason=%s",
                account_id, new_count, new_state, reason,
            )

    def enable_account(self, account_id: str) -> None:
        with self._lock:
            now = datetime.utcnow().isoformat(timespec="seconds")
            self._conn.execute(
                "UPDATE arena_accounts SET state = 'available', "
                "failure_count = 0, isolated_at = NULL, updated_at = ? "
                "WHERE id = ?",
                (now, account_id),
            )
            self._conn.commit()

    def soft_delete_account(self, account_id: str) -> None:
        with self._lock:
            now = datetime.utcnow().isoformat(timespec="seconds")
            self._conn.execute(
                "UPDATE arena_accounts SET state = 'destroyed', updated_at = ? "
                "WHERE id = ?",
                (now, account_id),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
