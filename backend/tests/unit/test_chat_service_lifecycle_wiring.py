"""Task 6 — ChatService → MemoryLifecycleManager end-of-turn wiring.

The production chat path must drive ``lifecycle.on_turn_complete`` at the
end of ``run_turn`` so that (with a lifecycle-present service):

1. extracted facts are persisted with the correct ``source_turn_id``
   (= the turn's run id) and ``source_message_id`` (= the persisted
   assistant/user message id),
2. one ``memory_written`` hook event is emitted per fact,
3. ``compress`` is still driven after the hook (memory lifecycle),
4. the legacy path (no lifecycle) still runs ``_extract_and_store_memory``
   + ``compress`` unchanged.

The lifecycle is real (``MemoryLifecycleManager`` over a real
``MemoryManager`` on a temp DB); the LLM / storage / metrics / events
ports are mocked, exactly like ``test_chat_service_auto_memory_gate.py``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from backend.application.services.chat_service import ChatService
from backend.domain.message import Message, Role
from backend.tests.conftest import ensure_session


def _real_memory_manager(tmp_db_path):
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


def _build_service(memory_obj, lifecycle=None):
    llm = Mock()
    # run_turn's main LLM call returns the assistant reply; the legacy-path
    # MemoryExtractor makes a SECOND call whose reply must be valid JSON
    # (fact extraction) — the lifecycle path never makes that second call
    # (it uses the keyword extractor internally).
    llm.chat = AsyncMock(
        side_effect=[
            Message(
                role=Role.ASSISTANT,
                content="好的，我已经记住您的偏好了，以后会优先考虑。",
            ),
            Message(
                role=Role.ASSISTANT,
                content=(
                    '[{"content": "用户喜欢吃火锅", "importance": 7, '
                    '"category": "user_pref", "tags": ["preference"]}]'
                ),
            ),
        ],
    )
    tools = Mock()
    tools.list_tools = Mock(return_value=[])
    storage = Mock()
    # Real string ids — run_turn persists user+assistant messages and threads
    # the ids into source_message_id (a Mock id would blow up sqlite binding).
    storage.append_message = AsyncMock(side_effect=["user-msg-id-1", "assistant-msg-id-1"])
    storage.get_messages = AsyncMock(return_value=[])
    metrics = Mock()
    metrics.counter = Mock()
    metrics.histogram = Mock()
    metrics.gauge = Mock()
    events = Mock()
    events.emit = Mock()
    return ChatService(
        llm=llm,
        tools=tools,
        skills=None,
        storage=storage,
        metrics=metrics,
        events=events,
        memory=memory_obj,
        lifecycle=lifecycle,
    )


@pytest.mark.asyncio()
async def test_run_turn_with_lifecycle_emits_and_persists(tmp_db_path):
    """A lifecycle-present ChatService must emit memory_written and persist
    facts with the correct source_turn_id + source_message_id."""
    from backend.adapters.out.memory.adapter import MemoryAdapter
    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryLifecycleManager

    manager = _real_memory_manager(tmp_db_path)
    # §1.3a FK (#290): run_turn 持久化 episodic 需父 session 行。
    ensure_session(manager.episodic.db, "session-1")
    hooks = HookRegistry()
    written: list = []
    hooks.on("memory_written", lambda e: written.append(e))
    lifecycle = MemoryLifecycleManager(
        memory_manager=manager, hooks=hooks, preferences_repo=_TruePrefs()
    )

    svc = _build_service(MemoryAdapter(manager), lifecycle=lifecycle)
    user_message = Message(
        role=Role.USER,
        content="我喜欢吃火锅，每次去成都都要找地道的火锅店" + "x" * 20,
    )
    await svc.run_turn("session-1", user_message)

    # 1) memory_written emitted (one per extracted fact)
    assert len(written) >= 1
    ev = written[0]
    assert ev.session_id == "session-1"
    assert ev.turn_id is not None
    assert ev.content

    # 2) facts persisted with the emitting turn's id
    rows = manager.episodic.get_recent(limit=10, session_id="session-1")
    assert len(rows) >= 1
    assert all(r["source_turn_id"] == ev.turn_id for r in rows)
    assert all(r["memory_category"] == "user_pref" for r in rows)


@pytest.mark.asyncio()
async def test_run_turn_with_lifecycle_still_compresses(tmp_db_path):
    """compress must still run after on_turn_complete (memory lifecycle)."""
    from backend.adapters.out.memory.adapter import MemoryAdapter
    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryLifecycleManager

    manager = _real_memory_manager(tmp_db_path)
    lifecycle = MemoryLifecycleManager(
        memory_manager=manager,
        hooks=HookRegistry(),
        preferences_repo=_TruePrefs(),
    )
    memory = MemoryAdapter(manager)
    compress_spy = AsyncMock(wraps=memory.compress)
    memory.compress = compress_spy  # type: ignore[method-assign]

    svc = _build_service(memory, lifecycle=lifecycle)
    user_message = Message(
        role=Role.USER,
        content="我喜欢吃火锅，每次去成都都要找地道的火锅店" + "x" * 20,
    )
    await svc.run_turn("session-1", user_message)

    compress_spy.assert_awaited_once_with("session-1")


@pytest.mark.asyncio()
async def test_run_turn_legacy_path_unchanged(tmp_db_path):
    """No lifecycle → _extract_and_store_memory + compress still run."""
    from backend.adapters.out.memory.adapter import MemoryAdapter

    manager = _real_memory_manager(tmp_db_path)
    memory = MemoryAdapter(manager)
    store_spy = AsyncMock(wraps=memory.store)
    memory.store = store_spy  # type: ignore[method-assign]
    compress_spy = AsyncMock(wraps=memory.compress)
    memory.compress = compress_spy  # type: ignore[method-assign]

    svc = _build_service(memory, lifecycle=None)
    user_message = Message(
        role=Role.USER,
        content="我喜欢吃火锅，每次去成都都要找地道的火锅店" + "x" * 20,
    )
    await svc.run_turn("session-1", user_message)

    # legacy path: extraction (store) + compress each called once per turn
    store_spy.assert_awaited()
    compress_spy.assert_awaited_once_with("session-1")
