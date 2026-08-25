"""Unit tests for SessionSummary model + persistence (批次三 step 3).

Contract (spec 2026-08-23-win7-parity-platform-fixes-design.md §4.3):

    SessionSummary {
      id: string
      session_id: string
      source_turn_id: string | null
      content: string
      created_at_ms: integer
      updated_at_ms: integer
      status: "pending" | "ready" | "failed"
    }

Failed summaries MUST also carry a diagnostic ``error_message`` (spec §4.3 step 4)
so callers can distinguish "LLM genuinely returned nothing" from "summary
generation crashed" without pretending failures are facts.
"""

from __future__ import annotations

import time

import pytest

from backend.data.database import Database
from backend.memory.summary import (
    FAILED,
    PENDING,
    READY,
    SessionSummary,
    SessionSummaryStore,
    SummaryStatusError,
    list_summaries_for_session,
)
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit


@pytest.fixture()
def store(tmp_db_path: str) -> SessionSummaryStore:
    db = Database(db_path=tmp_db_path)
    db.init_db()
    # FK requires sessions row before inserting session_summaries — create
    # every session id the tests below reference.
    for sid in (
        "session-1", "session-2", "session-3", "session-4",
        "session-5", "session-6",
        "session-A", "session-B", "session-X", "session-Y",
        "sZ", "sQ", "s1", "s2", "sx",
    ):
        ensure_session(db, sid)
    return SessionSummaryStore(db)


# ──────────────────────────────────────────────────────────────────────
# Module surface
# ──────────────────────────────────────────────────────────────────────


def test_status_constants_match_spec():
    assert PENDING == "pending"
    assert READY == "ready"
    assert FAILED == "failed"


def test_module_exposes_store_and_query_helper():
    """Public surface the rest of the codebase relies on:
    - SessionSummary dataclass (typed row representation)
    - SessionSummaryStore (CRUD)
    - list_summaries_for_session (read API used by retrieval + Memory UI)
    """
    import backend.memory.summary as summary_mod

    assert hasattr(summary_mod, "SessionSummary")
    assert hasattr(summary_mod, "SessionSummaryStore")
    assert hasattr(summary_mod, "list_summaries_for_session")


def test_summarystatuserror_is_subclass_of_value_error():
    """Status validation failures surface as ``ValueError`` so callers
    can let invalid input bubble through the existing error envelope
    without a new try/except chain.
    """
    assert issubclass(SummaryStatusError, ValueError)


# ── Persistence: create + read ────────────────────────────────────────


def test_create_pending_summary(store: SessionSummaryStore) -> None:
    summary = store.create(
        session_id="session-1",
        content="",
        status=PENDING,
        source_turn_id="turn-42",
    )

    assert isinstance(summary, SessionSummary)
    assert summary.session_id == "session-1"
    assert summary.source_turn_id == "turn-42"
    assert summary.content == ""
    assert summary.status == PENDING
    assert summary.error_message is None
    assert summary.created_at_ms > 0
    assert summary.updated_at_ms == summary.created_at_ms
    assert summary.id  # non-empty id assigned


def test_create_rejects_invalid_status(store: SessionSummaryStore) -> None:
    with pytest.raises(SummaryStatusError):
        store.create(session_id="sx", content="", status="bogus")


