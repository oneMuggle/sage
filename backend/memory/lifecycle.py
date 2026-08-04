"""MemoryLifecycleManager: wrap MemoryManager with hook-based observability.

Inspired by Hermes Agent's MemoryProvider lifecycle (initialize →
system_prompt_block → prefetch → sync_turn → on_session_end →
on_pre_compress). See docs/superpowers/specs/2026-08-04-auto-memory-wiring-design.md

Phase 1 (Task 2 — Gap B): auto_memory preference gate.
Phase 2 (Task 4 — Gap A): on_turn_complete / on_session_end / on_pre_compress
hook entry points + ``memory_written`` / ``session_ended`` / ``pre_compress``
event emission via ``HookRegistry``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    """Timezone-aware UTC now — keeps event timestamps unambiguous."""
    return datetime.now(timezone.utc)


@dataclass
class MemoryWriteEvent:
    """Emitted per fact written by ``on_turn_complete``.

    ``turn_id`` carries the current turn's id so downstream watchers (e.g.
    audit logs, UI toasts, background review) can correlate the fact with
    the message that produced it.
    """

    memory_id: str
    content: str
    memory_type: str
    memory_category: str
    session_id: str
    turn_id: Optional[str]
    timestamp: datetime


@dataclass
class SessionEndEvent:
    """Emitted after ``memory.consolidate`` runs for a session."""

    session_id: str
    timestamp: datetime


@dataclass
class PreCompressEvent:
    """Emitted after ``memory.snapshot`` runs for a session."""

    session_id: str
    timestamp: datetime


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

    # ------------------------------------------------------------------
    # Hook entry points (Task 4 / Gap A)
    # ------------------------------------------------------------------
    #
    # Contract: all three methods are *non-raising* — any exception thrown
    # by the underlying memory subsystem (db locked, vector store broken,
    # network failure on a remote LLM call) is logged and swallowed so the
    # caller (ChatService / EvolutionScheduler / session watchdog) is never
    # blocked by a memory hiccup.

    async def on_turn_complete(self, session_id: str, messages: list) -> None:
        """End-of-turn hook: extract facts and emit ``memory_written``.

        Gated by ``is_auto_memory_enabled()``. Each fact returned by
        ``memory.remember`` triggers one ``memory_written`` event tagged
        with the current turn id (set via ``set_current_turn`` earlier in
        the turn).
        """
        if not await self.is_auto_memory_enabled():
            return
        try:
            # ``aremember`` is the async, traceability-aware entry point
            # (Task 4 / Gap A). The legacy sync ``remember`` is still
            # available for non-async callers like ``core/legacy/agent.py``.
            remember = getattr(self._memory, "aremember", None)
            if remember is None:
                # Fallback: some fakes (tests) expose ``remember`` as async;
                # honor that too so existing tests keep passing.
                remember = self._memory.remember
            extracted = await remember(
                session_id=session_id,
                messages=messages,
                source_turn_id=self._current_turn_id,
            )
        except Exception as exc:  # noqa: BLE001 — never raise into caller
            logger.exception("on_turn_complete: memory.remember failed", exc_info=exc)
            return

        for mem in extracted or []:
            try:
                await self._hooks.emit(
                    "memory_written",
                    MemoryWriteEvent(
                        memory_id=mem.id,
                        content=mem.content,
                        memory_type=getattr(mem, "type", "episodic"),
                        memory_category=getattr(mem, "category", "project_fact"),
                        session_id=session_id,
                        turn_id=self._current_turn_id,
                        timestamp=utcnow(),
                    ),
                )
            except Exception as exc:  # noqa: BLE001 — hook failures are non-fatal
                logger.exception("on_turn_complete: emit memory_written failed", exc_info=exc)

    async def on_session_end(self, session_id: str) -> None:
        """End-of-session hook: consolidate + emit ``session_ended``.

        Currently does *not* gate on ``auto_memory`` — session-end
        consolidation is considered housekeeping that should always run,
        regardless of the per-turn extraction toggle.
        """
        try:
            await self._memory.consolidate(session_id)
        except Exception as exc:  # noqa: BLE001 — never raise into caller
            logger.exception("on_session_end: memory.consolidate failed", exc_info=exc)
            # Still emit session_ended so watchers can record the closure,
            # but skip if even the emit call itself blows up.
        try:
            await self._hooks.emit(
                "session_ended",
                SessionEndEvent(session_id=session_id, timestamp=utcnow()),
            )
        except Exception as exc:  # noqa: BLE001 — hook failures are non-fatal
            logger.exception("on_session_end: emit session_ended failed", exc_info=exc)

    async def on_pre_compress(self, session_id: str) -> None:
        """Pre-compress hook: snapshot + emit ``pre_compress``.

        Mirrors ``on_session_end`` but is invoked *before* a context-window
        compression event (e.g. before ``ConsolidationPipeline`` runs),
        giving listeners (audit logs, background review) a chance to read
        the current state first.
        """
        try:
            await self._memory.snapshot(session_id)
        except Exception as exc:  # noqa: BLE001 — never raise into caller
            logger.exception("on_pre_compress: memory.snapshot failed", exc_info=exc)
        try:
            await self._hooks.emit(
                "pre_compress",
                PreCompressEvent(session_id=session_id, timestamp=utcnow()),
            )
        except Exception as exc:  # noqa: BLE001 — hook failures are non-fatal
            logger.exception("on_pre_compress: emit pre_compress failed", exc_info=exc)