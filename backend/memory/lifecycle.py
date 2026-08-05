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

    Hook surface (``on_turn_complete`` / ``on_session_end`` /
    ``on_pre_compress``) is wired to ``HookRegistry`` and emits
    ``memory_written`` / ``session_ended`` / ``pre_compress`` events;
    all three are non-raising by contract.
    """

    _AUTO_MEMORY_TTL = 30.0
    _AUTO_MEMORY_KEY = "auto_memory"

    def __init__(
        self,
        memory_manager: Any,
        hooks: Any,
        preferences_repo: Any,
        extractor: Optional[Any] = None,
    ) -> None:
        self._memory = memory_manager
        self._hooks = hooks
        self._prefs = preferences_repo
        self._auto_memory_cache: Optional[bool] = None
        self._cache_timestamp: float = 0.0
        self._current_turn_id: Optional[str] = None
        # F1 — MemoryExtractor produces fact dicts from a turn's messages.
        # Default to the keyword-only extractor (no LLM) so on_turn_complete
        # works out of the box; callers with an LLM may inject a richer one.
        if extractor is None:
            from backend.memory.extractor import MemoryExtractor

            extractor = MemoryExtractor(llm_client=None)
        self._extractor = extractor

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

    async def on_turn_complete(
        self,
        session_id: str,
        messages: list,
        source_message_id: Optional[str] = None,
    ) -> None:
        """End-of-turn hook: extract facts and emit ``memory_written``.

        Gated by ``is_auto_memory_enabled()``. Facts are extracted from the
        turn's messages via ``MemoryExtractor`` (keyword fallback by default,
        injectable for LLM-backed extraction), persisted through the real
        ``MemoryManager.aremember`` — threading ``source_turn_id`` and
        ``memory_category`` into the episodic row — and one
        ``memory_written`` event is emitted per fact tagged with the current
        turn id (set via ``set_current_turn`` earlier in the turn).

        Task 6: ``source_message_id`` (the persisted assistant/user message
        id captured by ChatService) is threaded into the episodic row so the
        Memory page's click-to-trace can highlight the exact producing
        message (Chat renders ``data-turn-id={message.id}``) — same
        capability the legacy ``_extract_and_store_memory`` path had.
        """
        if not await self.is_auto_memory_enabled():
            return
        user_msg, assistant_msg = self._split_messages(messages)
        try:
            facts = await self._extractor.extract(user_msg, assistant_msg)
        except Exception as exc:  # noqa: BLE001 — never raise into caller
            logger.exception("on_turn_complete: fact extraction failed", exc_info=exc)
            return
        for fact in facts or []:
            try:
                memory_id = await self._persist_fact(
                    session_id, fact, source_message_id=source_message_id
                )
            except Exception as exc:  # noqa: BLE001 — one bad fact must not stop the rest
                logger.exception("on_turn_complete: persist failed", exc_info=exc)
                continue
            if not memory_id:
                continue
            try:
                await self._hooks.emit(
                    "memory_written",
                    MemoryWriteEvent(
                        memory_id=memory_id,
                        content=fact.get("content", ""),
                        memory_type="episodic",
                        memory_category=fact.get("category", "project_fact"),
                        session_id=session_id,
                        turn_id=self._current_turn_id,
                        timestamp=utcnow(),
                    ),
                )
            except Exception as exc:  # noqa: BLE001 — hook failures are non-fatal
                logger.exception(
                    "on_turn_complete: emit memory_written failed", exc_info=exc
                )

    def _split_messages(self, messages: list) -> "tuple[str, str]":
        """Derive the last user and assistant message texts from a turn.

        Accepts both plain dicts (``{"role", "content"}`` — the original
        contract, still used by tests) and ``backend.domain.message.Message``
        domain objects (the production ``ChatService.run_turn`` payload,
        Task 6). ``getattr`` / dict-access are tried so neither shape
        breaks the end-of-turn hook.
        """
        user_msg = ""
        assistant_msg = ""
        for m in messages or []:
            if isinstance(m, dict):
                role = m.get("role", "")
                content = m.get("content", "") or ""
            else:
                role = getattr(m, "role", "")
                content = getattr(m, "content", "") or ""
            if role == "user":
                user_msg = content
            elif role == "assistant":
                assistant_msg = content
        return user_msg, assistant_msg

    async def _persist_fact(
        self,
        session_id: str,
        fact: dict,
        source_message_id: Optional[str] = None,
    ) -> Optional[str]:
        """Persist one extracted fact through the real ``MemoryManager.aremember``.

        Returns the persisted memory id (or ``None`` if the memory object has
        no ``aremember`` / the store produced no id). ``source_turn_id`` and
        ``memory_category`` ride along so the episodic row is traceable;
        ``source_message_id`` (Task 6) lets the UI highlight the exact
        producing message.
        """
        aremember = getattr(self._memory, "aremember", None)
        if aremember is None:
            logger.warning(
                "on_turn_complete: memory has no aremember(); skipping persist"
            )
            return None
        return await aremember(
            content=fact.get("content", ""),
            session_id=session_id,
            source_turn_id=self._current_turn_id,
            source_message_id=source_message_id,
            memory_category=fact.get("category", "project_fact"),
            metadata={"importance": fact.get("importance", 5)},
        )

    async def on_session_end(self, session_id: str) -> None:
        """End-of-session hook: consolidate + emit ``session_ended``.

        Consolidation is driven through the real ``MemoryManager.consolidate``
        (async wrapper over ``ConsolidationPipeline``). The ``session_ended``
        event fires ONLY after consolidation succeeds — on failure we log and
        return without emitting, so watchers are never told consolidation
        succeeded when it failed.
        """
        try:
            await self._memory.consolidate(session_id)
        except Exception as exc:  # noqa: BLE001 — never raise into caller
            logger.exception("on_session_end: memory.consolidate failed", exc_info=exc)
            return
        try:
            await self._hooks.emit(
                "session_ended",
                SessionEndEvent(session_id=session_id, timestamp=utcnow()),
            )
        except Exception as exc:  # noqa: BLE001 — hook failures are non-fatal
            logger.exception("on_session_end: emit session_ended failed", exc_info=exc)

    async def on_pre_compress(self, session_id: str) -> None:
        """Pre-compress hook: snapshot + emit ``pre_compress``.

        Fires before a context-window compression event (e.g. before
        ``ConsolidationPipeline`` runs), giving listeners (audit logs,
        background review) a chance to read the current state first. The
        snapshot is driven through the real ``MemoryManager.snapshot``
        (persists the working-memory state). ``pre_compress`` is emitted only
        after the snapshot succeeds — on failure we log and return without
        emitting.
        """
        try:
            await self._memory.snapshot(session_id)
        except Exception as exc:  # noqa: BLE001 — never raise into caller
            logger.exception("on_pre_compress: memory.snapshot failed", exc_info=exc)
            return
        try:
            await self._hooks.emit(
                "pre_compress",
                PreCompressEvent(session_id=session_id, timestamp=utcnow()),
            )
        except Exception as exc:  # noqa: BLE001 — hook failures are non-fatal
            logger.exception("on_pre_compress: emit pre_compress failed", exc_info=exc)