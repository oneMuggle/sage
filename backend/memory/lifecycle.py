"""MemoryLifecycleManager: wrap MemoryManager with hook-based observability.

Inspired by Hermes Agent's MemoryProvider lifecycle (initialize →
system_prompt_block → prefetch → sync_turn → on_session_end →
on_pre_compress). See docs/superpowers/specs/2026-08-04-auto-memory-wiring-design.md

Phase 1 (Task 2 — Gap B): only the auto_memory preference gate is implemented.
HookRegistry wiring (Hook surface) lands in Task 6.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MemoryLifecycleManager:
    """Wrap MemoryManager with hooks; never raise into ChatService.

    Two surfaces today:
    - ``is_auto_memory_enabled()``: 30s-cached read of the ``auto_memory``
      preference. Defaults to True (backward-compatible — existing users see
      no behavior change). Read errors are logged and treated as True so a
      failing preferences table can never block ChatService.
    - ``invalidate_auto_memory_cache()``: test/debug helper that forces the
      next ``is_auto_memory_enabled()`` call to re-read.

    Hook surface (``memory.remember``, ``memory.compress``) is intentionally
    passthrough today; HookRegistry integration ships in Task 6.
    """

    _AUTO_MEMORY_TTL = 30.0
    _AUTO_MEMORY_KEY = "auto_memory"

    def __init__(self, memory_manager: Any, hooks: Any, preferences_repo: Any) -> None:
        self._memory = memory_manager
        self._hooks = hooks
        self._prefs = preferences_repo
        self._auto_memory_cache: Optional[bool] = None
        self._cache_timestamp: float = 0.0
        self._current_turn_id: Optional[str] = None

    def set_current_turn(self, turn_id: str) -> None:
        self._current_turn_id = turn_id

    async def is_auto_memory_enabled(self) -> bool:
        """Read auto_memory preference with 30s cache; default True.

        Fail-open: any exception reading the preference is logged and treated
        as True. The caller (ChatService) must never be blocked by a
        preferences-table hiccup.
        """
        now = time.monotonic()
        if (
            self._auto_memory_cache is not None
            and (now - self._cache_timestamp) < self._AUTO_MEMORY_TTL
        ):
            return self._auto_memory_cache
        try:
            val = await self._prefs.get(self._AUTO_MEMORY_KEY)
        except Exception as exc:  # noqa: BLE001 — fail-open by design
            logger.warning(
                "auto_memory pref read failed, defaulting True: %s", exc
            )
            self._auto_memory_cache = True
            self._cache_timestamp = now
            return True
        if val is None:
            enabled = True
        else:
            enabled = str(val).lower() == "true"
        self._auto_memory_cache = enabled
        self._cache_timestamp = now
        return enabled

    def invalidate_auto_memory_cache(self) -> None:
        """Force next read to hit DB (debug/testing helper)."""
        self._auto_memory_cache = None
        self._cache_timestamp = 0.0