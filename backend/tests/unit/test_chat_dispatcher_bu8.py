"""BU8（round19）— 聚合头部消耗可见性单测。

预算开启时 _aggregate 头部追加"已消耗 X / 预算 M tokens（P%）"行；
预算关闭 / session 未归因 / 查询失败时不展示（fail-open）。
"""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.tests.unit.test_chat_dispatcher import _make_queue


def _init_tmp_db(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "bu8.db"))
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


@pytest.mark.asyncio
async def test_aggregate_header_shows_budget_consumption(tmp_path, monkeypatch):
    """预算开启 → 聚合头展示已消耗/预算与百分比。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=queue,
        run_id="orch-bu8-1",
        session_id="sess-bu8",
    )
    d._semaphore = asyncio.Semaphore(4)
    d.settings.run_token_budget = 1000
    d._first_dispatch_at = time.time() - 10
    _seed_usage("sess-bu8", 400, int(time.time() * 1000))

    async def fake_run(state):
        state.status = "done"
        return "ok"

    d._run_subagent = fake_run
    aggregated = await d.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g1"}])
    assert "已消耗" in aggregated
    assert "/ 预算 1000 tokens" in aggregated


@pytest.mark.asyncio
async def test_aggregate_header_no_budget_line_when_disabled(tmp_path, monkeypatch):
    """预算关闭（0）→ 头部无消耗行。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s2",
        entry_queue=queue,
        run_id="orch-bu8-2",
        session_id="sess-bu8",
    )
    d._semaphore = asyncio.Semaphore(4)

    async def fake_run(state):
        state.status = "done"
        return "ok"

    d._run_subagent = fake_run
    aggregated = await d.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g1"}])
    assert "已消耗" not in aggregated
