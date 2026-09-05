"""Tests for orchestration observability database tables."""

from __future__ import annotations

from backend.data.database import Database


def test_observability_tables_are_initialized(tmp_path):
    """数据库初始化应创建事件、步骤和上下文表及关键索引。"""
    db = Database(str(tmp_path / "observability.db"))
    db.init_db()
    conn = db.get_connection()
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {"orch_events", "orch_steps", "orch_context_messages"} <= tables

    event_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(orch_events)").fetchall()
    }
    assert {
        "event_id",
        "run_id",
        "seq",
        "event_type",
        "payload",
        "visibility",
        "schema_version",
    } <= event_columns

    indexes = {
        row[1]
        for row in conn.execute(
            "SELECT type, name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    assert "idx_orch_events_run_seq" in indexes
    assert "idx_orch_steps_task_seq" in indexes


def test_observability_schema_is_idempotent(tmp_path):
    """重复初始化同一数据库不得报错或丢失表。"""
    path = str(tmp_path / "observability.db")
    first = Database(path)
    first.init_db()
    first.get_connection().close()
    second = Database(path)
    second.init_db()
    conn = second.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM orch_events").fetchone()[0] == 0
