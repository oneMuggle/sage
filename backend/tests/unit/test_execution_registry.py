"""Tests for cooperative lane execution handles."""

from __future__ import annotations

import asyncio

import pytest

from backend.orchestration.execution_registry import ExecutionRegistry


@pytest.mark.asyncio()
async def test_cancel_sets_interrupt_event_without_cancelling_task():
    registry = ExecutionRegistry()
    event = asyncio.Event()
    task = asyncio.create_task(asyncio.sleep(1))
    registry.register("lane-1", task, event)

    assert registry.cancel("lane-1") is True
    assert event.is_set()
    assert not task.cancelled()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio()
async def test_unregister_does_not_remove_newer_registration():
    registry = ExecutionRegistry()
    first_event = asyncio.Event()
    second_event = asyncio.Event()
    first = asyncio.create_task(asyncio.sleep(1))
    second = asyncio.create_task(asyncio.sleep(1))
    registry.register("lane-1", first, first_event)
    registry.register("lane-1", second, second_event)

    registry.unregister("lane-1", first)
    assert registry.get("lane-1").task is second

    first.cancel()
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(asyncio.CancelledError):
        await second


def test_cancel_unknown_lane_returns_false():
    assert ExecutionRegistry().cancel("missing") is False
