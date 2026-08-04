"""Unit tests for MemoryLifecycleManager (auto_memory preference gate, Gap B).

These tests pin the contract from task-2-brief.md:
- default True when pref missing
- respects pref=False
- 30s cache
- fail-open (True) on read error
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