"""ChatDispatcher 单元测试 —— 经 LaneExecutor 执行（P0-1 lane 镜像 + 重试）。

- 并发执行 + task_status 事件顺序 queued→running→done
- 单任务重试耗尽 → failed 错误隔离，其余继续
- 并发上限 4 生效（5 个任务最大并行 ≤4）
- lane 镜像：每子任务在 lane_registry 产生 SUCCEEDED lane
"""

from __future__ import annotations

import asyncio
import subprocess
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


@pytest.mark.asyncio()
async def test_worktree_isolation_wires_policy_and_cleans(monkeypatch, tmp_path):
    """开启隔离时 task parameters 使用 worktree，任务结束后清理副本。"""
    from backend.orchestration import chat_dispatcher as module

    created = []
    removed = []

    async def fake_is_git_repo(path):
        return path == tmp_path

    async def fake_create(repo, dest):
        created.append((repo, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.mkdir(exist_ok=True)
        return True

    async def fake_remove(dest):
        removed.append(dest)

    captured = {}

    async def fake_run_lane(executor, lane, agent_id):
        task = executor.task_registry.get_task(lane.task_id)
        captured["parameters"] = dict(task.parameters)
        return {"status": "succeeded", "result": {"output": "ok"}}

    monkeypatch.setattr(module, "run_lane_with_retry", fake_run_lane)
    monkeypatch.setattr(module, "get_database", lambda: type("DB", (), {"db_path": str(tmp_path / "sage.db")})())
    monkeypatch.setattr("backend.orchestration.worktree.is_git_repo_async", fake_is_git_repo)
    monkeypatch.setattr("backend.orchestration.worktree.create_worktree_async", fake_create)
    monkeypatch.setattr("backend.orchestration.worktree.remove_worktree_async", fake_remove)

    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=_make_queue(),
        run_id="orch-wt",
        settings=OrchSettings(worktree_isolation=True),
        workspace_root=str(tmp_path),
    )
    await dispatcher.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g"}])

    assert created
    assert captured["parameters"]["workspace_dir"] == str(tmp_path / "orch_worktrees" / "orch-wt" / "t1")
    assert removed == [tmp_path / "orch_worktrees" / "orch-wt" / "t1"]
    assert dispatcher._worktree_dirs == []


@pytest.mark.asyncio()
async def test_worktree_isolation_disabled_or_non_repo_falls_back(monkeypatch, tmp_path):
    """开关关闭或 workspace 非 git repo 时保持 scratch 行为。"""
    from backend.orchestration import chat_dispatcher as module

    captured = []

    async def fake_run_lane(executor, lane, agent_id):
        task = executor.task_registry.get_task(lane.task_id)
        captured.append(task.parameters)
        return {"status": "succeeded", "result": {"output": "ok"}}

    monkeypatch.setattr(module, "run_lane_with_retry", fake_run_lane)
    monkeypatch.setattr(module, "get_database", lambda: type("DB", (), {"db_path": str(tmp_path / "sage.db")})())

    async def fake_is_git_repo_false(path):
        return False

    monkeypatch.setattr(
        "backend.orchestration.worktree.is_git_repo_async", fake_is_git_repo_false
    )

    disabled = ChatDispatcher(
        stream_id="s1", entry_queue=_make_queue(), run_id="orch-off",
        settings=OrchSettings(worktree_isolation=False), workspace_root=str(tmp_path),
    )
    await disabled.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g"}])

    non_repo = ChatDispatcher(
        stream_id="s1", entry_queue=_make_queue(), run_id="orch-plain",
        settings=OrchSettings(worktree_isolation=True), workspace_root=str(tmp_path),
    )
    await non_repo.dispatch([{"task_id": "t2", "agent_id": "primary", "goal": "g"}])

    assert captured[0]["workspace_dir"] is None
    assert captured[1]["workspace_dir"] is None


@pytest.mark.asyncio()
async def test_worktree_create_async_exception_falls_back(monkeypatch, tmp_path):
    """创建路径抛异常 → 回落 scratch，任务照常成功，无残留副本。"""
    from backend.orchestration import chat_dispatcher as module

    captured = {}

    async def boom_create(repo, dest):
        raise RuntimeError("disk full")

    async def fake_run_lane(executor, lane, agent_id):
        task = executor.task_registry.get_task(lane.task_id)
        captured["parameters"] = dict(task.parameters)
        return {"status": "succeeded", "result": {"output": "ok"}}

    async def fake_is_git_repo_true(path):
        return True

    monkeypatch.setattr(module, "run_lane_with_retry", fake_run_lane)
    monkeypatch.setattr(module, "get_database", lambda: type("DB", (), {"db_path": str(tmp_path / "sage.db")})())
    monkeypatch.setattr(
        "backend.orchestration.worktree.is_git_repo_async", fake_is_git_repo_true
    )
    monkeypatch.setattr("backend.orchestration.worktree.create_worktree_async", boom_create)

    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=_make_queue(),
        run_id="orch-boom",
        settings=OrchSettings(worktree_isolation=True),
        workspace_root=str(tmp_path),
    )
    await dispatcher.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g"}])

    assert captured["parameters"]["workspace_dir"] is None
    assert dispatcher._worktree_dirs == []


