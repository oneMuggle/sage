"""BU11（round21）— run 级墙钟上限守门单测。

- 超限 → _wall_clock_exceeded 置位 + _cancelled 传播收口
- 归因：queued 收口任务 error = wall_clock_exceeded: …（先于用户取消判断）
- 关闭（0）/ 未超限 → 零影响；设置键映射正确
"""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.tests.unit.test_chat_dispatcher import _make_queue


def _init_tmp_db(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "wallclock.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


@pytest.mark.asyncio()
async def test_wall_clock_exceeded_stops_queued_tasks(tmp_path, monkeypatch):
    """t1 完成后守门发现墙钟已超（注入 10 分钟前首派、限 5 分钟）→ t2 收口。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-wc-1")
    d._semaphore = asyncio.Semaphore(1)  # t2 排队
    d._first_dispatch_at = time.time() - 10 * 60  # 注入：10 分钟前首派
    d.settings.run_wall_clock_limit_min = 5

    async def fake_run(state):
        state.status = "done"
        return f"ok {state.task_id}"

    d._run_subagent = fake_run
    await d.dispatch(
        [
            {"task_id": "t1", "agent_id": "primary", "goal": "g1"},
            {"task_id": "t2", "agent_id": "primary", "goal": "g2"},
        ]
    )

    assert d._wall_clock_exceeded is True
    assert d._states["t2"].status == "cancelled"
    assert d._states["t2"].error.startswith("wall_clock_exceeded")
    assert "5 分钟" in d._states["t2"].error
    assert d._states["t1"].status == "done"  # 已完成的任务不受影响


@pytest.mark.asyncio()
async def test_wall_clock_disabled_no_op(tmp_path, monkeypatch):
    """上限 0（关闭）→ 零影响。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s2", entry_queue=queue, run_id="orch-wc-2")
    d._semaphore = asyncio.Semaphore(4)
    d._first_dispatch_at = time.time() - 10 * 60  # 已远超任何限，但开关关闭
    d.settings.run_wall_clock_limit_min = 0

    async def fake_run(state):
        state.status = "done"
        return "ok"

    d._run_subagent = fake_run
    await d.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g1"}])
    assert d._states["t1"].status == "done"
    assert d._wall_clock_exceeded is False


def test_wall_clock_setting_key_registered():
    """OrchSettings 字段存在且默认 0（关闭）。"""
    from backend.orchestration.orch_settings import OrchSettings

    s = OrchSettings()
    assert s.run_wall_clock_limit_min == 0
    assert s.run_token_budget == 0


def test_wall_clock_raw_key_mapping():
    """_RAW_KEYS 映射 runWallClockLimitMinutes → run_wall_clock_limit_min。"""
    from backend.orchestration import orch_settings

    assert orch_settings._RAW_KEYS.get("runWallClockLimitMinutes") == "run_wall_clock_limit_min"
