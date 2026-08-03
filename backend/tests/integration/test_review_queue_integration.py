"""Integration tests for ReviewQueue + ReviewService + SkillDraftStore pipeline.

Tests the complete flow from event enqueue to draft creation.
"""
import contextlib
import os
import sqlite3
import tempfile
from unittest.mock import Mock

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
            '"when_to_use": "When testing", '
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
