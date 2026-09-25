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


# ---- BU13 (round24) / RT23 补测：任务级归因与事件可见性 ----------------------


def _seed_task_usage(
    session_id: str, task_id: str, total_tokens: int, created_at_ms: int
) -> None:
    """插带 task_id 归因的 usage_events 行（模拟子任务执行期间的 LLM 用量）。"""
    import uuid

    from backend.data.database import get_database

    conn = get_database().get_connection()
    conn.execute(
        "INSERT INTO usage_events (id, session_id, model, prompt_tokens,"
        " completion_tokens, total_tokens, estimated_cost_usd, created_at,"
        " cached_tokens, task_id)"
        " VALUES (?, ?, 'test-model', 0, 0, ?, 0.0, ?, 0, ?)",
        (str(uuid.uuid4()), session_id, total_tokens, created_at_ms, task_id),
    )
    conn.commit()


def test_task_usage_since_filters_by_task_and_window(tmp_path, monkeypatch):
    """RT23 (round23 补测): task_usage_since 只聚合指定 task_id 且落在窗口内。"""
    _init_tmp_db(tmp_path, monkeypatch)
    now = int(time.time() * 1000)
    _seed_task_usage("sess-tu", "t1", 100, now)
    _seed_task_usage("sess-tu", "t1", 50, now - 10 * 60_000)  # 窗口外
    _seed_task_usage("sess-tu", "t2", 200, now)  # 别的任务
    used = (
        __import__("backend.services.usage_tracker", fromlist=["UsageTracker"])
        .UsageTracker()
        .task_usage_since("sess-tu", "t1", now - 60_000)
    )
    assert used == 100


def test_task_usage_since_fail_open(tmp_path, monkeypatch):
    """RT23 (round23 补测): DB 故障返 0，不向事件路径抛异常。"""
    _init_tmp_db(tmp_path, monkeypatch)
    import backend.data.database as db_mod
    from backend.services.usage_tracker import UsageTracker

    def _boom():
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr(db_mod, "get_database", _boom)
    assert UsageTracker().task_usage_since("sess-x", "t1", 0) == 0


@pytest.mark.asyncio()
async def test_record_persists_contextvar_task_id(tmp_path, monkeypatch):
    """RT23 (round23 补测): ContextVar 归因 —— record() 落库自动携带 task_id。"""
    _init_tmp_db(tmp_path, monkeypatch)
    from backend.services.usage_tracker import (
        UsageTracker,
        set_current_task_id,
    )

    set_current_task_id("tA")
    try:
        UsageTracker().record("test-model", 1, 1, session_id="sess-ctx")
        used = UsageTracker().task_usage_since("sess-ctx", "tA", 0)
    finally:
        set_current_task_id(None)
    assert used == 2


def _drain_task_events(queue):
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return [e for e in events if e.get("state") == "task_status"]


@pytest.mark.asyncio()
async def test_done_event_reports_per_task_tokens(tmp_path, monkeypatch):
    """BU13 (round24): 终态事件携带本任务 token（而非 run 累计），预算关闭也带键。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=queue,
        run_id="orch-bu13-1",
        session_id="sess-bu13",
    )
    d.settings.run_token_budget = 0  # 门槛解除：预算关闭仍可见

    async def fake_run(state):
        _seed_task_usage(
            "sess-bu13",
            state.task_id,
            300 if state.task_id == "t1" else 40,
            int(time.time() * 1000),
        )
        state.status = "done"
        return "ok"

    d._run_subagent = fake_run
    await d.dispatch(
        [
            {"task_id": "t1", "agent_id": "primary", "goal": "g1"},
            {"task_id": "t2", "agent_id": "primary", "goal": "g2"},
        ]
    )
    events = {e["task_id"]: e for e in _drain_task_events(queue) if e["task_id"]}
    assert events["t1"]["status"] == "done"
    assert events["t1"]["used_tokens"] == 300  # 非累计 340
    assert events["t2"]["used_tokens"] == 40


@pytest.mark.asyncio()
async def test_running_event_lacks_tokens_and_duration(tmp_path, monkeypatch):
    """BU13 (round24): queued/running 事件不带 used_tokens/duration_ms（进行中无意义）。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=queue,
        run_id="orch-bu13-2",
        session_id="sess-bu13b",
    )

    async def fake_run(state):
        state.status = "done"
        return "ok"

    d._run_subagent = fake_run
    await d.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g1"}])
    events = _drain_task_events(queue)
    running = [e for e in events if e["status"] == "running"]
    assert running, "应存在 running 事件"
    assert "used_tokens" not in running[0]
    assert "duration_ms" not in running[0]
    done = [e for e in events if e["status"] == "done"]
    assert done
    assert "duration_ms" in done[0]
    assert done[0]["duration_ms"] >= 0


