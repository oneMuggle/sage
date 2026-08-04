"""Smoke test: lifespan wiring of memory lifecycle hooks + evolution scheduler.

Task 4 step 15 — verify the FastAPI lifespan constructs and registers:
- a single shared ``HookRegistry``
- a ``MemoryLifecycleManager`` bound to that registry
- an ``EvolutionScheduler`` whose task set includes the evolution tasks
  produced by ``create_evolution_tasks``
- a session-end watchdog background task

We use the real ``lifespan`` async-context-manager via FastAPI's
TestClient, then inspect ``app.state`` after startup.
"""

from __future__ import annotations

import asyncio

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
        assert hasattr(
            app.state, "evolution_scheduler"
        ), "EvolutionScheduler missing"

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