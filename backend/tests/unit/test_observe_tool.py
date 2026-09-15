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


@pytest.mark.asyncio()
async def test_observe_sync_execute_works_inside_running_loop():
    """O4 (2026-09-08): run_loop 对非特判工具走同步直调 —— 事件循环运行中
    调 ``execute`` 必须返回快照而非自拒错误（旧实现 asyncio.run 检测到
    running loop 即返回"应在 async 上下文调用"，工具注册后 conductor
    实际永远拿到错误）。"""
    store = SnapshotStore()
    await store.apply_event(make_event(
        run_id="run-sync", seq=0, event_type="run.started", producer="test",
    ))
    await store.apply_event(make_event(
        run_id="run-sync", seq=1, event_type="task.created", producer="test",
        entity={"task_id": "t1"}, payload={"agent_id": "a", "goal": "g"},
    ))
    tool = ObserveSubagentsTool(snapshot_store=store)
    # 本测试本身跑在 running loop 内 —— 直接同步调用 execute()
    result = tool.execute(run_id="run-sync")
    assert result.success is True
    data = json.loads(result.content)
    assert data["run_status"] == "running"
    assert len(data["tasks"]) == 1


@pytest.mark.asyncio()
async def test_observe_sync_execute_matches_async_payload():
    """同步与异步通路返回同一 payload（同一 _read_snapshot 实现）。"""
    store = SnapshotStore()
    await store.apply_event(make_event(
        run_id="run-parity", seq=0, event_type="run.started", producer="test",
    ))
    tool = ObserveSubagentsTool(snapshot_store=store)
    sync_result = tool.execute(run_id="run-parity")
    async_result = await tool.execute_async(run_id="run-parity")
    assert sync_result.success is True
    assert async_result.success is True
    assert json.loads(sync_result.content) == json.loads(async_result.content)