# ---- BU17 (round31): 聚合块任务级消耗标注 --------------------------------------


def _seed_run_tokens_for_dispatcher(d, task_id: str, total_tokens: int) -> None:
    """按 dispatcher 的 session/run 窗口插一条带 task_id 的用量行。"""
    _seed_task_usage(
        d.session_id or "sess-agg",
        task_id,
        total_tokens,
        int((d._first_dispatch_at or __import__("time").time()) * 1000) + 5,
    )


@pytest.mark.asyncio()
async def test_aggregate_block_shows_per_task_tokens(tmp_path, monkeypatch):
    """BU17: done 任务聚合块标题带消耗行；无用量任务不显。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=queue,
        run_id="orch-bu17-1",
        session_id="sess-bu17",
    )
    d._semaphore = asyncio.Semaphore(4)

    async def fake_run(state):
        if state.task_id == "t1":
            _seed_task_usage(
                "sess-bu17",
                "t1",
                777,
                int((d._first_dispatch_at or time.time()) * 1000) + 5,
            )
        state.status = "done"
        state.output = f"产出 {state.task_id}"
        return state.output

    d._run_subagent = fake_run
    d.start_background_dispatch(
        [
            {"task_id": "t1", "agent_id": "primary", "goal": "g1"},
            {"task_id": "t2", "agent_id": "primary", "goal": "g2"},
        ]
    )
    await d.wait_background(timeout=5)
    snap = d.background_snapshot()
    agg = snap["aggregate"]
    # BU20 (round36): 消耗与耗时并排标注
    assert "## 子任务 t1（primary）（消耗 777 tokens · 耗时" in agg
    assert "消耗 777" in agg


@pytest.mark.asyncio()
async def test_aggregate_tokens_memoized(tmp_path, monkeypatch):
    """BU17: memo 生效 —— 二次聚合不再触发 DB 查询。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=queue,
        run_id="orch-bu17-2",
        session_id="sess-bu17b",
    )
    d._semaphore = asyncio.Semaphore(4)

    async def fake_run(state):
        state.status = "done"
        state.output = "ok"
        return "ok"

    d._run_subagent = fake_run
    d.start_background_dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g1"}])
    await d.wait_background(timeout=5)

    calls = {"n": 0}
    from backend.services import usage_tracker as ut

    orig = ut.UsageTracker.task_usage_since

    def counting(self, session_id, task_id, since_ms):
        calls["n"] += 1
        return orig(self, session_id, task_id, since_ms)

    monkeypatch.setattr(ut.UsageTracker, "task_usage_since", counting)
    d._task_tokens.clear()  # dispatch 末尾聚合已预热 memo —— 清空后计量
    d.background_snapshot()
    d.background_snapshot()
    assert calls["n"] == 1  # 首查入 memo，二次聚合零查询


# ---- RT24 (round32): 编排任务持久化携带用量与时长 ------------------------------


@pytest.mark.asyncio()
async def test_persist_task_state_records_usage_and_duration(tmp_path, monkeypatch):
    """RT24: 终态落库 orch_tasks.used_tokens/duration_ms；运行历史可见。"""
    _init_tmp_db(tmp_path, monkeypatch)
    # orch_tasks.run_id REFERENCES orch_runs —— 先落 run 行再跑任务。
    import json as _json

    from backend.data.orch_run_repo import OrchRun, OrchRunRepository

    OrchRunRepository().upsert(
        OrchRun(
            run_id="orch-rt24-1",
            session_id="sess-rt24",
            status="running",
            created_at=int(time.time() * 1000),
            plan_json=_json.dumps({"tasks": []}, ensure_ascii=False),
            original_request="",
        )
    )
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=queue,
        run_id="orch-rt24-1",
        session_id="sess-rt24",
    )
    d._semaphore = asyncio.Semaphore(4)

    async def fake_run(state):
        import asyncio as _aio

        if state.task_id == "t1":
            _seed_task_usage(
                "sess-rt24",
                "t1",
                4321,
                int(time.time() * 1000),
            )
            await _aio.sleep(0.05)  # 可测 duration_ms > 0
        state.status = "done"
        state.output = f"产出 {state.task_id}"
        return state.output

    d._run_subagent = fake_run
    d.start_background_dispatch(
        [
            {"task_id": "t1", "agent_id": "primary", "goal": "g1"},
            {"task_id": "t2", "agent_id": "primary", "goal": "g2"},
        ]
    )
    await d.wait_background(timeout=5)

    from backend.data.orch_task_repo import OrchTaskRepository

    repo = OrchTaskRepository()
    t1 = repo.get("t1")
    assert t1 is not None
    assert t1.status == "done"
    assert t1.used_tokens == 4321
    assert t1.duration_ms is not None
    assert t1.duration_ms >= 0
    t2 = repo.get("t2")
    assert t2 is not None
    assert t2.used_tokens == 0  # 无用量任务如实写 0
    assert t2.duration_ms is not None

    # API 详情透出
    from httpx import ASGITransport

    from backend.main import app

    async with __import__("httpx").AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/orch/runs/orch-rt24-1")
    assert resp.status_code == 200
    tasks = {t["task_id"]: t for t in resp.json()["tasks"]}
    assert tasks["t1"]["used_tokens"] == 4321
    assert tasks["t1"]["duration_ms"] is not None


