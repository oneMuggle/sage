"""Unit tests for MemoryLifecycleManager.

Covers both surfaces shipped so far:

- ``auto_memory`` preference gate (Task 2 / Gap B) — default True when pref
  missing, respects pref=False, 30s cache, fail-open (True) on read error,
  cache invalidation.
- ``on_turn_complete`` / ``on_session_end`` / ``on_pre_compress`` lifecycle
  hook entry points (Task 4 / Gap A) — gates by auto_memory, emits
  ``memory_written`` per fact, emits ``session_ended`` and ``pre_compress``
  on their respective paths, and never propagates exceptions into the
  caller.
"""

from __future__ import annotations

import pytest

from backend.memory.lifecycle import MemoryLifecycleManager

pytestmark = pytest.mark.unit


@pytest.mark.asyncio()
async def test_is_auto_memory_enabled_default_true_when_pref_missing():
    """When preferences table has no auto_memory key, default to True."""

    class FakePrefs:
        async def get(self, key: str):
            return None

    mgr = MemoryLifecycleManager(
        memory_manager=None, hooks=None, preferences_repo=FakePrefs()
    )
    assert await mgr.is_auto_memory_enabled() is True


@pytest.mark.asyncio()
async def test_is_auto_memory_enabled_respects_pref_false():
    """When pref value is 'false', returns False."""

    class FakePrefs:
        async def get(self, key: str):
            return "false"

    mgr = MemoryLifecycleManager(
        memory_manager=None, hooks=None, preferences_repo=FakePrefs()
    )
    assert await mgr.is_auto_memory_enabled() is False


@pytest.mark.asyncio()
async def test_is_auto_memory_enabled_caches_for_30s():
    """Reading the pref three times within 30s should hit the cache (call_count == 1)."""
    call_count = 0

    class CountingPrefs:
        async def get(self, key: str):
            nonlocal call_count
            call_count += 1
            return "true"

    mgr = MemoryLifecycleManager(
        memory_manager=None, hooks=None, preferences_repo=CountingPrefs()
    )
    await mgr.is_auto_memory_enabled()
    await mgr.is_auto_memory_enabled()
    await mgr.is_auto_memory_enabled()
    assert call_count == 1


@pytest.mark.asyncio()
async def test_is_auto_memory_enabled_defaults_true_on_read_error():
    """When prefs.get raises, default to True (fail-open, never block ChatService)."""

    class FailingPrefs:
        async def get(self, key: str):
            raise RuntimeError("db locked")

    mgr = MemoryLifecycleManager(
        memory_manager=None, hooks=None, preferences_repo=FailingPrefs()
    )
    assert await mgr.is_auto_memory_enabled() is True


@pytest.mark.asyncio()
async def test_invalidate_auto_memory_cache_forces_re_read():
    """invalidate_auto_memory_cache() should drop the cache so next read hits DB."""
    call_count = 0

    class CountingPrefs:
        async def get(self, key: str):
            nonlocal call_count
            call_count += 1
            return "true"

    mgr = MemoryLifecycleManager(
        memory_manager=None, hooks=None, preferences_repo=CountingPrefs()
    )
    await mgr.is_auto_memory_enabled()
    await mgr.is_auto_memory_enabled()
    assert call_count == 1
    mgr.invalidate_auto_memory_cache()
    await mgr.is_auto_memory_enabled()
    assert call_count == 2


# ===========================================================================
# Task 4 / Gap A — lifecycle hook entry points
#
# F1/F2 fix: these tests now exercise the REAL MemoryManager (not a
# FakeMemory with an imagined API). on_turn_complete must extract facts
# from messages, persist them with traceability, and emit one
# memory_written per fact; on_session_end / on_pre_compress must drive the
# real consolidate / snapshot paths and only emit their events after
# success (never lie that consolidation succeeded when it failed).
# ===========================================================================


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
    async def get(self, key):
        return "true"


class _FalsePrefs:
    async def get(self, key):
        return "false"


@pytest.mark.asyncio()
async def test_on_turn_complete_extracts_persists_and_emits(tmp_db_path):
    """F1 — on_turn_complete against the REAL MemoryManager must:
    1. extract facts from the messages (keyword extractor, no LLM),
    2. persist each fact with source_turn_id / memory_category,
    3. emit one memory_written event per fact tagged with the turn id."""
    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryLifecycleManager

    manager = _real_memory_manager(tmp_db_path)
    hooks = HookRegistry()
    events: list[object] = []
    hooks.on("memory_written", lambda e: events.append(e))

    mgr = MemoryLifecycleManager(
        memory_manager=manager, hooks=hooks, preferences_repo=_TruePrefs()
    )
    mgr.set_current_turn("turn-1")
    messages = [
        {"role": "user", "content": "我喜欢吃火锅，每次去成都都要找地道的火锅店" + "x" * 20},
        {"role": "assistant", "content": "好的记住了"},
    ]
    await mgr.on_turn_complete("session-1", messages)

    assert len(events) >= 1
    ev = events[0]
    assert ev.turn_id == "turn-1"
    assert ev.session_id == "session-1"
    assert ev.content  # non-empty fact content

    # the fact(s) must be persisted with traceability
    rows = manager.episodic.get_recent(limit=10, session_id="session-1")
    assert len(rows) >= 1
    assert all(r["source_turn_id"] == "turn-1" for r in rows)
    assert all(r["memory_category"] == "user_pref" for r in rows)


