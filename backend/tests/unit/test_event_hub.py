"""EventHub contract tests for Phase 1 realtime orchestration monitoring."""

from __future__ import annotations

import asyncio

import pytest

from backend.domain.orch_events import RunEventType, make_event
from backend.orchestration.event_hub import EventHub


@pytest.mark.asyncio()
async def test_publish_assigns_monotonic_seq_per_run_and_subscriber_receives() -> None:
    hub = EventHub(history_size=10)
    subscription = await hub.subscribe("run-1")

    first = await hub.publish(
        make_event(run_id="run-1", seq=999, event_type=RunEventType.RUN_CREATED.value, producer="test")
    )
    second = await hub.publish(
        make_event(run_id="run-1", seq=999, event_type=RunEventType.RUN_STARTED.value, producer="test")
    )
    other = await hub.publish(
        make_event(run_id="run-2", seq=999, event_type=RunEventType.RUN_CREATED.value, producer="test")
    )

    assert (first.seq, second.seq, other.seq) == (1, 2, 1)
    assert (await subscription.__anext__()).seq == 1
    assert (await subscription.__anext__()).seq == 2
    await subscription.close()


@pytest.mark.asyncio()
async def test_subscribe_after_seq_replays_history_then_live_events() -> None:
    hub = EventHub(history_size=10)
    for _ in range(4):
        await hub.publish(make_event(run_id="run-1", seq=0, event_type="progress", producer="test"))

    subscription = await hub.subscribe("run-1", after_seq=2)
    assert [
        (await asyncio.wait_for(subscription.__anext__(), timeout=0.1)).seq
        for _ in range(2)
    ] == [3, 4]

    await hub.publish(make_event(run_id="run-1", seq=0, event_type="live", producer="test"))
    assert (await asyncio.wait_for(subscription.__anext__(), timeout=0.1)).seq == 5
    await subscription.close()


@pytest.mark.asyncio()
async def test_slow_subscriber_does_not_block_other_subscriber() -> None:
    hub = EventHub(history_size=10, subscriber_queue_size=1)
    slow = await hub.subscribe("run-1")
    fast = await hub.subscribe("run-1")

    await hub.publish(make_event(run_id="run-1", seq=0, event_type="one", producer="test"))
    assert (await asyncio.wait_for(fast.__anext__(), timeout=0.1)).seq == 1
    await hub.publish(make_event(run_id="run-1", seq=0, event_type="two", producer="test"))

    assert (await asyncio.wait_for(fast.__anext__(), timeout=0.1)).seq == 2
    assert slow.dropped_count == 1
    await slow.close()
    await fast.close()


@pytest.mark.asyncio()
async def test_publish_calls_event_applier() -> None:
    applied = []

    async def apply(event) -> None:
        applied.append(event)

    hub = EventHub(event_applier=apply)
    published = await hub.publish(
        make_event(run_id="run-1", seq=0, event_type="run.started", producer="test")
    )

    assert applied == [published]


@pytest.mark.asyncio()
async def test_publish_restores_sequence_from_repository() -> None:
    class Repository:
        def __init__(self) -> None:
            self.appended: list = []

        def max_seq(self, run_id: str) -> int:
            assert run_id == "run-1"
            return 7

        def append(self, event) -> None:
            self.appended.append(event)

    repo = Repository()
    hub = EventHub(event_repository=repo)
    event = await hub.publish(make_event(run_id="run-1", seq=0, event_type="resumed", producer="test"))
    assert event.seq == 8
    assert len(repo.appended) == 1
    assert repo.appended[0].seq == 8
    hub = EventHub()
    subscription = await hub.subscribe("run-1")
    await subscription.close()
    await hub.publish(make_event(run_id="run-1", seq=0, event_type="done", producer="test"))
    assert hub.subscriber_count("run-1") == 0


@pytest.mark.asyncio()
async def test_restore_runs_default_branch_replays_from_list_runs_returning_str_ids() -> None:
    """Regression guard for PR #1786: list_runs() returns List[str] per protocol
    contract; restore_runs() must not assume objects with a ``run_id`` attribute.
    Without the fix this crashed with AttributeError: 'str' object has no
    attribute 'run_id', which broke backend startup on any machine with
    pre-existing orch_events rows.
    """
    class Repository:
        def __init__(self) -> None:
            self.events: dict[str, list] = {"run-a": [], "run-b": []}
            self.replayed: list[str] = []

        def list_runs(self) -> list[str]:
            return ["run-a", "run-b"]

        def list_after(self, run_id: str, after_seq: int = 0, limit: int = 1000):
            return [e for e in self.events[run_id] if e.seq > after_seq]

        def append(self, event) -> None:
            self.events.setdefault(event.run_id, []).append(event)

        def max_seq(self, run_id: str) -> int:
            seqs = [e.seq for e in self.events.get(run_id, [])]
            return max(seqs) if seqs else 0

    repo = Repository()
    repo.events["run-a"] = [
        make_event(run_id="run-a", seq=1, event_type="run.started", producer="p"),
        make_event(run_id="run-a", seq=2, event_type="progress", producer="p"),
    ]
    repo.events["run-b"] = [
        make_event(run_id="run-b", seq=1, event_type="run.started", producer="p"),
    ]

    hub = EventHub(event_repository=repo)
    restored = await hub.restore_runs()

    assert restored == 3
    assert hub.subscriber_count("run-a") == 0
    assert hub.subscriber_count("run-b") == 0
    # history was populated from persisted events
    assert len(hub._history["run-a"]) == 2
    assert len(hub._history["run-b"]) == 1
