"""
Important-1 (final whole-branch review): the production chat path must
drive the lifecycle.

The renderer's ONLY chat command is ``agent_chat_stream`` →
``POST /api/v1/chat/stream`` → legacy ``chat_stream_create`` →
``SageAgent.run_loop``. The producer previously only persisted messages —
it never called ``lifecycle.on_turn_complete``, so no ``memory_written``
ever fired on the production flow and the SSE ``/memory/events`` stream
stayed silent (Memory page toast/prepend never activated; the
``auto_memory`` toggle gated nothing).

This test proves, end-to-end through the real HTTP route:
  1. a ``/api/v1/chat/stream`` turn (patched SageAgent) with a real
     lifecycle present emits ``memory_written`` on ``app.state.hooks``,
  2. the persisted episodic row carries ``source_message_id`` = the REAL
     persisted assistant message id (so MemoryCard click-to-trace works),
  3. when ``app.state.lifecycle`` is absent the stream still completes
     normally (the producer must never break the stream over memory).
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import patch

import httpx
import pytest

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.main import app
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"


def _real_memory_manager(tmp_db_path: str):
    from backend.data.database import Database
    from backend.memory.episodic import EpisodicMemory
    from backend.memory.manager import MemoryManager
    from backend.memory.semantic import SemanticMemory
    from backend.memory.working import WorkingMemory

    db = Database(db_path=tmp_db_path)
    db.init_db()
    return MemoryManager(
        working=WorkingMemory(max_size=10, max_tokens=2000),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
    )


class _TruePrefs:
    async def get(self, key):  # noqa: ARG002 — fixture
        return "true"


async def _drain_producer(stream_id: str) -> None:
    """Wait for the background producer task to finish (persist + hooks)."""
    entry = app.state.streams.get(stream_id)
    if entry and entry.task:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await entry.task


@pytest.mark.asyncio()
async def test_chat_stream_producer_drives_lifecycle_and_traceability(tmp_db_path):
    """A /chat/stream turn with a lifecycle present emits memory_written AND
    the episodic row carries source_message_id == persisted assistant msg id."""
    from backend.api.chat_stream_registry import StreamRegistry
    from backend.data.session_repo import MessageRepository
    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryLifecycleManager

    manager = _real_memory_manager(tmp_db_path)
    hooks = HookRegistry()
    written: list = []
    hooks.on("memory_written", lambda e: written.append(e))
    lifecycle = MemoryLifecycleManager(
        memory_manager=manager, hooks=hooks, preferences_repo=_TruePrefs()
    )

    # Save/restore the app state so we never leak state into other tests.
    prev_lifecycle = getattr(app.state, "lifecycle", None)
    prev_hooks = getattr(app.state, "hooks", None)
    app.state.lifecycle = lifecycle
    app.state.hooks = hooks
    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()
    try:
        async def mock_run_loop(messages, max_iterations=5, **kwargs):
            yield AgentEvent(state=AgentState.THINKING, iteration=0)
            yield AgentEvent(
                state=AgentState.DONE,
                iteration=0,
                content="好的，我已经记住您的偏好了，以后会优先考虑。",
            )

        session_id = "00000000-0000-0000-0000-000000000000"
        user_message = "我喜欢吃火锅，每次去成都都要找地道的火锅店，这家真的绝了" + "x" * 10

        # §1.3a FK (#290): /chat/stream 写 messages + memories_episodic 都引用
        # sessions(id);先建父 session 行,否则两个 INSERT 都抛 IntegrityError。
        ensure_session(manager.episodic.db, session_id)

        with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
            MockAgent.return_value.run_loop = mock_run_loop
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as ac:
                create_resp = await ac.post(
                    CHAT_STREAM_PATH,
                    json={"session_id": session_id, "message": user_message},
                )
                assert create_resp.status_code == 200, create_resp.text
                stream_id = create_resp.json()["streamId"]
                attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
                assert attach_resp.status_code == 200
        await _drain_producer(stream_id)

        # 1) memory_written emitted on app.state.hooks
        assert len(written) >= 1, "no memory_written fired on the /chat/stream path"
        ev = written[0]
        assert ev.session_id == session_id

        # 2) the REAL persisted assistant message id is threaded as
        #    source_message_id (click-to-trace capability).
        persisted = MessageRepository().get_by_session(session_id)
        asst_msg = next((m for m in persisted if m.role == "assistant"), None)
        assert asst_msg is not None, "assistant message not persisted"
        rows = manager.episodic.get_recent(limit=10, session_id=session_id)
        assert len(rows) >= 1
        assert rows[0]["source_message_id"] == asst_msg.id, (
            f"source_message_id {rows[0]['source_message_id']!r} != "
            f"persisted assistant id {asst_msg.id!r}"
        )
        assert all(r["source_message_id"] == asst_msg.id for r in rows)
    finally:
        app.state.lifecycle = prev_lifecycle
        app.state.hooks = prev_hooks
        if app.state.streams is not None:
            for entry in list(app.state.streams._entries.values()):
                if entry.task is not None and not entry.task.done():
                    entry.task.cancel()
            app.state.streams._entries.clear()


@pytest.mark.asyncio()
async def test_chat_stream_producer_works_without_lifecycle(tmp_db_path):
    """When app.state.lifecycle is absent (tests / legacy boots), the stream
    must still complete normally — memory must never break the chat flow."""
    from backend.api.chat_stream_registry import StreamRegistry

    prev_lifecycle = getattr(app.state, "lifecycle", None)
    prev_hooks = getattr(app.state, "hooks", None)
    app.state.lifecycle = None
    app.state.hooks = None
    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()
    try:
        async def mock_run_loop(messages, max_iterations=5, **kwargs):
            yield AgentEvent(state=AgentState.THINKING, iteration=0)
            yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok")

        with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
            MockAgent.return_value.run_loop = mock_run_loop
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as ac:
                create_resp = await ac.post(
                    CHAT_STREAM_PATH,
                    json={
                        "session_id": "s",
                        "message": "hi there this is a test",
                    },
                )
                assert create_resp.status_code == 200, create_resp.text
                stream_id = create_resp.json()["streamId"]
                attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
                assert attach_resp.status_code == 200
                # the done event must still arrive (stream not broken)
                assert "done" in attach_resp.text
        await _drain_producer(stream_id)
    finally:
        app.state.lifecycle = prev_lifecycle
        app.state.hooks = prev_hooks
        if app.state.streams is not None:
            for entry in list(app.state.streams._entries.values()):
                if entry.task is not None and not entry.task.done():
                    entry.task.cancel()
            app.state.streams._entries.clear()