@pytest.mark.asyncio()
async def test_on_turn_complete_skips_when_auto_memory_false():
    """When the pref gate is False, extraction must never run."""

    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryLifecycleManager

    class FakeMemory:
        async def remember(self, **kwargs):  # noqa: ARG002
            raise AssertionError("should not be called")

    mgr = MemoryLifecycleManager(
        memory_manager=FakeMemory(), hooks=HookRegistry(), preferences_repo=_FalsePrefs()
    )
    # Must not raise:
    await mgr.on_turn_complete("session-1", [])


@pytest.mark.asyncio()
async def test_on_session_end_consolidates_and_emits(tmp_db_path):
    """F2 — on_session_end against the REAL MemoryManager consolidates the
    working memory into episodic and emits session_ended after success."""
    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryLifecycleManager

    manager = _real_memory_manager(tmp_db_path)
    manager.add_to_working(
        "user", "hello there this is a test message worth remembering"
    )

    hooks = HookRegistry()
    events: list[object] = []
    hooks.on("session_ended", lambda e: events.append(e))

    mgr = MemoryLifecycleManager(
        memory_manager=manager, hooks=hooks, preferences_repo=None
    )
    await mgr.on_session_end("session-99")

    assert len(events) == 1
    assert events[0].session_id == "session-99"
    # consolidation ran: working memory cleared, episodic has a summary
    assert len(manager.working.messages) == 0
    assert manager.episodic.count() >= 1


@pytest.mark.asyncio()
async def test_on_session_end_does_not_emit_when_consolidation_fails():
    """F2 — when consolidation raises, session_ended must NOT be emitted
    (do not lie that consolidation succeeded when it failed)."""
    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryLifecycleManager

    class BrokenMemory:
        async def consolidate(self, session_id):  # noqa: ARG002
            raise RuntimeError("db locked")

        async def snapshot(self, session_id):  # noqa: ARG002
            return None

    hooks = HookRegistry()
    events: list[object] = []
    hooks.on("session_ended", lambda e: events.append(e))

    mgr = MemoryLifecycleManager(
        memory_manager=BrokenMemory(), hooks=hooks, preferences_repo=None
    )
    await mgr.on_session_end("session-99")  # must not raise
    assert events == []


@pytest.mark.asyncio()
async def test_on_pre_compress_snapshots_and_emits(tmp_db_path):
    """F2 — on_pre_compress snapshots the real manager and emits pre_compress
    after success."""
    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryLifecycleManager

    manager = _real_memory_manager(tmp_db_path)
    manager.add_to_working("user", "hello snapshot me")

    hooks = HookRegistry()
    events: list[object] = []
    hooks.on("pre_compress", lambda e: events.append(e))

    mgr = MemoryLifecycleManager(
        memory_manager=manager, hooks=hooks, preferences_repo=None
    )
    await mgr.on_pre_compress("session-5")
    assert len(events) == 1
    assert events[0].session_id == "session-5"


@pytest.mark.asyncio()
async def test_on_pre_compress_does_not_emit_when_snapshot_fails():
    """F2 — when snapshot raises, pre_compress must NOT be emitted."""
    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryLifecycleManager

    class BrokenMemory:
        async def consolidate(self, session_id):  # noqa: ARG002
            return None

        async def snapshot(self, session_id):  # noqa: ARG002
            raise RuntimeError("snapshot boom")

    hooks = HookRegistry()
    events: list[object] = []
    hooks.on("pre_compress", lambda e: events.append(e))

    mgr = MemoryLifecycleManager(
        memory_manager=BrokenMemory(), hooks=hooks, preferences_repo=None
    )
    await mgr.on_pre_compress("session-5")  # must not raise
    assert events == []


@pytest.mark.asyncio()
async def test_lifecycle_never_raises_into_caller():
    """Even if the extractor or memory subsystem throws, lifecycle must
    swallow and never propagate to the caller."""
    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryLifecycleManager

    class BrokenExtractor:
        async def extract(self, user_message, assistant_message):  # noqa: ARG002
            raise RuntimeError("llm down")

    class BrokenMemory:
        async def consolidate(self, session_id):  # noqa: ARG002
            raise RuntimeError("db broken")

        async def snapshot(self, session_id):  # noqa: ARG002
            raise RuntimeError("db broken")

    hooks = HookRegistry()

    # on_turn_complete with a broken extractor must not raise
    mgr = MemoryLifecycleManager(
        memory_manager=None,
        hooks=hooks,
        preferences_repo=_TruePrefs(),
        extractor=BrokenExtractor(),
    )
    await mgr.on_turn_complete("s", [{"role": "user", "content": "hi"}])

    # on_session_end / on_pre_compress with a broken memory must not raise
    mgr2 = MemoryLifecycleManager(
        memory_manager=BrokenMemory(), hooks=hooks, preferences_repo=None
    )
    await mgr2.on_session_end("s")
    await mgr2.on_pre_compress("s")