"""Smoke test: lifespan wiring of memory lifecycle hooks + evolution scheduler.

Task 4 step 15 — verify the FastAPI lifespan constructs and registers:
- a single shared ``HookRegistry``
- a ``MemoryLifecycleManager`` bound to that registry
- five evolution jobs on the unified ``SchedulerService``
- a session-end watchdog background task

We use the real ``lifespan`` async-context-manager via FastAPI's
TestClient, then inspect ``app.state`` after startup.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio()
async def test_lifespan_wires_hooks_and_evolution_scheduler(tmp_db_path):
    """Run the lifespan, then assert the hook/lifecycle/scheduler trio
    is present on ``app.state``."""
    from fastapi.testclient import TestClient

    import backend.data.database as db_mod
    from backend.main import app

    # Redirect the global DB to a temp path for isolation.
    db_mod._db = db_mod.Database(db_path=tmp_db_path)

    # TestClient triggers lifespan startup/shutdown synchronously.
    with TestClient(app) as client:
        # Health endpoint smoke check — proves the app booted.
        r = client.get("/health")
        assert r.status_code == 200

        # All three objects must be attached to app.state.
        assert hasattr(app.state, "hooks"), "HookRegistry missing from app.state"
        assert hasattr(app.state, "lifecycle"), "MemoryLifecycleManager missing"
        assert hasattr(app.state, "scheduler"), "SchedulerService missing"
        evolution_jobs = {
            job.id
            for job in app.state.scheduler._scheduler.get_jobs()
            if job.id.startswith("evolution/")
        }
        assert len(evolution_jobs) == 5, (
            f"Expected five evolution jobs, got {evolution_jobs!r}"
        )

        # The registry must accept subscriptions (sanity).
        app.state.hooks.on("test", lambda _p: None)
        assert "test" in app.state.hooks._listeners

        # The lifecycle must be wired to the same registry.
        assert app.state.lifecycle._hooks is app.state.hooks

        # The watchdog must be a running asyncio.Task.
        assert hasattr(app.state, "session_watchdog")
        watchdog = app.state.session_watchdog
        assert isinstance(watchdog, asyncio.Task)
        assert not watchdog.done()


# ----------------------------------------------------------------------------
# Code review fix — session watchdog SQLite SELECT must not block the loop.
#
# The watchdog scans the ``sessions`` table every 60 s for stale rows. The
# raw ``sqlite3`` cursor.execute() is synchronous; if invoked on the event
# loop it stalls every other coroutine waiting for I/O. The fix wraps the
# query in ``asyncio.to_thread`` and re-acquires the DB connection *inside*
# the worker thread so the existing single-connection / WAL contract holds.
#
# The watchdog helper ``_fetch_stale_session_ids`` is module-private but
# re-exported as ``app.state._watchdog_query_fn`` so this test can hit it
# without waiting 60 s. The assertion is: when invoked from the event loop,
# the thread that actually runs the SQLite SELECT must NOT be the event
# loop's thread.
# ----------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_watchdog_fetch_runs_sql_off_event_loop(tmp_db_path: str) -> None:
    """The watchdog helper must run its SELECT on a worker thread."""
    import backend.data.database as db_mod
    from backend.main import app

    db_mod._db = db_mod.Database(db_path=tmp_db_path)

    # Start the lifespan so the helper gets bound on app.state.
    from fastapi.testclient import TestClient

    with TestClient(app):
        # The lifespan must expose the watchdog query helper for tests.
        assert hasattr(app.state, "_watchdog_query_fn"), (
            "main.py lifespan must expose _watchdog_query_fn on app.state "
            "so async event-loop-blocking tests can call it directly"
        )

        fetch = app.state._watchdog_query_fn

        # Capture the event-loop thread id AFTER yielding to the loop so
        # we are not racing the test runner's thread.
        await asyncio.sleep(0)
        event_loop_thread_id = threading.get_ident()

        # Wrap db.get_connection so we can observe which thread runs it.
        db = app.state.db
        original_get_connection = db.get_connection
        connection_thread_id: dict[str, int | None] = {"value": None}

        def _probe_get_connection():
            connection_thread_id["value"] = threading.get_ident()
            return original_get_connection()

        db.get_connection = _probe_get_connection  # type: ignore[assignment]

        try:
            # Pick a far-past cutoff so the SELECT returns no rows.
            result = await fetch(cutoff_ts=0)
            assert result == [], (
                f"Expected empty stale list with cutoff_ts=0 got {result!r}"
            )
        finally:
            db.get_connection = original_get_connection  # type: ignore[assignment]

        assert connection_thread_id["value"] is not None, (
            "watchdog helper never called db.get_connection"
        )
        assert connection_thread_id["value"] != event_loop_thread_id, (
            "session-watchdog SELECT ran on the event-loop thread; "
            "it must be wrapped in asyncio.to_thread"
        )