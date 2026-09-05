"""Integration tests for ReviewQueue + ReviewService + SkillDraftStore pipeline.

Tests the complete flow from event enqueue to draft creation.
"""
import contextlib
import os
import sqlite3
import tempfile
from unittest.mock import AsyncMock, Mock

import pytest

from backend.ports.llm import AssistantTurn
from backend.skills.draft_store import SkillDraftStore
from backend.skills.review_queue import ReviewQueue
from backend.skills.review_service import ReviewService


@pytest.fixture()
def temp_db():
    """Create a temporary database with required tables."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Create required tables
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS review_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_type TEXT NOT NULL,
                session_id TEXT NOT NULL,
                context TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                processed_at INTEGER,
                error_message TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_drafts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                when_to_use TEXT NOT NULL,
                content TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                source_session_id TEXT NOT NULL,
                source_context TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                reviewed_at INTEGER,
                reviewed_by_user_id TEXT
            )
            """
        )

    yield db_path

    with contextlib.suppress(OSError):
        os.unlink(db_path)


@pytest.fixture()
def mock_llm_provider():
    """Mock LLM provider that returns a valid skill draft JSON."""
    provider = Mock()

    # Create an async mock for complete()
    async def mock_complete(model, messages):
        return AssistantTurn(
            text='{"name": "test-skill", "description": "A test skill", '
            '"when_to_use": "Use this skill whenever repeated testing steps need consistent validation", '
            '"content": "# Test Skill\\n\\nTest content"}'
        )

    provider.complete = mock_complete
    return provider


def test_queue_processes_event_and_creates_draft(temp_db, mock_llm_provider):
    """Test that ReviewQueue processes an event and creates a skill draft."""
    # Setup
    review_service = ReviewService(mock_llm_provider)
    draft_store = SkillDraftStore(temp_db)

    queue = ReviewQueue(temp_db)
    queue.review_service = review_service
    queue.draft_store = draft_store

    # Enqueue an event
    queue.enqueue(
        trigger_type="complex_turn",
        session_id="session_1",
        context={"tool_calls": [{"tool": "read", "args": {"path": "/a"}}]},
    )

    # Dequeue and process
    event = queue._dequeue_next()
    assert event is not None
    assert event.trigger_type == "complex_turn"

    queue._process_event(event)
    queue._mark_done(event.id)

    # Verify draft was created
    drafts = draft_store.list(status="pending")
    assert len(drafts) == 1
    assert drafts[0].name == "test-skill"
    assert drafts[0].trigger_type == "complex_turn"
    assert drafts[0].source_session_id == "session_1"


def test_queue_handles_missing_services_gracefully(temp_db):
    """Test that _process_event handles missing review_service or draft_store."""
    queue = ReviewQueue(temp_db)

    # Enqueue an event
    queue.enqueue(
        trigger_type="complex_turn",
        session_id="session_1",
        context={"tool_calls": []},
    )

    # Dequeue
    event = queue._dequeue_next()
    assert event is not None

    # Process without services configured - should log error but not crash
    queue._process_event(event)

    # Event should still be markable as done (no exception raised)
    queue._mark_done(event.id)


def test_queue_handles_llm_error(temp_db):
    """Test that _process_event handles LLM errors and propagates them."""
    # Setup mock that raises an error
    provider = Mock()

    async def mock_complete(model, messages):
        raise RuntimeError("LLM API error")

    provider.complete = mock_complete

    review_service = ReviewService(provider)
    draft_store = SkillDraftStore(temp_db)

    queue = ReviewQueue(temp_db)
    queue.review_service = review_service
    queue.draft_store = draft_store

    # Enqueue
    queue.enqueue(
        trigger_type="complex_turn",
        session_id="session_1",
        context={},
    )

    # Dequeue and process - should raise exception
    event = queue._dequeue_next()
    assert event is not None

    with pytest.raises(RuntimeError, match="LLM API error"):
        queue._process_event(event)

    # No draft should be created
    drafts = draft_store.list(status="pending")
    assert len(drafts) == 0


def test_queue_handles_db_error_on_insert(temp_db, mock_llm_provider):
    """Test that _process_event handles database errors during insert."""
    review_service = ReviewService(mock_llm_provider)

    # Create a draft_store with invalid db_path to force error
    draft_store = SkillDraftStore("/nonexistent/path/db.sqlite")

    queue = ReviewQueue(temp_db)
    queue.review_service = review_service
    queue.draft_store = draft_store

    # Enqueue
    queue.enqueue(
        trigger_type="complex_turn",
        session_id="session_1",
        context={},
    )

    # Dequeue and process - should raise exception
    event = queue._dequeue_next()
    assert event is not None

    with pytest.raises(sqlite3.OperationalError, match="unable to open"):
        queue._process_event(event)


