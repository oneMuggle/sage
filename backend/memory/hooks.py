"""Process-local pub/sub for memory lifecycle events.

This is a separate module from ``backend/hooks/`` (which is the tool/skill
hook runner); here we just need a tiny synchronous-with-coroutine-aware
event bus for memory lifecycle events (``memory_written``, ``session_ended``,
``pre_compress``, ``evolution_completed``).

Listener errors are swallowed so a misbehaving listener cannot break the
memory subsystem — the MemoryLifecycleManager contract requires that all
hook-driven methods never raise into the caller.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Dict, List, Union

logger = logging.getLogger(__name__)

# A listener may be either a plain callable or an async coroutine function.
AsyncOrSyncListener = Callable[[object], Union[None, "asyncio.Future[None]"]]


class HookRegistry:
    """In-process event bus for memory lifecycle events.

    Usage::

        reg = HookRegistry()
        reg.on("memory_written", listener)
        await reg.emit("memory_written", event_obj)
        reg.off("memory_written", listener)
    """

    def __init__(self) -> None:
        self._listeners: Dict[str, List[AsyncOrSyncListener]] = {}

    def on(self, event: str, callback: AsyncOrSyncListener) -> None:
        """Register a listener for ``event``.

        Listeners are called in registration order. Adding the same callable
        twice is allowed and results in two invocations per ``emit``.
        """
        self._listeners.setdefault(event, []).append(callback)

    def off(self, event: str, callback: AsyncOrSyncListener) -> None:
        """Remove a previously-registered listener.

        Identity (``is``) comparison is used so callers should hold on to
        the original callable reference.
        """
        if event in self._listeners:
            self._listeners[event] = [
                cb for cb in self._listeners[event] if cb is not callback
            ]

    async def emit(self, event: str, payload: object) -> None:
        """Fire ``event`` with ``payload`` to every registered listener.

        Exceptions raised by any listener are logged and swallowed — they
        never propagate to the caller.
        """
        # Snapshot the list so a listener that calls on()/off() during
        # dispatch doesn't mutate the iteration.
        listeners = list(self._listeners.get(event, []))
        for cb in listeners:
            try:
                result = cb(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # noqa: BLE001 — listener failures must never escape
                logger.exception(
                    "hook listener for %r raised; continuing with remaining listeners",
                    event,
                    exc_info=exc,
                )