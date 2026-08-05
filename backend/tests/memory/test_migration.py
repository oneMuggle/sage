"""Tests for the idempotent memory_traceability schema migration (Task 4 step 9).

Pins the contract:
- After ``init_db()`` on a fresh DB, the new columns exist on
  ``memories_episodic`` and the supporting indexes exist.
- Calling ``init_db()`` again on the same DB is a no-op (no exceptions,
  no duplicate columns, no duplicate indexes).
- The columns are nullable so existing rows remain valid.
"""

from __future__ import annotations

import pytest

from backend.data.database import Database

pytestmark = pytest.mark.unit


def test_init_db_creates_traceability_columns(tmp_db_path):
    """Fresh DB: source_turn_id / source_message_id / memory_category exist."""
    db = Database(db_path=tmp_db_path)
    db.init_db()

    cur = db.get_connection().execute("PRAGMA table_info(memories_episodic)")
    cols = {row[1] for row in cur.fetchall()}
    assert "source_turn_id" in cols
    assert "source_message_id" in cols
    assert "memory_category" in cols


def test_init_db_creates_traceability_indexes(tmp_db_path):
    """Fresh DB: indexes for session+turn and category are created."""
    db = Database(db_path=tmp_db_path)
    db.init_db()

    cur = db.get_connection().execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_mem_episodic%'"
    )
    idx = {row[0] for row in cur.fetchall()}
    assert "idx_mem_episodic_session_turn" in idx
    assert "idx_mem_episodic_category" in idx


def test_init_db_is_idempotent(tmp_db_path):
    """Calling init_db() twice on the same DB does not raise / duplicate
    columns / duplicate indexes."""
    db = Database(db_path=tmp_db_path)
    db.init_db()
    # Second call — must not raise
    db.init_db()

    cur = db.get_connection().execute("PRAGMA table_info(memories_episodic)")
    cols = [row[1] for row in cur.fetchall()]
    # Columns must not appear twice (no duplicate from a naive second migration)
    assert cols.count("source_turn_id") == 1
    assert cols.count("source_message_id") == 1
    assert cols.count("memory_category") == 1


def test_traceability_columns_are_nullable(tmp_db_path):
    """Old rows (no traceability) must remain readable: columns are nullable."""
    db = Database(db_path=tmp_db_path)
    db.init_db()

    # Insert a row without traceability info — mimics a legacy row
    db.get_connection().execute(
        """
        INSERT INTO memories_episodic
        (id, content, created_at) VALUES ('legacy-1', 'old fact', 1)
    """
    )
    db.get_connection().commit()

    cur = db.get_connection().execute(
        "SELECT id, source_turn_id, source_message_id, memory_category "
        "FROM memories_episodic WHERE id = 'legacy-1'"
    )
    row = cur.fetchone()
    assert row[0] == "legacy-1"
    assert row[1] is None
    assert row[2] is None
    assert row[3] is None