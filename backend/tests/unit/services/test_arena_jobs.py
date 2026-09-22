"""Unit tests for backend/services/arena_jobs.py."""

import threading

import pytest

from backend.services.arena_jobs import JobStore


def test_create_and_snapshot():
    store = JobStore()
    job = store.create("registration", total=5, params={"count": 5})
    assert job.status == "running"
    snap = store.get(job.id).snapshot()
    assert snap["kind"] == "registration"
    assert snap["total"] == 5
    assert snap["done"] == 0
    assert snap["last_seq"] == 0
    assert store.list()[0]["id"] == job.id


def test_create_rejects_unknown_kind():
    store = JobStore()
    with pytest.raises(ValueError, match="unknown job kind"):
        store.create("scraper", total=1)


def test_events_seq_monotonic_and_after_filter():
    store = JobStore()
    job = store.create("registration", total=3)
    for i in range(5):
        store.append_event(job.id, "info", "log", f"m{i}")
    events = store.events_after(job.id)
    assert [e.seq for e in events] == [1, 2, 3, 4, 5]
    assert store.events_after(job.id, after_seq=3) == [e for e in events if e.seq > 3]
    assert store.get(job.id).snapshot()["last_seq"] == 5


def test_append_event_unknown_job_returns_none():
    store = JobStore()
    assert store.append_event("nope", "info", "log", "x") is None
    assert store.events_after("nope") == []


def test_event_ndjson_shape():
    store = JobStore()
    job = store.create("draw", total=1)
    event = store.append_event(
        job.id, "warn", "gate", "429 退避 30s", {"level": 2, "left_sec": 30}
    )
    import json

    payload = json.loads(event.to_ndjson())
    assert payload["seq"] == 1
    assert payload["level"] == "warn"
    assert payload["kind"] == "gate"
    assert payload["message"] == "429 退避 30s"
    assert payload["data"] == {"level": 2, "left_sec": 30}
    assert payload["ts"]


def test_stop_flow():
    store = JobStore()
    job = store.create("registration", total=9)
    assert store.is_stop_requested(job.id) is False
    assert store.request_stop(job.id) is True
    assert store.is_stop_requested(job.id) is True
    assert store.get(job.id).status == "stopping"
    assert store.request_stop("nope") is False


def test_finish_statuses():
    store = JobStore()
    job = store.create("registration", total=2)
    store.finish(job.id, "done", ok_count=2, failed_count=0)
    snap = store.get(job.id).snapshot()
    assert snap["status"] == "done"
    assert snap["ok"] == 2 and snap["failed"] == 0 and snap["done"] == 2
    with pytest.raises(ValueError, match="invalid final status"):
        store.finish(job.id, "running")


def test_threaded_appends_are_safe():
    store = JobStore()
    job = store.create("registration", total=100)

    def spam():
        for _ in range(200):
            store.append_event(job.id, "info", "log", "x")

    threads = [threading.Thread(target=spam) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    events = store.events_after(job.id)
    assert len(events) == 800
    assert [e.seq for e in events] == sorted(e.seq for e in events)  # no gaps/dupes
