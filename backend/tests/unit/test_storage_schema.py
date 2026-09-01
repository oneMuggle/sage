"""Tests for background-review storage schema (review_events + skill_drafts).

Task 4 of 2026-08-02-background-review: verify both tables are created by
Database.init_db() with the correct column definitions.
"""
import os
import sqlite3
import tempfile

from backend.data.database import Database


def _init_fresh_db() -> str:
    """Create a temp DB file, run init_db, return the path."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(db_path)
    db.init_db()
    db.close()
    return db_path


def _table_columns(db_path: str, table_name: str) -> list[dict]:
    """Return PRAGMA table_info rows for *table_name* as dicts."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
        cols = cursor.fetchall()
    # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
    return [
        {
            "cid": r[0],
            "name": r[1],
            "type": r[2],
            "notnull": r[3],
            "dflt_value": r[4],
            "pk": r[5],
        }
        for r in cols
    ]


def test_fresh_database_does_not_create_legacy_skills_table():
    """新数据库不应创建已废弃且无运行时消费者的 skills 表。"""
    db_path = _init_fresh_db()
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='skills'"
            ).fetchone()
            assert row is None
    finally:
        os.unlink(db_path)


def test_init_db_preserves_existing_legacy_skills_table():
    """迁移只停止新建，不删除已有用户数据库中的 skills 表或数据。"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE skills (id TEXT PRIMARY KEY, name TEXT NOT NULL)"
            )
            conn.execute("INSERT INTO skills (id, name) VALUES ('legacy-1', '旧技能')")
            conn.commit()

        db = Database(db_path)
        db.init_db()
        db.close()

        with sqlite3.connect(db_path) as conn:
            table = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='skills'"
            ).fetchone()
            row = conn.execute(
                "SELECT id, name FROM skills WHERE id='legacy-1'"
            ).fetchone()
            assert table is not None
            assert row == ("legacy-1", "旧技能")
    finally:
        os.unlink(db_path)


# ------------------------------------------------------------------ #
# Table existence
# ------------------------------------------------------------------ #


def test_review_events_table_created():
    """review_events table exists after init_db."""
    db_path = _init_fresh_db()
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='review_events'"
            ).fetchone()
            assert row is not None, "review_events table not found"
    finally:
        os.unlink(db_path)


def test_skill_drafts_table_created():
    """skill_drafts table exists after init_db."""
    db_path = _init_fresh_db()
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='skill_drafts'"
            ).fetchone()
            assert row is not None, "skill_drafts table not found"
    finally:
        os.unlink(db_path)


# ------------------------------------------------------------------ #
# review_events column schema
# ------------------------------------------------------------------ #


def test_review_events_columns():
    """review_events has the exact columns from the brief spec."""
    db_path = _init_fresh_db()
    try:
        cols = _table_columns(db_path, "review_events")
        col_names = [c["name"] for c in cols]

        expected = [
            "id",
            "trigger_type",
            "session_id",
            "context",
            "status",
            "created_at",
            "processed_at",
            "error_message",
        ]
        for name in expected:
            assert name in col_names, f"Missing column: {name}"

        # Type / constraint spot-checks
        col_map = {c["name"]: c for c in cols}
        assert col_map["id"]["pk"] == 1, "id should be PRIMARY KEY"
        assert col_map["trigger_type"]["notnull"] == 1
        assert col_map["session_id"]["notnull"] == 1
        assert col_map["context"]["notnull"] == 1
        assert col_map["status"]["notnull"] == 1
        assert col_map["status"]["dflt_value"] == "'pending'"
        assert col_map["created_at"]["notnull"] == 1
        # processed_at and error_message are nullable
        assert col_map["processed_at"]["notnull"] == 0
        assert col_map["error_message"]["notnull"] == 0
    finally:
        os.unlink(db_path)


# ------------------------------------------------------------------ #
# skill_drafts column schema
# ------------------------------------------------------------------ #


def test_skill_drafts_columns():
    """skill_drafts has the exact columns from the brief spec."""
    db_path = _init_fresh_db()
    try:
        cols = _table_columns(db_path, "skill_drafts")
        col_names = [c["name"] for c in cols]

        expected = [
            "id",
            "name",
            "description",
            "when_to_use",
            "content",
            "trigger_type",
            "source_session_id",
            "source_context",
            "status",
            "created_at",
            "reviewed_at",
            "reviewed_by_user_id",
        ]
        for name in expected:
            assert name in col_names, f"Missing column: {name}"

        col_map = {c["name"]: c for c in cols}
        # id is TEXT PRIMARY KEY
        assert col_map["id"]["pk"] == 1
        assert col_map["id"]["type"].upper() == "TEXT"
        # Required NOT NULL columns
        for required_col in (
            "name",
            "description",
            "when_to_use",
            "content",
            "trigger_type",
            "created_at",
        ):
            assert col_map[required_col]["notnull"] == 1, (
                f"{required_col} should be NOT NULL"
            )
        # status defaults to 'pending'
        assert col_map["status"]["notnull"] == 1
        assert col_map["status"]["dflt_value"] == "'pending'"
        # Nullable columns
        assert col_map["source_session_id"]["notnull"] == 0
        assert col_map["source_context"]["notnull"] == 0
        assert col_map["reviewed_at"]["notnull"] == 0
        assert col_map["reviewed_by_user_id"]["notnull"] == 0
    finally:
        os.unlink(db_path)


# ------------------------------------------------------------------ #
# Idempotency — calling init_db twice should not fail
# ------------------------------------------------------------------ #


def test_init_db_idempotent():
    """Calling init_db twice must not raise (CREATE TABLE IF NOT EXISTS)."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = Database(db_path)
        db.init_db()
        db.init_db()  # second call should be a no-op
        db.close()

        # Tables still exist and are usable
        with sqlite3.connect(db_path) as conn:
            for table in ("review_events", "skill_drafts"):
                row = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                assert row is not None, f"{table} missing after double init"
    finally:
        os.unlink(db_path)
