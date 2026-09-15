"""ChatDispatcher preset 短路（RV1, round8）+ rerun-failed 端点（RV2）单测。

- RV1: 计划条目带 preset_output → 直接收口 done（不派子代理、零 LLM 调用），
  histories 注入回放对；下游依赖照常以 done 放行。
- RV2: rerun-failed 端点 —— done 条目注入 preset_output、失败条目重建；
  run 未终态 / 无失败 / 无计划 → 409。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.tests.unit.test_chat_dispatcher import _make_queue
from backend.tests.unit.test_chat_dispatcher_topology import _inject_plan


def _init_tmp_db(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "preset.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


def _drain(queue):
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


# ---- RV1: dispatcher preset 短路 ---------------------------------------------


@pytest.mark.asyncio()
async def test_preset_task_short_circuits_without_subagent(tmp_path, monkeypatch):
    """带 preset_output 的任务 → 直接 done，_run_subagent 从未被调用。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-preset-1")
    d._semaphore = asyncio.Semaphore(4)
    _inject_plan(
        d,
        [("t1", "已完成的目标", "primary", [])],
    )
    d._plan_by_id["t1"]["preset_output"] = "原执行结果：生成了 X"

    ran = []

    async def fake_run(state):
        ran.append(state.task_id)
        state.status = "done"
        state.output = "should not happen"

    d._run_subagent = fake_run
    await d.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "已完成的目标"}])

    assert ran == []  # 从未派子代理
    assert d._states["t1"].status == "done"
    assert d._states["t1"].output == "原执行结果：生成了 X"
    # 回放对注入 histories（followup / 下游聚合可引用）
    hist = d._histories["t1"]
    assert hist[0]["role"] == "user"
    assert hist[1] == {"role": "assistant", "content": "原执行结果：生成了 X"}
    statuses = [e.get("status") for e in _drain(queue) if e.get("state") == "task_status"]
    assert statuses.count("done") >= 1


@pytest.mark.asyncio()
async def test_preset_done_unblocks_downstream(tmp_path, monkeypatch):
    """preset done 的上游放行下游真实执行 —— 级联闭包不误伤。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s2", entry_queue=queue, run_id="orch-preset-2")
    d._semaphore = asyncio.Semaphore(4)
    _inject_plan(
        d,
        [("t1", "上游", "primary", []), ("t2", "下游", "primary", ["t1"])],
    )
    d._plan_by_id["t1"]["preset_output"] = "上游结果"

    async def fake_run(state):
        assert state.task_id == "t2"  # 只有下游真实执行
        # 上游 done（回放）必须在下游启动前可见
        assert d._states["t1"].status == "done"
        state.status = "done"
        state.output = "下游完成"

    d._run_subagent = fake_run
    await d.dispatch(
        [
            {"task_id": "t1", "agent_id": "primary", "goal": "上游"},
            {"task_id": "t2", "agent_id": "primary", "goal": "下游"},
        ]
    )
    assert d._states["t1"].status == "done"
    assert d._states["t2"].status == "done"


@pytest.mark.asyncio()
async def test_preset_without_marker_runs_normally(tmp_path, monkeypatch):
    """无 preset_output 的计划 → 行为与旧版逐字一致。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s3", entry_queue=queue, run_id="orch-preset-3")
    d._semaphore = asyncio.Semaphore(4)
    _inject_plan(d, [("t1", "普通目标", "primary", [])])

    async def fake_run(state):
        state.status = "done"
        state.output = "真实执行"
        return "真实执行"

    d._run_subagent = fake_run
    await d.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "普通目标"}])
    assert d._states["t1"].output == "真实执行"
    assert "t1" not in d._histories  # 旧路径不注入回放对（runner 成功时才注入）


# ---- RV2: rerun-failed 端点 ---------------------------------------------------


def _seed_run_with_tasks(run_id: str, statuses: list):
    import json
    import time

    from backend.data.orch_run_repo import OrchRun, OrchRunRepository
    from backend.data.orch_task_repo import OrchTaskRepository

    plan_tasks = [
        {"task_id": f"t{i + 1}", "goal": f"目标{i + 1}", "agent_id": "primary"}
        for i in range(len(statuses))
    ]
    run = OrchRun(
        run_id=run_id,
        session_id="sess-rerun",
        status="failed",
        created_at=int(time.time() * 1000),
        plan_json=json.dumps({"tasks": plan_tasks, "reasoning": ""}, ensure_ascii=False),
        original_request="做一个网站",
    )
    OrchRunRepository().upsert(run)
    task_repo = OrchTaskRepository()
    for i, status in enumerate(statuses):
        task_repo.upsert_state(
            run_id=run_id,
            task_id=f"t{i + 1}",
            agent_id="primary",
            goal=f"目标{i + 1}",
            status=status,
            output_preview=("结果预览" + str(i + 1)) if status == "done" else None,
        )


@pytest.mark.asyncio()
async def test_rerun_failed_endpoint_builds_override(tmp_path, monkeypatch):
    from httpx import ASGITransport

    from backend.main import app

    _init_tmp_db(tmp_path, monkeypatch)
    _seed_run_with_tasks("orch-rerun-1", ["done", "failed", "pending"])

    async with __import__("httpx").AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/orch/runs/orch-rerun-1/rerun-failed")

    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "sess-rerun"
    assert "重跑失败任务" in data["goal"]
    override = data["plan_override"]
    assert override[0]["preset_output"] == "结果预览1"  # done → 回放
    assert "preset_output" not in override[1]  # failed → 重建
    assert "preset_output" not in override[2]


@pytest.mark.asyncio()
async def test_rerun_failed_endpoint_409_when_no_failures(tmp_path, monkeypatch):
    from httpx import ASGITransport

    from backend.main import app

    _init_tmp_db(tmp_path, monkeypatch)
    _seed_run_with_tasks("orch-rerun-2", ["done", "done"])

    async with __import__("httpx").AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/orch/runs/orch-rerun-2/rerun-failed")
    assert resp.status_code == 409


@pytest.mark.asyncio()
async def test_rerun_failed_endpoint_404_unknown_run(tmp_path, monkeypatch):
    from httpx import ASGITransport

    from backend.main import app

    _init_tmp_db(tmp_path, monkeypatch)

    async with __import__("httpx").AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/orch/runs/orch-nope/rerun-failed")
    assert resp.status_code == 404
