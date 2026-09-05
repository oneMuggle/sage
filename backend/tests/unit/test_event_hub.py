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