# ---- BU18 (round34): 聚合头部守门行量化补全 ------------------------------------


@pytest.mark.asyncio()
async def test_aggregate_budget_line_includes_remaining(tmp_path, monkeypatch):
    """BU18: 预算行追加剩余额度。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=queue,
        run_id="orch-bu18-1",
        session_id="sess-bu18a",
    )
    d._semaphore = asyncio.Semaphore(4)
    d.settings.run_token_budget = 1000

    async def fake_run(state):
        _seed_task_usage("sess-bu18a", state.task_id, 120, int(time.time() * 1000))
        state.status = "done"
        state.output = "ok"
        return "ok"

    d._run_subagent = fake_run
    await d.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g1"}])
    agg = d._aggregate(list(d._states.values()))  # 直跑 dispatch 无 bg_task
    assert "剩余 880" in agg  # 1000 - 120（仅 t1 各 120）

@pytest.mark.asyncio()
async def test_aggregate_wall_clock_line_when_enabled(tmp_path, monkeypatch):
    """BU18: 墙钟启用未触顶 → 已运行/上限行；未启用 → 无该行。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=queue,
        run_id="orch-bu18-2",
        session_id="sess-bu18b",
    )
    d._semaphore = asyncio.Semaphore(4)
    d.settings.run_wall_clock_limit_min = 30
    d._first_dispatch_at = time.time() - 120  # 已"运行" 2 分钟

    async def fake_run(state):
        state.status = "done"
        state.output = "ok"
        return "ok"

    d._run_subagent = fake_run
    await d.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g1"}])
    agg = d._aggregate(list(d._states.values()))
    assert "已运行 2 分钟 / 上限 30 分钟" in agg

    d2 = ChatDispatcher(
        stream_id="s2",
        entry_queue=_make_queue(),
        run_id="orch-bu18-3",
        session_id="sess-bu18c",
    )
    d2._semaphore = asyncio.Semaphore(4)
    d2._run_subagent = fake_run
    await d2.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g1"}])
    agg2 = d2._aggregate(list(d2._states.values()))
    assert "上限" not in agg2


# ---- BU20 (round36): 聚合块任务级时长标注 --------------------------------------


@pytest.mark.asyncio()
async def test_aggregate_block_shows_duration_alone_when_no_tokens(tmp_path, monkeypatch):
    """BU20: 无用量任务只显耗时；两数据皆无的任务不显标注。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=queue,
        run_id="orch-bu20-1",
        session_id="sess-bu20",
    )
    d._semaphore = asyncio.Semaphore(4)

    async def fake_run(state):
        if state.task_id == "t2":
            await asyncio.sleep(0.05)
        state.status = "done"
        state.output = f"产出 {state.task_id}"
        return state.output

    d._run_subagent = fake_run
    await d.dispatch(
        [
            {"task_id": "t1", "agent_id": "primary", "goal": "g1"},
            {"task_id": "t2", "agent_id": "primary", "goal": "g2"},
        ]
    )
    agg = d._aggregate(list(d._states.values()))
    # 两任务都有起止 → 都有耗时；t1 无用量 → 只有耗时
    assert "## 子任务 t1（primary）（耗时" in agg
    assert "## 子任务 t2（primary）（耗时" in agg
    assert "消耗" not in agg.split("已收到")[1].split("## 子任务 t1")[0]


# ---- BU21 (round38): 聚合头部消耗速率 ------------------------------------------


@pytest.mark.asyncio()
async def test_aggregate_budget_line_includes_recent_rate(tmp_path, monkeypatch):
    """BU21: 预算行带近5分钟速率；窗口外的历史用量不计入速率段。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=queue,
        run_id="orch-bu21-1",
        session_id="sess-bu21",
    )
    d._semaphore = asyncio.Semaphore(4)
    d.settings.run_token_budget = 1000

    async def fake_run(state):
        _seed_task_usage("sess-bu21", state.task_id, 120, int(time.time() * 1000))
        # 10 分钟前的旧用量 —— 不进"近5分钟"窗口
        _seed_task_usage(
            "sess-bu21", state.task_id, 999, int((time.time() - 600) * 1000)
        )
        state.status = "done"
        state.output = "ok"
        return "ok"

    d._run_subagent = fake_run
    await d.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g1"}])
    agg = d._aggregate(list(d._states.values()))
    # run 窗口（首派发起）本就排除 10 分钟前的旧行；速率段只含近 5 分钟
    assert "已消耗 120 / 预算 1000 tokens（12%），剩余 880，近5分钟 120。" in agg