def test_get_by_id_roundtrip(store: SessionSummaryStore) -> None:
    created = store.create(
        session_id="session-2",
        content="Some compressed facts.",
        status=READY,
        source_turn_id="turn-7",
    )

    fetched = store.get_by_id(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.session_id == "session-2"
    assert fetched.content == "Some compressed facts."
    assert fetched.status == READY
    assert fetched.source_turn_id == "turn-7"


def test_get_by_id_returns_none_when_missing(store: SessionSummaryStore) -> None:
    assert store.get_by_id("nope-not-here") is None


def test_failed_summary_persists_error_message(store: SessionSummaryStore) -> None:
    """Step 4: failed summaries MUST retain their diagnostic error so
    retrieval callers can surface a structured failure (no silent
    truth-pretending).
    """
    created = store.create(
        session_id="session-3",
        content="",
        status=FAILED,
        source_turn_id="turn-9",
        error_message="LLM timeout after 30s",
    )

    fetched = store.get_by_id(created.id)
    assert fetched is not None
    assert fetched.status == FAILED
    assert fetched.error_message == "LLM timeout after 30s"


def test_update_content_marks_ready(store: SessionSummaryStore) -> None:
    """The generation hook creates a PENDING row, then promotes to READY
    after the LLM returns; this round-trip exercises that path.
    """
    pending = store.create(session_id="session-4", content="", status=PENDING)
    time.sleep(0.005)  # ensure updated_at_ms advances

    ready = store.update(
        pending_id=pending.id,
        content="User asked about office round-trip.",
        status=READY,
    )

    assert ready.status == READY
    assert ready.content == "User asked about office round-trip."
    assert ready.error_message is None
    assert ready.updated_at_ms >= pending.created_at_ms


def test_update_failure_preserves_diagnostic(store: SessionSummaryStore) -> None:
    pending = store.create(session_id="session-5", content="", status=PENDING)

    failed = store.update(
        pending_id=pending.id,
        content="",
        status=FAILED,
        error_message="JSON parse error on LLM response",
    )

    assert failed.status == FAILED
    assert failed.error_message == "JSON parse error on LLM response"
    assert failed.content == ""


def test_update_rejects_invalid_status(store: SessionSummaryStore) -> None:
    pending = store.create(session_id="session-6", content="", status=PENDING)
    with pytest.raises(SummaryStatusError):
        store.update(pending_id=pending.id, content="x", status="bogus")


def test_update_returns_none_when_pending_row_missing(store: SessionSummaryStore) -> None:
    assert store.update(pending_id="nope", content="x", status=READY) is None


# ──────────────────────────────────────────────────────────────────────
# Query: by session
# ──────────────────────────────────────────────────────────────────────


def test_list_summaries_for_session_isolation(store: SessionSummaryStore) -> None:
    """Step 5: different sessions MUST NOT cross-inject summaries.
    Listing summaries for ``session-A`` returns only that session's
    rows, never ``session-B``'s.
    """
    store.create(session_id="session-A", content="a-1", status=READY)
    store.create(session_id="session-A", content="a-2", status=READY)
    store.create(session_id="session-B", content="b-1", status=READY)

    a_summaries = list_summaries_for_session(store.db, "session-A")
    assert {s.content for s in a_summaries} == {"a-1", "a-2"}
    assert all(s.session_id == "session-A" for s in a_summaries)


def test_list_summaries_for_session_returns_newest_first(
    store: SessionSummaryStore,
) -> None:
    a_first = store.create(session_id="session-X", content="first", status=READY)
    time.sleep(0.005)
    a_second = store.create(session_id="session-X", content="second", status=READY)

    rows = list_summaries_for_session(store.db, "session-X")
    assert len(rows) == 2
    # Newest first.
    assert rows[0].created_at_ms >= rows[1].created_at_ms
    assert rows[0].id == a_second.id
    assert rows[1].id == a_first.id


def test_list_summaries_for_session_limit(store: SessionSummaryStore) -> None:
    for i in range(5):
        store.create(session_id="session-Y", content=f"c-{i}", status=READY)

    rows = list_summaries_for_session(store.db, "session-Y", limit=3)
    assert len(rows) == 3


def test_list_summaries_empty_when_session_unknown(store: SessionSummaryStore) -> None:
    assert list_summaries_for_session(store.db, "never-existed") == []


# ──────────────────────────────────────────────────────────────────────
# latest-summary accessor (used by retrieval priority)
# ──────────────────────────────────────────────────────────────────────


def test_get_latest_ready_summary(store: SessionSummaryStore) -> None:
    """Retrieval priority (step 5) needs the most recent READY summary
    for the bound session. ``get_latest_ready`` returns that row, or
    None when nothing is ready yet (caller falls back to working +
    episodic).
    """
    failed = store.create(session_id="sZ", content="", status=FAILED, error_message="x")
    time.sleep(0.005)
    store.create(session_id="sZ", content="ready content", status=READY)
    time.sleep(0.005)
    newer_ready = store.create(
        session_id="sZ", content="newer ready content", status=READY
    )

    latest = store.get_latest_ready("sZ")
    assert latest is not None
    assert latest.id == newer_ready.id
    assert latest.content == "newer ready content"
    # Sanity: failed row never becomes "latest" even if it's chronologically newer.
    assert latest.id != failed.id


def test_get_latest_ready_returns_none_when_no_ready(
    store: SessionSummaryStore,
) -> None:
    store.create(session_id="sQ", content="", status=PENDING)
    store.create(session_id="sQ", content="", status=FAILED, error_message="x")
    assert store.get_latest_ready("sQ") is None


def test_get_latest_ready_session_isolation(store: SessionSummaryStore) -> None:
    """Different sessions MUST NOT cross-inject summaries (step 5).
    """
    store.create(session_id="s1", content="only for s1", status=READY)
    store.create(session_id="s2", content="only for s2", status=READY)

    s1_latest = store.get_latest_ready("s1")
    s2_latest = store.get_latest_ready("s2")
    assert s1_latest is not None
    assert s1_latest.content == "only for s1"
    assert s2_latest is not None
    assert s2_latest.content == "only for s2"
    # Each session's latest is its own row.
    assert s1_latest.session_id == "s1"
    assert s2_latest.session_id == "s2"


# ──────────────────────────────────────────────────────────────────────
# Schema migration: legacy init_db MUST create session_summaries
# ──────────────────────────────────────────────────────────────────────


def test_init_db_creates_session_summaries_table(tmp_db_path: str) -> None:
    """Regression guard: any code path that builds the schema (including
    legacy DBs upgrading in place) must create ``session_summaries``
    with all the columns the spec mandates.
    """
    db = Database(db_path=tmp_db_path)
    db.init_db()

    cursor = db.get_connection().cursor()
    rows = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='session_summaries'"
    ).fetchall()
    assert rows, "session_summaries table must be created by init_db()"

    cols = {
        row["name"]
        for row in cursor.execute("PRAGMA table_info(session_summaries)").fetchall()
    }
    expected = {
        "id",
        "session_id",
        "source_turn_id",
        "content",
        "created_at_ms",
        "updated_at_ms",
        "status",
        "error_message",
    }
    assert expected.issubset(cols), f"missing columns: {expected - cols}"


def test_init_db_creates_session_summaries_index(tmp_db_path: str) -> None:
    """The retrieval list-by-session query hits the (session_id, created_at_ms)
    path on every chat turn; index is mandatory, not optional.
    """
    db = Database(db_path=tmp_db_path)
    db.init_db()

    cursor = db.get_connection().cursor()
    indexes = {
        row["name"]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='session_summaries'"
        ).fetchall()
    }
    assert any("session_summaries" in name for name in indexes), (
        f"missing index on session_summaries (found: {indexes})"
    )