@pytest.mark.asyncio()
async def test_worktree_cleanup_async_exception_keeps_result(monkeypatch, tmp_path):
    """清理抛异常被吞 → 成功任务的文本结果不被覆盖。"""
    from backend.orchestration import chat_dispatcher as module

    created = []

    async def fake_is_git_repo(path):
        return path == tmp_path

    async def fake_create(repo, dest):
        created.append(dest)
        dest.mkdir(parents=True, exist_ok=True)
        return True

    async def boom_remove(dest):
        raise RuntimeError("cleanup failed")

    async def fake_run_lane(executor, lane, agent_id):
        return {"status": "succeeded", "result": {"output": "完成结果"}}

    monkeypatch.setattr(module, "run_lane_with_retry", fake_run_lane)
    monkeypatch.setattr(module, "get_database", lambda: type("DB", (), {"db_path": str(tmp_path / "sage.db")})())
    monkeypatch.setattr("backend.orchestration.worktree.is_git_repo_async", fake_is_git_repo)
    monkeypatch.setattr("backend.orchestration.worktree.create_worktree_async", fake_create)
    monkeypatch.setattr("backend.orchestration.worktree.remove_worktree_async", boom_remove)

    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=_make_queue(),
        run_id="orch-cleanup",
        settings=OrchSettings(worktree_isolation=True),
        workspace_root=str(tmp_path),
    )
    aggregated = await dispatcher.dispatch(
        [{"task_id": "t1", "agent_id": "primary", "goal": "g"}]
    )

    assert "完成结果" in aggregated
    assert dispatcher._worktree_dirs == []


@pytest.mark.asyncio()
async def test_worktree_async_path_does_not_block_event_loop(monkeypatch, tmp_path):
    """git 慢操作期间事件循环仍能响应并发任务 —— 异步路径不阻塞。"""
    from backend.orchestration import chat_dispatcher as module

    entered = asyncio.Event()
    release = asyncio.Event()
    ticker_done = asyncio.Event()
    ticks = 0

    async def slow_create(repo, dest):
        entered.set()
        await release.wait()
        dest.mkdir(parents=True, exist_ok=True)
        return True

    async def ticker():
        nonlocal ticks
        release.set()
        while not ticker_done.is_set():
            ticks += 1
            await asyncio.sleep(0)

    async def fake_is_git_repo(path):
        return True

    async def fake_remove(dest):
        return None

    async def fake_run_lane(executor, lane, agent_id):
        return {"status": "succeeded", "result": {"output": "ok"}}

    monkeypatch.setattr(module, "run_lane_with_retry", fake_run_lane)
    monkeypatch.setattr(module, "get_database", lambda: type("DB", (), {"db_path": str(tmp_path / "sage.db")})())
    monkeypatch.setattr("backend.orchestration.worktree.is_git_repo_async", fake_is_git_repo)
    monkeypatch.setattr("backend.orchestration.worktree.create_worktree_async", slow_create)
    monkeypatch.setattr("backend.orchestration.worktree.remove_worktree_async", fake_remove)

    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=_make_queue(),
        run_id="orch-nb",
        settings=OrchSettings(worktree_isolation=True),
        workspace_root=str(tmp_path),
    )
    t = asyncio.create_task(ticker())
    await dispatcher.dispatch([{"task_id": "t1", "agent_id": "primary", "goal": "g"}])
    ticker_done.set()
    await t

    assert entered.is_set()
    assert ticks > 0


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
                "agent_id": "writer",
                "goal": "追问",
                "followup_of": "t1",
            }
        ]
    )

    assert dispatcher._states["t2"].parent_task_id == "t1"
    assert dispatcher._states["t2"].agent_id == "primary"
    assert dispatcher.task_registry.get_task("task-t2").parameters["history"] == history
    assert dispatcher._histories["t2"] == history
    assert built["deps"]["t2"] == ["t1"]


