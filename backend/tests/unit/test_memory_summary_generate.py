"""Unit tests for the session-summary generation hook (批次三 step 4).

Spec §4.3 step 4:

    会话压缩或 turn 完成时生成摘要；摘要生成失败保留 ``failed`` 状态
    和可诊断错误，**不**伪装为普通事实。摘要持久化到专用
    ``session_summaries`` 表以避免与普通事实混淆。

Contract under test:

* :func:`backend.memory.summary.generate_summary` is the synchronous hook
  that turns the working-context messages into a single summary string.
* :func:`backend.memory.summary.persist_summary` takes the result and
  writes it to the dedicated table — READY on success, FAILED on error.
* On any exception, the row is **always** written with status="failed"
  + an error_message so callers can distinguish "no summary yet" from
  "summary generation crashed". The summary must NEVER be silently
  re-saved as a generic episodic fact (that would be a
  spec-§4.3-step-4 violation).
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from backend.data.database import Database
from backend.memory.summary import (
    FAILED,
    READY,
    SessionSummaryStore,
    generate_summary,
    persist_summary,
)
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture()
def store(tmp_db_path: str) -> SessionSummaryStore:
    db = Database(db_path=tmp_db_path)
    db.init_db()
    ensure_session(db, "sess-gen")
    return SessionSummaryStore(db)


def _llm_succeed(_msgs: List[Dict[str, str]], _temperature: float) -> str:
    """Stand-in LLM call: returns a canned summary string."""
    return "User asked about office round-trip; assistant explained create→list→read flow."


def _llm_timeout(_msgs: List[Dict[str, str]], _temperature: float) -> str:
    raise TimeoutError("LLM request timed out after 30s")


def _llm_garbage(_msgs: List[Dict[str, str]], _temperature: float) -> str:
    return ""  # LLM returned nothing usable


# ──────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────


def test_generate_summary_calls_llm_and_returns_string():
    """The generator wraps the callable and returns its result verbatim
    on success.
    """
    out = generate_summary(
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
        llm_call=_llm_succeed,
    )
    assert "office round-trip" in out


def test_persist_summary_marks_ready_on_success(store: SessionSummaryStore) -> None:
    """Happy path: summary content is generated, persisted with READY.
    """
    content = generate_summary(
        messages=[{"role": "user", "content": "hi"}],
        llm_call=_llm_succeed,
    )
    summary = persist_summary(
        store=store,
        session_id="sess-gen",
        source_turn_id="turn-1",
        content=content,
    )

    assert summary.status == READY
    assert summary.content == content
    assert summary.error_message is None
    assert summary.session_id == "sess-gen"


# ──────────────────────────────────────────────────────────────────────
# Failure path: spec §4.3 step 4 forbids silent fallback to episodic
# ──────────────────────────────────────────────────────────────────────


def test_generate_summary_raises_on_llm_error():
    """LLM exceptions propagate so the caller can route them to the
    failed-status branch (rather than catch-and-retry-into-episodic).
    """
    with pytest.raises(TimeoutError):
        generate_summary(
            messages=[{"role": "user", "content": "x"}],
            llm_call=_llm_timeout,
        )


def test_persist_summary_marks_failed_with_diagnostic(store: SessionSummaryStore) -> None:
    """Failed summaries MUST retain their diagnostic message; callers
    rely on this to surface "summary generation crashed" instead of
    pretending it's a regular fact.
    """
    summary = persist_summary(
        store=store,
        session_id="sess-gen",
        source_turn_id="turn-1",
        content="",
        status=FAILED,
        error_message="LLM timeout after 30s",
    )

    assert summary.status == FAILED
    assert summary.error_message == "LLM timeout after 30s"
    assert summary.content == ""

    # Round-trip from DB: diagnostic survives a write+read cycle.
    fetched = store.get_by_id(summary.id)
    assert fetched is not None
    assert fetched.status == FAILED
    assert fetched.error_message == "LLM timeout after 30s"


# ──────────────────────────────────────────────────────────────────────
# End-to-end: generate_and_persist covers the full hook
# ──────────────────────────────────────────────────────────────────────


def test_generate_and_persist_writes_ready_row(store: SessionSummaryStore) -> None:
    """The all-in-one hook :func:`generate_and_persist_summary` writes
    exactly one row: READY when the LLM succeeds.
    """
    from backend.memory.summary import generate_and_persist_summary

    summary = generate_and_persist_summary(
        store=store,
        session_id="sess-gen",
        messages=[
            {"role": "user", "content": "explain office"},
            {"role": "assistant", "content": "docx/pptx/xlsx"},
        ],
        llm_call=_llm_succeed,
        source_turn_id="turn-2",
    )

    assert summary.status == READY
    assert summary.session_id == "sess-gen"
    assert summary.source_turn_id == "turn-2"

    # Exactly one row in the table.
    rows = store.db.get_connection().execute(
        "SELECT count(*) AS c FROM session_summaries WHERE session_id = ?",
        ("sess-gen",),
    ).fetchone()
    assert rows["c"] == 1


def test_generate_and_persist_writes_failed_row_on_llm_error(
    store: SessionSummaryStore,
) -> None:
    """When the LLM raises, the hook MUST still write a FAILED row
    with the diagnostic message — never an empty READY row, never a
    fallback save to episodic memory.
    """
    from backend.memory.summary import generate_and_persist_summary

    summary = generate_and_persist_summary(
        store=store,
        session_id="sess-gen",
        messages=[{"role": "user", "content": "x"}],
        llm_call=_llm_timeout,
        source_turn_id="turn-3",
    )

    assert summary.status == FAILED
    assert "LLM request timed out" in (summary.error_message or "")

    # No READY row exists — failed rows do NOT silently masquerade.
    ready_rows = store.db.get_connection().execute(
        "SELECT count(*) AS c FROM session_summaries WHERE session_id = ? AND status = 'ready'",
        ("sess-gen",),
    ).fetchone()
    assert ready_rows["c"] == 0

    # No row in memories_episodic — failed summary must NEVER fall back
    # to "save as a generic fact" (spec §4.3 step 4 violation guard).
    episodic_rows = store.db.get_connection().execute(
        "SELECT count(*) AS c FROM memories_episodic WHERE session_id = ?",
        ("sess-gen",),
    ).fetchone()
    assert episodic_rows["c"] == 0


def test_generate_and_persist_writes_failed_row_on_garbage_output(
    store: SessionSummaryStore,
) -> None:
    """Even when the LLM doesn't crash but returns empty/garbage, the
    hook writes a FAILED row so the caller sees the failure.
    """
    from backend.memory.summary import generate_and_persist_summary

    summary = generate_and_persist_summary(
        store=store,
        session_id="sess-gen",
        messages=[{"role": "user", "content": "x"}],
        llm_call=_llm_garbage,
        source_turn_id="turn-4",
    )

    assert summary.status == FAILED
    assert summary.error_message is not None
    assert summary.content == ""


def test_generate_and_persist_never_writes_to_episodic(
    store: SessionSummaryStore,
) -> None:
    """Hard guard: the summary generation hook MUST NOT silently fall
    back to writing into ``memories_episodic``. A summary is a derived
    artifact; mixing it with ordinary facts would let downstream code
    surface it as a real memory (spec §4.3 step 4 violation).
    """
    from backend.memory.summary import generate_and_persist_summary

    generate_and_persist_summary(
        store=store,
        session_id="sess-gen",
        messages=[{"role": "user", "content": "hello"}],
        llm_call=_llm_succeed,
        source_turn_id="turn-5",
    )

    episodic_rows = store.db.get_connection().execute(
        "SELECT count(*) AS c FROM memories_episodic WHERE session_id = ?",
        ("sess-gen",),
    ).fetchone()
    assert episodic_rows["c"] == 0


def test_generate_and_persist_session_isolation(
    store: SessionSummaryStore,
) -> None:
    """Two different sessions MUST NOT share summary rows — every row
    carries the session_id from the caller.
    """
    from backend.memory.summary import generate_and_persist_summary

    ensure_session(store.db, "other-session")

    a = generate_and_persist_summary(
        store=store,
        session_id="sess-gen",
        messages=[{"role": "user", "content": "a"}],
        llm_call=_llm_succeed,
    )
    b = generate_and_persist_summary(
        store=store,
        session_id="other-session",
        messages=[{"role": "user", "content": "b"}],
        llm_call=_llm_succeed,
    )

    assert a.session_id == "sess-gen"
    assert b.session_id == "other-session"
    assert a.id != b.id
