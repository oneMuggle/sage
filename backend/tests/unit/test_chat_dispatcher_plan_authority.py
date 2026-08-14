"""P2-7 — 计划权威派发：匹配用计划 goal/agent、未知回退 tool 值、缺省自分配。"""
from __future__ import annotations

import asyncio
import json

import pytest

from backend.data import database as db_mod
from backend.orchestration.chat_dispatcher import ChatDispatcher


def _mk_dispatcher(tmp_path, monkeypatch, plan_json: str):
    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()
    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-test")
    d.init_orch_run(session_id="s-1", plan_json=plan_json)
    return d


async def _drain(d: ChatDispatcher):
    """让 dispatch 直接执行（不真跑子 agent）：mock _run_subagent。"""
    async def fake_run(state):
        state.status = "done"
        state.output = "ok"
        return "ok"  # _run_one 用返回值覆写 state.output —— 真 _run_subagent 返回内容
    d._run_subagent = fake_run


@pytest.mark.asyncio()
async def test_plan_matched_task_uses_plan_goal_agent(tmp_path, monkeypatch):
    """task_id 匹配计划 → goal/agent 以计划为准（覆盖 tool-passed 值）。"""
    plan = json.dumps(
        {
            "tasks": [
                {"task_id": "t1", "agent_id": "writer", "goal": "计划目标1"},
                {"task_id": "t2", "agent_id": "researcher", "goal": "计划目标2"},
            ],
            "reasoning": "",
        },
        ensure_ascii=False,
    )
    d = _mk_dispatcher(tmp_path, monkeypatch, plan)
    await _drain(d)
    # conductor 故意传错 goal/agent —— 计划权威应覆盖
    out = await d.dispatch(
        [{"task_id": "t1", "agent_id": "wrong", "goal": "错误目标"},
         {"task_id": "t2", "agent_id": "wrong", "goal": "错误目标"}]
    )
    assert d._states["t1"].goal == "计划目标1"
    assert d._states["t1"].agent_id == "writer"
    assert d._states["t2"].goal == "计划目标2"
    assert "ok" in out


@pytest.mark.asyncio()
async def test_unknown_task_id_falls_back_to_tool_values(tmp_path, monkeypatch):
    """未知 task_id（不在计划）→ 回退 tool-passed 值，允许动态加任务。"""
    plan = json.dumps({"tasks": [{"task_id": "t1", "agent_id": "writer", "goal": "G1"}], "reasoning": ""})
    d = _mk_dispatcher(tmp_path, monkeypatch, plan)
    await _drain(d)
    await d.dispatch([{"task_id": "t9", "agent_id": "researcher", "goal": "动态任务"}])
    assert d._states["t9"].goal == "动态任务"
    assert d._states["t9"].agent_id == "researcher"


@pytest.mark.asyncio()
async def test_missing_task_id_auto_assigns(tmp_path, monkeypatch):
    """缺 task_id（malformed/旧客户端）→ 自分配 t{next}，跳过计划已占编号。"""
    plan = json.dumps({"tasks": [{"task_id": "t1", "agent_id": "writer", "goal": "G1"}], "reasoning": ""})
    d = _mk_dispatcher(tmp_path, monkeypatch, plan)
    await _drain(d)
    # 计划 t1 一并派发（conductor 传错 goal/agent → 计划覆盖为 writer/G1）——
    # 随后缺省任务自分配必须跳过 t1（计划编号已占用）落到 t2。
    await d.dispatch([{"task_id": "t1", "agent_id": "wrong", "goal": "错"},
                      {"agent_id": "researcher", "goal": "无编号"}])
    assigned = [k for k in d._states if k.startswith("t") and d._states[k].goal == "无编号"]
    # 计划权威下 t1 已被计划占用 → 自分配跳过 → t2（不撞计划编号）
    assert assigned == ["t2"]
    assert d._states["t1"].agent_id == "writer"  # 计划 t1 未被缺省分配覆盖

@pytest.mark.asyncio()
async def test_plan_by_id_built_once_at_first_dispatch(tmp_path, monkeypatch):
    """_plan_by_id 只建一次：首 dispatch 后缓存，后续复用（编辑在首派发前生效）。"""
    plan = json.dumps({"tasks": [{"task_id": "t1", "agent_id": "writer", "goal": "G1"}], "reasoning": ""})
    d = _mk_dispatcher(tmp_path, monkeypatch, plan)
    await _drain(d)
    # 首派发前改库 → 首派发读到编辑后计划
    repo = d._orch_run_repo
    run = repo.get("orch-test")
    run.plan_json = json.dumps({"tasks": [{"task_id": "t1", "agent_id": "coder", "goal": "编辑后"}], "reasoning": ""})
    repo.upsert(run)
    await d.dispatch([{"task_id": "t1", "agent_id": "wrong", "goal": "x"}])
    assert d._states["t1"].goal == "编辑后"
    assert d._states["t1"].agent_id == "coder"
    # 首派发后再改库 → 缓存不重建：第二次派发仍用首次索引
    run = repo.get("orch-test")
    run.plan_json = json.dumps({"tasks": [{"task_id": "t1", "agent_id": "writer", "goal": "再改"}], "reasoning": ""})
    repo.upsert(run)
    await d.dispatch([{"task_id": "t1", "agent_id": "wrong", "goal": "x"}])
    assert d._states["t1"].goal == "编辑后"  # 缓存生效，不读到"再改"
