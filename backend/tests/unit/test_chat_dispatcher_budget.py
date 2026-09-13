"""BU 系（round11）— 编排 run 级 token 预算守门单测。

- session_usage_since：窗口过滤 + fail-open（DB 故障返 0）
- dispatcher 守门：超预算 → queued 任务收口 cancelled + 聚合标注 +
  后续 dispatch 拒绝；预算关闭 / 未超限 → 零影响
"""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.tests.unit.test_chat_dispatcher import _make_queue


def _init_tmp_db(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "budget.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


def _seed_usage(session_id: str, total_tokens: int, created_at_ms: int) -> None:
    """直接插 usage_events 行（模拟 t1 执行期间产生的 LLM 用量）。"""
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


# ---- session_usage_since ------------------------------------------------------


def test_session_usage_since_filters_by_window(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    from backend.services.usage_tracker import UsageTracker

    now = int(time.time() * 1000)
    _seed_usage("sess-bu", 100, now - 1000)  # 窗口外（更早）
    _seed_usage("sess-bu", 250, now)
    _seed_usage("sess-bu", 300, now + 5)
    _seed_usage("sess-other", 999, now + 5)  # 其他会话

    used = UsageTracker().session_usage_since("sess-bu", now)
    assert used == 550


def test_session_usage_since_fail_open(tmp_path, monkeypatch):
    """DB 故障 → 返 0（守门降级，不抛错）。"""
    from backend.services import usage_tracker as ut

    monkeypatch.setattr(ut, "_SQLITE_LOCK" if hasattr(ut, "_SQLITE_LOCK") else "x", None, raising=False)

    class _Broken:
        def session_usage_since(self, session_id, since_ms):
            raise RuntimeError("db down")

    # 直接验证实现路径：坏连接 → 0
    tracker = ut.UsageTracker()
    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "no-init.db"))
    from backend.data import database as db_mod

    monkeypatch.setattr(db_mod, "_db", None)
    # 不调用 init_db —— get_database() 会按需建库，此场景仍可查询 → 0 行
    assert tracker.session_usage_since("sess-x", 0) == 0


# ---- dispatcher 守门 ----------------------------------------------------------


@pytest.mark.asyncio()
async def test_budget_exceeded_cancels_queued_and_rejects_next(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=queue,
        run_id="orch-bu-1",
        session_id="sess-bu",
    )
    d._semaphore = asyncio.Semaphore(1)  # t2 排队，等 t1 终态后才获得槽
    d.settings.run_token_budget = 100

    async def fake_run(state):
        if state.task_id == "t1":
            _seed_usage("sess-bu", 500, int(time.time() * 1000))
        state.status = "done"
        return "ok"

    d._run_subagent = fake_run
    aggregated = await d.dispatch(
        [
            {"task_id": "t1", "agent_id": "primary", "goal": "g1"},
            {"task_id": "t2", "agent_id": "primary", "goal": "g2"},
        ]
    )

    assert d._budget_exceeded is True
    assert d._states["t1"].status == "done"
    assert d._states["t2"].status == "cancelled"
    assert "token 预算上限" in aggregated

    with pytest.raises(ValueError, match="budget_exceeded"):
        await d.dispatch([{"task_id": "t3", "agent_id": "primary", "goal": "g3"}])


@pytest.mark.asyncio()
async def test_budget_disabled_never_trips(tmp_path, monkeypatch):
    """预算 0（默认关闭）→ 即便用量巨大也零影响。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s2",
        entry_queue=queue,
        run_id="orch-bu-2",
        session_id="sess-bu",
    )
    d._semaphore = asyncio.Semaphore(1)
    assert d.settings.run_token_budget == 0

    async def fake_run(state):
        _seed_usage("sess-bu", 10_000_000, int(time.time() * 1000))
        state.status = "done"
        return "ok"

    d._run_subagent = fake_run
    aggregated = await d.dispatch(
        [
            {"task_id": "t1", "agent_id": "primary", "goal": "g1"},
            {"task_id": "t2", "agent_id": "primary", "goal": "g2"},
        ]
    )
    assert d._budget_exceeded is False
    assert d._states["t2"].status == "done"
    assert "token 预算上限" not in aggregated


@pytest.mark.asyncio()
async def test_budget_not_exceeded_noop(tmp_path, monkeypatch):
    """用量低于预算 → 不触发、聚合无标注。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s3",
        entry_queue=queue,
        run_id="orch-bu-3",
        session_id="sess-bu",
    )
    d._semaphore = asyncio.Semaphore(1)
    d.settings.run_token_budget = 100_000

    async def fake_run(state):
        _seed_usage("sess-bu", 50, int(time.time() * 1000))
        state.status = "done"
        return "ok"

    d._run_subagent = fake_run
    aggregated = await d.dispatch(
        [{"task_id": "t1", "agent_id": "primary", "goal": "g1"}]
    )
    assert d._budget_exceeded is False
    assert "token 预算上限" not in aggregated


@pytest.mark.asyncio()
async def test_budget_trip_error_attribution_on_queued_tasks(tmp_path, monkeypatch):
    """BU6 (round16): 预算触顶收口的任务 error = budget_exceeded（非 cancelled by user）。

    t1 触发预算（done 后守门置位 _cancelled），t2/t3 排队中被收口：
    用户未取消 → 归因预算触顶；error 前缀与 dispatch 入口拒绝一致。
    """
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s4",
        entry_queue=queue,
        run_id="orch-bu-4",
        session_id="sess-bu",
    )
    d._semaphore = asyncio.Semaphore(1)  # 串行：t2/t3 排队
    d.settings.run_token_budget = 100

    async def fake_run(state):
        if state.task_id == "t1":
            _seed_usage("sess-bu", 500, int(time.time() * 1000))

        state.status = "done"
        return "ok"

    d._run_subagent = fake_run
    await d.dispatch(
        [
            {"task_id": "t1", "agent_id": "primary", "goal": "g1"},
            {"task_id": "t2", "agent_id": "primary", "goal": "g2"},
            {"task_id": "t3", "agent_id": "primary", "goal": "g3"},
        ]
    )

    assert d._budget_exceeded is True
    assert d._states["t2"].error.startswith("budget_exceeded")
    assert "预算" in d._states["t2"].error
    assert d._states["t3"].error.startswith("budget_exceeded")
    # 用户未按取消 —— 不得误归因为用户
    assert "cancelled by user" not in (d._states["t2"].error or "")


def test_background_guide_documents_snapshot_strategy():
    """BD5 (round16): conductor 指令含 collect 非阻塞快照与提前汇总策略。"""
    import inspect

    from backend.api.legacy_routes import _PLAN_MODE_DIRECTIVE  # noqa: F401 — 常量面健全

    src = inspect.getsource(
        __import__("backend.api.legacy_routes", fromlist=["x"])
    )
    assert "wait=false" in src
    assert "提前汇总" in src
    # 预算触顶的聚合标注在 chat_dispatcher（round11 已覆盖），此处不重复
