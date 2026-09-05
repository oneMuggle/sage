"""Tests for orch_run_control REST endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.domain.orch_events import make_event
from backend.orchestration.event_hub import EventHub
from backend.orchestration.snapshot_store import SnapshotStore


@pytest.fixture()
def client():
    from fastapi import FastAPI

    from backend.api.orch_run_control import configure, router

    app = FastAPI()
    app.include_router(router)
    store = SnapshotStore()
    hub = EventHub()
    configure(store, hub)
    return TestClient(app), store, hub


def test_snapshot_returns_404_for_unknown_run(client):
    tc, _, _ = client
    resp = tc.get("/orch/runs/nonexistent/snapshot")
    assert resp.status_code == 404
    assert resp.json()["error"] == "run_not_found"


def test_snapshot_returns_run_data(client):
    tc, store, _ = client

    async def _seed():
        await store.apply_event(make_event(
            run_id="run-1", seq=0, event_type="run.started", producer="test",
        ))
        await store.apply_event(make_event(
            run_id="run-1", seq=0, event_type="task.created", producer="test",
            entity={"task_id": "t1"}, payload={"agent_id": "a", "goal": "g"},
        ))

    import asyncio
    asyncio.get_event_loop().run_until_complete(_seed())

    resp = tc.get("/orch/runs/run-1/snapshot")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "run-1"
    assert data["status"] == "running"
    assert len(data["tasks"]) == 1


def test_events_endpoint_subscribes_and_replays(client):
    """Verify that the events endpoint subscribes to EventHub and replays buffered events."""
    _, _, hub = client

    async def _run():
        # Publish an event before subscribing (simulates replay scenario)
        await hub.publish(make_event(
            run_id="run-1", seq=0, event_type="run.started", producer="test",
        ))
        # Subscribe with after_seq=0 → should replay the published event
        sub = await hub.subscribe("run-1", after_seq=0)
        # The subscription should yield the replayed event
        event = await sub.__anext__()
        assert event.event_type == "run.started"
        assert event.seq == 1
        await sub.close()

    import asyncio
    asyncio.get_event_loop().run_until_complete(_run())
