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


# ==================== Version History (Phase 2 M2) ====================


def test_artifact_versions_table_exists():
    """artifact_versions 表由 init_db() 创建。"""
    db = get_database()
    conn = db.get_connection()
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='artifact_versions'"
    )
    row = cursor.fetchone()
    assert row is not None
    assert row["name"] == "artifact_versions"


def test_artifact_versions_table_columns():
    """复合主键 (artifact_id, version_num)；索引 idx_artifact_versions_artifact。"""
    db = get_database()
    conn = db.get_connection()
    cursor = conn.execute("PRAGMA table_info(artifact_versions)")
    cols = {r["name"] for r in cursor.fetchall()}
    assert {"artifact_id", "version_num", "content_hash", "snapshot_path", "created_at", "note"} <= cols

    cursor_idx = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_artifact_versions_artifact'"
    )
    assert cursor_idx.fetchone() is not None
