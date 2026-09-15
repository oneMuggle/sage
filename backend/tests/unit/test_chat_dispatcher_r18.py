"""BD7/BU7（round18）— 快照聚合增强与预算预警单测。

- BD7: background_snapshot 增 aggregate（当前部分聚合）与 budget_exceeded
  标志；none 态不聚合。
- BU7: _check_run_budget 在用量跨过 80% 预算时打一次性 WARNING 预警
  （不改变守门行为）；触顶仍正常收口。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.tests.unit.test_chat_dispatcher import _make_queue


def _init_tmp_db(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "r18.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


def _seed_usage(session_id: str, total_tokens: int, created_at_ms: int) -> None:
    import uuid

    from backend.data.database import get_database

    conn = get_database().get_connection()
    conn.execute(
        "INSERT INTO usage_events (id, session_id, model, prompt_tokens,"
        " completion_tokens, total_tokens, estimated_cost_usd, created_at, cached_tokens)"
        " VALUES (?, ?, 'test-model', 0, 0, ?, 0.0, ?, 0)",
        (str(uuid.uuid4()), session_id, total_tokens, created_at_ms),
    )
    conn.commit()


# ---- BD7: 快照聚合增强 --------------------------------------------------------


@pytest.mark.asyncio()
async def test_snapshot_includes_partial_aggregate(tmp_path, monkeypatch):
    """wait=false 快照含 aggregate 字段（部分聚合 markdown）。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-r18-1")
    d._semaphore = asyncio.Semaphore(4)

    async def fake_run(state):
        state.status = "done"
        return f"结果 {state.task_id}"

    d._run_subagent = fake_run
    d.start_background_dispatch(
        [{"task_id": "t1", "agent_id": "primary", "goal": "g1"}]
    )
    handle = d._bg_task
    assert handle is not None
    await handle

    snap = d.background_snapshot()
    assert snap["status"] == "completed"
    assert "aggregate" in snap
    assert "结果 t1" in snap["aggregate"]
    assert snap["budget_exceeded"] is False


@pytest.mark.asyncio()
async def test_snapshot_none_state_has_no_aggregate(tmp_path, monkeypatch):
    """从未后台派发 → none 态不带 aggregate（无 states 可聚合）。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s2", entry_queue=queue, run_id="orch-r18-2")
    snap = d.background_snapshot()
    assert snap["status"] == "none"
    assert "aggregate" not in snap
    assert snap["budget_exceeded"] is False


# ---- BU7: 预算预警 ------------------------------------------------------------


@pytest.mark.asyncio()
async def test_budget_warning_at_80_percent(tmp_path, monkeypatch, caplog):
    """用量跨过预算 80% → 一次性 WARNING 预警；守门不触发。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s3",
        entry_queue=queue,
        run_id="orch-r18-3",
        session_id="sess-r18",
    )
    d._semaphore = asyncio.Semaphore(4)
    d.settings.run_token_budget = 1000

    import time

    async def fake_run(state):
        _seed_usage("sess-r18", 900, int(time.time() * 1000))  # 90% — 预警区间
        state.status = "done"
        return "ok"

    d._run_subagent = fake_run
    with caplog.at_level("WARNING", logger="backend.orchestration.chat_dispatcher"):
        await d.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g1"}])

    assert d._budget_exceeded is False  # 未触顶，守门不动
    assert any("接近 token 预算上限" in r.message for r in caplog.records)


def test_budget_warning_not_repeated(tmp_path, monkeypatch, caplog):
    """80% 预警一次性 —— 重复守门调用不重复打（_budget_warned 防刷）。"""
    import time


    _seed_usage("sess-r18", 850, int(time.time() * 1000))
    d = ChatDispatcher(
        stream_id="s4",
        entry_queue=_make_queue(),
        run_id="orch-r18-4",
        session_id="sess-r18",
    )
    d.settings.run_token_budget = 1000
    d._first_dispatch_at = time.time() - 10  # 窗口起点（秒）

    d._check_run_budget()
    d._check_run_budget()
    d._check_run_budget()

    warns = [
        rec
        for rec in caplog.records
        if rec.levelname == "WARNING" and "接近 token 预算上限" in rec.getMessage()
    ]
    assert len(warns) == 1
