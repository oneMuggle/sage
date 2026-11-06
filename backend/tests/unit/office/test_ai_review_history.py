"""Unit tests for :mod:`backend.office.ai_review_history`.

Covers:

* :func:`record` is best-effort — never raises, even against a closed
  connection or a missing table.
* :func:`list_for_document` deserializes the JSON summary, returns
  rows newest-first, and respects ``limit``.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from backend.data import database as db_mod
from backend.data.database import Database
from backend.office.ai_review_history import list_for_document, record


@pytest.fixture()
def conn() -> sqlite3.Connection:
    db_mod._db = Database(":memory:")
    db_mod._db.init_db()
    yield db_mod._db.get_connection()
    db_mod._db.close()
    db_mod._db = None


# ── record: best-effort ──────────────────────────────────────────────


def test_record_inserts_one_row(conn):
    record(
        "doc-1",
        scope="full",
        issue_count=5,
        spec_id="spec-x",
        model="openai:gpt-4o-mini",
        summary={"error_count": 0, "warning_count": 3, "info_count": 2},
        duration_ms=1200,
        prompt_tokens=800,
        completion_tokens=200,
        conn=conn,
    )
    row = conn.execute(
        "SELECT doc_id, spec_id, model, scope, issue_count, summary, "
        "duration_ms, prompt_tokens, completion_tokens FROM office_ai_reviews "
        "WHERE doc_id = ?",
        ("doc-1",),
    ).fetchone()
    assert row is not None
    assert row["doc_id"] == "doc-1"
    assert row["spec_id"] == "spec-x"
    assert row["model"] == "openai:gpt-4o-mini"
    assert row["scope"] == "full"
    assert row["issue_count"] == 5
    assert json.loads(row["summary"])["warning_count"] == 3
    assert row["duration_ms"] == 1200


def test_record_without_summary_leaves_column_null(conn):
    record("doc-1", scope="full", issue_count=0, conn=conn)
    row = conn.execute(
        "SELECT summary FROM office_ai_reviews WHERE doc_id = ?", ("doc-1",)
    ).fetchone()
    assert row["summary"] is None


def test_record_never_raises_on_closed_connection():
    """A closed connection would normally raise — record must swallow."""
    closed_conn = sqlite3.connect(":memory:")
    closed_conn.close()
    # Should not raise.
    record(
        "doc-1",
        scope="full",
        issue_count=1,
        conn=closed_conn,
    )


def test_record_never_raises_on_missing_table():
    """An un-migrated DB (no table) must not break the caller."""
    conn = sqlite3.connect(":memory:")
    try:
        record(
            "doc-1",
            scope="full",
            issue_count=1,
            conn=conn,
        )
    finally:
        conn.close()


def test_record_uses_global_connection_when_none_passed(conn):
    # Pass conn=None → record resolves get_database() internally.
    record("doc-2", scope="full", issue_count=2)
    count = conn.execute(
        "SELECT COUNT(*) FROM office_ai_reviews WHERE doc_id = ?", ("doc-2",)
    ).fetchone()[0]
    assert count == 1


# ── list_for_document ────────────────────────────────────────────────


def _seed(conn, *, doc_id, created_at, issue_count=1, summary=None):
    summary_json = json.dumps(summary) if summary is not None else None
    conn.execute(
        "INSERT INTO office_ai_reviews "
        "(doc_id, spec_id, model, scope, issue_count, summary, "
        "duration_ms, prompt_tokens, completion_tokens, created_at) "
        "VALUES (?, NULL, NULL, 'full', ?, ?, 100, NULL, NULL, ?)",
        (doc_id, issue_count, summary_json, created_at),
    )
    conn.commit()


def test_list_newest_first(conn):
    _seed(conn, doc_id="doc-1", created_at=1000)
    _seed(conn, doc_id="doc-1", created_at=3000)
    _seed(conn, doc_id="doc-1", created_at=2000)
    rows = list_for_document(conn, "doc-1")
    assert [r["created_at"] for r in rows] == [3000, 2000, 1000]


def test_list_isolates_by_doc_id(conn):
    _seed(conn, doc_id="doc-1", created_at=1000)
    _seed(conn, doc_id="doc-2", created_at=2000)
    rows = list_for_document(conn, "doc-1")
    assert len(rows) == 1
    assert rows[0]["doc_id"] == "doc-1"


def test_list_respects_limit(conn):
    for i in range(5):
        _seed(conn, doc_id="doc-1", created_at=1000 + i)
    rows = list_for_document(conn, "doc-1", limit=2)
    assert len(rows) == 2
    assert rows[0]["created_at"] == 1004
    assert rows[1]["created_at"] == 1003


def test_list_deserializes_summary(conn):
    _seed(
        conn,
        doc_id="doc-1",
        created_at=1000,
        summary={"error_count": 0, "warning_count": 5},
    )
    rows = list_for_document(conn, "doc-1")
    assert rows[0]["summary"] == {"error_count": 0, "warning_count": 5}


def test_list_treats_unparseable_summary_as_none(conn):
    conn.execute(
        "INSERT INTO office_ai_reviews "
        "(doc_id, spec_id, model, scope, issue_count, summary, "
        "duration_ms, prompt_tokens, completion_tokens, created_at) "
        "VALUES (?, NULL, NULL, 'full', 1, 'not-json', 0, NULL, NULL, 1000)",
        ("doc-1",),
    )
    conn.commit()
    rows = list_for_document(conn, "doc-1")
    assert rows[0]["summary"] is None


def test_list_returns_empty_for_unknown_doc(conn):
    assert list_for_document(conn, "no-such") == []