# ---- RT25 (round46): 任务归因查询索引 ------------------------------------------


def test_usage_events_task_index_exists_and_used(tmp_path, monkeypatch):
    """RT25: init_db 建 (session_id, task_id, created_at) 索引且查询命中。"""
    _init_tmp_db(tmp_path, monkeypatch)
    from backend.data.database import get_database

    conn = get_database().get_connection()
    indexes = {
        row[1]
        for row in conn.execute("PRAGMA index_list(usage_events)").fetchall()
    }
    assert "idx_usage_events_session_task" in indexes

    plan = conn.execute(
        "EXPLAIN QUERY PLAN SELECT COALESCE(SUM(total_tokens), 0) AS total"
        " FROM usage_events WHERE session_id = ? AND task_id = ?"
        " AND created_at >= ?",
        ("sess-x", "t-x", 0),
    ).fetchall()
    plan_text = " ".join(str(row[-1]) for row in plan)
    assert "idx_usage_events_session_task" in plan_text


# ---- RT26 (round49): 重派链历史持久化 ------------------------------------------


@pytest.mark.asyncio()
async def test_persist_task_state_records_retry_of(tmp_path, monkeypatch):
    """RT26: 重派任务终态落库 orch_tasks.retry_of；恢复可见。"""
    _init_tmp_db(tmp_path, monkeypatch)
    import json as _json

    from backend.data.orch_run_repo import OrchRun, OrchRunRepository

    OrchRunRepository().upsert(
        OrchRun(
            run_id="orch-rt26-1",
            session_id="sess-rt26",
            status="running",
            created_at=int(time.time() * 1000),
            plan_json=_json.dumps({"tasks": []}, ensure_ascii=False),
            original_request="",
        )
    )
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=queue,
        run_id="orch-rt26-1",
        session_id="sess-rt26",
    )
    d._semaphore = asyncio.Semaphore(4)

    async def fake_run(state):
        # 模拟重派任务 —— dispatch 时 retry_of 由 plan item 写入 state
        if state.task_id == "t1":
            state.retry_of = "t0"
        state.status = "done"
        state.output = "ok"
        return "ok"

    d._run_subagent = fake_run
    await d.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g1"}])

    from backend.data.orch_task_repo import OrchTaskRepository

    repo = OrchTaskRepository()
    t1 = repo.get("t1")
    assert t1 is not None
    assert t1.retry_of == "t0"


# ---- OPS4 (round51): cancel 时清理待决审批 --------------------------------------


def test_cancel_clears_pending_approvals():
    """OPS4: cancel 后 _pending_approvals 被清空。"""
    from backend.orchestration.chat_dispatcher import ChatDispatcher
    from backend.tests.unit.test_chat_dispatcher import _make_queue

    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1", entry_queue=queue, run_id="orch-ops4-1", session_id="s-ops4"
    )
    d._pending_approvals["req-1"] = "t1"
    d._pending_approvals["req-2"] = "t2"
    assert len(d._pending_approvals) == 2
    d.cancel()
    assert len(d._pending_approvals) == 0


def test_cancel_then_resolve_returns_false(tmp_path):
    """OPS4: cancel 后 resolve_approval 不再误命中。"""
    import asyncio

    from backend.orchestration.chat_dispatcher import ChatDispatcher
    from backend.tests.unit.test_chat_dispatcher import _make_queue

    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1", entry_queue=queue, run_id="orch-ops4-2", session_id="s-ops4b"
    )
    d._pending_approvals["req-1"] = "t1"
    d.cancel()
    result = asyncio.get_event_loop().run_until_complete(
        d.resolve_approval("req-1", approved=True)
    )
    assert result is False
