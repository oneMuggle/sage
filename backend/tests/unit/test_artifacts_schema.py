from backend.data.database import get_database


def test_artifacts_table_exists():
    db = get_database()
    conn = db.get_connection()
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='artifacts'"
    )
    row = cursor.fetchone()
    assert row is not None
    assert row["name"] == "artifacts"


def test_artifacts_table_columns():
    db = get_database()
    conn = db.get_connection()
    cursor = conn.execute("PRAGMA table_info(artifacts)")
    cols = {r["name"] for r in cursor.fetchall()}
    assert {"id", "session_id", "tool_call_id", "path", "name", "kind", "size", "created_at"} <= cols
