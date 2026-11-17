"""Tests for the idempotent memory_traceability schema migration (Task 4 step 9).

Pins the contract:
- After ``init_db()`` on a fresh DB, the new columns exist on
  ``memories_episodic`` and the supporting indexes exist.
- Calling ``init_db()`` again on the same DB is a no-op (no exceptions,
  no duplicate columns, no duplicate indexes).
- The columns are nullable so existing rows remain valid.
"""

from __future__ import annotations

import sqlite3

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


# 旧版建表语句（2026-11-17 记忆详情化之前）：不含 title 列。
_LEGACY_EPISODIC_DDL = """
CREATE TABLE memories_episodic (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    content TEXT NOT NULL,
    summary TEXT,
    memory_type TEXT DEFAULT 'conversation',
    importance INTEGER DEFAULT 5,
    source TEXT DEFAULT 'auto',
    tags TEXT,
    created_at INTEGER NOT NULL,
    accessed_at INTEGER,
    access_count INTEGER DEFAULT 0,
    sentiment TEXT,
    is_valid INTEGER DEFAULT 1,
    expires_at INTEGER,
    scope TEXT DEFAULT 'user',
    project_key TEXT,
    invalid_at INTEGER,
    supersedes_id TEXT
)
"""

_LEGACY_SEMANTIC_DDL = """
CREATE TABLE memories_semantic (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    summary TEXT,
    tags TEXT DEFAULT '[]',
    created_at INTEGER NOT NULL,
    scope TEXT DEFAULT 'user',
    project_key TEXT,
    invalid_at INTEGER,
    supersedes_id TEXT
)
"""


def test_init_db_adds_title_column_to_legacy_tables(tmp_path):
    """存量库缺 title 列时，init_db 必须幂等补列（ALTER 路径）。

    刻意不用 ``tmp_db_path`` fixture —— autouse 的 ``setup_test_db`` 会先在该
    文件上跑一遍完整 init_db，旧表结构就无从模拟了。
    """
    db_file = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_file)
    conn.execute(_LEGACY_EPISODIC_DDL)
    conn.execute(_LEGACY_SEMANTIC_DDL)
    conn.commit()
    conn.close()

    db = Database(db_path=db_file)
    db.init_db()
    try:
        episodic_cols = {
            row[1]
            for row in db.get_connection().execute(
                "PRAGMA table_info(memories_episodic)"
            )
        }
        semantic_cols = {
            row[1]
            for row in db.get_connection().execute(
                "PRAGMA table_info(memories_semantic)"
            )
        }
        assert "title" in episodic_cols
        assert "title" in semantic_cols
    finally:
        db.close()
