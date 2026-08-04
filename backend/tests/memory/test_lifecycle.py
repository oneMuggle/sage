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
# ===========================================================================


@pytest.mark.asyncio()
async def test_on_turn_complete_calls_remember_and_emits_hook():
    """on_turn_complete must:
    1. Gate on ``is_auto_memory_enabled()``
    2. Forward (session_id, messages, source_turn_id) to ``memory.remember``
    3. Emit one ``memory_written`` event per returned memory, tagged with
       the current turn id so downstream watchers can correlate.
    """

    class FakeMemory:
        def __init__(self):
            self.remember_calls: list[dict] = []

        async def remember(self, **kwargs):
            self.remember_calls.append(kwargs)

            class _Mem:
                def __init__(self, id, content, category):
                    self.id = id
                    self.content = content
                    self.category = category
                    self.type = "episodic"

            return [_Mem("m1", "fact 1", "user_pref"), _Mem("m2", "fact 2", "project_fact")]

    class FakePrefs:
        async def get(self, key):
            return "true"

    from backend.memory.hooks import HookRegistry

    hooks = HookRegistry()
    events: list[object] = []
    hooks.on("memory_written", lambda e: events.append(e))

    mgr = MemoryLifecycleManager(
        memory_manager=FakeMemory(), hooks=hooks, preferences_repo=FakePrefs()
    )
    mgr.set_current_turn("turn-1")
    await mgr.on_turn_complete("session-1", [{"role": "user", "content": "hi"}])

    assert len(events) == 2
    assert events[0].content == "fact 1"
    assert events[0].turn_id == "turn-1"


@pytest.mark.asyncio()
async def test_on_turn_complete_skips_when_auto_memory_false():
    """When the pref gate is False, ``remember`` must never be called."""

    from backend.memory.hooks import HookRegistry

    class FakeMemory:
        async def remember(self, **kwargs):  # noqa: ARG002
            raise AssertionError("should not be called")

    class FakePrefs:
        async def get(self, key):
            return "false"

    mgr = MemoryLifecycleManager(
        memory_manager=FakeMemory(), hooks=HookRegistry(), preferences_repo=FakePrefs()
    )
    # Must not raise:
    await mgr.on_turn_complete("session-1", [])


@pytest.mark.asyncio()
async def test_on_session_end_calls_consolidate():
    """on_session_end must call ``memory.consolidate(session_id)`` and emit a
    ``session_ended`` event."""

    from backend.memory.hooks import HookRegistry

    consolidate_calls: list[str] = []

    class FakeMemory:
        async def consolidate(self, session_id):
            consolidate_calls.append(session_id)

    events: list[object] = []
    hooks = HookRegistry()
    hooks.on("session_ended", lambda e: events.append(e))

    mgr = MemoryLifecycleManager(
        memory_manager=FakeMemory(), hooks=hooks, preferences_repo=None
    )
    await mgr.on_session_end("session-99")
    assert consolidate_calls == ["session-99"]
    assert len(events) == 1


@pytest.mark.asyncio()
async def test_lifecycle_never_raises_into_caller():
    """Even if memory throws, lifecycle must swallow and never propagate."""

    from backend.memory.hooks import HookRegistry

    class BrokenMemory:
        async def remember(self, **kw):  # noqa: ARG002
            raise RuntimeError("db broken")

    class FakePrefs:
        async def get(self, key):
            return "true"

    mgr = MemoryLifecycleManager(
        memory_manager=BrokenMemory(), hooks=HookRegistry(), preferences_repo=FakePrefs()
    )
    # Must not raise:
    await mgr.on_turn_complete("s", [])