# backend/tests/data/test_artifact_repo.py
"""Tests for artifact_repo dedup logic (Task 1)."""

from __future__ import annotations

import pytest

from backend.data.artifact_repo import record_artifact
from backend.data.database import Database

pytestmark = pytest.mark.unit


@pytest.fixture()
def conn(tmp_path):
    db = Database(db_path=str(tmp_path / "artifacts_test.db"))
    db.init_db()
    try:
        yield db.get_connection()
    finally:
        db.close()


def test_record_artifact_dedup_by_session_and_path(conn):
    """Same (session_id, path) twice should produce only one row."""
    session_id = "sess_dedup"
    path = "/workspace/report.html"

    id1 = record_artifact(
        session_id=session_id,
        path=path,
        name="report.html",
        kind="code",
        size=100,
        conn=conn,
    )
    id2 = record_artifact(
        session_id=session_id,
        path=path,
        name="report.html",
        kind="code",
        size=200,  # size changed
        conn=conn,
    )

    rows = conn.execute(
        "SELECT * FROM artifacts WHERE session_id = ? AND path = ?",
        (session_id, path),
    ).fetchall()
    assert len(rows) == 1, f"Expected 1 artifact, got {len(rows)}"
    assert rows[0]["id"] == id1, "Should reuse existing artifact id"
    assert rows[0]["size"] == 200, "Should update size"
    assert id1 == id2, "Should return same id"


def test_record_artifact_distinct_paths_not_deduped(conn):
    """Different paths within same session should create separate rows."""
    id1 = record_artifact(
        session_id="sess_x",
        path="/a.md",
        name="a.md",
        kind="markdown",
        size=10,
        conn=conn,
    )
    id2 = record_artifact(
        session_id="sess_x",
        path="/b.md",
        name="b.md",
        kind="markdown",
        size=20,
        conn=conn,
    )

    rows = conn.execute("SELECT * FROM artifacts WHERE session_id = ?", ("sess_x",)).fetchall()
    assert len(rows) == 2
    assert id1 != id2


def test_record_artifact_same_path_different_session_not_deduped(conn):
    """Same path but different sessions should create separate rows."""
    id1 = record_artifact(
        session_id="sess_a",
        path="/report.html",
        name="report.html",
        kind="code",
        size=100,
        conn=conn,
    )
    id2 = record_artifact(
        session_id="sess_b",
        path="/report.html",
        name="report.html",
        kind="code",
        size=200,
        conn=conn,
    )

    total = conn.execute("SELECT COUNT(*) AS cnt FROM artifacts").fetchone()["cnt"]
    assert total == 2
    assert id1 != id2


def test_record_artifact_dedup_updates_tool_call_id(conn):
    """Dedup UPDATE should also refresh tool_call_id."""
    record_artifact(
        session_id="sess_t",
        path="/out.py",
        name="out.py",
        kind="code",
        size=50,
        tool_call_id="call_old",
        conn=conn,
    )
    record_artifact(
        session_id="sess_t",
        path="/out.py",
        name="out.py",
        kind="code",
        size=60,
        tool_call_id="call_new",
        conn=conn,
    )

    row = conn.execute(
        "SELECT * FROM artifacts WHERE session_id = ? AND path = ?",
        ("sess_t", "/out.py"),
    ).fetchone()
    assert row["tool_call_id"] == "call_new"
    assert row["size"] == 60