def test_worker_loop_processes_events(temp_db, mock_llm_provider):
    """Test that the worker loop processes events end-to-end."""
    import time

    review_service = ReviewService(mock_llm_provider)
    draft_store = SkillDraftStore(temp_db)

    queue = ReviewQueue(temp_db)
    queue.review_service = review_service
    queue.draft_store = draft_store

    # Start worker
    queue.start()

    try:
        # Enqueue an event
        queue.enqueue(
            trigger_type="complex_turn",
            session_id="session_1",
            context={},
        )

        # Wait for processing (up to 5 seconds)
        for _ in range(50):
            time.sleep(0.1)
            drafts = draft_store.list(status="pending")
            if len(drafts) > 0:
                break

        # Verify draft was created
        drafts = draft_store.list(status="pending")
        assert len(drafts) == 1
        assert drafts[0].name == "test-skill"

        # Verify event was marked done
        with sqlite3.connect(temp_db) as conn:
            cursor = conn.execute(
                "SELECT status FROM review_events "
                "WHERE trigger_type = 'complex_turn'"
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == "done"

    finally:
        queue.stop()


# ------------------------------------------------------------------ #
# fix/security-perf-quickwins §1.3a d (2026-08-09):
# explicit_learn worker should load real conversation history from
# MessageRepository instead of passing the empty messages=[] placeholder
# that the route enqueues.
# ------------------------------------------------------------------ #


def test_explicit_learn_worker_loads_messages_from_db(temp_db, mock_llm_provider):
    """explicit_learn trigger: worker replaces messages=[] with rows loaded from
    MessageRepository.get_by_session(session_id).

    Verifies the LLM prompt sees the loaded messages, not the empty list.
    """
    from unittest.mock import patch

    review_service = ReviewService(mock_llm_provider)
    draft_store = SkillDraftStore(temp_db)

    queue = ReviewQueue(temp_db)
    queue.review_service = review_service
    queue.draft_store = draft_store

    # Replace the fixture's plain-async-function ``complete`` with an
    # AsyncMock so we can assert on the call (the fixture intentionally uses
    # a real function to avoid coupling other tests to Mock semantics).
    mock_llm_provider.complete = AsyncMock(
        return_value=AssistantTurn(
            text='{"name": "test-skill", "description": "A test skill", '
            '"when_to_use": "Use this skill whenever repeated testing steps need consistent validation", '
            '"content": "# Test Skill\\n\\nTest content"}'
        )
    )

    # Fake MessageRepository — return two rows when the worker calls
    # get_by_session("session_explicit_learn").
    fake_messages = [
        Mock(role="user", content="Hello, please review this code"),
        Mock(role="assistant", content="Sure, I see a Python file with bugs."),
    ]
    mock_message_repo = Mock()
    mock_message_repo.get_by_session.return_value = fake_messages

    # Enqueue an explicit_learn event with the empty messages placeholder
    # (matches what /learn actually sends today).
    queue.enqueue(
        trigger_type="explicit_learn",
        session_id="session_explicit_learn",
        context={"messages": [], "user_prompt": "summarize"},
    )

    event = queue._dequeue_next()
    assert event is not None

    with patch(
        "backend.data.session_repo.MessageRepository",
        return_value=mock_message_repo,
    ):
        queue._process_event(event)

    # Worker must have asked MessageRepository for this session's history.
    mock_message_repo.get_by_session.assert_called_once_with(
        "session_explicit_learn"
    )

    # Capture what the LLM received. ReviewService.generate_draft() dumps
    # the context dict as JSON into the prompt template, so check that the
    # prompt string contains the loaded message content — not the empty list.
    mock_llm_provider.complete.assert_called_once()
    call_args = mock_llm_provider.complete.call_args
    sent_messages = call_args.kwargs.get("messages") or call_args.args[1]
    prompt_content = sent_messages[1].content  # user-role prompt with template
    assert "Hello, please review this code" in prompt_content
    assert "Sure, I see a Python file with bugs." in prompt_content
    # The empty placeholder must NOT appear as a literal empty array in
    # the prompt (otherwise the worker silently skipped loading).
    assert '"messages": []' not in prompt_content


def test_complex_turn_does_not_load_messages(temp_db, mock_llm_provider):
    """complex_turn trigger: worker must NOT load messages — only tool-call
    metadata is needed for skill extraction."""
    from unittest.mock import patch

    review_service = ReviewService(mock_llm_provider)
    draft_store = SkillDraftStore(temp_db)

    queue = ReviewQueue(temp_db)
    queue.review_service = review_service
    queue.draft_store = draft_store

    mock_message_repo = Mock()
    mock_message_repo.get_by_session.return_value = []  # would be a bug if called

    queue.enqueue(
        trigger_type="complex_turn",
        session_id="session_complex",
        context={
            "tool_calls": [{"name": "read", "args": {"path": "/x"}}],
            "tool_call_count": 1,
            "threshold": 3,
        },
    )

    event = queue._dequeue_next()
    assert event is not None

    with patch(
        "backend.data.session_repo.MessageRepository",
        return_value=mock_message_repo,
    ):
        queue._process_event(event)

    # Must NOT touch MessageRepository for complex_turn — that would waste
    # DB I/O and token budget (the LLM only needs tool-call metadata here).
    mock_message_repo.get_by_session.assert_not_called()


def test_explicit_learn_load_failure_is_swallowed(temp_db, mock_llm_provider):
    """explicit_learn: if MessageRepository raises, worker must still produce
    a draft (best-effort: empty context is better than no draft at all)."""
    from unittest.mock import patch

    review_service = ReviewService(mock_llm_provider)
    draft_store = SkillDraftStore(temp_db)

    queue = ReviewQueue(temp_db)
    queue.review_service = review_service
    queue.draft_store = draft_store

    # Ensure the LLM still produces a draft even when DB load fails.
    mock_llm_provider.complete = AsyncMock(
        return_value=AssistantTurn(
            text='{"name": "test-skill", "description": "A test skill", '
            '"when_to_use": "Use this skill whenever repeated testing steps need consistent validation", '
            '"content": "# Test Skill\\n\\nTest content"}'
        )
    )

    # MessageRepository constructor itself raises — simulates a DB outage.
    with patch(
        "backend.data.session_repo.MessageRepository",
        side_effect=RuntimeError("DB down"),
    ):
        queue.enqueue(
            trigger_type="explicit_learn",
            session_id="session_db_down",
            context={"messages": [], "user_prompt": "summarize"},
        )

        event = queue._dequeue_next()
        assert event is not None

        # Must NOT raise — the worker degrades gracefully.
        queue._process_event(event)

    # Draft was still produced (LLM ran with empty context).
    drafts = draft_store.list(status="pending")
    assert len(drafts) == 1
    assert drafts[0].name == "test-skill"


# --- PR-C §5.2: production-path wiring via bootstrap_review_collaborators
#
# Before this fix, ReviewQueue.review_service and .draft_store were left as
# None in production (only test_review_queue_integration.py set them
# manually). The bootstrap helper injects them at lifespan startup so that
# `complex_turn` events enqueued in main.py actually produce drafts without
# requiring test-only fixtures.
def test_bootstrap_review_collaborators_wires_singleton(
    temp_db, mock_llm_provider, monkeypatch
):
    """bootstrap_review_collaborators() injects collaborators into the
    global get_review_queue() singleton. Without this, _process_event
    in production degrades to a no-op (logs "ReviewService not configured").
    """
    from backend.skills import review_queue as rq_module

    monkeypatch.setattr(
        "backend.data.database.get_database",
        lambda: type("_FakeDB", (), {"db_path": temp_db})(),
    )

    # Reset singleton so it picks up the patched get_database + temp db.
    rq_module.reset_review_queue()

    from backend.skills.review_bootstrap import bootstrap_review_collaborators

    # Inject mocks to avoid pulling a real LLMClient at import time
    review_service = ReviewService(mock_llm_provider)
    draft_store = SkillDraftStore(temp_db)

    bootstrap_review_collaborators(
        queue=rq_module.get_review_queue(),
        review_service=review_service,
        draft_store=draft_store,
    )

    queue = rq_module.get_review_queue()
    assert queue.review_service is review_service
    assert queue.draft_store is draft_store

    # Idempotency: re-calling with same collaborators is a no-op (no warning)
    bootstrap_review_collaborators(
        queue=queue,
        review_service=review_service,
        draft_store=draft_store,
    )
    assert queue.review_service is review_service
    assert queue.draft_store is draft_store

    rq_module.reset_review_queue()
