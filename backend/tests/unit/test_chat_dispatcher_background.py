"""BD 系（round12）— 后台子代理派发与中途收集单测。

- dispatcher: start_background_dispatch（在飞互斥）+ wait_background
  （shield 等待、超时不杀派发、无派发报错）
- 工具: DispatchSubagentsTool(background=true) 立即返回快照；
  CollectSubagentsTool 透传聚合 / 超时错误 / 无派发错误
"""

from __future__ import annotations

import asyncio

import pytest

from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.tests.unit.test_chat_dispatcher import _make_queue
from backend.tools.subagent_tool import (
    INPUT_SCHEMA,
    CollectSubagentsTool,
    DispatchSubagentsTool,
)


def _init_tmp_db(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "bg.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


@pytest.mark.asyncio()
async def test_background_dispatch_and_collect(tmp_path, monkeypatch):
    """后台派发：start 返回句柄、在飞互斥、wait 拿到聚合。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-bg-1")
    d._semaphore = asyncio.Semaphore(4)

    async def fake_run(state):
        await asyncio.sleep(0.05)
        state.status = "done"
        return f"结果 {state.task_id}"

    d._run_subagent = fake_run
    tasks = [
        {"task_id": "t1", "agent_id": "primary", "goal": "g1"},
        {"task_id": "t2", "agent_id": "primary", "goal": "g2"},
    ]

    handle = d.start_background_dispatch(tasks)
    assert handle is not None
    # 在飞时再次 start → None（互斥）
    assert d.start_background_dispatch(tasks) is None

    aggregated = await d.wait_background(timeout=5)
    assert "结果 t1" in aggregated
    assert "结果 t2" in aggregated
    assert d._states["t1"].status == "done"

    # 已终态 → 可再次启动
    handle2 = d.start_background_dispatch(tasks)
    assert handle2 is not None
    await d.wait_background(timeout=5)


@pytest.mark.asyncio()
async def test_wait_background_timeout_does_not_kill_dispatch(tmp_path, monkeypatch):
    """collect 超时（shield）→ 后台派发继续推进，之后仍可拿到结果。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s2", entry_queue=queue, run_id="orch-bg-2")
    d._semaphore = asyncio.Semaphore(4)

    async def fake_run(state):
        await asyncio.sleep(0.3)
        state.status = "done"
        return f"结果 {state.task_id}"

    d._run_subagent = fake_run
    handle = d.start_background_dispatch(
        [{"task_id": "t1", "agent_id": "primary", "goal": "g1"}]
    )
    assert handle is not None
    with pytest.raises(asyncio.TimeoutError):
        await d.wait_background(timeout=0.05)

    aggregated = await d.wait_background(timeout=5)
    assert "结果 t1" in aggregated


@pytest.mark.asyncio()
async def test_wait_background_without_dispatch_raises(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s3", entry_queue=queue, run_id="orch-bg-3")
    with pytest.raises(RuntimeError, match="no_background_dispatch"):
        await d.wait_background(timeout=1)


@pytest.mark.asyncio()
async def test_collect_tool_passthrough_and_errors(tmp_path, monkeypatch):
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s4", entry_queue=queue, run_id="orch-bg-4")
    d._semaphore = asyncio.Semaphore(4)
    tool = CollectSubagentsTool(d)

    # 无后台派发 → 明确错误
    no_bg = await tool.execute_async()
    assert no_bg.success is False
    assert "no_background_dispatch" in (no_bg.error or "")

    # 正常路径：聚合透传
    d.start_background_dispatch(
        [{"task_id": "t1", "agent_id": "primary", "goal": "g1"}]
    )
    d._run_subagent = None  # 占位：真实路径不经过（fake 见下）
    # 用最小 dispatcher 桩直接验证透传逻辑
    class _Stub:
        run_id = "stub"

        async def wait_background(self, timeout=None):
            return "聚合文本"

    stub_tool = CollectSubagentsTool(_Stub())
    ok = await stub_tool.execute_async(timeout_secs=5)
    assert ok.success is True
    assert ok.content == "聚合文本"

    class _Timeout:
        async def wait_background(self, timeout=None):
            # noqa 语义与工具侧一致：py3.8 下 asyncio.TimeoutError ≠ 内建
            raise asyncio.TimeoutError()  # noqa: UP041

    timeout_result = await CollectSubagentsTool(_Timeout()).execute_async(timeout_secs=1)
    assert timeout_result.success is False
    assert "collect_timeout" in (timeout_result.error or "")
    assert queue is not None


@pytest.mark.asyncio()
async def test_dispatch_tool_background_snapshot(tmp_path, monkeypatch):
    """background=true → 立即返回快照（dispatched_background + task_ids）。"""
    _init_tmp_db(tmp_path, monkeypatch)
    queue = _make_queue()
    d = ChatDispatcher(stream_id="s5", entry_queue=queue, run_id="orch-bg-5")
    d._semaphore = asyncio.Semaphore(4)

    async def fake_run(state):
        await asyncio.sleep(0.05)
        state.status = "done"
        return "ok"

    d._run_subagent = fake_run
    tool = DispatchSubagentsTool(d)
    result = await tool.execute_async(
        tasks=[
            {"task_id": "t1", "agent_id": "primary", "goal": "g1"},
            {"task_id": "t2", "agent_id": "primary", "goal": "g2"},
        ],
        background=True,
    )
    assert result.success is True
    content = result.content
    assert content["status"] == "dispatched_background"
    assert content["task_ids"] == ["t1", "t2"]
    assert await d.wait_background(timeout=5)

    # 在飞已结束后再来一次后台 → 正常；运行中重复 → in_progress 错误
    slow_started = asyncio.Event()

    async def slow_run(state):
        slow_started.set()
        await asyncio.sleep(0.2)
        state.status = "done"
        return "slow ok"

    d._run_subagent = slow_run
    bg = d.start_background_dispatch(
        [{"task_id": "t3", "agent_id": "primary", "goal": "g3"}]
    )
    assert bg is not None
    await slow_started.wait()
    dup = await tool.execute_async(
        tasks=[{"task_id": "t4", "agent_id": "primary", "goal": "g4"}],
        background=True,
    )
    assert dup.success is False
    assert "background_dispatch_in_progress" in (dup.error or "")
    await d.wait_background(timeout=5)


def test_schema_exposes_background():
    props = INPUT_SCHEMA["properties"]
    assert "background" in props


def test_collect_tool_requires_async():
    tool = CollectSubagentsTool(object())
    result = tool.execute()
    assert result.success is False
