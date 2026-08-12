"""ChatDispatcher 单元测试 —— 轻量子 agent 调度器。

- 并发执行 + task_status 事件顺序 queued→running→done
- 单任务失败错误隔离，其余继续
- 并发上限 4 生效（5 个任务最大并行 ≤4）
- 单子结果截断 50KB
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from backend.orchestration.chat_dispatcher import (
    MAX_AGGREGATE_CHARS,
    MAX_CONCURRENT_SUBAGENTS,
    MAX_SUBAGENT_RESULT_CHARS,
    ChatDispatcher,
)


class _FakeSageAgent:
    """可编程子 agent：记录并发数 + 每次调用注入延迟。"""

    def __init__(self, results, delay: float = 0.0):
        self.results = list(results)
        self.delay = delay
        self.active = 0
        self.max_active = 0

    async def run_loop(self, messages, max_iterations=None, llm_config=None):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            content = self.results.pop(0) if self.results else "ok"
            yield self._event("DONE", content)
        finally:
            self.active -= 1

    @staticmethod
    def _event(state: str, content: str):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        return AgentEvent(state=AgentState.DONE, content=content)


def _make_queue():
    return asyncio.Queue()


def _collect_events(queue: asyncio.Queue, n: int) -> list[dict]:
    return [queue.get_nowait() for _ in range(n)]


@pytest.mark.asyncio()
async def test_dispatch_parallel_runs_and_pushes_statuses():
    """2 个子任务 → 事件序 queued→running→done 各 2 次，聚合含两子结果。"""
    queue = _make_queue()
    dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
    fake = _FakeSageAgent(results=["研究结果 A", "研究结果 B"])

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=fake):
        aggregated = await dispatcher.dispatch(
            [
                {"agent_id": "researcher", "goal": "搜集资料 A"},
                {"agent_id": "researcher", "goal": "搜集资料 B"},
            ]
        )

    events = _collect_events(queue, 6)
    statuses = [e["status"] for e in events]
    assert statuses == ["queued", "queued", "running", "running", "done", "done"]
    assert {e["state"] for e in events} == {"task_status"}
    assert all(e["run_id"] == "orch-test" for e in events)
    assert [e["task_id"] for e in events] == ["t1", "t2", "t1", "t2", "t1", "t2"]

    assert "研究结果 A" in aggregated
    assert "研究结果 B" in aggregated
    assert fake.max_active <= 2


@pytest.mark.asyncio()
async def test_dispatch_single_failure_isolated():
    """子任务 2 抛异常 → failed + 错误进聚合，子任务 1 正常 done，不整体崩溃。"""
    queue = _make_queue()

    class _FailSecond:
        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            from backend.core.legacy.agent_state import AgentEvent, AgentState

            goal = messages[-1]["content"]
            if "崩溃" in goal:
                raise RuntimeError("调研网络失败")
            yield AgentEvent(state=AgentState.DONE, content="正常结果")

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=_FailSecond()):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        aggregated = await dispatcher.dispatch(
            [
                {"agent_id": "researcher", "goal": "正常任务"},
                {"agent_id": "researcher", "goal": "这个会崩溃"},
            ]
        )

    events = _collect_events(queue, 6)
    done = {e["task_id"] for e in events if e["status"] == "done"}
    failed = {e["task_id"] for e in events if e["status"] == "failed"}
    assert done == {"t1"}
    assert failed == {"t2"}
    assert "正常结果" in aggregated
    assert "调研网络失败" in aggregated


@pytest.mark.asyncio()
async def test_dispatch_concurrency_capped_at_four():
    """5 个任务，并发上限 4 —— 最大同时 active ≤ 4。"""
    queue = _make_queue()
    fake = _FakeSageAgent(results=["r"] * 5, delay=0.02)

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        await dispatcher.dispatch([{"agent_id": "researcher", "goal": f"g{i}"} for i in range(5)])

    assert fake.max_active == MAX_CONCURRENT_SUBAGENTS


@pytest.mark.asyncio()
async def test_dispatch_truncates_results_to_50kb():
    """单子结果超长 → 聚合截断到 MAX_SUBAGENT_RESULT_CHARS。"""
    queue = _make_queue()
    big = "x" * (MAX_SUBAGENT_RESULT_CHARS + 10_000)
    fake = _FakeSageAgent(results=[big])

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        aggregated = await dispatcher.dispatch([{"agent_id": "researcher", "goal": "g"}])

    body = aggregated.split("## 子任务 t1")[-1]
    assert len(body) <= MAX_SUBAGENT_RESULT_CHARS + 100
    assert "xxxxx" in body


@pytest.mark.asyncio()
async def test_dispatch_no_done_content_raises():
    """子 agent 未产出 DONE content → 该任务 failed，其余继续。"""
    queue = _make_queue()

    class _NoOutput:
        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            from backend.core.legacy.agent_state import AgentEvent, AgentState

            yield AgentEvent(state=AgentState.THINKING, iteration=0)
            yield AgentEvent(state=AgentState.DONE, iteration=0, content=None)

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=_NoOutput()):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        aggregated = await dispatcher.dispatch([{"agent_id": "researcher", "goal": "g"}])

    events = _collect_events(queue, 3)
    assert events[-1]["status"] == "failed"
    assert "未产出 DONE content" in aggregated


@pytest.mark.asyncio()
async def test_dispatch_task_ids_are_t_indexed():
    """dispatch 按传入顺序编号 t1/t2/t3 —— 与 producer task_plan 契约一致。"""
    queue = _make_queue()
    fake = _FakeSageAgent(results=["a", "b", "c"])

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": f"g{i}"} for i in range(3)]
        )

    events = _collect_events(queue, 9)
    assert {e["task_id"] for e in events} == {"t1", "t2", "t3"}


@pytest.mark.asyncio()
async def test_dispatch_unknown_agent_fails_fast():
    """agent_id 不存在/禁用 → 快速失败（spec §5.1），不构造无身份 child。"""
    queue = _make_queue()

    class _ShouldNotRun:
        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            raise AssertionError("未知 agent 不应被构造")

    # 关键：chat_dispatcher 在模块顶部 from-import 创建本地绑定，
    # patch 必须打在 chat_dispatcher 模块里的符号，不能打 profiles 路径。
    with patch(
        "backend.orchestration.chat_dispatcher.get_enabled_agent", return_value=None
    ), patch(
        "backend.orchestration.chat_dispatcher.SageAgent",
        return_value=_ShouldNotRun(),
    ):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        aggregated = await dispatcher.dispatch(
            [{"agent_id": "ghost_agent", "goal": "g"}]
        )

    events = _collect_events(queue, 3)
    assert events[0]["status"] == "queued"
    assert events[-1]["status"] == "failed"
    assert "ghost_agent" in aggregated
    # 修复前：child 被构造、run_loop 抛 AssertionError → 错误信息不符 → 本断言 RED
    assert "不存在或已禁用" in aggregated


@pytest.mark.asyncio()
async def test_dispatch_missing_agent_id_key_fails():
    """缺 agent_id 键（malformed input）→ KeyError → failed 状态事件，错误含 agent_id。"""
    queue = _make_queue()

    class _ShouldNotRun:
        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            raise AssertionError("缺 agent_id 的任务不应触发 SageAgent.run_loop")

    with patch(
        "backend.orchestration.chat_dispatcher.SageAgent",
        return_value=_ShouldNotRun(),
    ):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        aggregated = await dispatcher.dispatch([{}])

    events = _collect_events(queue, 2)
    assert events[0]["status"] == "queued"
    assert events[-1]["status"] == "failed"
    assert "agent_id" in aggregated


# =========================================================================
# 进度可视化 P0-1 (2026-08-12): _aggregate 头部进度摘要
# =========================================================================


@pytest.mark.asyncio()
async def test_aggregate_includes_progress_header_when_partial():
    """3 子任务中 1 done + 2 running,聚合 markdown 头部含 '已收到 1/3' 与提示文。"""
    queue = _make_queue()
    fake = _FakeSageAgent(results=["唯一完成的结果"], delay=0.0)

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        aggregated = await dispatcher.dispatch(
            [
                {"agent_id": "researcher", "goal": "正常"},
                {"agent_id": "writer", "goal": None},  # 缺键 → failed
                {"agent_id": "writer", "goal": "另一个"},
            ]
        )

    # 上面 3 任务实际是 2 done + 1 failed,全完成路径;校验 header 存在
    # 且不出现 "仍在并行运行" 字眼(避免 partial 路径串扰)。
    assert "## 子任务进度摘要" in aggregated
    assert "已收到" in aggregated
    assert "仍在并行运行" not in aggregated


@pytest.mark.asyncio()
async def test_aggregate_partial_shows_inflight_notice():
    """部分完成路径:header 出现 "仍在并行运行" + 请等待所有子任务。"""
    from backend.orchestration.chat_dispatcher import ChatDispatcher, ChatTaskState

    queue = _make_queue()
    dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
    # 1 done + 1 running + 1 queued
    states = [
        ChatTaskState(
            task_id="t1", agent_id="researcher", goal="g1",
            status="done", output="前 1 完成的结果",
        ),
        ChatTaskState(
            task_id="t2", agent_id="researcher", goal="g2",
            status="running",
        ),
        ChatTaskState(
            task_id="t3", agent_id="researcher", goal="g3",
            status="queued",
        ),
    ]
    aggregated = dispatcher._aggregate(states)

    assert "## 子任务进度摘要（部分完成）" in aggregated
    assert "已收到 1/3 子任务结果" in aggregated
    assert "2 个仍在并行运行" in aggregated
    assert "请等待所有子任务完成后给出最终汇总" in aggregated
    assert "## 子任务 t1" in aggregated
    assert "前 1 完成的结果" in aggregated


@pytest.mark.asyncio()
async def test_aggregate_all_done_omits_inflight_notice():
    """全部完成路径:header 简化,不出现 "仍在并行运行"。"""
    from backend.orchestration.chat_dispatcher import ChatDispatcher, ChatTaskState

    queue = _make_queue()
    dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
    states = [
        ChatTaskState(task_id="t1", agent_id="r", goal="g1", status="done", output="a"),
        ChatTaskState(task_id="t2", agent_id="r", goal="g2", status="done", output="b"),
        ChatTaskState(task_id="t3", agent_id="r", goal="g3", status="done", output="c"),
    ]
    aggregated = dispatcher._aggregate(states)

    assert "## 子任务进度摘要（全部完成）" in aggregated
    assert "已收到 3/3 子任务结果" in aggregated
    assert "仍在并行运行" not in aggregated
    assert "请等待" not in aggregated


# =========================================================================
# 修复 F1 (2026-08-12): task_id 跨 dispatch 调用全局递增
# =========================================================================


@pytest.mark.asyncio()
async def test_dispatch_task_ids_continue_across_calls():
    """多次 dispatch 调用 task_id 全局递增 —— 修复前每次从 t1 重编号，
    计划 t4-t6 永远收不到 status 事件（UI 恒显 3/6）。"""
    queue = _make_queue()
    fake = _FakeSageAgent(results=["a", "b", "c", "d", "e"])

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": f"g{i}"} for i in range(3)]
        )
        await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": f"g{i}"} for i in range(2)]
        )

    events = _collect_events(queue, 15)
    task_ids = [e["task_id"] for e in events]
    # 第一次派发 t1-t3、第二次派发 t4-t5 —— 全局唯一，无碰撞
    assert set(task_ids) == {"t1", "t2", "t3", "t4", "t5"}
    # 与 producer 计划编号（t1..tN）对齐：第二次调用的首个任务必须是 t4
    assert task_ids[0] == "t1"
    assert task_ids[9] == "t4"


@pytest.mark.asyncio()
async def test_dispatch_task_ids_skip_malformed_consumes_counter():
    """malformed 任务（缺 agent_id）也消耗全局计数器，不挤占后续合法任务编号。"""
    queue = _make_queue()
    fake = _FakeSageAgent(results=["ok"])

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        # 第 1 个缺 agent_id（failed 占位 t1），第 2 个正常（t2）
        aggregated = await dispatcher.dispatch([{}, {"agent_id": "researcher", "goal": "g"}])

    assert "t1" in aggregated  # malformed 占位
    assert "## 子任务 t2" in aggregated  # 合法任务编号未被 t1 挤占
    events = _collect_events(queue, 5)  # t1: queued+failed; t2: queued+running+done
    task_ids = {e["task_id"] for e in events}
    assert task_ids == {"t1", "t2"}


# =========================================================================
# F3 (2026-08-12): 聚合总上限（maxItems 4→8 后单批最多 8 项，防灌爆上下文）
# =========================================================================


@pytest.mark.asyncio()
async def test_dispatch_aggregate_total_capped():
    """8 个子任务各接近单任务上限 → 聚合总长度被 MAX_AGGREGATE_CHARS 截断。"""
    queue = _make_queue()
    big = "x" * MAX_SUBAGENT_RESULT_CHARS  # 每项接近单任务 50KB 上限
    fake = _FakeSageAgent(results=[big] * 8)

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        aggregated = await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": f"g{i}"} for i in range(8)]
        )

    assert len(aggregated) <= MAX_AGGREGATE_CHARS + 200, (
        f"聚合总长 {len(aggregated)} 超过上限 {MAX_AGGREGATE_CHARS}"
    )
    assert "已截断" in aggregated  # 尾部提示让 conductor 知道结果不完整
    # 截断必须保留头部进度摘要（header 是前缀，切片不砍它）——
    # 否则 conductor 失去"8 个结果已收到"的计数锚点。
    assert "已收到 8/8 子任务结果" in aggregated