@pytest.mark.asyncio()
async def test_planned_followup_uses_new_goal_and_replays_it(monkeypatch):
    """计划权威任务续聊时，raw goal 覆盖计划 goal，并传给 runner。"""
    from backend.orchestration import chat_dispatcher as module

    dispatcher = ChatDispatcher(
        stream_id="s1", entry_queue=_make_queue(), run_id="orch-planned-followup"
    )
    dispatcher._states["t1"] = module.ChatTaskState(
        task_id="t1", agent_id="researcher", goal="原任务", status="done"
    )
    history = [{"role": "system", "content": "system"}]
    dispatcher._histories["t1"] = history
    dispatcher._plan_loaded = True
    dispatcher._plan_by_id = {
        "t2": {"task_id": "t2", "agent_id": "writer", "goal": "计划原目标"}
    }
    captured = {}

    async def fake_lane_result(executor, lane, agent_id):
        task = dispatcher.task_registry.get_task(lane.task_id)
        captured["task_goal"] = task.parameters["goal"]
        captured["agent_id"] = agent_id
        return {
            "status": "succeeded",
            "result": {"output": "ok", "messages": history},
        }

    monkeypatch.setattr(module, "run_lane_with_retry", fake_lane_result)
    await dispatcher.dispatch(
        [
            {
                "task_id": "t2",
                "agent_id": "writer",
                "goal": "新的追问目标",
                "followup_of": "t1",
            }
        ]
    )

    assert dispatcher._states["t2"].goal == "新的追问目标"
    assert captured["task_goal"] == "新的追问目标"
    assert captured["agent_id"] == "researcher"
    assert dispatcher._histories["t2"] == history


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


@pytest.mark.asyncio()
async def test_followup_self_reference_degrades_and_does_not_reject_batch(
    monkeypatch, caplog
):
    """自指 followup_of（task 引用自身）→ warning 后降级普通任务，不因自环拒整批。

    回归场景：父任务 t1 前一批已 done（或 resume 重放），同 run 再次派发
    task_id=t1 且 followup_of=t1 —— 守卫缺失时隐式自环依赖会让 build_waves
    抛环错误拒掉整批（含无辜的 t2）。
    """
    from backend.orchestration import chat_dispatcher as module

    queue = _make_queue()
    dispatcher = ChatDispatcher(
        stream_id="s1", entry_queue=queue, run_id="orch-self-followup"
    )
    dispatcher._states["t1"] = module.ChatTaskState(
        task_id="t1", agent_id="primary", goal="旧任务", status="done"
    )
    ran = []

    async def fake_run_lane(executor, lane, agent_id):
        ran.append(lane.task_id)
        return {"status": "succeeded", "result": {"output": "ok"}}

    monkeypatch.setattr(module, "run_lane_with_retry", fake_run_lane)

    with caplog.at_level("WARNING"):
        await dispatcher.dispatch(
            [
                {"task_id": "t1", "agent_id": "primary", "goal": "g", "followup_of": "t1"},
                {"task_id": "t2", "agent_id": "primary", "goal": "g2"},
            ]
        )

    assert dispatcher._states["t1"].parent_task_id is None
    assert ran == ["task-t1", "task-t2"]
    assert "followup_of" in caplog.text


@pytest.mark.parametrize(
    "bad_run_id",
    [
        "../victim",
        "../../../victim",
        "",
        "a" * 129,
        "has space",
        "slash/path",
        "-leading-dash",
        "_leading_underscore",
        "中文id",
        "dot.name",
    ],
)
def test_constructor_rejects_invalid_run_id(bad_run_id):
    """安全修复波 (2026-08-23): 非法 run_id 构造即抛 ValueError。

    run_id 会拼进 ``<data_dir>/orch_worktrees/<run_id>`` 与 scratch 路径并参与
    ``shutil.rmtree`` —— 含路径分隔符 / 空串 / 超长 / 特殊字符的值可造成路径
    穿越。白名单校验必须在任何副作用（DB、清扫）之前执行。
    """
    with pytest.raises(ValueError, match="非法 run_id"):
        ChatDispatcher(
            stream_id="s1",
            entry_queue=_make_queue(),
            run_id=bad_run_id,
        )


@pytest.mark.parametrize(
    "good_run_id",
    ["orch-test", "orch-self-followup", "a", "A1_b-c", "x" * 128],
)
def test_constructor_accepts_valid_run_id(good_run_id):
    """合法 run_id（含现有测试风格 orch-* / 边界 128 字符）正常构造。"""
    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=_make_queue(),
        run_id=good_run_id,
    )
    assert dispatcher.run_id == good_run_id


def test_constructor_sweeps_stale_worktree_root(monkeypatch, tmp_path):
    """构造时机会性清扫崩溃残留的 ``orch_worktrees/<run_id>`` 孤儿目录。"""
    from backend.orchestration import chat_dispatcher as module

    monkeypatch.setattr(
        module,
        "get_database",
        lambda: type("DB", (), {"db_path": str(tmp_path / "sage.db")})(),
    )
    stale = tmp_path / "orch_worktrees" / "orch-stale-run" / "t9"
    stale.mkdir(parents=True)
    (stale / "marker.txt").write_text("orphan")

    other_run = tmp_path / "orch_worktrees" / "other-run"
    other_run.mkdir(parents=True)

    ChatDispatcher(
        stream_id="s1",
        entry_queue=_make_queue(),
        run_id="orch-stale-run",
        workspace_root=str(tmp_path),
    )

    assert not (tmp_path / "orch_worktrees" / "orch-stale-run").exists()
    # 其他 run 的目录不受影响。
    assert other_run.exists()


