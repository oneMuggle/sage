"""Thread-aware lazy ``asyncio.Lock`` factory.

Background
----------
``asyncio.Lock()`` historically required a running event loop at
construction time. Py3.10+ kept the same signature but changed the
semantics: the lock is now bound to a loop on first ``await``. Older
Python (notably Py3.8 used by the ``release/win7`` LTS branch) still
raises ``RuntimeError`` when no current loop is bound.

``LazyLock`` provides a property-style accessor that constructs the
underlying ``asyncio.Lock`` only on first access. By that point the
calling code is inside an ``async with`` block, so a loop is
guaranteed to be running (or one is created by ``asyncio.run`` for
the sync fixture pattern).

This is the fix for issue #536 — production ``EventHub`` /
``SnapshotStore`` objects must be safe to instantiate from a thread
that has no running event loop (e.g. pytest-xdist worker main
thread at fixture-build time, or FastAPI startup before the lifespan
event loop spins up).

Usage
-----

.. code-block:: python

    class MyService:
        def __init__(self) -> None:
            self._lock = LazyLock()

        async def critical_section(self) -> None:
            async with self._lock:
                ...

The descriptor returns the same underlying lock on every access —
the construction happens once, on first ``async with``.
"""

from __future__ import annotations

import asyncio
from typing import Optional


class LazyLock:
    """Deferred ``asyncio.Lock`` accessor.

    ``__init__`` does NOT call ``asyncio.Lock()`` — that's the whole
    point. The lock is created the first time ``acquire()`` /
    ``__aenter__`` is called (i.e. the first ``async with self._lock``),
    by which point the caller is inside a running event loop.

    Thread safety: ``__init__`` is called once per object. The first
    ``acquire`` is single-threaded by virtue of the ``asyncio.Lock``
    itself — the underlying ``_loop`` field assignment is a plain
    Python attribute write that is safe before any await, and the
    loop becomes bound on first ``await self._lock.acquire()``.
    """

    __slots__ = ("_lock",)

    def __init__(self) -> None:
        # Intentionally NOT calling asyncio.Lock() — defer until first await.
        self._lock: Optional[asyncio.Lock] = None

    def _ensure_lock(self) -> asyncio.Lock:
        """Return the underlying lock, constructing it on first call.

        Subsequent calls return the same lock. This is safe because
        the first call happens inside an ``async`` block — the loop
        is active.
        """
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def __aenter__(self) -> LazyLock:
        await self._ensure_lock().__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._ensure_lock().__aexit__(exc_type, exc, tb)

    async def acquire(self) -> bool:
        return await self._ensure_lock().acquire()

    def release(self) -> None:
        """Release the lock; raises if not yet constructed or not held."""
        self._ensure_lock().release()

    def locked(self) -> bool:
        """Return whether the lock is currently held.

        Returns ``False`` before first acquire (the lock has not been
        constructed yet, so it cannot be held).
        """
        if self._lock is None:
            return False
        return self._lock.locked()


__all__ = ["LazyLock"]
