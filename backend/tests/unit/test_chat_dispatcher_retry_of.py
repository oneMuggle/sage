"""RD2 (round10) — dispatch_subagents 重派原语（retry_of）单测。

- dispatch 解析：有效源（failed/cancelled）→ state.retry_of；无效源
  （done/未知）降级普通任务
- _apply_retry_inheritance：scratch_dir 延续 + retry_hint（last_error）
  注入；非 retry 任务无操作
- 工具 schema 暴露 retry_of
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest

from backend.orchestration.chat_dispatcher import ChatDispatcher, ChatTaskState
from backend.tests.unit.test_chat_dispatcher import _make_queue


def _init_tmp_db(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "retry-of.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


@pytest.mark.asyncio()
async def test_retry_of_resolves_failed_source(tmp_path, monkeypatch):
    """failed 源 → retry_of 生效；done 源 → 降级。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-rd-1")
    d._semaphore = asyncio.Semaphore(4)

    calls = {"n": 0}

    async def fake_run(state):
        calls["n"] += 1
        if state.task_id == "t1":
            raise ValueError("依赖文件缺失: config.yaml")
        state.status = "done"
        return "ok"

    d._run_subagent = fake_run
    await d.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "第一次尝试"}])
    assert d._states["t1"].status == "failed"

    await d.dispatch(
        [{"task_id": "t2", "agent_id": "primary", "goal": "修正后重做", "retry_of": "t1"}]
    )
    assert d._states["t2"].retry_of == "t1"
    assert d._states["t2"].status == "done"

    # done 源 → 降级
    await d.dispatch(
        [{"task_id": "t3", "agent_id": "primary", "goal": "g3", "retry_of": "t2"}]
    )
    assert d._states["t3"].retry_of is None


@pytest.mark.asyncio()
async def test_retry_of_unknown_source_degrades(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s2", entry_queue=queue, run_id="orch-rd-2")
    d._semaphore = asyncio.Semaphore(4)

    async def ok(state):
        state.status = "done"
        return "ok"

    d._run_subagent = ok
    await d.dispatch(
        [{"task_id": "t1", "agent_id": "primary", "goal": "g1", "retry_of": "t-unknown"}]
    )
    assert d._states["t1"].retry_of is None


def test_apply_retry_inheritance_seeds_hint_and_scratch(tmp_path, monkeypatch):
    """继承：scratch_dir 延续 + retry_hint(attempt=源重试数+1, last_error)。"""
    _init_tmp_db(tmp_path, monkeypatch)
    from backend.orchestration.models import Task

    queue = _make_queue()
    d = ChatDispatcher(stream_id="s3", entry_queue=queue, run_id="orch-rd-3")
    d._states["t1"] = ChatTaskState(
        task_id="t1",
        agent_id="primary",
        goal="g1",
        status="failed",
        error="boom 原因",
        retry_count=2,
    )
    d.task_registry.create_task(
        Task(
            task_id="task-t1",
            name="t1",
            description="t1",
            parameters={"scratch_dir": "/ws/keep"},
        )
    )

    dst = ChatTaskState(task_id="t2", agent_id="primary", goal="g2", retry_of="t1")
    params: Dict[str, Any] = {"goal": "g2", "scratch_dir": "/ws/fresh"}
    d._apply_retry_inheritance(dst, params)
    assert params["scratch_dir"] == "/ws/keep"
    assert params["retry_hint"] == {"attempt": 3, "last_error": "boom 原因"}

    # 非 retry 任务 → 无操作
    plain = ChatTaskState(task_id="t4", agent_id="primary", goal="g4")
    params3: Dict[str, Any] = {"scratch_dir": "/ws/plain"}
    d._apply_retry_inheritance(plain, params3)
    assert params3 == {"scratch_dir": "/ws/plain"}
    assert "retry_hint" not in params3


def test_apply_retry_inheritance_without_source_task(tmp_path, monkeypatch):
    """注册表无源 task（跨 run/已清理）→ scratch 不覆盖，hint 仍注入兜底。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s5", entry_queue=queue, run_id="orch-rd-5")
    d._states["t1"] = ChatTaskState(
        task_id="t1", agent_id="primary", goal="g1", status="failed", error=None
    )

    dst = ChatTaskState(task_id="t2", agent_id="primary", goal="g2", retry_of="t1")
    params: Dict[str, Any] = {"scratch_dir": "/ws/fresh"}
    d._apply_retry_inheritance(dst, params)
    assert params["scratch_dir"] == "/ws/fresh"
    assert params["retry_hint"] == {"attempt": 1, "last_error": "unknown"}


def test_schema_exposes_retry_of():
    from backend.tools.subagent_tool import _TOOL_DESCRIPTION, INPUT_SCHEMA

    props = INPUT_SCHEMA["properties"]["tasks"]["items"]["properties"]
    assert "retry_of" in props
    assert "失败" in props["retry_of"]["description"]
    assert "retry_of" in _TOOL_DESCRIPTION