def test_constructor_sweep_failure_is_swallowed(monkeypatch, tmp_path):
    """清扫失败（目录只读等）全吞降级 —— 构造绝不抛异常。"""
    from backend.orchestration import chat_dispatcher as module

    monkeypatch.setattr(
        module,
        "get_database",
        lambda: type("DB", (), {"db_path": str(tmp_path / "sage.db")})(),
    )
    stale = tmp_path / "orch_worktrees" / "orch-boom-sweep"
    stale.mkdir(parents=True)

    calls = []

    def flaky_rmtree(path, *args, **kwargs):
        calls.append(path)
        raise OSError("permission denied")

    monkeypatch.setattr(module.shutil, "rmtree", flaky_rmtree)

    dispatcher = ChatDispatcher(
        stream_id="s1", entry_queue=_make_queue(), run_id="orch-boom-sweep"
    )
    assert calls == [tmp_path / "orch_worktrees" / "orch-boom-sweep"]
    assert dispatcher.run_id == "orch-boom-sweep"


def test_constructor_sweep_runs_git_worktree_prune(monkeypatch, tmp_path):
    """清扫 rmtree 成功后 best-effort ``git worktree prune``（安全修复波）。

    崩溃残留目录被 rmtree 后主仓 ``.git/worktrees/`` 管理条目仍在，同路径重建
    worktree 会 rc=128 失败静默回落 scratch —— prune 清掉悬空元数据。
    """
    from backend.orchestration import chat_dispatcher as module

    monkeypatch.setattr(
        module,
        "get_database",
        lambda: type("DB", (), {"db_path": str(tmp_path / "sage.db")})(),
    )
    stale = tmp_path / "orch_worktrees" / "orch-prune-run"
    stale.mkdir(parents=True)

    prune_calls = []

    def fake_prune(cwd=None):
        prune_calls.append(cwd)
        return True

    monkeypatch.setattr("backend.orchestration.worktree.prune_worktrees", fake_prune)

    ChatDispatcher(
        stream_id="s1",
        entry_queue=_make_queue(),
        run_id="orch-prune-run",
        workspace_root=str(tmp_path),
    )

    assert not stale.exists()
    assert len(prune_calls) == 1
    assert prune_calls[0] == tmp_path


def test_constructor_sweep_prune_skipped_without_workspace(monkeypatch, tmp_path):
    """workspace_root 未绑定 → 不执行 prune（无 repo 可清）。"""
    from backend.orchestration import chat_dispatcher as module

    monkeypatch.setattr(
        module,
        "get_database",
        lambda: type("DB", (), {"db_path": str(tmp_path / "sage.db")})(),
    )
    stale = tmp_path / "orch_worktrees" / "orch-prune-skip"
    stale.mkdir(parents=True)

    prune_calls = []

    def fake_prune(cwd=None):
        prune_calls.append(cwd)
        return True

    monkeypatch.setattr("backend.orchestration.worktree.prune_worktrees", fake_prune)

    ChatDispatcher(
        stream_id="s1", entry_queue=_make_queue(), run_id="orch-prune-skip"
    )

    assert not stale.exists()
    assert prune_calls == []


def test_constructor_sweep_prune_failure_is_swallowed(monkeypatch, tmp_path):
    """prune 抛异常全吞降级 —— 构造与清扫结果不受影响。"""
    from backend.orchestration import chat_dispatcher as module

    monkeypatch.setattr(
        module,
        "get_database",
        lambda: type("DB", (), {"db_path": str(tmp_path / "sage.db")})(),
    )
    stale = tmp_path / "orch_worktrees" / "orch-prune-boom"
    stale.mkdir(parents=True)

    def boom_prune(cwd=None):
        raise RuntimeError("git gone")

    monkeypatch.setattr("backend.orchestration.worktree.prune_worktrees", boom_prune)

    dispatcher = ChatDispatcher(
        stream_id="s1",
        entry_queue=_make_queue(),
        run_id="orch-prune-boom",
        workspace_root=str(tmp_path),
    )

    assert not stale.exists()
    assert dispatcher.run_id == "orch-prune-boom"


def test_prune_worktree_helper_real_git(tmp_path):
    """prune_worktrees helper：真 git 仓库上调用 rc=0；非目录返回 False。"""
    from backend.orchestration.worktree import prune_worktrees

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    assert prune_worktrees(repo) is True
    assert prune_worktrees(tmp_path / "not-a-dir") is False
