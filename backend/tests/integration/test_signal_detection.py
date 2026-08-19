"""Integration tests for signal detection hooks in ChatService and SkillUsageStore.

Tests that complex turns (>=4 tool calls, no skill activation) and low skill
success rates (<60% after >=10 uses) trigger review event enqueue.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import sqlite3
import tempfile
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from backend.skills.review_queue import reset_review_queue
from backend.skills.usage import SkillUsageStore, reset_usage_store

# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture(autouse=True)
def _cleanup_singletons():
    """Reset global singletons after each test to avoid cross-test leakage."""
    yield
    reset_review_queue()
    reset_usage_store()


@pytest.fixture()
def temp_db_path():
    """Create a temporary SQLite DB with the skill_usage table."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_usage (
                name TEXT PRIMARY KEY,
                use_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                fail_count INTEGER NOT NULL DEFAULT 0,
                last_used_at INTEGER NOT NULL DEFAULT 0
            )
            """
        )
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

    yield db_path

    with contextlib.suppress(OSError):
        os.unlink(db_path)


# ------------------------------------------------------------------ #
# 1. Complex turn detection (ChatService)
# ------------------------------------------------------------------ #


class TestComplexTurnSignalDetection:
    """Complex turn (>=4 tool calls, no skill activation) enqueues review."""

    def test_complex_turn_triggers_review_enqueue(self):
        """When >=4 tool calls and no skill activation, enqueue complex_turn."""
        from backend.application.services.chat_service import ChatService
        from backend.domain.message import Message, Role, ToolCall

        mock_review_queue = Mock()

        # Build a mock ChatService with minimal wiring
        mock_llm = AsyncMock()
        mock_tools = MagicMock()
        mock_skills = MagicMock()
        mock_storage = AsyncMock()
        mock_metrics = MagicMock()
        mock_events = MagicMock()

        # LLM returns a Message with >= threshold tool calls
        tool_calls = [
            ToolCall(name="read", args={"path": "/a"}),
            ToolCall(name="edit", args={"path": "/b"}),
            ToolCall(name="read", args={"path": "/c"}),
            ToolCall(name="edit", args={"path": "/d"}),
        ]
        mock_llm.chat.return_value = Message(
            role=Role.ASSISTANT,
            content="Done",
            tool_calls=tool_calls,
        )

        # tools.list_tools returns empty list (no tool schemas needed)
        mock_tools.list_tools.return_value = []

        # Storage returns empty history
        mock_storage.get_messages.return_value = []

        with patch(
            "backend.skills.review_queue.get_review_queue",
            return_value=mock_review_queue,
        ):
            service = ChatService(
                llm=mock_llm,
                tools=mock_tools,
                skills=mock_skills,
                storage=mock_storage,
                metrics=mock_metrics,
                events=mock_events,
            )

            # Mock _execute_tool_calls to return False (no budget exceeded)
            with patch.object(
                service, "_execute_tool_calls", new_callable=AsyncMock
            ) as mock_exec:
                mock_exec.return_value = False

                asyncio.run(
                    service._run_turn_inner(
                        session_id="test-session",
                        user_message=Message(role=Role.USER, content="Do a complex task"),
                        span=MagicMock(),
                    )
                )

        # Verify review was enqueued
        mock_review_queue.enqueue.assert_called_once()
        call_kwargs = mock_review_queue.enqueue.call_args
        trigger_type = call_kwargs.kwargs.get(
            "trigger_type", call_kwargs.args[0] if call_kwargs.args else None
        )
        assert trigger_type == "complex_turn"

    def test_no_review_when_few_tool_calls(self):
        """When <4 tool calls, no review is enqueued."""
        from backend.application.services.chat_service import ChatService
        from backend.domain.message import Message, Role, ToolCall

        mock_review_queue = Mock()

        mock_llm = AsyncMock()
        mock_tools = MagicMock()
        mock_skills = MagicMock()
        mock_storage = AsyncMock()
        mock_metrics = MagicMock()
        mock_events = MagicMock()

        # Only 2 tool calls (below threshold)
        tool_calls = [
            ToolCall(name="read", args={"path": "/a"}),
            ToolCall(name="read", args={"path": "/b"}),
        ]
        mock_llm.chat.return_value = Message(
            role=Role.ASSISTANT,
            content="Done",
            tool_calls=tool_calls,
        )
        mock_tools.list_tools.return_value = []
        mock_storage.get_messages.return_value = []

        with patch(
            "backend.skills.review_queue.get_review_queue",
            return_value=mock_review_queue,
        ):
            service = ChatService(
                llm=mock_llm,
                tools=mock_tools,
                skills=mock_skills,
                storage=mock_storage,
                metrics=mock_metrics,
                events=mock_events,
            )

            with patch.object(
                service, "_execute_tool_calls", new_callable=AsyncMock
            ) as mock_exec:
                mock_exec.return_value = False

                asyncio.run(
                    service._run_turn_inner(
                        session_id="test-session",
                        user_message=Message(role=Role.USER, content="Simple task"),
                        span=MagicMock(),
                    )
                )

        # No review should be enqueued
        mock_review_queue.enqueue.assert_not_called()

    def test_no_review_when_skill_activated(self):
        """When skill activation block is present, no review even with >=4 calls."""
        from backend.application.services.chat_service import ChatService
        from backend.domain.message import Message, Role, ToolCall

        mock_review_queue = Mock()

        mock_llm = AsyncMock()
        mock_tools = MagicMock()
        mock_skills = MagicMock()
        mock_storage = AsyncMock()
        mock_metrics = MagicMock()
        mock_events = MagicMock()

        # >=4 tool calls
        tool_calls = [
            ToolCall(name="read", args={"path": "/a"}),
            ToolCall(name="edit", args={"path": "/b"}),
            ToolCall(name="read", args={"path": "/c"}),
            ToolCall(name="edit", args={"path": "/d"}),
        ]
        mock_llm.chat.return_value = Message(
            role=Role.ASSISTANT,
            content="Done",
            tool_calls=tool_calls,
        )
        mock_tools.list_tools.return_value = []
        mock_storage.get_messages.return_value = []

        with patch(
            "backend.skills.review_queue.get_review_queue",
            return_value=mock_review_queue,
        ), patch(
            "backend.application.services.chat_service._skill_activation_block",
            return_value="\n\n# Activated Skill\nsome content",
        ):
            service = ChatService(
                llm=mock_llm,
                tools=mock_tools,
                skills=mock_skills,
                storage=mock_storage,
                metrics=mock_metrics,
                events=mock_events,
            )

            with patch.object(
                service, "_execute_tool_calls", new_callable=AsyncMock
            ) as mock_exec:
                mock_exec.return_value = False

                asyncio.run(
                    service._run_turn_inner(
                        session_id="test-session",
                        user_message=Message(
                            role=Role.USER, content="Use the deploy skill"
                        ),
                        span=MagicMock(),
                    )
                )

        # No review enqueued because a skill was already activated
        mock_review_queue.enqueue.assert_not_called()


# ------------------------------------------------------------------ #
# 2. Low success rate detection (SkillUsageStore)
# ------------------------------------------------------------------ #


class TestLowSuccessRateSignalDetection:
    """Low success rate (<60% after >=10 uses) enqueues review."""

    def test_low_success_rate_triggers_review(self, temp_db_path):
        """After >=10 uses with <60% success, enqueue low_success_rate."""
        mock_review_queue = Mock()

        with patch(
            "backend.skills.review_queue.get_review_queue",
            return_value=mock_review_queue,
        ):
            # Create store with a real SQLite DB
            mock_db = MagicMock()
            mock_conn = sqlite3.connect(temp_db_path)
            mock_conn.row_factory = sqlite3.Row
            mock_db.get_connection.return_value = mock_conn

            store = SkillUsageStore(db=mock_db)

            # Simulate 10 uses with 50% success rate (below 60%)
            for _ in range(5):
                store.bump("skill_a", success=True)
            for _ in range(5):
                store.bump("skill_a", success=False)

            # 10th use: use_count=10, success_rate=0.5 < 0.6 → trigger

        # Verify review was enqueued
        assert mock_review_queue.enqueue.called
        # Find the low_success_rate call
        calls = mock_review_queue.enqueue.call_args_list
        low_sr_calls = [
            c
            for c in calls
            if (c.kwargs.get("trigger_type") == "low_success_rate")
            or (c.args and c.args[0] == "low_success_rate")
        ]
        assert len(low_sr_calls) >= 1, (
            f"Expected low_success_rate enqueue, got calls: {calls}"
        )

    def test_high_success_rate_no_review(self, temp_db_path):
        """When success rate is >=60%, no review is enqueued."""
        mock_review_queue = Mock()

        with patch(
            "backend.skills.review_queue.get_review_queue",
            return_value=mock_review_queue,
        ):
            mock_db = MagicMock()
            mock_conn = sqlite3.connect(temp_db_path)
            mock_conn.row_factory = sqlite3.Row
            mock_db.get_connection.return_value = mock_conn

            store = SkillUsageStore(db=mock_db)

            # 10 uses with 80% success rate (above 60%)
            for _ in range(8):
                store.bump("skill_b", success=True)
            for _ in range(2):
                store.bump("skill_b", success=False)

        # No low_success_rate review enqueued
        calls = mock_review_queue.enqueue.call_args_list
        low_sr_calls = [
            c
            for c in calls
            if (c.kwargs.get("trigger_type") == "low_success_rate")
            or (c.args and c.args[0] == "low_success_rate")
        ]
        assert len(low_sr_calls) == 0

    def test_below_min_usage_threshold_no_review(self, temp_db_path):
        """When use_count < 10, no review even with 0% success rate."""
        mock_review_queue = Mock()

        with patch(
            "backend.skills.review_queue.get_review_queue",
            return_value=mock_review_queue,
        ):
            mock_db = MagicMock()
            mock_conn = sqlite3.connect(temp_db_path)
            mock_conn.row_factory = sqlite3.Row
            mock_db.get_connection.return_value = mock_conn

            store = SkillUsageStore(db=mock_db)

            # Only 5 uses, all failures (0% success rate but below threshold)
            for _ in range(5):
                store.bump("skill_c", success=False)

        # No review enqueued (below MIN_USAGE_THRESHOLD)
        calls = mock_review_queue.enqueue.call_args_list
        low_sr_calls = [
            c
            for c in calls
            if (c.kwargs.get("trigger_type") == "low_success_rate")
            or (c.args and c.args[0] == "low_success_rate")
        ]
        assert len(low_sr_calls) == 0

    def test_review_enqueued_with_correct_context(self, temp_db_path):
        """Review event includes skill_name, success_rate, and use_count."""
        mock_review_queue = Mock()

        with patch(
            "backend.skills.review_queue.get_review_queue",
            return_value=mock_review_queue,
        ):
            mock_db = MagicMock()
            mock_conn = sqlite3.connect(temp_db_path)
            mock_conn.row_factory = sqlite3.Row
            mock_db.get_connection.return_value = mock_conn

            store = SkillUsageStore(db=mock_db)

            # 10 uses, 40% success rate
            for _ in range(4):
                store.bump("skill_d", success=True)
            for _ in range(6):
                store.bump("skill_d", success=False)

        # Find the low_success_rate call
        calls = mock_review_queue.enqueue.call_args_list
        low_sr_calls = [
            c
            for c in calls
            if (c.kwargs.get("trigger_type") == "low_success_rate")
            or (c.args and c.args[0] == "low_success_rate")
        ]
        assert len(low_sr_calls) >= 1

        # Check context contains required fields
        call = low_sr_calls[0]
        context = call.kwargs.get("context") or call.args[2]
        assert context["skill_name"] == "skill_d"
        assert context["use_count"] == 10
        assert abs(context["success_rate"] - 0.4) < 0.01
