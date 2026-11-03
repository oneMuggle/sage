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

from backend.api.legacy_routes import drain_post_turn_tasks
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
    # 收尾副作用（stop hooks / 记忆抽取）已移出 DONE 关键路径，改为后台任务；
    # 断言它们的效果前必须显式等待。
    await drain_post_turn_tasks()


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


@pytest.mark.asyncio()
async def test_chat_stream_done_not_blocked_by_slow_lifecycle(tmp_db_path):
    """DONE must reach the client while ``on_turn_complete`` is still running.

    Regression: the producer used to inline-await the lifecycle (memory
    extraction) before queueing DONE. With an unreachable default endpoint
    the assistant row was persisted at 21:22:18 and DONE only arrived at
    21:24:34 — the cursor sat at the end of the message for 136s.
    """
    from backend.api.chat_stream_registry import StreamRegistry
    from backend.data.database import get_database

    class _SlowLifecycle:
        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def on_turn_complete(self, *args, **kwargs):  # noqa: ARG002 — fixture
            self.started.set()
            await self.release.wait()

    slow = _SlowLifecycle()
    prev_lifecycle = getattr(app.state, "lifecycle", None)
    prev_hooks = getattr(app.state, "hooks", None)
    app.state.lifecycle = slow
    app.state.hooks = None
    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()

    session_id = "00000000-0000-0000-0000-00000000000a"
    ensure_session(get_database(), session_id)

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="即时完成")

    try:
        with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
            MockAgent.return_value.run_loop = mock_run_loop
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as ac:
                create_resp = await ac.post(
                    CHAT_STREAM_PATH,
                    json={
                        "session_id": session_id,
                        "message": "帮我记住这个偏好：我更喜欢简洁的回答",
                    },
                )
                assert create_resp.status_code == 200, create_resp.text
                stream_id = create_resp.json()["streamId"]
                attach_resp = await asyncio.wait_for(
                    ac.get(f"{CHAT_STREAM_PATH}/{stream_id}"), timeout=2.0
                )
        assert "done" in attach_resp.text
        # 收尾任务确实已启动，但尚未完成 —— DONE 已先送达。
        await asyncio.wait_for(slow.started.wait(), timeout=1.0)
        assert not slow.release.is_set()
        slow.release.set()
        await _drain_producer(stream_id)
    finally:
        slow.release.set()
        await drain_post_turn_tasks(timeout=1.0)
        app.state.lifecycle = prev_lifecycle
        app.state.hooks = prev_hooks
        if app.state.streams is not None:
            for entry in list(app.state.streams._entries.values()):
                if entry.task is not None and not entry.task.done():
                    entry.task.cancel()
            app.state.streams._entries.clear()


@pytest.mark.asyncio()
async def test_chat_stream_producer_passes_reasoning_delta_through(tmp_db_path):
    """Reasoning deltas must reach the wire as-is and be concatenated for
    persistence — no second chunking pass, no duplicate full ``reasoning``.

    Regression: the agent buffered every adapter ``reasoning_delta`` and only
    emitted one full ``REASONING`` after the stream ended, so the producer's
    re-chunking always put the thinking panel after the body.
    """
    from backend.api.chat_stream_registry import StreamRegistry
    from backend.data.database import get_database
    from backend.data.session_repo import MessageRepository

    prev_lifecycle = getattr(app.state, "lifecycle", None)
    prev_hooks = getattr(app.state, "hooks", None)
    app.state.lifecycle = None
    app.state.hooks = None
    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()

    session_id = "00000000-0000-0000-0000-00000000000b"
    ensure_session(get_database(), session_id)

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(
            state=AgentState.REASONING_DELTA, iteration=0, reasoning="先读文件，"
        )
        yield AgentEvent(
            state=AgentState.REASONING_DELTA, iteration=0, reasoning="再改代码。"
        )
        yield AgentEvent(state=AgentState.CONTENT_DELTA, iteration=0, content="正文")
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="已完成")

    try:
        with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
            MockAgent.return_value.run_loop = mock_run_loop
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as ac:
                create_resp = await ac.post(
                    CHAT_STREAM_PATH,
                    json={"session_id": session_id, "message": "看一下这个文件"},
                )
                assert create_resp.status_code == 200, create_resp.text
                stream_id = create_resp.json()["streamId"]
                attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
                assert attach_resp.status_code == 200

        assert "reasoning_delta" in attach_resp.text
        assert "先读文件，" in attach_resp.text
        assert "再改代码。" in attach_resp.text
        assert "reasoning_final" not in attach_resp.text
        # 每段增量只上一次 wire（producer 不再二次切块/重发整段）
        assert attach_resp.text.count("先读文件，") == 1
        assert attach_resp.text.count("再改代码。") == 1
        # 思考必须在正文之前到达
        assert attach_resp.text.index("先读文件，") < attach_resp.text.index("content_delta")

        await _drain_producer(stream_id)
        persisted = MessageRepository().get_by_session(session_id)
        asst = next((m for m in persisted if m.role == "assistant"), None)
        assert asst is not None, "assistant message not persisted"
        assert asst.reasoning_content == "先读文件，再改代码。"
    finally:
        app.state.lifecycle = prev_lifecycle
        app.state.hooks = prev_hooks
        if app.state.streams is not None:
            for entry in list(app.state.streams._entries.values()):
                if entry.task is not None and not entry.task.done():
                    entry.task.cancel()
            app.state.streams._entries.clear()
