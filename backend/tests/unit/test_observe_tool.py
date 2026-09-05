"""Tests for observe_subagents tool."""

from __future__ import annotations

import json

import pytest

from backend.domain.orch_events import make_event
from backend.orchestration.snapshot_store import SnapshotStore
from backend.tools.observe_tool import ObserveSubagentsTool


@pytest.mark.asyncio()
async def test_observe_returns_snapshot():
    store = SnapshotStore()
    await store.apply_event(make_event(
        run_id="run-1", seq=0, event_type="run.started", producer="test",
    ))
    await store.apply_event(make_event(
        run_id="run-1", seq=0, event_type="task.created", producer="test",
        entity={"task_id": "t1"}, payload={"agent_id": "a", "goal": "g"},
    ))
    tool = ObserveSubagentsTool(snapshot_store=store)
    result = await tool.execute_async(run_id="run-1")
    assert result.success is True
    data = json.loads(result.content)
    assert data["run_status"] == "running"
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["task_id"] == "t1"


@pytest.mark.asyncio()
async def test_observe_filters_by_task_ids():
    store = SnapshotStore()
    for tid in ["t1", "t2", "t3"]:
        await store.apply_event(make_event(
            run_id="run-1", seq=0, event_type="task.created", producer="test",
            entity={"task_id": tid}, payload={"agent_id": "a", "goal": "g"},
        ))
    tool = ObserveSubagentsTool(snapshot_store=store)
    result = await tool.execute_async(run_id="run-1", task_ids=["t1", "t3"])
    data = json.loads(result.content)
    assert len(data["tasks"]) == 2
    ids = {t["task_id"] for t in data["tasks"]}
    assert ids == {"t1", "t3"}


@pytest.mark.asyncio()
async def test_observe_unknown_run():
    store = SnapshotStore()
    tool = ObserveSubagentsTool(snapshot_store=store)
    result = await tool.execute_async(run_id="missing")
    assert result.success is False
    assert "不存在" in result.error


@pytest.mark.asyncio()
async def test_observe_missing_run_id():
    store = SnapshotStore()
    tool = ObserveSubagentsTool(snapshot_store=store)
    result = await tool.execute_async()
    assert result.success is False
    assert "run_id" in result.error


@pytest.mark.asyncio()
async def test_observe_default_run_id():
    store = SnapshotStore()
    await store.apply_event(make_event(
        run_id="default-run", seq=0, event_type="run.started", producer="test",
    ))
    tool = ObserveSubagentsTool(snapshot_store=store, default_run_id="default-run")
    result = await tool.execute_async()
    assert result.success is True
    data = json.loads(result.content)
    assert data["run_id"] == "default-run"
