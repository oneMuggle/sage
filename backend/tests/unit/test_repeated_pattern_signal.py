"""Unit tests for backend.skills.repeated_pattern_signal.

Covers:
- _serialize_tool_calls: extracting tool_calls from Message-like objects
- detect_and_enqueue: below/above threshold behavior, context shape, exceptions
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from backend.skills.repeated_pattern_signal import (
    DEFAULT_REPEATED_PATTERN_THRESHOLD,
    _serialize_tool_calls,
    detect_and_enqueue,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _msg_with_tool_calls(tool_calls: List[tuple]) -> SimpleNamespace:
    """Build a Message-like object with the given (name, args) tool_calls."""
    return SimpleNamespace(
        role="assistant",
        content="",
        tool_calls=[SimpleNamespace(name=name, args=args) for name, args in tool_calls],
    )


def _msg_without_tool_calls() -> SimpleNamespace:
    return SimpleNamespace(role="assistant", content="hi", tool_calls=None)


# ---------------------------------------------------------------------------
# _serialize_tool_calls
# ---------------------------------------------------------------------------


class TestSerializeToolCalls:
    def test_extracts_all_tool_calls_across_messages(self):
        """Pull tool_calls from each message, in order."""
        m1 = _msg_with_tool_calls([("read", {"path": "/a"})])
        m2 = _msg_with_tool_calls([("edit", {"path": "/b"}), ("read", {"path": "/c"})])

        result = _serialize_tool_calls([m1, m2])

        assert result == [
            {"tool": "read", "args": {"path": "/a"}},
            {"tool": "edit", "args": {"path": "/b"}},
            {"tool": "read", "args": {"path": "/c"}},
        ]

    def test_skips_messages_without_tool_calls(self):
        """Messages with tool_calls=None or [] are skipped silently."""
        msgs = [
            _msg_with_tool_calls([("read", {"path": "/a"})]),
            _msg_without_tool_calls(),
            _msg_with_tool_calls([]),  # empty list
            _msg_with_tool_calls([("read", {"path": "/b"})]),
        ]
        result = _serialize_tool_calls(msgs)
        assert len(result) == 2
        assert result[0]["tool"] == "read"
        assert result[1]["args"] == {"path": "/b"}

    def test_skips_tool_calls_missing_name(self):
        """ToolCall without .name is skipped (best-effort)."""
        bad = SimpleNamespace(name=None, args={"x": 1})
        good = SimpleNamespace(name="read", args={"path": "/a"})
        msg = SimpleNamespace(role="assistant", tool_calls=[bad, good])

        result = _serialize_tool_calls([msg])

        assert len(result) == 1
        assert result[0]["tool"] == "read"

    def test_non_dict_args_coerced_to_empty(self):
        """ToolCall with non-dict args is recorded with args={}."""
        tc = SimpleNamespace(name="weird", args="not-a-dict")
        msg = SimpleNamespace(role="assistant", tool_calls=[tc])

        result = _serialize_tool_calls([msg])

        assert result == [{"tool": "weird", "args": {}}]

    def test_empty_input(self):
        """Empty input → empty list (no exception)."""
        assert _serialize_tool_calls([]) == []


# ---------------------------------------------------------------------------
# detect_and_enqueue — happy path
# ---------------------------------------------------------------------------


class TestDetectAndEnqueue:
    """Tests for detect_and_enqueue covering all thresholds and shapes."""

    @patch("backend.skills.review_queue.get_review_queue")
    def test_below_threshold_returns_none_no_enqueue(self, mock_get_queue):
        """Fewer than 3 tool calls → no enqueue, returns None."""
        mock_queue = MagicMock()
        mock_get_queue.return_value = mock_queue

        msgs = [
            _msg_with_tool_calls([("read", {"path": "/a"})]),
            _msg_with_tool_calls([("read", {"path": "/b"})]),
        ]

        result = detect_and_enqueue("s1", msgs)

        assert result is None
        mock_queue.enqueue.assert_not_called()

    @patch("backend.skills.review_queue.get_review_queue")
    def test_at_threshold_enqueues_with_correct_context(self, mock_get_queue):
        """Exactly 3 same-signature calls → enqueue with expected context shape."""
        mock_queue = MagicMock()
        mock_get_queue.return_value = mock_queue

        msgs = [
            _msg_with_tool_calls([("read", {"path": "/a"})]),
            _msg_with_tool_calls([("edit", {"path": "/b"})]),
            _msg_with_tool_calls([("read", {"path": "/c"})]),  # 2nd read
            _msg_with_tool_calls([("read", {"path": "/d"})]),  # 3rd read
        ]

        result = detect_and_enqueue("s1", msgs)

        assert result == "read:path"
        mock_queue.enqueue.assert_called_once()
        call = mock_queue.enqueue.call_args
        assert call.kwargs["trigger_type"] == "repeated_pattern"
        assert call.kwargs["session_id"] == "s1"
        ctx = call.kwargs["context"]
        assert ctx["signature"] == "read:path"
        assert ctx["count"] == 3
        assert ctx["threshold"] == DEFAULT_REPEATED_PATTERN_THRESHOLD
        assert len(ctx["sample_calls"]) == 3
        # Sample calls preserve original dict shape
        assert all("tool" in sc and "args" in sc for sc in ctx["sample_calls"])

    @patch("backend.skills.review_queue.get_review_queue")
    def test_multiple_patterns_returns_highest_count(self, mock_get_queue):
        """When two patterns both ≥ threshold, the most frequent wins."""
        mock_queue = MagicMock()
        mock_get_queue.return_value = mock_queue

        msgs = [
            _msg_with_tool_calls([("read", {"path": "/a"})]),
            _msg_with_tool_calls([("edit", {"path": "/b"})]),
            _msg_with_tool_calls([("read", {"path": "/c"})]),
            _msg_with_tool_calls([("edit", {"path": "/d"})]),
            _msg_with_tool_calls([("read", {"path": "/e"})]),  # 3 reads
            _msg_with_tool_calls([("edit", {"path": "/f"})]),
            _msg_with_tool_calls([("edit", {"path": "/g"})]),  # 4 edits
        ]

        result = detect_and_enqueue("s1", msgs)

        assert result == "edit:path"
        ctx = mock_queue.enqueue.call_args.kwargs["context"]
        assert ctx["count"] == 4
        assert ctx["signature"] == "edit:path"

    @patch("backend.skills.review_queue.get_review_queue")
    def test_sample_calls_capped_at_max(self, mock_get_queue):
        """sample_calls in context is capped at 5 to bound prompt size."""
        mock_queue = MagicMock()
        mock_get_queue.return_value = mock_queue

        # 10 same-signature calls — sample_calls should have only 5
        msgs = [
            _msg_with_tool_calls([("read", {"path": f"/p{i}"})]) for i in range(10)
        ]

        result = detect_and_enqueue("s1", msgs)

        assert result == "read:path"
        ctx = mock_queue.enqueue.call_args.kwargs["context"]
        assert ctx["count"] == 10
        assert len(ctx["sample_calls"]) == 5

    @patch("backend.skills.review_queue.get_review_queue")
    def test_custom_threshold(self, mock_get_queue):
        """Custom threshold=2 triggers at 2 repetitions."""
        mock_queue = MagicMock()
        mock_get_queue.return_value = mock_queue

        msgs = [
            _msg_with_tool_calls([("read", {"path": "/a"})]),
            _msg_with_tool_calls([("edit", {"path": "/b"})]),
            _msg_with_tool_calls([("read", {"path": "/c"})]),  # 2nd read
        ]

        result = detect_and_enqueue("s1", msgs, threshold=2)

        assert result == "read:path"
        ctx = mock_queue.enqueue.call_args.kwargs["context"]
        assert ctx["threshold"] == 2
        assert ctx["count"] == 2

    @patch("backend.skills.review_queue.get_review_queue")
    def test_span_attributes_set_when_span_provided(self, mock_get_queue):
        """When span is provided, set expected OTel attributes."""
        mock_queue = MagicMock()
        mock_get_queue.return_value = mock_queue

        msgs = [
            _msg_with_tool_calls([("read", {"path": "/a"})]),
            _msg_with_tool_calls([("read", {"path": "/b"})]),
            _msg_with_tool_calls([("read", {"path": "/c"})]),
        ]

        span = MagicMock()
        detect_and_enqueue("s1", msgs, span=span)

        span.set_attribute.assert_any_call("review.repeated_pattern_enqueued", True)
        span.set_attribute.assert_any_call(
            "review.repeated_pattern_signature", "read:path"
        )
        span.set_attribute.assert_any_call("review.repeated_pattern_count", 3)

    @patch("backend.skills.review_queue.get_review_queue")
    def test_span_attribute_failure_does_not_break(self, mock_get_queue):
        """If span.set_attribute raises, detect_and_enqueue still returns the signature."""
        mock_queue = MagicMock()
        mock_get_queue.return_value = mock_queue

        msgs = [
            _msg_with_tool_calls([("read", {"path": "/a"})]),
            _msg_with_tool_calls([("read", {"path": "/b"})]),
            _msg_with_tool_calls([("read", {"path": "/c"})]),
        ]

        span = MagicMock()
        span.set_attribute.side_effect = RuntimeError("otel broken")

        result = detect_and_enqueue("s1", msgs, span=span)
        assert result == "read:path"
        mock_queue.enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# detect_and_enqueue — exception / error resilience
# ---------------------------------------------------------------------------


class TestDetectAndEnqueueRobustness:
    """best-effort contract: any exception must be caught and swallowed."""

    @patch("backend.skills.review_queue.get_review_queue")
    def test_enqueue_failure_returns_none(self, mock_get_queue):
        """If review_queue.enqueue raises, return None (don't propagate)."""
        mock_queue = MagicMock()
        mock_queue.enqueue.side_effect = RuntimeError("db locked")
        mock_get_queue.return_value = mock_queue

        msgs = [
            _msg_with_tool_calls([("read", {"path": "/a"})]),
            _msg_with_tool_calls([("read", {"path": "/b"})]),
            _msg_with_tool_calls([("read", {"path": "/c"})]),
        ]

        result = detect_and_enqueue("s1", msgs)
        assert result is None

    @patch("backend.skills.review_queue.get_review_queue")
    def test_get_review_queue_failure_returns_none(self, mock_get_queue):
        """If get_review_queue itself raises, return None."""
        mock_get_queue.side_effect = RuntimeError("queue init failed")

        msgs = [
            _msg_with_tool_calls([("read", {"path": "/a"})]),
            _msg_with_tool_calls([("read", {"path": "/b"})]),
            _msg_with_tool_calls([("read", {"path": "/c"})]),
        ]

        result = detect_and_enqueue("s1", msgs)
        assert result is None

    def test_pattern_detector_failure_returns_none(self):
        """If PatternDetector raises (corrupted state), return None."""
        msgs = [
            _msg_with_tool_calls([("read", {"path": "/a"})]),
            _msg_with_tool_calls([("read", {"path": "/b"})]),
            _msg_with_tool_calls([("read", {"path": "/c"})]),
        ]

        with patch(
            "backend.skills.pattern_detector.PatternDetector.detect_repeated_pattern",
            side_effect=RuntimeError("detector broken"),
        ):
            result = detect_and_enqueue("s1", msgs)
            assert result is None


# ---------------------------------------------------------------------------
# ReviewQueue._has_existing_draft_for_pattern — end-to-end via real SQLite
# ---------------------------------------------------------------------------


class TestHasExistingDraftForPattern:
    """Tests the dedup helper introduced in ReviewQueue.

    Uses a shared ``tmp_db`` fixture so we can pass an explicit sqlite
    connection into the production code (``conn=`` parameter) without
    touching the global ``get_database()`` singleton.
    """

    @pytest.fixture()
    def tmp_db(self, tmp_path):
        """Bootstrap skill_drafts schema and return (db_path, conn)."""

        db_path = str(tmp_path / "dedup.db")
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    description TEXT,
                    when_to_use TEXT,
                    content TEXT,
                    trigger_type TEXT,
                    source_session_id TEXT,
                    source_context TEXT,
                    status TEXT,
                    created_at INTEGER
                )
                """
            )
            conn.commit()
        return db_path

    def _make_queue(self, db_path):
        from backend.skills.review_queue import ReviewQueue

        return ReviewQueue(db_path)

    def _insert_draft(self, db_path, session_id, signature, status):
        import json

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO skill_drafts "
                "(name, trigger_type, source_session_id, source_context, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"draft-{signature}",
                    "repeated_pattern",
                    session_id,
                    json.dumps({"signature": signature, "count": 3}),
                    status,
                    1_700_000_000_000,
                ),
            )
            conn.commit()

    def test_no_existing_draft_returns_false(self, tmp_db):
        q = self._make_queue(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            assert q._has_existing_draft_for_pattern(
                "s1", "read:path", conn=conn
            ) is False

    def test_pending_draft_exists_returns_true(self, tmp_db):
        self._insert_draft(tmp_db, "s1", "read:path", "pending")
        q = self._make_queue(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            assert q._has_existing_draft_for_pattern(
                "s1", "read:path", conn=conn
            ) is True

    def test_approved_draft_exists_returns_true(self, tmp_db):
        self._insert_draft(tmp_db, "s1", "read:path", "approved")
        q = self._make_queue(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            assert q._has_existing_draft_for_pattern(
                "s1", "read:path", conn=conn
            ) is True

    def test_rejected_draft_does_not_count(self, tmp_db):
        """Rejected drafts should NOT block re-generation."""
        self._insert_draft(tmp_db, "s1", "read:path", "rejected")
        q = self._make_queue(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            assert q._has_existing_draft_for_pattern(
                "s1", "read:path", conn=conn
            ) is False

    def test_different_session_returns_false(self, tmp_db):
        """Signature match but different session → not a duplicate."""
        self._insert_draft(tmp_db, "s_other", "read:path", "pending")
        q = self._make_queue(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            assert q._has_existing_draft_for_pattern(
                "s1", "read:path", conn=conn
            ) is False

    def test_different_signature_returns_false(self, tmp_db):
        """Same session but different signature → not a duplicate."""
        self._insert_draft(tmp_db, "s1", "read:path", "pending")
        q = self._make_queue(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            assert q._has_existing_draft_for_pattern(
                "s1", "edit:path", conn=conn
            ) is False

    def test_empty_inputs_return_false(self, tmp_db):
        """Defensive: empty session_id or signature → False (don't crash)."""
        q = self._make_queue(tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            assert q._has_existing_draft_for_pattern(
                "", "read:path", conn=conn
            ) is False
            assert q._has_existing_draft_for_pattern("s1", "", conn=conn) is False
