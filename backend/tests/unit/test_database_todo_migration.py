"""Test todos table migration"""
import pytest
from backend.data.database import Database


def test_todos_table_created(tmp_path):
    """Verify todos table is created on init_db()"""
    db_path = tmp_path / "test.db"
    db = Database(db_path=str(db_path))
    db.init_db()

    # Query table info
    conn = db.get_connection()
    cursor = conn.execute("PRAGMA table_info(todos)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}

    assert "id" in columns
    assert "title" in columns
    assert "status" in columns
    assert "priority" in columns
    assert "due_at" in columns
    assert "created_at" in columns

    db.close()


def test_todos_indexes_created(tmp_path):
    """Verify indexes are created"""
    db_path = tmp_path / "test.db"
    db = Database(db_path=str(db_path))
    db.init_db()

    conn = db.get_connection()
    cursor = conn.execute("PRAGMA index_list(todos)")
    indexes = {row[1] for row in cursor.fetchall()}

    assert "idx_todos_status" in indexes
    assert "idx_todos_due_at" in indexes
    assert "idx_todos_project_tag" in indexes
    assert "idx_todos_parent_id" in indexes

    db.close()
