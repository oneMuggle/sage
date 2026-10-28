"""RP1 (round34) — re-plan 工具族单元测试。

覆盖 conductor 在 run 中动态调整计划的三条路径：
- ``update_pending_task`` 改未派发任务的 goal / agent
- ``cancel_pending_task``  取消未派发 or 已派发 queued/running 的任务
- ``add_task_to_plan``     添加新任务（含悬空依赖 / 自依赖 / 环校验）

以及 dispatch 侧的联动：已取消任务拒绝派发（否则会走"未知 task_id 回退
tool-passed 值"路径复活）。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.data import database as db_mod
from backend.orchestration.chat_dispatcher import ChatDispatcher, ChatTaskState
from backend.tools.replan_tool import (
    AddTaskToPlanTool,
    CancelPendingTaskTool,
    UpdatePendingTaskTool,
)


def _mk_dispatcher(tmp_path, monkeypatch, plan_json: str) -> ChatDispatcher:
    db = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()
    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-test")
    d.init_orch_run(session_id="s-1", plan_json=plan_json)
    return d


def _plan(*tasks) -> str:
    return json.dumps({"tasks": list(tasks), "reasoning": ""}, ensure_ascii=False)


def _t(tid: str, goal: str = "目标", agent: str = "writer") -> dict:
    return {"task_id": tid, "agent_id": agent, "goal": goal}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_tool_names(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        assert UpdatePendingTaskTool(d).name == "update_pending_task"
        assert CancelPendingTaskTool(d).name == "cancel_pending_task"
        assert AddTaskToPlanTool(d).name == "add_task_to_plan"

    def test_required_fields(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        assert UpdatePendingTaskTool(d).schema.parameters["required"] == ["task_id"]
        assert CancelPendingTaskTool(d).schema.parameters["required"] == ["task_id"]
        assert AddTaskToPlanTool(d).schema.parameters["required"] == [
            "task_id",
            "goal",
            "agent_id",
        ]


# ---------------------------------------------------------------------------
# update_pending_task
# ---------------------------------------------------------------------------


class TestUpdatePendingTask:
    def test_updates_goal_and_agent(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1"), _t("t2")))
        result = UpdatePendingTaskTool(d).execute(
            task_id="t2", goal="新目标", agent_id="researcher"
        )
        assert result.success is True
        assert result.content["updated_fields"] == ["goal", "agent_id"]
        assert d._plan_by_id["t2"]["goal"] == "新目标"
        assert d._plan_by_id["t2"]["agent_id"] == "researcher"

    def test_update_persists_to_db(self, tmp_path, monkeypatch):
        """调整回写 plan_json —— resume 后仍可见（不被原始计划覆盖）。"""
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        UpdatePendingTaskTool(d).execute(task_id="t1", goal="持久化目标")
        run = d._orch_run_repo.get("orch-test")
        assert "持久化目标" in (run.plan_json or "")

    def test_partial_update_only_goal(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1", agent="writer")))
        result = UpdatePendingTaskTool(d).execute(task_id="t1", goal="只改目标")
        assert result.success is True
        assert result.content["updated_fields"] == ["goal"]
        assert d._plan_by_id["t1"]["agent_id"] == "writer"

    def test_rejects_empty_update(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        result = UpdatePendingTaskTool(d).execute(task_id="t1")
        assert result.success is False
        assert "至少需要提供" in result.error

    def test_rejects_unknown_task(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        result = UpdatePendingTaskTool(d).execute(task_id="t99", goal="x")
        assert result.success is False
        assert "不在计划中" in result.error

    def test_rejects_dispatched_task(self, tmp_path, monkeypatch):
        """已派发任务不可改 —— 运行层 goal 已被读走，需 cancel + add 重建。"""
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        d._dispatched_plan_ids.add("t1")
        result = UpdatePendingTaskTool(d).execute(task_id="t1", goal="x")
        assert result.success is False
        assert "已派发" in result.error

    def test_rejects_cancelled_task(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        d._cancelled_plan_ids.add("t1")
        result = UpdatePendingTaskTool(d).execute(task_id="t1", goal="x")
        assert result.success is False
        assert "已取消" in result.error

    def test_marks_adjusted(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        UpdatePendingTaskTool(d).execute(task_id="t1", goal="x")
        assert "t1" in d.adjusted_plan_ids()


# ---------------------------------------------------------------------------
# cancel_pending_task
# ---------------------------------------------------------------------------


class TestCancelPendingTask:
    def test_cancels_undispatched_task(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1"), _t("t2")))
        result = CancelPendingTaskTool(d).execute(task_id="t2", reason="不再需要")
        assert result.success is True
        assert result.content["status"] == "cancelled"
        assert "t2" in d._cancelled_plan_ids
        assert d._plan_by_id["t2"]["cancel_reason"] == "不再需要"

    def test_rejects_double_cancel(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        CancelPendingTaskTool(d).execute(task_id="t1")
        result = CancelPendingTaskTool(d).execute(task_id="t1")
        assert result.success is False
        assert "已是取消状态" in result.error

    def test_rejects_unknown_task(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        result = CancelPendingTaskTool(d).execute(task_id="t99")
        assert result.success is False
        assert "不存在" in result.error

    def test_cancels_dispatched_queued_task(self, tmp_path, monkeypatch):
        """已派发仍在排队的任务走 skip 事件通道（复用 cancel_task）。"""
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        skip = asyncio.Event()
        d._task_skip_events["t1"] = skip
        d._states["t1"] = ChatTaskState(task_id="t1", agent_id="w", goal="g")
        result = CancelPendingTaskTool(d).execute(task_id="t1", reason="r")
        assert result.success is True
        assert result.content["status"] == "cancelling"
        assert skip.is_set() is True

    def test_rejects_terminal_task(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        d._states["t1"] = ChatTaskState(task_id="t1", agent_id="w", goal="g")
        d._states["t1"].status = "done"
        result = CancelPendingTaskTool(d).execute(task_id="t1")
        assert result.success is False
        assert "已终态" in result.error

    def test_marks_adjusted(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        CancelPendingTaskTool(d).execute(task_id="t1")
        assert "t1" in d.adjusted_plan_ids()


# ---------------------------------------------------------------------------
# add_task_to_plan
# ---------------------------------------------------------------------------


class TestAddTaskToPlan:
    def test_adds_task_without_deps(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        result = AddTaskToPlanTool(d).execute(
            task_id="t9", goal="新任务", agent_id="researcher"
        )
        assert result.success is True
        assert d._plan_by_id["t9"]["goal"] == "新任务"
        assert d._plan_by_id["t9"]["added_by_llm"] is True

    def test_adds_task_with_parent(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        result = AddTaskToPlanTool(d).execute(
            task_id="t9",
            goal="g",
            agent_id="r",
            depends_on=[],
            parent_task_id="t1",
        )
        assert result.success is True
        assert result.content["parent_task_id"] == "t1"
        assert result.content["depth"] == 1
        assert d._plan_by_id["t9"]["parent_task_id"] == "t1"
        assert d._plan_by_id["t9"]["depth"] == 1

    def test_rejects_invalid_parent(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        result = AddTaskToPlanTool(d).execute(
            task_id="t9",
            goal="g",
            agent_id="r",
            parent_task_id="missing",
        )
        assert result.success is False
        assert "parent" in result.error.lower()
        assert "t9" not in d._plan_by_id

    def test_schema_exposes_optional_parent(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        parent = AddTaskToPlanTool(d).schema.parameters["properties"]["parent_task_id"]
        assert parent["type"] == ["string", "null"]

    def test_adds_task_with_valid_deps(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1"), _t("t2")))
        result = AddTaskToPlanTool(d).execute(
            task_id="t9", goal="g", agent_id="r", depends_on=["t1", "t2"]
        )
        assert result.success is True
        assert d._plan_by_id["t9"]["depends_on"] == ["t1", "t2"]

    def test_rejects_missing_required(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        result = AddTaskToPlanTool(d).execute(task_id="t9", goal="", agent_id="r")
        assert result.success is False
        assert "必填" in result.error

    def test_rejects_duplicate_id(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        result = AddTaskToPlanTool(d).execute(task_id="t1", goal="g", agent_id="r")
        assert result.success is False
        assert "已存在" in result.error

    def test_rejects_dangling_dep(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        result = AddTaskToPlanTool(d).execute(
            task_id="t9", goal="g", agent_id="r", depends_on=["t404"]
        )
        assert result.success is False
        assert "不存在的任务" in result.error
        assert "t9" not in d._plan_by_id  # 原子：拒绝不留痕

    def test_rejects_self_dep(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        result = AddTaskToPlanTool(d).execute(
            task_id="t9", goal="g", agent_id="r", depends_on=["t9"]
        )
        assert result.success is False
        assert "不能依赖自身" in result.error

    def test_rejects_cycle(self, tmp_path, monkeypatch):
        """新增边成环时拒绝且不留痕。"""
        d = _mk_dispatcher(
            tmp_path,
            monkeypatch,
            _plan(
                {"task_id": "t1", "agent_id": "w", "goal": "g", "depends_on": ["t9"]},
                {"task_id": "t2", "agent_id": "w", "goal": "g", "depends_on": ["t1"]},
            ),
        )
        # t1→t9（既有）, t2→t1（既有）；新增 t9→t2 构成 t1→t9→t2→t1 环。
        result = AddTaskToPlanTool(d).execute(
            task_id="t9", goal="g", agent_id="r", depends_on=["t2"]
        )
        assert result.success is False
        assert "引入环" in result.error
        assert "t9" not in d._plan_by_id

    def test_marks_adjusted(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        AddTaskToPlanTool(d).execute(task_id="t9", goal="g", agent_id="r")
        assert "t9" in d.adjusted_plan_ids()


# ---------------------------------------------------------------------------
# dispatch 联动
# ---------------------------------------------------------------------------


def _drain(d: ChatDispatcher) -> None:
    """让 dispatch 直接收口（不真跑子 agent）。"""

    async def fake_run(state):
        state.status = "done"
        state.output = "ok"
        return "ok"

    d._run_subagent = fake_run


class TestDispatchIntegration:
    @pytest.mark.asyncio()
    async def test_cancelled_task_not_dispatched(self, tmp_path, monkeypatch):
        """取消后即使 conductor 再派发，任务也不会复活。"""
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1"), _t("t2")))
        _drain(d)
        CancelPendingTaskTool(d).execute(task_id="t2")
        out = await d.dispatch(
            [
                {"task_id": "t1", "agent_id": "w", "goal": "g"},
                {"task_id": "t2", "agent_id": "w", "goal": "g"},
            ]
        )
        assert "t2" not in d._states
        assert "已被取消" in out

    @pytest.mark.asyncio()
    async def test_all_cancelled_raises(self, tmp_path, monkeypatch):
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        CancelPendingTaskTool(d).execute(task_id="t1")
        with pytest.raises(ValueError, match="all_tasks_cancelled"):
            await d.dispatch([{"task_id": "t1", "agent_id": "w", "goal": "g"}])

    @pytest.mark.asyncio()
    async def test_updated_goal_takes_effect_on_dispatch(self, tmp_path, monkeypatch):
        """update 后派发 → 计划权威用新 goal（而非 tool-passed 旧值）。"""
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1", goal="旧目标")))
        _drain(d)
        UpdatePendingTaskTool(d).execute(task_id="t1", goal="新目标")
        await d.dispatch([{"task_id": "t1", "agent_id": "w", "goal": "tool 传的旧值"}])
        assert d._states["t1"].goal == "新目标"

    @pytest.mark.asyncio()
    async def test_added_task_dispatches(self, tmp_path, monkeypatch):
        """新增任务经 dispatch 正常执行，且计划权威生效。"""
        d = _mk_dispatcher(tmp_path, monkeypatch, _plan(_t("t1")))
        _drain(d)
        AddTaskToPlanTool(d).execute(
            task_id="t9", goal="补充调研", agent_id="researcher"
        )
        await d.dispatch([{"task_id": "t9", "agent_id": "x", "goal": "旧值"}])
        assert d._states["t9"].goal == "补充调研"
        assert d._states["t9"].agent_id == "researcher"
