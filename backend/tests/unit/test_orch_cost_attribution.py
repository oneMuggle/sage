# backend/tests/unit/test_orch_cost_attribution.py
"""M4.3b（成本透明）：编排金额归因 —— run_id 维度 + 金额账本。

三件事：
  1. 子代理执行期间 usage 落库携带 run_id + task_id（ContextVar 接线）；
  2. 终态事件携带本任务已定价金额（全未知定价 → 不带键，不显示 0）；
  3. API run 详情透出**任务级 + run 级**金额，且金额按 run 隔离。

金额的唯一真相源是 ``usage_events``（按 run_id 聚合），**不落 orch_tasks** ——
该表主键是 task_id 而计划编号跨 run 复用，同会话第二个 run 会覆盖第一个
run 的行（金额会串 run）。用例 ``test_two_runs_in_same_session_keep_own_cost``
正是这条回归。

用例从 test_chat_dispatcher_budget.py 迁出单列 —— 该文件已接近体量上限，
本组用例自成一档（成本透明），便于后续 M4.3c（run 级成本面板）复用夹具。
"""
from __future__ import annotations

import asyncio
import time

import pytest

from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.tests.unit.test_chat_dispatcher import _make_queue
from backend.tests.unit.test_chat_dispatcher_budget import (
    _drain_task_events,
    _init_tmp_db,
    _seed_task_usage,
)


def _seed_run(run_id: str, session_id: str) -> None:
    """建一个 run 行（orch_tasks 有 FK 到 orch_runs）。"""
    import json as _json

    from backend.data.orch_run_repo import OrchRun, OrchRunRepository

    OrchRunRepository().upsert(
        OrchRun(
            run_id=run_id,
            session_id=session_id,
            status="running",
            created_at=int(time.time() * 1000),
            plan_json=_json.dumps({"tasks": []}, ensure_ascii=False),
            original_request="",
        )
    )


