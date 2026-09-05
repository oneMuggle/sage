"""Tests for the ``POST /orch/runs/{run_id}/tasks/{task_id}/steer`` endpoint.

Covers:
- 202 happy path (context persisted, events broadcast)
- 409 CAS mismatch (``task_state_changed``)
- 409 terminal task (``task_terminal``)
- 404 unknown run / task
- 400 validation errors (source / message_type / apply_mode / empty content /
  8 KB cap / non-integer expected_task_revision)
- 503 unconfigured dependency
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import orch_run_control
from backend.api.orch_run_control import configure, router
from backend.data.orch_context_repo import OrchestrationContextRepository
from backend.data.orch_task_repo import OrchTaskRepository
from backend.domain.orch_events import make_event
from backend.orchestration.event_hub import EventHub
from backend.orchestration.snapshot_store import SnapshotStore


@pytest.fixture()
def app_deps():
    """Build a FastAPI TestClient wired with all steer dependencies.

    Returns ``(TestClient, SnapshotStore, EventHub, OrchestrationContextRepository,
    OrchTaskRepository)``.

    Also seeds default FK parent rows (``run-1`` / ``t1``) in the temp DB so
    that ``orch_context_messages`` INSERTs succeed (database.py DDL declares
    ``REFERENCES orch_runs(run_id)`` and ``REFERENCES orch_tasks(task_id)``).
    """
    from backend.data.database import get_database

    app = FastAPI()
    app.include_router(router)
    store = SnapshotStore()
    hub = EventHub()
    ctx_repo = OrchestrationContextRepository()
    task_repo = OrchTaskRepository()
    configure(store, hub, context_repo=ctx_repo, task_repo=task_repo)

    conn = get_database().get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO orch_runs "
        "(run_id, session_id, status, created_at, plan_json) "
        "VALUES ('run-1', 'session-1', 'running', 1700000000000, '{}')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO orch_tasks "
        "(task_id, run_id, agent_id, goal, status) "
        "VALUES ('t1', 'run-1', 'agent-1', 'do the thing', 'running')"
    )
    conn.commit()

    return TestClient(app), store, hub, ctx_repo, task_repo


def _seed_run_and_task_sync(store: SnapshotStore, *, run_id="run-1", task_id="t1", revision=1) -> None:
    """Seed a running run + running task into SnapshotStore (sync helper)."""
    async def _go():
        await store.apply_event(make_event(
            run_id=run_id, seq=0, event_type="run.started", producer="test",
        ))
        await store.apply_event(make_event(
            run_id=run_id, seq=0, event_type="task.created", producer="test",
            entity={"task_id": task_id}, payload={"agent_id": "a", "goal": "g"},
        ))
        await store.apply_event(make_event(
            run_id=run_id, seq=0, event_type="task.started", producer="test",
            entity={"task_id": task_id},
        ))
        # Bump revision to target value via task.progress events
        # Each task event increments revision by 1 in SnapshotStore
        # After task.created + task.started = 2 events → revision == 2
        current = store.get_task_revision(run_id, task_id)
        while current is not None and current < revision:
            await store.apply_event(make_event(
                run_id=run_id, seq=0, event_type="task.progress", producer="test",
                entity={"task_id": task_id}, payload={"output_preview": "tick"},
            ))
            current = store.get_task_revision(run_id, task_id)

    asyncio.get_event_loop().run_until_complete(_go())


# ---------------------------------------------------------------- happy path


def test_steer_returns_202_and_persists_context(app_deps) -> None:
    tc, store, hub, ctx_repo, task_repo = app_deps
    _seed_run_and_task_sync(store)
    current_revision = store.get_task_revision("run-1", "t1")

    resp = tc.post(
        "/orch/runs/run-1/tasks/t1/steer",
        json={
            "source": "parent_agent",
            "message_type": "clarification",
            "content_redacted": "clarify target format",
            "apply_mode": "next_boundary",
            "expected_task_revision": current_revision,
            "created_by": "agent-007",
        },
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["task_id"] == "t1"
    assert body["run_id"] == "run-1"
    assert body["apply_mode"] == "next_boundary"
    assert body["status"] == "pending"
    assert body["context_id"].startswith("ctx-")

    # Context row persisted
    msg = ctx_repo.get(body["context_id"])
    assert msg is not None
    assert msg.content_redacted == "clarify target format"
    assert msg.source == "parent_agent"
    assert msg.created_by == "agent-007"

    # DB audit revision bumped (independent of SnapshotStore memory revision)
    db_task = task_repo.get("t1")
    assert db_task is not None
    assert db_task.revision == 1  # first steer → revision = 1


def test_steer_broadcasts_control_events(app_deps) -> None:
    tc, store, hub, _, _ = app_deps
    _seed_run_and_task_sync(store)
    current_revision = store.get_task_revision("run-1", "t1")

    async def _capture():
        sub = await hub.subscribe("run-1", after_seq=0)
        try:
            events = []
            # Drain whatever is already buffered from seeding
            while True:
                try:
                    evt = await asyncio.wait_for(sub.__anext__(), timeout=0.01)
                    events.append(evt)
                except asyncio.TimeoutError:
                    break
            # Now fire the steer request (in a thread — TestClient is sync)
            def _post():
                return tc.post(
                    "/orch/runs/run-1/tasks/t1/steer",
                    json={
                        "message_type": "correction",
                        "content_redacted": "stop using v1 API",
                        "expected_task_revision": current_revision,
                    },
                )
            await asyncio.to_thread(_post)
            # Collect broadcast events
            while True:
                try:
                    evt = await asyncio.wait_for(sub.__anext__(), timeout=0.5)
                    events.append(evt)
                except asyncio.TimeoutError:
                    break
            return events
        finally:
            await sub.close()

    events = asyncio.get_event_loop().run_until_complete(_capture())
    types = [e.event_type for e in events]
    assert "task.context.append_requested" in types
    assert "task.context.appended" in types


# ----------------------------------------------------------- 409 CAS mismatch


def test_steer_returns_409_on_revision_mismatch(app_deps) -> None:
    tc, store, _, _, _ = app_deps
    _seed_run_and_task_sync(store, revision=5)

    resp = tc.post(
        "/orch/runs/run-1/tasks/t1/steer",
        json={
            "message_type": "clarification",
            "content_redacted": "x",
            "expected_task_revision": 1,  # stale
        },
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] == "task_state_changed"
    assert body["expected_task_revision"] == 1
    assert body["current_task_revision"] == store.get_task_revision("run-1", "t1")


def test_steer_requires_expected_revision(app_deps) -> None:
    """Every steer request must participate in optimistic concurrency control."""
    tc, store, _, _, _ = app_deps
    _seed_run_and_task_sync(store, revision=7)

    resp = tc.post(
        "/orch/runs/run-1/tasks/t1/steer",
        json={
            "message_type": "clarification",
            "content_redacted": "missing CAS revision",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "missing_expected_task_revision"


# ----------------------------------------------------------- 409 terminal task


def test_steer_returns_409_when_task_succeeded(app_deps) -> None:
    tc, store, _, _, _ = app_deps

    async def _seed_terminal():
        await store.apply_event(make_event(
            run_id="run-1", seq=0, event_type="run.started", producer="test",
        ))
        await store.apply_event(make_event(
            run_id="run-1", seq=0, event_type="task.created", producer="test",
            entity={"task_id": "t1"}, payload={"agent_id": "a", "goal": "g"},
        ))
        await store.apply_event(make_event(
            run_id="run-1", seq=0, event_type="task.succeeded", producer="test",
            entity={"task_id": "t1"}, payload={"output_preview": "done"},
        ))

    asyncio.get_event_loop().run_until_complete(_seed_terminal())

    resp = tc.post(
        "/orch/runs/run-1/tasks/t1/steer",
        json={
            "message_type": "clarification",
            "content_redacted": "x",
            "expected_task_revision": store.get_task_revision("run-1", "t1") or 0,
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"] == "task_terminal"
    assert resp.json()["task_status"] == "succeeded"


def test_steer_returns_409_when_task_failed(app_deps) -> None:
    tc, store, _, _, _ = app_deps

    async def _seed_terminal():
        await store.apply_event(make_event(
            run_id="run-1", seq=0, event_type="run.started", producer="test",
        ))
        await store.apply_event(make_event(
            run_id="run-1", seq=0, event_type="task.created", producer="test",
            entity={"task_id": "t1"}, payload={"agent_id": "a", "goal": "g"},
        ))
        await store.apply_event(make_event(
            run_id="run-1", seq=0, event_type="task.failed", producer="test",
            entity={"task_id": "t1"}, payload={"error": "boom"},
        ))

    asyncio.get_event_loop().run_until_complete(_seed_terminal())

    resp = tc.post(
        "/orch/runs/run-1/tasks/t1/steer",
        json={
            "message_type": "clarification",
            "content_redacted": "x",
            "expected_task_revision": store.get_task_revision("run-1", "t1") or 0,
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"] == "task_terminal"


# --------------------------------------------------------------------------- 404


def test_steer_returns_404_unknown_run(app_deps) -> None:
    tc, _, _, _, _ = app_deps
    resp = tc.post(
        "/orch/runs/unknown-run/tasks/t1/steer",
        json={
            "message_type": "clarification",
            "content_redacted": "x",
            "expected_task_revision": 0,
        },
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "run_not_found"


def test_steer_returns_404_unknown_task(app_deps) -> None:
    tc, store, _, _, _ = app_deps
    _seed_run_and_task_sync(store)

    resp = tc.post(
        "/orch/runs/run-1/tasks/missing-task/steer",
        json={
            "message_type": "clarification",
            "content_redacted": "x",
            "expected_task_revision": 0,
        },
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "task_not_found"


# ------------------------------------------------------------------------- 400


def test_steer_rejects_invalid_source(app_deps) -> None:
    tc, store, _, _, _ = app_deps
    _seed_run_and_task_sync(store)

    resp = tc.post(
        "/orch/runs/run-1/tasks/t1/steer",
        json={"source": "attacker", "message_type": "clarification", "content_redacted": "x"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_source"


def test_steer_rejects_invalid_message_type(app_deps) -> None:
    tc, store, _, _, _ = app_deps
    _seed_run_and_task_sync(store)

    resp = tc.post(
        "/orch/runs/run-1/tasks/t1/steer",
        json={"message_type": "do_anything", "content_redacted": "x"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_message_type"


def test_steer_rejects_invalid_apply_mode(app_deps) -> None:
    tc, store, _, _, _ = app_deps
    _seed_run_and_task_sync(store)

    resp = tc.post(
        "/orch/runs/run-1/tasks/t1/steer",
        json={
            "message_type": "clarification",
            "content_redacted": "x",
            "apply_mode": "immediately",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_apply_mode"


def test_steer_rejects_empty_content(app_deps) -> None:
    tc, store, _, _, _ = app_deps
    _seed_run_and_task_sync(store)

    resp = tc.post(
        "/orch/runs/run-1/tasks/t1/steer",
        json={"message_type": "clarification", "content_redacted": "   "},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "empty_content"


def test_steer_rejects_content_over_8kb(app_deps) -> None:
    tc, store, _, _, _ = app_deps
    _seed_run_and_task_sync(store)

    resp = tc.post(
        "/orch/runs/run-1/tasks/t1/steer",
        json={"message_type": "clarification", "content_redacted": "x" * (8 * 1024 + 1)},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "content_too_large"


def test_steer_rejects_non_integer_expected_revision(app_deps) -> None:
    tc, store, _, _, _ = app_deps
    _seed_run_and_task_sync(store)

    resp = tc.post(
        "/orch/runs/run-1/tasks/t1/steer",
        json={
            "message_type": "clarification",
            "content_redacted": "x",
            "expected_task_revision": "three",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_expected_task_revision"


def test_steer_rejects_invalid_json_body(app_deps) -> None:
    tc, store, _, _, _ = app_deps
    _seed_run_and_task_sync(store)

    resp = tc.post(
        "/orch/runs/run-1/tasks/t1/steer",
        content=b"not json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_json"


# ------------------------------------------------------------------------- 503


def test_steer_returns_503_when_unconfigured() -> None:
    """Without context_repo/task_repo wired, steer must 503, not 500."""
    # Reset module state to simulate startup before configure() runs
    orch_run_control._context_repo = None  # type: ignore[attr-defined]
    orch_run_control._task_repo = None  # type: ignore[attr-defined]

    app = FastAPI()
    app.include_router(router)
    # configure() intentionally NOT called
    tc = TestClient(app)
    try:
        resp = tc.post(
            "/orch/runs/run-1/tasks/t1/steer",
            json={"message_type": "clarification", "content_redacted": "x"},
        )
        assert resp.status_code == 503
        assert resp.json()["error"] == "not_initialized"
    finally:
        # Restore by calling configure with fresh deps (other tests depend on it)
        configure(SnapshotStore(), EventHub(),
                  context_repo=OrchestrationContextRepository(),
                  task_repo=OrchTaskRepository())
