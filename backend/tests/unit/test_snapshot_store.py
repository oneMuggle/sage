"""Tests for SnapshotStore — Phase 1 backend observability."""

from __future__ import annotations

import pytest

from backend.domain.orch_events import make_event
from backend.orchestration.snapshot_store import SnapshotStore


@pytest.mark.asyncio()
async def test_apply_run_event_updates_status():
    store = SnapshotStore()
    event = make_event(run_id="run-1", seq=0, event_type="run.started", producer="test")
    await store.apply_event(event)
    snapshot = store.get_run_snapshot("run-1")
    assert snapshot is not None
    assert snapshot.status == "running"
    assert snapshot.run_id == "run-1"


@pytest.mark.asyncio()
async def test_apply_task_event_creates_task():
    store = SnapshotStore()
    event = make_event(
        run_id="run-1",
        seq=0,
        event_type="task.created",
        producer="test",
        entity={"task_id": "t1", "agent_id": "researcher"},
        payload={"agent_id": "researcher", "goal": "research topic"},
    )
    await store.apply_event(event)
    snapshot = store.get_run_snapshot("run-1")
    assert snapshot is not None
    assert len(snapshot.tasks) == 1
    assert snapshot.tasks[0].task_id == "t1"
    assert snapshot.tasks[0].status == "pending"


@pytest.mark.asyncio()
async def test_old_worker_cannot_overwrite_new_state():
    store = SnapshotStore()
    new = make_event(
        run_id="run-1", seq=0, event_type="run.completed",
        producer="test", producer_generation=2,
    )
    await store.apply_event(new)
    old = make_event(
        run_id="run-1", seq=1, event_type="run.started",
        producer="test", producer_generation=1,
    )
    await store.apply_event(old)
    snapshot = store.get_run_snapshot("run-1")
    assert snapshot.status == "completed"


@pytest.mark.asyncio()
async def test_summary_counts_tasks_by_status():
    store = SnapshotStore()
    await store.apply_event(make_event(
        run_id="run-1", seq=0, event_type="task.created", producer="test",
        entity={"task_id": "t1"}, payload={"agent_id": "a", "goal": "g"},
    ))
    await store.apply_event(make_event(
        run_id="run-1", seq=0, event_type="task.started", producer="test",
        entity={"task_id": "t1"},
    ))
    await store.apply_event(make_event(
        run_id="run-1", seq=0, event_type="task.created", producer="test",
        entity={"task_id": "t2"}, payload={"agent_id": "b", "goal": "g2"},
    ))
    snapshot = store.get_run_snapshot("run-1")
    assert snapshot.summary["total"] == 2
    assert snapshot.summary.get("running", 0) == 1
    assert snapshot.summary.get("pending", 0) == 1


@pytest.mark.asyncio()
async def test_unknown_run_returns_none():
    store = SnapshotStore()
    assert store.get_run_snapshot("nonexistent") is None


@pytest.mark.asyncio()
async def test_list_run_ids():
    store = SnapshotStore()
    await store.apply_event(make_event(run_id="run-1", seq=0, event_type="run.created", producer="test"))
    await store.apply_event(make_event(run_id="run-2", seq=0, event_type="run.created", producer="test"))
    assert set(store.list_run_ids()) == {"run-1", "run-2"}
