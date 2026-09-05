"""In-process pub/sub hub for realtime orchestration run events."""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from typing import Awaitable, Callable, Deque, Dict, Optional, Protocol, cast

from backend.domain.orch_events import RunEvent


class _EventRepository(Protocol):
    def max_seq(self, run_id: str) -> int: ...
    def append(self, event: RunEvent) -> None: ...
    def list_after(self, run_id: str, after_seq: int = 0, limit: int = 1000) -> list[RunEvent]: ...
    def list_runs(self) -> list[str]: ...


@dataclass
class _Subscriber:
    queue: asyncio.Queue[object]
    dropped_count: int = 0
    closed: bool = False


class EventSubscription:
    """Async iterator over one subscriber's independent event queue."""

    def __init__(self, hub: EventHub, run_id: str, subscriber: _Subscriber) -> None:
        self._hub = hub
        self.run_id = run_id
        self._subscriber = subscriber

    @property
    def dropped_count(self) -> int:
        return self._subscriber.dropped_count

    async def __anext__(self) -> RunEvent:
        if self._subscriber.closed and self._subscriber.queue.empty():
            raise StopAsyncIteration
        item = await self._subscriber.queue.get()
        if item is _CLOSE:
            raise StopAsyncIteration
        return cast(RunEvent, item)

    def __aiter__(self) -> EventSubscription:
        return self

    async def close(self) -> None:
        await self._hub.unsubscribe(self)


_CLOSE = object()


class EventHub:
    """Per-run event hub with replayable bounded history.

    Publishing never awaits a subscriber. A subscriber whose queue is full loses
    only its own newest event, while other subscribers continue receiving events.
    """

    def __init__(
        self,
        history_size: int = 1000,
        subscriber_queue_size: int = 1000,
        event_repository: Optional[_EventRepository] = None,
        event_applier: Optional[Callable[[RunEvent], Awaitable[None]]] = None,
    ) -> None:
        if history_size < 1 or subscriber_queue_size < 1:
            raise ValueError("history_size and subscriber_queue_size must be positive")
        self.history_size = history_size
        self.subscriber_queue_size = subscriber_queue_size
        self._history: Dict[str, Deque[RunEvent]] = defaultdict(
            lambda: deque(maxlen=history_size)
        )
        self._next_seq: Dict[str, int] = defaultdict(int)
        self._event_repository = event_repository
        self._event_applier = event_applier
        self._subscribers: Dict[str, list[_Subscriber]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def publish(self, event: RunEvent) -> RunEvent:
        """Assign the next run-local sequence, persist, and broadcast."""
        async with self._lock:
            if event.run_id not in self._next_seq and self._event_repository is not None:
                self._next_seq[event.run_id] = self._event_repository.max_seq(event.run_id)
            seq = self._next_seq[event.run_id] + 1
            self._next_seq[event.run_id] = seq
            event = replace(event, seq=seq) if event.seq != seq else event
            self._history[event.run_id].append(event)
            if self._event_repository is not None:
                self._event_repository.append(event)
            if self._event_applier is not None:
                await self._event_applier(event)
            for subscriber in tuple(self._subscribers[event.run_id]):
                if subscriber.closed:
                    continue
                try:
                    subscriber.queue.put_nowait(event)
                except asyncio.QueueFull:
                    subscriber.dropped_count += 1
            return event

    async def restore_run(self, run_id: str) -> int:
        """Replay persisted events for one run into history and snapshot state."""
        if self._event_repository is None:
            return 0
        async with self._lock:
            start_seq = self._next_seq[run_id]
            events = self._event_repository.list_after(run_id, after_seq=start_seq)
            for event in events:
                self._history[run_id].append(event)
                self._next_seq[run_id] = max(self._next_seq[run_id], event.seq)
                if self._event_applier is not None:
                    await self._event_applier(event)
            return len(events)

    async def restore_runs(self, run_ids: Optional[list[str]] = None) -> int:
        """Replay persisted events for selected runs, or all known runs."""
        if self._event_repository is None:
            return 0
        if run_ids is None:
            run_ids = [run.run_id for run in self._event_repository.list_runs()]
        restored = 0
        for run_id in run_ids:
            restored += await self.restore_run(run_id)
        return restored

    async def subscribe(self, run_id: str, after_seq: int = 0) -> EventSubscription:
        """Subscribe to a run, replaying retained and persisted events atomically."""
        if after_seq < 0:
            raise ValueError("after_seq must be non-negative")
        subscriber = _Subscriber(asyncio.Queue(maxsize=self.subscriber_queue_size))
        async with self._lock:
            replay = [event for event in self._history[run_id] if event.seq > after_seq]
            if self._event_repository is not None and hasattr(
                self._event_repository, "list_after"
            ):
                persisted = self._event_repository.list_after(run_id, after_seq=after_seq)
                known = {event.event_id for event in replay}
                replay.extend(event for event in persisted if event.event_id not in known)
                replay.sort(key=lambda event: event.seq)
                for event in persisted:
                    if event.event_id not in known:
                        self._history[run_id].append(event)
                        self._next_seq[run_id] = max(self._next_seq[run_id], event.seq)
                        if self._event_applier is not None:
                            await self._event_applier(event)
            for event in replay:
                try:
                    subscriber.queue.put_nowait(event)
                except asyncio.QueueFull:
                    subscriber.dropped_count += 1
                    break
            self._subscribers[run_id].append(subscriber)
        return EventSubscription(self, run_id, subscriber)

    async def unsubscribe(self, subscription: EventSubscription) -> None:
        """Remove a subscription and wake a pending consumer."""
        subscriber = subscription._subscriber
        async with self._lock:
            if subscriber.closed:
                return
            subscriber.closed = True
            subscribers = self._subscribers[subscription.run_id]
            with contextlib.suppress(ValueError):
                subscribers.remove(subscriber)
            with contextlib.suppress(asyncio.QueueFull):
                subscriber.queue.put_nowait(_CLOSE)

    def subscriber_count(self, run_id: Optional[str] = None) -> int:
        """Return active subscriber count, optionally scoped to one run."""
        if run_id is not None:
            return sum(not sub.closed for sub in self._subscribers[run_id])
        return sum(not sub.closed for subs in self._subscribers.values() for sub in subs)


__all__ = ["EventHub", "EventSubscription"]
