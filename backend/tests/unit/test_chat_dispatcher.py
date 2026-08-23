"""ChatDispatcher 单元测试 —— 经 LaneExecutor 执行（P0-1 lane 镜像 + 重试）。

- 并发执行 + task_status 事件顺序 queued→running→done
- 单任务重试耗尽 → failed 错误隔离，其余继续
- 并发上限 4 生效（5 个任务最大并行 ≤4）
- lane 镜像：每子任务在 lane_registry 产生 SUCCEEDED lane
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from backend.orchestration.chat_dispatcher import ChatDispatcher
from backend.orchestration.orch_settings import OrchSettings

_DUMMY_PROFILE = {"system_prompt": "你是测试子 agent", "tools": []}


class _FakeSageAgent:
    """可编程子 agent：记录并发数 + 可注入失败次数。"""

    def __init__(
        self,
        results=("ok",),
        delay: float = 0.0,
        fail_times: int = 0,
        fail_goal: str | None = None,
    ):
        self.results = list(results)
        self.delay = delay
        self.fail_times = fail_times
        self.fail_goal = fail_goal
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def run_loop(self, messages, max_iterations=None, llm_config=None):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        self.calls += 1
        goal = messages[-1]["content"] if messages else ""
        if (self.fail_goal is not None and self.fail_goal in goal) or (
            self.calls <= self.fail_times
        ):
            raise RuntimeError("transient failure")
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            content = self.results.pop(0) if self.results else "ok"
            yield AgentEvent(state=AgentState.DONE, content=content)
        finally:
            self.active -= 1


class _BrokenReview(_FakeSageAgent):
    """Wave 2 Minor T5 M1 fix: 真 async gen — 先 yield 一次再 raise。

    保持 async gen 协议（yield → raise），注入 RuntimeError 时不触发
    "coroutine never awaited" RuntimeWarning；exc 可注入（默认 "reviewer boom"
    兼容既有 reviewer 崩溃测试的零参构造）。
    """

    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc if exc is not None else RuntimeError("reviewer boom")

    async def run_loop(self, messages=None, max_iterations=None, llm_config=None):
        # 必须先 yield 一次（async gen 协议），然后抛
        yield {"state": "task_review_partial", "text": "starting"}
        raise self.exc


def _make_queue():
    return asyncio.Queue()


def _collect_events(queue: asyncio.Queue, n: int) -> list[dict]:
    return [queue.get_nowait() for _ in range(n)]


def _patch_subagents(fake):
    """Enter both subagent patches on an ExitStack so the returned object can be
    used directly as ``with _patch_subagents(fake):``（py3.10 元组不可直接作 CM）。"""
    stack = ExitStack()
    stack.enter_context(
        patch(
            "backend.orchestration.subagent_runner.get_enabled_agent",
            return_value=_DUMMY_PROFILE,
        )
    )
    stack.enter_context(
        patch("backend.orchestration.subagent_runner.SageAgent", return_value=fake)
    )
    return stack


@pytest.mark.asyncio()
async def test_dispatch_parallel_runs_and_pushes_statuses():
    """2 个子任务 → 事件序 queued→running→done 各 2 次，聚合含两子结果。"""
    queue = _make_queue()
    dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
    fake = _FakeSageAgent(results=["研究结果 A", "研究结果 B"])

    with _patch_subagents(fake):
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
    assert all(e["retry_count"] == 0 for e in events)

    assert "研究结果 A" in aggregated
    assert "研究结果 B" in aggregated
    assert fake.max_active <= 2


@pytest.mark.asyncio()
async def test_dispatch_retry_exhausted_isolated():
    """子任务 2 恒失败 → 重试 2 次后 failed + 错误进聚合，子任务 1 正常 done。"""
    queue = _make_queue()
    # brief 原用 fail_times=999（共享 fake 全局计数）——两个子任务并发共享同一
    # 计数器，999 会让 t1 也耗尽重试而 failed，无法验证"错误隔离"。改为按 goal
    # 定向失败：仅"崩溃任务"恒失败，其余子任务正常完成（assertions 不变）。
    fake = _FakeSageAgent(results=["正常结果", "失败结果"], fail_goal="崩溃")

    with _patch_subagents(fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        aggregated = await dispatcher.dispatch(
            [
                {"agent_id": "researcher", "goal": "正常任务"},
                {"agent_id": "researcher", "goal": "崩溃任务"},
            ]
        )

    events = _collect_events(queue, 6)
    done = {e["task_id"] for e in events if e["status"] == "done"}
    failed = {e["task_id"] for e in events if e["status"] == "failed"}
    assert done == {"t1"}
    assert failed == {"t2"}
    assert "正常结果" in aggregated
    assert "MAX_RETRIES_EXCEEDED" in aggregated or "transient failure" in aggregated
    assert fake.calls >= 3  # 4 次 = t1 成功×1 + t2 首次+重试×2


@pytest.mark.asyncio()
async def test_dispatch_concurrency_capped_at_four():
    """5 个任务，并发上限 = settings.max_concurrent_subagents（默认 4）—— 最大 active ≤ 上限。"""
    queue = _make_queue()
    fake = _FakeSageAgent(results=["ok"] * 5, delay=0.01)

    with _patch_subagents(fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": f"任务{i}"} for i in range(5)]
        )

    # P2-9: semaphore 由 settings 驱动，断言对齐实例配置而非模块常量。
    assert fake.max_active <= dispatcher.settings.max_concurrent_subagents


@pytest.mark.asyncio()
async def test_dispatch_lane_mirrored_with_retry_count():
    """lane 镜像：子任务 lane 落库且 SUCCEEDED；重试后 retry_count 进事件。"""
    from backend.orchestration.lane_registry import LaneRegistry
    from backend.orchestration.task_registry import TaskRegistry

    queue = _make_queue()
    lane_registry = LaneRegistry()
    task_registry = TaskRegistry()
    fake = _FakeSageAgent(results=["最终成功"], fail_times=1)

    with _patch_subagents(fake):
        dispatcher = ChatDispatcher(
            stream_id="s1",
            entry_queue=queue,
            run_id="orch-retry",
            lane_registry=lane_registry,
            task_registry=task_registry,
        )
        aggregated = await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": "一次失败后成功"}]
        )

    events = _collect_events(queue, 3)
    assert events[-1]["status"] == "done"
    assert events[-1]["retry_count"] == 1  # fail 1 次 → 重试 1 次

    lane = lane_registry.get_lane("lane-t1")
    assert lane is not None
    assert lane.status.value == "succeeded"
    assert lane.metadata["retry_count"] == 1
    assert lane.metadata["task_id"] == "t1"
    assert "最终成功" in aggregated


_REVIEW_OUTPUT = (
    "[FACT] 资料已完整覆盖量化交易基础 (confidence: 0.9)\n"
    "[HYPOTHESIS] 回测结果可外推 (confidence: 0.5)\n"
)


class _ReviewSageAgent(_FakeSageAgent):
    """reviewer 专用 fake：产出 assertion 文本。"""

    def __init__(self, content: str = _REVIEW_OUTPUT):
        super().__init__(results=[content])


@pytest.mark.asyncio()
async def test_dispatch_runs_review_when_all_planned_tasks_dispatched():
    """total_tasks 达标 → 聚合追加复核块 + review lane SUCCEEDED。"""
    from backend.orchestration.lane_registry import LaneRegistry
    from backend.orchestration.task_registry import TaskRegistry

    queue = _make_queue()
    lane_registry = LaneRegistry()
    task_registry = TaskRegistry()
    sub_fake = _FakeSageAgent(results=["研究结果"])
    rev_fake = _ReviewSageAgent()

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch(
        "backend.orchestration.subagent_runner.SageAgent",
        side_effect=[sub_fake, rev_fake],
    ):
        dispatcher = ChatDispatcher(
            stream_id="s1",
            entry_queue=queue,
            run_id="orch-review",
            lane_registry=lane_registry,
            task_registry=task_registry,
            total_tasks=1,
        )
        aggregated = await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": "调研量化交易"}]
        )

    assert "## 复核结果（reviewer）" in aggregated
    assert "verdict: pass" in aggregated
    assert "2 条 assertion" in aggregated
    # review lane 落库 SUCCEEDED
    review_lane = lane_registry.get_lane("lane-review-orch-review")
    assert review_lane is not None
    assert review_lane.status.value == "succeeded"
    # 子任务 lane 也 SUCCEEDED
    assert lane_registry.get_lane("lane-t1").status.value == "succeeded"


@pytest.mark.asyncio()
async def test_dispatch_review_fail_on_negative_evidence():
    """NEGATIVE_EVIDENCE 高置信 → verdict fail，block 要求修复。"""
    queue = _make_queue()
    rev_fake = _ReviewSageAgent(
        content="[NEGATIVE_EVIDENCE] 缺少回测数据支撑 (confidence: 0.9)\n"
    )

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch(
        "backend.orchestration.subagent_runner.SageAgent",
        side_effect=[_FakeSageAgent(results=["研究结果"]), rev_fake],
    ):
        dispatcher = ChatDispatcher(
            stream_id="s1", entry_queue=queue, run_id="orch-review-fail", total_tasks=1
        )
        aggregated = await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": "调研量化交易"}]
        )

    assert "verdict: fail" in aggregated
    assert "修复" in aggregated


@pytest.mark.asyncio()
async def test_dispatch_review_failure_skips_without_blocking():
    """reviewer 崩溃 → 跳过验证，聚合不变，不抛异常。"""
    queue = _make_queue()

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch(
        "backend.orchestration.subagent_runner.SageAgent",
        side_effect=[_FakeSageAgent(results=["研究结果"]), _BrokenReview()],
    ):
        dispatcher = ChatDispatcher(
            stream_id="s1", entry_queue=queue, run_id="orch-review-skip", total_tasks=1
        )
        aggregated = await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": "调研量化交易"}]
        )

    assert "研究结果" in aggregated
    assert "## 复核结果" not in aggregated


@pytest.mark.asyncio()
async def test_dispatch_no_review_when_total_tasks_unset():
    """total_tasks 未设（None）→ 不跑 review，聚合无复核块。"""
    queue = _make_queue()
    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch(
        "backend.orchestration.subagent_runner.SageAgent",
        return_value=_FakeSageAgent(results=["研究结果"]),
    ):
        dispatcher = ChatDispatcher(
            stream_id="s1", entry_queue=queue, run_id="orch-plain"
        )
        aggregated = await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": "调研量化交易"}]
        )

    assert "## 复核结果" not in aggregated


# P2-9 (2026-08-14) — dispatcher 注入 OrchSettings：构造注入覆盖默认；缺省回落。
def test_dispatcher_injects_settings():
    """构造传入 settings → 实例用它（semaphore/retry/scratch）。"""
    d = ChatDispatcher(
        stream_id="s1",
        entry_queue=asyncio.Queue(),
        run_id="orch-test",
        settings=OrchSettings(max_concurrent_subagents=1, scratch_root="custom"),
    )
    assert d._semaphore._value == 1
    assert d.settings.scratch_root == "custom"


def test_dispatcher_defaults_settings_when_omitted():
    """不传 settings → load_orch_settings() 回落默认。"""
    d = ChatDispatcher(stream_id="s1", entry_queue=asyncio.Queue(), run_id="orch-test")
    assert d.settings.max_concurrent_subagents == 4


@pytest.mark.asyncio()
async def test_dispatch_passes_output_schema_to_subagent(monkeypatch):
    """tool-passed output_schema 进入 ChatTaskState 并写进 Task.parameters。"""
    captured = {}
    queue = _make_queue()
    dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-schema")

    async def fake_run_subagent(state):
        captured["schema"] = state.output_schema
        return "ok"

    monkeypatch.setattr(dispatcher, "_run_subagent", fake_run_subagent)
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}

    await dispatcher.dispatch(
        [
            {
                "task_id": "dynamic-1",
                "agent_id": "primary",
                "goal": "g",
                "output_schema": schema,
            }
        ]
    )

    assert captured["schema"] == schema
    assert dispatcher._states["dynamic-1"].output_schema == schema


@pytest.mark.asyncio()
async def test_followup_task_inherits_done_parent_history(monkeypatch):
    """有效 followup_of 复用已完成父任务历史，并建立隐式依赖。"""
    queue = _make_queue()
    dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-followup")
    history = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "previous"},
    ]

    async def fake_run_subagent(state):
        return "done"

    original_run_subagent = dispatcher._run_subagent
    monkeypatch.setattr(dispatcher, "_run_subagent", fake_run_subagent)
    await dispatcher.dispatch(
        [{"task_id": "t1", "agent_id": "primary", "goal": "原任务"}]
    )
    dispatcher._histories["t1"] = history

    async def fake_lane_result(executor, lane, agent_id):
        task = dispatcher.task_registry.get_task(lane.task_id)
        assert task.parameters["history"] == history
        return {
            "status": "succeeded",
            "result": {"output": "done", "messages": history},
        }

    from backend.orchestration import chat_dispatcher as module

    monkeypatch.setattr(module, "run_lane_with_retry", fake_lane_result)
    monkeypatch.setattr(dispatcher, "_run_subagent", original_run_subagent)

    built = {}
    original_build_waves = module.build_waves

    def capture_build_waves(task_ids, deps_by_id):
        built["deps"] = deps_by_id
        return original_build_waves(task_ids, deps_by_id)

    monkeypatch.setattr(module, "build_waves", capture_build_waves)
    await dispatcher.dispatch(
        [
            {
                "task_id": "t2",
                "agent_id": "primary",
                "goal": "追问",
                "followup_of": "t1",
            }
        ]
    )

    assert dispatcher._states["t2"].parent_task_id == "t1"
    assert dispatcher.task_registry.get_task("task-t2").parameters["history"] == history
    assert built["deps"]["t2"] == ["t1"]


@pytest.mark.asyncio()
async def test_followup_invalid_parent_degrades_to_new_task(caplog):
    """不存在或未完成的 followup_of 降级为普通任务，不建立父依赖。"""
    dispatcher = ChatDispatcher(
        stream_id="s1", entry_queue=_make_queue(), run_id="orch-invalid-followup"
    )

    async def fake_run_subagent(state):
        return "done"

    dispatcher._run_subagent = fake_run_subagent
    with caplog.at_level("WARNING"):
        await dispatcher.dispatch(
            [
                {
                    "task_id": "t1",
                    "agent_id": "primary",
                    "goal": "未完成父任务",
                    "followup_of": "missing",
                }
            ]
        )

    assert dispatcher._states["t1"].parent_task_id is None
    assert "followup_of" in caplog.text
