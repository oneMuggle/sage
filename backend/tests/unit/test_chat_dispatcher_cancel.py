"""P2-9/PR A — run 级取消：queued 转 cancelled、幂等、running 不硬杀。"""
from __future__ import annotations

import asyncio

import pytest

from backend.orchestration.chat_dispatcher import ChatDispatcher


def _init_tmp_db(tmp_path, monkeypatch):
    """SAGE_DB_PATH 隔离 —— 经 dispatch() 会触发 orch_repo 落库，指向 tmp 而非真实 data。"""
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "cancel.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


@pytest.mark.asyncio()
async def test_cancel_is_idempotent():
    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-test")
    assert d.cancel() is True
    assert d.cancel() is False  # 已 set
    assert d._cancelled.is_set()


@pytest.mark.asyncio()
async def test_cancel_before_dispatch_skips_queued_in_gather(tmp_path, monkeypatch):
    """dispatch 前 cancel → 全部 queued 转 cancelled，不做任何子任务。

    注：_run_one 是 dispatch() 内的嵌套闭包，不能 `await d._run_one(state)` 直接调
    （AttributeError）—— 一律经 dispatch() 走 gather 触发。
    """
    _init_tmp_db(tmp_path, monkeypatch)
    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-test")
    ran = []

    async def fake_run(state):
        ran.append(state.task_id)

    d._run_subagent = fake_run
    d.cancel()
    await d.dispatch([{"task_id": "t1", "agent_id": "r", "goal": "g"}])
    assert ran == []  # 守卫在 acquire 后拦截，未调 _run_subagent
    assert d._states["t1"].status == "cancelled"
    assert d._states["t1"].error == "cancelled by user"


@pytest.mark.asyncio()
async def test_cancel_during_run_short_circuits_queued(tmp_path, monkeypatch):
    """cancel 在 t1 running 时到达 → t1 放行完成；排队等槽的 t2 拿到槽后短路为 cancelled。

    复现信号量竞态：守卫若只在 `_run_one` 入口判取消，排队在信号量上的 t2
    已在 cancel 前越过守卫，拿到槽后会照跑。守卫必须在 acquire 之后（见 Step 3）。
    """
    _init_tmp_db(tmp_path, monkeypatch)
    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-test")
    d._semaphore = asyncio.Semaphore(1)  # 单槽 → t2 在信号量上排队
    t1_started = asyncio.Event()
    release_t1 = asyncio.Event()
    ran = []

    async def fake_run(state):
        ran.append(state.task_id)
        if state.task_id == "t1":
            t1_started.set()          # t1 已进入执行
            await release_t1.wait()   # 阻塞让 t2 排队
        state.status = "done"
        state.output = "ok"

    d._run_subagent = fake_run
    dispatch_task = asyncio.create_task(
        d.dispatch(
            [
                {"task_id": "t1", "agent_id": "r", "goal": "g1"},
                {"task_id": "t2", "agent_id": "r", "goal": "g2"},
            ]
        )
    )
    await t1_started.wait()  # 确定性：t1 running，t2 已阻塞在信号量上
    d.cancel()               # 取消在 t1 running 时到达
    release_t1.set()
    await dispatch_task
    assert d._states["t1"].status == "done"  # running 子任务不硬杀
    assert d._states["t2"].status == "cancelled"
    assert d._states["t2"].error == "cancelled by user"
    assert ran == ["t1"]  # t2 未调 _run_subagent


@pytest.mark.asyncio()
async def test_cancel_before_dispatch_skips_review_loop(tmp_path, monkeypatch):
    """取消后验证环不触发：plan_covered 已满足也不拉 reviewer。

    回归 A8 fix round 1 —— 单批全量 dispatch 时 _next_task_index 覆盖
    total_tasks → plan_covered=True；修复前取消后仍会调 _run_review 拉
    reviewer（浪费 token + 落 review + 给已取消 run 推 task_review 事件）。
    """
    _init_tmp_db(tmp_path, monkeypatch)
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="orch-test",
        total_tasks=1,
    )
    ran = []
    review_calls = []

    async def fake_run(state):
        ran.append(state.task_id)

    async def fake_review(aggregated):
        review_calls.append(aggregated)
        return {"verdict": "pass", "block": "\n\n[复核通过]", "assertion_count": 0}

    d._run_subagent = fake_run
    d._run_review = fake_review
    d.cancel()
    # 缺 task_id → 自分配路径 → _next_task_index=1 覆盖 total_tasks=1 → plan_covered=True。
    # 取消后 review 门必须拦下（不触发 _run_review）。
    await d.dispatch([{"agent_id": "r", "goal": "g"}])
    assert ran == []  # queued 全转 cancelled，未调 _run_subagent
    assert review_calls == []  # 取消后绝不拉 reviewer
    assert d._reviewed is False  # 门被跳过，未置位一次性守卫


def test_aggregate_in_flight_excludes_cancelled():
    """_aggregate 把 cancelled 从 in_flight 扣除，聚合头单列「已取消」。

    回归 A8 fix round 1 —— 修复前 cancelled 计入 in_flight，取消的任务仍
    显示"仍在并行运行"，误导 conductor 继续等待/重复 dispatch。
    """
    from backend.orchestration.chat_dispatcher import ChatTaskState

    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-test")
    terminal = [
        ChatTaskState(task_id="t1", agent_id="r", goal="g1", status="done", output="ok"),
        ChatTaskState(
            task_id="t2",
            agent_id="r",
            goal="g2",
            status="cancelled",
            error="cancelled by user",
        ),
        ChatTaskState(task_id="t3", agent_id="r", goal="g3", status="failed", error="boom"),
    ]
    result = d._aggregate(terminal)
    assert "仍在并行运行" not in result  # in_flight=0 → 全部完成
    assert "（1 已取消）" in result  # 聚合头单列已取消
    assert "[状态: cancelled]" in result  # cancelled 子任务块仍展示

    partial = [
        ChatTaskState(task_id="t1", agent_id="r", goal="g1", status="running"),
        ChatTaskState(
            task_id="t2",
            agent_id="r",
            goal="g2",
            status="cancelled",
            error="cancelled by user",
        ),
    ]
    result2 = d._aggregate(partial)
    assert ",1 个仍在并行运行" in result2  # in_flight=1（仅 running），cancelled 不计
    assert "（1 已取消）" in result2