@pytest.mark.asyncio()
async def test_subagent_usage_recorded_with_run_and_task_attribution(
    tmp_path, monkeypatch
):
    """M4.3b: 子代理执行期间 record() 落库携带 run_id + task_id（ContextVar 接线）。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=queue,
        run_id="orch-attr-1",
        session_id="sess-attr",
    )

    async def fake_run(state):
        from backend.services.usage_tracker import UsageTracker

        UsageTracker().record("test-model", 3, 4, session_id="sess-attr")
        state.status = "done"
        return "ok"

    d._run_subagent = fake_run
    await d.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g1"}])

    from backend.data.database import get_database

    rows = (
        get_database()
        .get_connection()
        .execute(
            "SELECT task_id, run_id FROM usage_events WHERE session_id = 'sess-attr'"
        )
        .fetchall()
    )
    assert len(rows) == 1
    assert rows[0]["run_id"] == "orch-attr-1"
    assert rows[0]["task_id"] == "t1"


@pytest.mark.asyncio()
async def test_done_event_reports_per_task_cost(tmp_path, monkeypatch):
    """M4.3b: 终态事件携带本任务已定价金额；全未知定价任务不带键。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=queue,
        run_id="orch-cost-1",
        session_id="sess-cost",
    )
    d._semaphore = asyncio.Semaphore(4)

    async def fake_run(state):
        now = int((d._first_dispatch_at or time.time()) * 1000) + 5
        _seed_task_usage(
            "sess-cost",
            state.task_id,
            10,
            now,
            cost=0.0123 if state.task_id == "t1" else None,
            run_id="orch-cost-1",
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
    assert events["t1"]["used_cost_usd"] == pytest.approx(0.0123)
    assert "used_cost_usd" not in events["t2"]  # 未知定价 → 隐藏，不显示 0


@pytest.mark.asyncio()
async def test_detail_exposes_task_and_run_cost(tmp_path, monkeypatch):
    """M4.3b: API run 详情透出任务级金额与 run 级合计；未知定价为 null。"""
    _init_tmp_db(tmp_path, monkeypatch)
    _seed_run("orch-cost-2", "sess-cost2")
    queue = _make_queue()
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=queue,
        run_id="orch-cost-2",
        session_id="sess-cost2",
    )
    d._semaphore = asyncio.Semaphore(4)

    async def fake_run(state):
        now = int((d._first_dispatch_at or time.time()) * 1000) + 5
        if state.task_id == "t1":
            _seed_task_usage(
                "sess-cost2", "t1", 10, now, cost=0.0042, run_id="orch-cost-2"
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

    from httpx import ASGITransport, AsyncClient

    from backend.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/orch/runs/orch-cost-2")
    assert resp.status_code == 200
    body = resp.json()
    tasks = {t["task_id"]: t for t in body["tasks"]}
    assert tasks["t1"]["cost_usd"] == pytest.approx(0.0042)
    assert tasks["t2"]["cost_usd"] is None  # 无定价行 → null，不是 0
    assert body["cost_usd"] == pytest.approx(0.0042)  # run 级合计


@pytest.mark.asyncio()
async def test_two_runs_in_same_session_keep_own_cost(tmp_path, monkeypatch):
    """M4.3b 回归：同会话两个 run 的同名任务（t1）金额互不串扰。

    ``orch_tasks`` 主键是 task_id → 第二个 run 的 t1 覆盖第一个的行；
    金额若存在该表就会串 run。金额账本在 usage_events（按 run_id 聚合），
    故两个 run 的 run 级金额各自独立。
    """
    _init_tmp_db(tmp_path, monkeypatch)
    _seed_run("run-A", "sess-shared")
    _seed_run("run-B", "sess-shared")
    now = int(time.time() * 1000)
    _seed_task_usage("sess-shared", "t1", 10, now, cost=0.007, run_id="run-A")
    _seed_task_usage("sess-shared", "t1", 10, now + 1, cost=0.011, run_id="run-B")

    from httpx import ASGITransport, AsyncClient

    from backend.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        a = (await client.get("/api/v1/orch/runs/run-A")).json()
        b = (await client.get("/api/v1/orch/runs/run-B")).json()

    assert a["cost_usd"] == pytest.approx(0.007)
    assert b["cost_usd"] == pytest.approx(0.011)


def test_usage_cost_repo_semantics(tmp_path, monkeypatch):
    """M4.3b: 账本聚合口径 —— 只算已定价行；全未知 → None；run 级合计一致。"""
    _init_tmp_db(tmp_path, monkeypatch)
    now = int(time.time() * 1000)
    _seed_task_usage("s1", "t1", 10, now, cost=0.002, run_id="orch-1")
    _seed_task_usage("s1", "t1", 10, now + 1, cost=0.003, run_id="orch-1")
    _seed_task_usage("s1", "t2", 10, now, cost=None, run_id="orch-1")
    _seed_task_usage("s2", "t1", 10, now, cost=9.9, run_id="orch-2")

    from backend.data.usage_cost_repo import UsageCostRepository

    repo = UsageCostRepository()
    assert repo.task_cost_usd("orch-1", "t1") == pytest.approx(0.005)
    # 未知定价 → None（不得折成 0）
    assert repo.task_cost_usd("orch-1", "t2") is None
    # 无任何行 → None
    assert repo.task_cost_usd("orch-1", "t9") is None
    # 别的 run 的行不计入
    assert repo.task_cost_usd("orch-3", "t1") is None

    costs = repo.run_costs_usd("orch-1")
    assert costs["total"] == pytest.approx(0.005)
    assert costs["tasks"] == {"t1": pytest.approx(0.005)}
    # 全未知定价的 run → total 为 None（前端隐藏，不显示 $0）
    assert repo.run_costs_usd("orch-empty")["total"] is None


def test_usage_cost_repo_fail_open(monkeypatch):
    """M4.3b: DB 故障 → None / 空结果（不向事件与 API 路径抛异常）。"""
    import backend.data.database as db_mod

    def _boom():
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr(db_mod, "get_database", _boom)

    from backend.data.usage_cost_repo import UsageCostRepository

    repo = UsageCostRepository()
    assert repo.task_cost_usd("orch-1", "t1") is None
    assert repo.run_costs_usd("orch-1") == {"total": None, "tasks": {}}
