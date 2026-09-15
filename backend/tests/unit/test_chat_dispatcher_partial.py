"""BD6 (round17) — collect 超时返回部分聚合单测。

- wait_background 超时后 partial_aggregate 返回已完成产出与进度计数
- CollectSubagentsTool 超时路径返回 success 载荷（status=partial + note）
- 无在飞派发时 partial_aggregate 抛 RuntimeError
"""

from __future__ import annotations

import asyncio

import pytest

from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.tests.unit.test_chat_dispatcher import _make_queue
from backend.tools.subagent_tool import CollectSubagentsTool


def _init_tmp_db(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "bd6.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


@pytest.mark.asyncio
async def test_collect_timeout_returns_partial_aggregate(tmp_path, monkeypatch):
    """t1 快 t2 慢：collect 超时 → partial 载荷含 t1 结果；再 collect 收全量。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-bd6-1")
    d._semaphore = asyncio.Semaphore(4)

    async def fake_run(state):
        if state.task_id == "t2":
            await asyncio.sleep(0.5)
            state.status = "done"
            return "慢结果 t2"
        state.status = "done"
        return "快结果 t1"

    d._run_subagent = fake_run
    d.start_background_dispatch(
        [
            {"task_id": "t1", "agent_id": "primary", "goal": "g1"},
            {"task_id": "t2", "agent_id": "primary", "goal": "g2"},
        ]
    )
    await asyncio.sleep(0.2)  # t1 完成、t2 在跑

    tool = CollectSubagentsTool(d)
    partial = await tool.execute_async(timeout_secs=0.05)
    assert partial.success is True
    content = partial.content
    assert content["status"] == "partial"
    assert content["done"] == 1
    assert content["total"] == 2
    assert "快结果 t1" in content["aggregate"]
    assert "再次 collect_subagents" in content["note"]
    assert "提前汇总" in content["note"]

    # 全部完成后再次 collect → 全量聚合
    await d.wait_background(timeout=5)
    full = await tool.execute_async()
    assert full.success is True
    assert "慢结果 t2" in full.content


@pytest.mark.asyncio
async def test_partial_aggregate_without_dispatch_raises(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s2", entry_queue=queue, run_id="orch-bd6-2")
    with pytest.raises(RuntimeError, match="no_background_dispatch"):
        d.partial_aggregate()


@pytest.mark.asyncio
async def test_partial_aggregate_counts_failed(tmp_path, monkeypatch):
    """failed 任务计入 total，聚合头带失败摘要（既有 _aggregate 语义）。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s3", entry_queue=queue, run_id="orch-bd6-3")
    d._semaphore = asyncio.Semaphore(4)

    async def fail_run(state):
        raise RuntimeError("源任务失败")

    d._run_subagent = fail_run
    d.start_background_dispatch(
        [{"task_id": "t1", "agent_id": "primary", "goal": "g1"}]
    )
    handle = d._bg_task
    assert handle is not None
    await handle

    snap = d.partial_aggregate()
    assert snap["status"] == "partial"
    assert snap["done"] == 0
    assert "失败" in snap["aggregate"]
