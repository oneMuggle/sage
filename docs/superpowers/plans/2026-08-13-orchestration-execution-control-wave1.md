# Wave 1 — 编排执行控制层：P0 后端接线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让聊天编排子任务经 `LaneExecutor` 执行——获得 RecoveryPolicy 结构化重试（P0-1）、reviewer 验证环（P0-2）、scratch 目录隔离（P0-3）。

**Architecture:** ChatDispatcher 的执行职责下沉到新的 `SubagentRunner`（真实 agent runner）+ 既有 `LaneExecutor.execute_lane`（重试/backoff/事件已实现）。每个子任务建 Task+Lane 并经 lane 执行循环运行；全部完成后跑 reviewer 子 agent 复核聚合结果并落 `ReviewReport`；子 agent 以 `ToolPolicy(workspace_root=<scratch_dir>)` 构建使 write_file 锁进隔离目录。

**Tech Stack:** Python 3.11 / asyncio / FastAPI / SQLite（`backend.data.orchestration_repo`）/ pytest。

## Global Constraints

- 运行环境：`/home/fz/anaconda3/envs/sage-backend/bin/python`（conda env `sage-backend`），禁止系统 python3。
- 分支：本波在 `feat/orchestration-execution-control-wave1`（从 main 切出）上开发。
- 并发上限：`MAX_CONCURRENT_SUBAGENTS = 4`（多出排队）。
- 结果截断：`MAX_SUBAGENT_RESULT_CHARS = 50 * 1024`；聚合总上限 `MAX_AGGREGATE_CHARS = 120 * 1024`。
- 重试策略：`RecoveryPolicy(on_failure="retry", max_retries=2)`（默认）。
- scratch 根：`Path(get_database().db_path).parent / "orch_scratch"`；`orch_scratch` 加入 `.gitignore`。
- 有效 agent 角色白名单 `_VALID_AGENT_ROLES`（`backend/api/legacy_routes.py`）当前含 coordinator/researcher/coder/memory_manager/writer，本波追加 `reviewer`。
- 降级铁律：持久化/复核/scratch 任何失败**不得阻塞聊天主流程**（log + 降级）。
- **范围修正（相对 spec）**：
  1. lane 镜像在 Wave 1 事实落地——`LaneRepository`/`TaskRepository` 仅 SQLite（无内存模式），ChatDispatcher 路由 `LaneExecutor` 必然写 lane/task 表。Wave 3 的 P2-10 相应只剩 board 端点 + API `/lanes` 可执行。
  2. `task_review` NDJSON 事件**延后到 Wave 2**——新增 AgentState 变体会触发前端 `agentStateToText` 的 `assertNever` 断裂（§42 §9.3 已知限制）；Wave 1 复核结论以 markdown 追加进聚合 + `ReviewReport` 落库，纯后端成立。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/core/legacy/agent.py`（修改） | `__init__` 增 `policy` 参数透传 `register_all_tools`（scratch 边界注入点） |
| `backend/orchestration/subagent_runner.py`（新建） | `SubagentRunner`（真实 agent runner）+ `run_lane_with_retry`（重试循环 helper） |
| `backend/orchestration/chat_dispatcher.py`（修改） | `_run_subagent` 改走 lane 执行；`ChatTaskState.retry_count`；`task_status` 事件带 retry_count；scratch 目录创建；`total_tasks` 门控 + `_run_review` |
| `backend/agents/profiles.py`（修改） | `create_default_agents()` 增 reviewer profile |
| `backend/api/legacy_routes.py`（修改） | `_VALID_AGENT_ROLES` 增 `"reviewer"`；ChatDispatcher 构造传 `total_tasks` |
| `backend/tests/unit/test_agent_policy_param.py`（新建） | Task 1 测试 |
| `backend/tests/unit/test_subagent_runner.py`（新建） | Task 2 测试 |
| `backend/tests/unit/test_reviewer_role.py`（新建） | Task 4 测试 |
| `backend/tests/unit/test_chat_dispatcher.py`（重写） | Task 3/5 测试（改 mock 缝到 subagent_runner） |
| `docs/technical/42-chat-multi-agent-orchestration.md`（修改） | 记录本波接线 |
| `.gitignore`（修改） | `orch_scratch` 条目 |

---

### Task 1: SageAgent policy 参数（P0-3 注入点）

**Files:**
- Modify: `backend/core/legacy/agent.py`（import ToolPolicy + `__init__` 增 `policy` 参数 + `register_all_tools(self.tool_registry, policy=policy)`）
- Test: Create `backend/tests/unit/test_agent_policy_param.py`

**Interfaces:**
- Consumes: `ToolPolicy(workspace_root: Optional[str])`（`backend.domain.tool_policy`，已存在）。
- Produces: `SageAgent.__init__(llm_config=None, agent_id=None, bare=False, policy: Optional[ToolPolicy] = None)`——`bare=False` 时把 `policy` 透传给 `register_all_tools(registry, policy)`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_agent_policy_param.py
"""SageAgent 把 policy 透传给 register_all_tools（P0-3 scratch 注入点）。"""

from unittest.mock import patch

from backend.domain.tool_policy import ToolPolicy


def test_sageagent_forwards_policy_to_register_all_tools():
    from backend.core.legacy.agent import SageAgent

    with patch("backend.core.legacy.agent.register_all_tools") as mock_reg:
        SageAgent(bare=False, policy=ToolPolicy(workspace_root="/tmp/scratch"))

    assert mock_reg.call_count == 1
    _, kwargs = mock_reg.call_args
    assert kwargs.get("policy") is not None
    assert kwargs["policy"].workspace_root == "/tmp/scratch"
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_agent_policy_param.py -v`
Expected: FAIL——`kwargs.get("policy")` 为 None（`register_all_tools` 当前只收 registry 一个位置参数）。

- [ ] **Step 3: 最小实现**

在 `backend/core/legacy/agent.py`：

```python
# 顶部 import 区（与既有 backend.tools import 相邻）
from backend.domain.tool_policy import ToolPolicy

# __init__ 签名增参数（bare 之后）：
    def __init__(
        self,
        llm_config: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        bare: bool = False,
        policy: Optional[ToolPolicy] = None,
    ):
```

非 bare 分支（原 `register_all_tools(self.tool_registry)` 行）改为：

```python
            # 初始化工具注册表
            self.tool_registry = ToolRegistry()
            register_all_tools(self.tool_registry, policy=policy)
```

- [ ] **Step 4: 运行确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_agent_policy_param.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/core/legacy/agent.py backend/tests/unit/test_agent_policy_param.py
git commit -m "feat(orch): SageAgent 透传 ToolPolicy 到 register_all_tools（P0-3 注入点）"
```

---

### Task 2: SubagentRunner + run_lane_with_retry（P0-1 真实 runner）

**Files:**
- Create: `backend/orchestration/subagent_runner.py`
- Test: Create `backend/tests/unit/test_subagent_runner.py`

**Interfaces:**
- Consumes: `SageAgent(llm_config=..., agent_id=..., policy=...)`（Task 1）、`get_enabled_agent`/`build_system_base`（`backend.agents.profiles`）、`ToolPolicy`、`LaneExecutor.execute_lane(lane, agent_id) -> dict`。
- Produces:
  - `class SubagentRunner`：`__init__(llm_config: Optional[dict] = None)`；`async __call__(task, agent_id: Optional[str]) -> dict`。返回 `{"status": "succeeded", "output": <str>}`；失败 raise `RuntimeError`。
  - `async def run_lane_with_retry(executor: LaneExecutor, lane: Lane, agent_id: Optional[str]) -> dict`——循环再调 `execute_lane` 直到结果非 `"retrying"`（LaneExecutor 的 retry 分支只重置 lane 并返回 retrying，需调用方重入）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_subagent_runner.py
"""SubagentRunner + run_lane_with_retry 单元测试。"""

from __future__ import annotations

import pytest
from unittest.mock import patch


class _FakeSageAgent:
    """可编程子 agent：run_loop 产出 DONE；可注入失败次数。"""

    def __init__(self, fail_times: int = 0, content: str = "子任务输出"):
        self.fail_times = fail_times
        self.content = content
        self.calls = 0

    async def run_loop(self, messages, max_iterations=None, llm_config=None):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient failure")
        yield AgentEvent(state=AgentState.DONE, content=self.content)


_DUMMY_PROFILE = {"system_prompt": "你是测试子 agent", "tools": []}


def _make_task(goal: str = "调研 X", scratch: str | None = None):
    from backend.orchestration.models import Task

    params = {"goal": goal}
    if scratch:
        params["scratch_dir"] = scratch
    return Task(task_id="t1", name="T1", description=goal, parameters=params)


@pytest.mark.asyncio()
async def test_runner_returns_succeeded_dict():
    from backend.orchestration.subagent_runner import SubagentRunner

    fake = _FakeSageAgent(content="调研结果")
    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch("backend.orchestration.subagent_runner.SageAgent", return_value=fake):
        result = await SubagentRunner()(_make_task(goal="调研 X"), "researcher")

    assert result == {"status": "succeeded", "output": "调研结果"}
    assert fake.calls == 1


@pytest.mark.asyncio()
async def test_runner_invalid_agent_raises():
    from backend.orchestration.subagent_runner import SubagentRunner

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent", return_value=None
    ):
        with pytest.raises(RuntimeError, match="不存在或已禁用"):
            await SubagentRunner()(_make_task(), "ghost_agent")


@pytest.mark.asyncio()
async def test_run_lane_with_retry_loops_until_terminal():
    from backend.orchestration.models import Lane, LaneStatus
    from backend.orchestration.subagent_runner import run_lane_with_retry

    class _FakeExecutor:
        def __init__(self):
            self.calls = 0

        async def execute_lane(self, lane, agent_id=None):
            self.calls += 1
            if self.calls < 3:
                return {"status": "retrying", "retry_count": self.calls}
            return {"status": "succeeded", "lane_id": "lane-t1", "result": {"output": "ok"}}

    lane = Lane(lane_id="lane-t1", task_id="t1", status=LaneStatus.READY)
    result = await run_lane_with_retry(_FakeExecutor(), lane, "researcher")

    assert result["status"] == "succeeded"
    assert result["result"]["output"] == "ok"


@pytest.mark.asyncio()
async def test_run_lane_with_retry_returns_failed_terminal():
    from backend.orchestration.models import Lane, LaneStatus
    from backend.orchestration.subagent_runner import run_lane_with_retry

    class _FakeExecutor:
        def __init__(self):
            self.calls = 0

        async def execute_lane(self, lane, agent_id=None):
            self.calls += 1
            if self.calls < 3:
                return {"status": "retrying", "retry_count": self.calls}
            return {"status": "failed", "error": "MAX_RETRIES_EXCEEDED"}

    lane = Lane(lane_id="lane-t1", task_id="t1", status=LaneStatus.READY)
    result = await run_lane_with_retry(_FakeExecutor(), lane, "researcher")

    assert result["status"] == "failed"
    assert "MAX_RETRIES_EXCEEDED" in result["error"]


@pytest.mark.asyncio()
async def test_lane_executor_runs_real_subagent_runner():
    """LaneExecutor + SubagentRunner 集成（spec §5.4）：真实 runner 产出
    DONE content → 任务 COMPLETED、lane SUCCEEDED。"""
    from backend.orchestration.executor import LaneExecutor
    from backend.orchestration.lane_registry import LaneRegistry
    from backend.orchestration.models import (
        Lane,
        RecoveryPolicy,
        Task,
        TaskPacket,
    )
    from backend.orchestration.subagent_runner import SubagentRunner
    from backend.orchestration.task_registry import TaskRegistry

    lane_registry = LaneRegistry()
    task_registry = TaskRegistry()
    fake = _FakeSageAgent(content="调研完成")

    with patch(
        "backend.orchestration.subagent_runner.get_enabled_agent",
        return_value=_DUMMY_PROFILE,
    ), patch("backend.orchestration.subagent_runner.SageAgent", return_value=fake):
        task = task_registry.create_task(
            Task(
                task_id="task-it",
                name="集成测试",
                description="go",
                parameters={"goal": "调研 X"},
                packet=TaskPacket(
                    objective="调研 X",
                    recovery_policy=RecoveryPolicy(on_failure="retry", max_retries=2),
                ),
            )
        )
        task_registry.mark_running("task-it")
        lane = Lane(lane_id="lane-it", task_id="task-it", agent_id="researcher")
        lane_registry.create_lane(lane)

        executor = LaneExecutor(
            lane_registry=lane_registry,
            task_registry=task_registry,
            agent_runner=SubagentRunner(),
        )
        result = await executor.execute_lane(lane, "researcher")

    assert result["status"] == "succeeded"
    assert result["result"]["output"] == "调研完成"
    assert lane_registry.get_lane("lane-it").status.value == "succeeded"
    assert task_registry.get_task("task-it").status.value == "completed"
    assert fake.calls == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_subagent_runner.py -v`
Expected: FAIL——`ModuleNotFoundError: No module named 'backend.orchestration.subagent_runner'`。

- [ ] **Step 3: 实现**

```python
# backend/orchestration/subagent_runner.py
"""``SubagentRunner`` — 编排子任务的真实 agent 执行 runner（Wave 1 P0-1/P0-3）。

把子任务执行从 ChatDispatcher 内联的 ``SageAgent.run_loop`` 提升为
``LaneExecutor.agent_runner`` 契约的 callable，使 RecoveryPolicy 重试/backoff
在 lane 执行循环中生效。子 agent 以 ``ToolPolicy(workspace_root=scratch_dir)``
构造（P0-3 隔离）：write_file 被 ``file_tool._path_within_workspace`` 边界检查
锁进 scratch 目录，越界写返回 ``path_outside_workspace`` 拒绝。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.agents.profiles import build_system_base, get_enabled_agent
from backend.core.legacy.agent import SageAgent
from backend.domain.tool_policy import ToolPolicy
from backend.orchestration.executor import LaneExecutor
from backend.orchestration.models import Lane

logger = logging.getLogger(__name__)


class SubagentRunner:
    """经 ``LaneExecutor.agent_runner`` 契约执行单个编排子任务。"""

    def __init__(self, llm_config: Optional[Dict[str, Any]] = None) -> None:
        self._llm_config = llm_config

    async def __call__(self, task: Any, agent_id: Optional[str]) -> Dict[str, Any]:
        """Run one subtask via SageAgent.run_loop; return executor-usable dict.

        Args:
            task: orchestration Task（``parameters["goal"]`` 为目标，
                ``parameters["scratch_dir"]`` 为隔离目录）。
            agent_id: 执行 agent 角色。

        Returns:
            ``{"status": "succeeded", "output": <DONE content>}``

        Raises:
            RuntimeError: agent 不存在/已禁用，或子 agent 未产出 DONE content。
        """
        if not agent_id:
            raise RuntimeError("subagent runner 缺少 agent_id")
        if get_enabled_agent(agent_id) is None:
            raise RuntimeError(f"agent {agent_id!r} 不存在或已禁用，无法派发")

        goal = task.parameters.get("goal", "")
        scratch_dir = task.parameters.get("scratch_dir")
        policy = ToolPolicy(workspace_root=scratch_dir) if scratch_dir else None

        child_system = build_system_base()
        profile = get_enabled_agent(agent_id)
        if profile and profile.get("system_prompt"):
            child_system += "\n\n" + profile["system_prompt"]

        child = SageAgent(agent_id=agent_id, policy=policy)
        messages = [
            {"role": "system", "content": child_system},
            {"role": "user", "content": goal},
        ]
        collected: list[str] = []
        async for evt in child.run_loop(messages, llm_config=self._llm_config):
            if evt.state.value == "done" and evt.content:
                collected.append(evt.content)
        if not collected:
            raise RuntimeError("子 agent 未产出 DONE content")
        return {"status": "succeeded", "output": "\n\n".join(collected)}


async def run_lane_with_retry(
    executor: LaneExecutor,
    lane: Lane,
    agent_id: Optional[str],
) -> Dict[str, Any]:
    """执行 lane 并在 executor 返回 ``retrying`` 时循环再调（retry 语义）。

    ``LaneExecutor._handle_failure`` 的 retry 分支把 lane 重置为 READY 并返回
    ``{"status": "retrying"}``——重试由调用方**再调 execute_lane 触发**（lane
    调度器模型，非循环内自动重跑）。本 helper 封装该循环；retry_count 累积在
    lane.metadata，max_retries 耗尽后 executor 返回 failed 终态。
    """
    result = await executor.execute_lane(lane, agent_id)
    while result.get("status") == "retrying":
        result = await executor.execute_lane(lane, agent_id)
    return result
```

- [ ] **Step 4: 运行确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_subagent_runner.py -v`
Expected: 5 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/orchestration/subagent_runner.py backend/tests/unit/test_subagent_runner.py
git commit -m "feat(orch): SubagentRunner 真实 runner + run_lane_with_retry 重试循环（P0-1）"
```

---

### Task 3: ChatDispatcher 改走 LaneExecutor（lane 镜像 + 重试 + scratch + retry_count）

**Files:**
- Modify: `backend/orchestration/chat_dispatcher.py`
- Test: Rewrite `backend/tests/unit/test_chat_dispatcher.py`

**Interfaces:**
- Consumes: Task 2 的 `SubagentRunner`/`run_lane_with_retry`；`TaskRegistry`/`LaneRegistry`（`create_task`/`mark_running`/`create_lane` 接受预构建 Lane）；`EventRecorder`；`Task`/`TaskPacket`/`RecoveryPolicy`/`Lane`；`get_database().db_path`。
- Produces（后续 Task 5 依赖）:
  - `ChatDispatcher.__init__(stream_id, entry_queue, run_id, llm_config=None, lane_registry=None, task_registry=None, event_recorder=None, total_tasks=None)`
  - `ChatTaskState` 增 `retry_count: int = 0`
  - `task_status` 事件增 `retry_count` 字段
  - `async def _run_subagent(state: ChatTaskState) -> str`——走 lane 执行，返回输出字符串或 raise
  - `def _scratch_dir_for(state: ChatTaskState) -> Path`——`<data_dir>/orch_scratch/<run_id>/<task_id>`

- [ ] **Step 1: 重写测试（新缝：patch subagent_runner.SageAgent + get_enabled_agent）**

```python
# backend/tests/unit/test_chat_dispatcher.py（整体重写）
"""ChatDispatcher 单元测试 —— 经 LaneExecutor 执行（P0-1 lane 镜像 + 重试）。

- 并发执行 + task_status 事件顺序 queued→running→done
- 单任务重试耗尽 → failed 错误隔离，其余继续
- 并发上限 4 生效（5 个任务最大并行 ≤4）
- lane 镜像：每子任务在 lane_registry 产生 SUCCEEDED lane
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

_DUMMY_PROFILE = {"system_prompt": "你是测试子 agent", "tools": []}


class _FakeSageAgent:
    """可编程子 agent：记录并发数 + 可注入失败次数。"""

    def __init__(self, results=("ok",), delay: float = 0.0, fail_times: int = 0):
        self.results = list(results)
        self.delay = delay
        self.fail_times = fail_times
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def run_loop(self, messages, max_iterations=None, llm_config=None):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        self.calls += 1
        if self.calls <= self.fail_times:
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


def _make_queue():
    return asyncio.Queue()


def _collect_events(queue: asyncio.Queue, n: int) -> list[dict]:
    return [queue.get_nowait() for _ in range(n)]


def _patch_subagents(fake):
    return (
        patch(
            "backend.orchestration.subagent_runner.get_enabled_agent",
            return_value=_DUMMY_PROFILE,
        ),
        patch("backend.orchestration.subagent_runner.SageAgent", return_value=fake),
    )


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
    fake = _FakeSageAgent(results=["正常结果", "失败结果"], fail_times=999)

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
    assert fake.calls >= 3  # t2: 首次 + retry_count=1 + retry_count=2


@pytest.mark.asyncio()
async def test_dispatch_concurrency_capped_at_four():
    """5 个任务，并发上限 4 —— 最大同时 active ≤ 4。"""
    queue = _make_queue()
    fake = _FakeSageAgent(results=["ok"] * 5, delay=0.01)

    with _patch_subagents(fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": f"任务{i}"} for i in range(5)]
        )

    assert fake.max_active <= MAX_CONCURRENT_SUBAGENTS


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
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher.py -v`
Expected: FAIL——事件无 `retry_count` 字段、无 `lane-t1`、`_run_subagent` 旧内联实现不建 lane。

- [ ] **Step 3: 实现（chat_dispatcher.py）**

import 区新增：

```python
from pathlib import Path

from backend.data.database import get_database
from backend.orchestration.events import EventRecorder
from backend.orchestration.executor import LaneExecutor
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.models import Lane, RecoveryPolicy, Task, TaskPacket
from backend.orchestration.subagent_runner import SubagentRunner, run_lane_with_retry
from backend.orchestration.task_registry import TaskRegistry
```

（删除原有 `from backend.agents.profiles import build_system_base, get_enabled_agent` 与 `from backend.core.legacy.agent import SageAgent`——这些职责移入 SubagentRunner。若模块顶部仍有别处使用再保留。）

`ChatTaskState` 增字段：

```python
    output: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    retry_count: int = 0
```

模块级常量增：

```python
#: scratch 根目录名（data_dir 下）。
SCRATCH_ROOT = "orch_scratch"
```

`__init__` 增参数与注册表：

```python
    def __init__(
        self,
        stream_id: str,
        entry_queue: asyncio.Queue[Dict[str, Any]],
        run_id: str,
        llm_config: Optional[Dict[str, Any]] = None,
        lane_registry: Optional[Any] = None,
        task_registry: Optional[Any] = None,
        event_recorder: Optional[EventRecorder] = None,
        total_tasks: Optional[int] = None,
    ) -> None:
        self.stream_id = stream_id
        self.entry_queue = entry_queue
        self.run_id = run_id
        self.llm_config = llm_config
        # P0-1：子任务经 LaneExecutor 执行（lane 镜像 + RecoveryPolicy 重试）。
        self.lane_registry = lane_registry or LaneRegistry()
        self.task_registry = task_registry or TaskRegistry()
        self.event_recorder = event_recorder or EventRecorder()
        # P0-2：总任务数门控 —— 达到 plan 总量后跑 reviewer 验证环（Task 5）。
        self.total_tasks = total_tasks
        self._states: Dict[str, ChatTaskState] = {}
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_SUBAGENTS)
        self._next_task_index = 0
```

`_emit_task_status` 事件 dict 增：

```python
            "error": state.error,
            "retry_count": state.retry_count,
            "output_preview": self._preview(state),
```

`_run_subagent` 重写为 lane 执行（替换原 inline SageAgent 逻辑）：

```python
    async def _run_subagent(self, state: ChatTaskState) -> str:
        """经 LaneExecutor 执行子任务（P0-1）：创建 lane+task，复用重试策略。

        子 agent 以 ToolPolicy(workspace_root=<scratch_dir>) 构建（P0-3）——
        write_file 等文件工具被锁进隔离目录，越界写返回 path_outside_workspace。
        """
        task_id = f"task-{state.task_id}"
        lane_id = f"lane-{state.task_id}"
        scratch_dir = self._scratch_dir_for(state)
        scratch_dir.mkdir(parents=True, exist_ok=True)

        task = Task(
            task_id=task_id,
            name=f"Subtask {state.task_id}",
            description=state.goal,
            parameters={
                "goal": state.goal,
                "agent_id": state.agent_id,
                "scratch_dir": str(scratch_dir),
            },
            packet=TaskPacket(
                objective=state.goal,
                recovery_policy=RecoveryPolicy(on_failure="retry", max_retries=2),
            ),
        )
        self.task_registry.create_task(task)
        self.task_registry.mark_running(task_id)

        lane = Lane(
            lane_id=lane_id,
            task_id=task_id,
            agent_id=state.agent_id,
            metadata={"task_id": state.task_id},
        )
        self.lane_registry.create_lane(lane)

        executor = LaneExecutor(
            lane_registry=self.lane_registry,
            task_registry=self.task_registry,
            event_recorder=self.event_recorder,
            agent_runner=SubagentRunner(self.llm_config),
        )
        result = await run_lane_with_retry(executor, lane, state.agent_id)

        # 重试信息回填 state → task_status 事件携带
        state.retry_count = lane.metadata.get("retry_count", 0) if lane.metadata else 0
        if result.get("status") == "failed":
            raise RuntimeError(result.get("error", "subtask failed"))
        if result.get("status") != "succeeded":
            raise RuntimeError(f"subtask unexpected status: {result.get('status')}")
        return result["result"]["output"]

    def _scratch_dir_for(self, state: ChatTaskState) -> Path:
        """子任务隔离目录：``<data_dir>/orch_scratch/<run_id>/<task_id>``。"""
        data_dir = Path(get_database().db_path).parent
        return data_dir / SCRATCH_ROOT / self.run_id / state.task_id
```

- [ ] **Step 4: 运行确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher.py -v`
Expected: 4 PASS。

- [ ] **Step 5: 回归既有编排测试**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_subagent_tool.py backend/tests/unit/test_classify_orchestration_mode.py -v`
Expected: PASS（未受影响，快速确认无 import 侧漏）。

- [ ] **Step 6: Commit**

```bash
git add backend/orchestration/chat_dispatcher.py backend/tests/unit/test_chat_dispatcher.py
git commit -m "feat(orch): ChatDispatcher 子任务经 LaneExecutor 执行 + lane 镜像 + scratch + retry_count（P0-1/P0-3）"
```

---

### Task 4: reviewer 角色 + profile（P0-2 前置）

**Files:**
- Modify: `backend/agents/profiles.py`（`create_default_agents()` 增 reviewer）
- Modify: `backend/api/legacy_routes.py`（`_VALID_AGENT_ROLES` 增 `"reviewer"`）
- Test: Create `backend/tests/unit/test_reviewer_role.py`

**Interfaces:**
- Consumes: `AgentProfile` dataclass（`id`/`name`/`role`/`system_prompt`/`tools`）；`create_default_agents()` 既有 writer 模式。
- Produces: `get_enabled_agent("reviewer")` 返回 profile（DB 种子后）；`_VALID_AGENT_ROLES` 含 `"reviewer"`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_reviewer_role.py
"""reviewer 角色 + profile（P0-2）。"""

from backend.agents.profiles import create_default_agents


def test_create_default_agents_includes_reviewer():
    profiles = create_default_agents()
    ids = {p.id for p in profiles}
    assert "reviewer" in ids


def test_reviewer_profile_is_structured_for_assertions():
    reviewer = next(p for p in create_default_agents() if p.id == "reviewer")
    assert "FACT" in reviewer.system_prompt
    assert "HYPOTHESIS" in reviewer.system_prompt
    assert "NEGATIVE_EVIDENCE" in reviewer.system_prompt
    assert "confidence" in reviewer.system_prompt


def test_valid_agent_roles_include_reviewer():
    from backend.api.legacy_routes import _VALID_AGENT_ROLES

    assert "reviewer" in _VALID_AGENT_ROLES
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_reviewer_role.py -v`
Expected: FAIL——`"reviewer"` 不在默认 profiles、`_VALID_AGENT_ROLES` 无 reviewer。

- [ ] **Step 3: 实现**

`backend/agents/profiles.py` 的 `create_default_agents()` 末尾（writer profile 之后）追加：

```python
        AgentProfile(
            id="reviewer",
            name="Reviewer",
            role="reviewer",
            system_prompt=(
                "你是一个严格的复核 Agent。对照子任务的 goal 与产出，逐条给出 "
                "assertion，格式：\n"
                "[FACT|HYPOTHESIS|NEGATIVE_EVIDENCE] <断言> (confidence: 0-1)\n"
                "- FACT：产出中已证实的事实断言；\n"
                "- HYPOTHESIS：产出中提出但未经证实的假设；\n"
                "- NEGATIVE_EVIDENCE：与目标相矛盾或缺失关键证据的断言。\n"
                "只输出 assertions 列表，不要多余说明。"
            ),
            tools=[],
        ),
```

`backend/api/legacy_routes.py` 的 `_VALID_AGENT_ROLES` 追加 `"reviewer"`。

- [ ] **Step 4: 运行确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_reviewer_role.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/agents/profiles.py backend/api/legacy_routes.py backend/tests/unit/test_reviewer_role.py
git commit -m "feat(orch): reviewer 角色 + profile（P0-2 验证环前置）"
```

---

### Task 5: 验证环 —— dispatch 聚合后跑 reviewer（P0-2）

**Files:**
- Modify: `backend/orchestration/chat_dispatcher.py`
- Test: Modify `backend/tests/unit/test_chat_dispatcher.py`

**Interfaces:**
- Consumes: Task 3 的 `total_tasks` 参数、`_run_subagent` lane 路径；`LaneExecutor.submit_with_report(lane_id, task_id, assertions, reviewer_id)`（已实现）。
- Produces:
  - `async def _run_review(aggregated: str) -> dict`——跑 reviewer 子 agent → 解析 assertions → `submit_with_report` → 返回 `{"verdict": str, "block": str}`
  - `def _parse_assertions(raw: str) -> list[dict]`
  - `def _review_block(verdict: str, count: int) -> str`
  - `dispatch()` 在 `self.total_tasks and self._next_task_index >= self.total_tasks` 且本轮 gather 完成后追加 review block；reviewer 失败 → log + 跳过。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/unit/test_chat_dispatcher.py

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

    class _BrokenReview(_FakeSageAgent):
        async def run_loop(self, messages, max_iterations=None, llm_config=None):
            raise RuntimeError("reviewer boom")

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
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-plain")
        aggregated = await dispatcher.dispatch(
            [{"agent_id": "researcher", "goal": "调研量化交易"}]
        )

    assert "## 复核结果" not in aggregated
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher.py -v`
Expected: 新增 4 测 FAIL——`total_tasks` 参数不存在 / `_run_review` 未实现 / 无 `lane-review-*`。

- [ ] **Step 3: 实现**

`chat_dispatcher.py` 增方法（`_aggregate` 定义之后）：

```python
    def _parse_assertions(self, raw: str) -> list[dict]:
        """解析 reviewer 输出的 assertion 行 → [{kind, text, confidence}]。

        容忍非严格格式：行前缀 [FACT|HYPOTHESIS|NEGATIVE_EVIDENCE]，可选
        "(confidence: 0-1)" 后缀；无法解析的行跳过。
        """
        import re

        pattern = re.compile(
            r"^\[(FACT|HYPOTHESIS|NEGATIVE_EVIDENCE)\]\s*(.+?)"
            r"(?:\s*\(confidence:\s*([0-9.]+)\))?\s*$"
        )
        assertions: list[dict] = []
        for line in raw.splitlines():
            m = pattern.match(line.strip())
            if not m:
                continue
            try:
                confidence = float(m.group(3)) if m.group(3) else 0.0
            except ValueError:
                confidence = 0.0
            assertions.append(
                {"kind": m.group(1), "text": m.group(2), "confidence": confidence}
            )
        return assertions

    def _review_block(self, verdict: str, count: int) -> str:
        """复核结论 markdown（追加进聚合进 conductor 上下文）。"""
        if verdict == "fail":
            instruction = "存在关键 NEGATIVE_EVIDENCE，请修复后再给出最终汇总。"
        else:
            instruction = "全部断言通过，可给出最终汇总。"
        return (
            "\n\n## 复核结果（reviewer）\n\n"
            f"- verdict: {verdict}（{count} 条 assertion）\n"
            f"- {instruction}"
        )

    async def _run_review(self, aggregated: str) -> dict:
        """P0-2 验证环：reviewer 子 agent 复核聚合 → ReviewReport + markdown 块。

        reviewer 失败（raise）由 dispatch 捕获 → 跳过验证（降级不阻塞）。
        """
        review_goal = (
            "复核以下多 agent 子任务聚合结果，逐条给出 assertion。\n"
            + aggregated[:MAX_SUBAGENT_RESULT_CHARS]
        )
        lane_id = f"lane-review-{self.run_id}"
        task_id = f"task-review-{self.run_id}"

        task = Task(
            task_id=task_id,
            name=f"Review {self.run_id}",
            description=review_goal,
            parameters={"goal": review_goal},
        )
        self.task_registry.create_task(task)
        # 置 RUNNING：executor 成功路径 mark_completed / 失败路径 mark_failed
        # 都要求 RUNNING 态（否则 review task 停在 CREATED，状态机不一致）。
        self.task_registry.mark_running(task_id)
        lane = Lane(lane_id=lane_id, task_id=task_id, agent_id="reviewer", metadata={})
        self.lane_registry.create_lane(lane)

        executor = LaneExecutor(
            lane_registry=self.lane_registry,
            task_registry=self.task_registry,
            event_recorder=self.event_recorder,
            agent_runner=SubagentRunner(self.llm_config),
        )
        result = await run_lane_with_retry(executor, lane, "reviewer")
        if result.get("status") != "succeeded":
            raise RuntimeError(result.get("error", "reviewer 未产出内容"))
        raw = result["result"]["output"]

        assertions = self._parse_assertions(raw)
        executor.submit_with_report(lane_id, task_id, assertions, reviewer_id="reviewer")
        verdict = (
            "fail"
            if any(
                a["kind"] == "NEGATIVE_EVIDENCE" and a["confidence"] >= 0.7
                for a in assertions
            )
            else "pass"
        )
        block = self._review_block(verdict, len(assertions))
        logger.info("编排复核完成: verdict=%s, assertions=%d", verdict, len(assertions))
        return {"verdict": verdict, "block": block}
```

`dispatch()` 末尾（`return self._aggregate(states)` 之前）改：

```python
        aggregated = self._aggregate(states)
        # P0-2 验证环：仅当本次调用已覆盖 plan 全部任务后跑 reviewer；
        # 失败降级跳过（绝不阻塞聊天）。
        if self.total_tasks and self._next_task_index >= self.total_tasks:
            try:
                review = await self._run_review(aggregated)
                aggregated = aggregated + review["block"]
            except Exception as exc:  # noqa: BLE001 — 复核失败降级
                logger.warning("编排复核失败，跳过验证: %s", exc)
        return aggregated
```

- [ ] **Step 4: 运行确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher.py -v`
Expected: 8 PASS（4 旧 + 4 新）。

- [ ] **Step 5: 接线 legacy_routes —— 构造 ChatDispatcher 时传 total_tasks**

`backend/api/legacy_routes.py` 编排分支中构造 `ChatDispatcher(...)` 处增传 `total_tasks=len(plan_tasks)`：

```python
            dispatcher = ChatDispatcher(
                stream_id=stream_id,
                entry_queue=entry_queue,
                run_id=run_id,
                llm_config=llm_config,
                total_tasks=len(plan_tasks),
            )
```

- [ ] **Step 6: 运行集成测试确认无回归**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_orchestration_stream.py -v`
Expected: PASS（该集成测试 mock 的 conductor 不触发 dispatch，故本波不改其断言；multi 路径仍出 task_plan + 注册工具）。

- [ ] **Step 7: Commit**

```bash
git add backend/orchestration/chat_dispatcher.py backend/tests/unit/test_chat_dispatcher.py backend/api/legacy_routes.py
git commit -m "feat(orch): dispatch 聚合后 reviewer 验证环 + ReviewReport（P0-2）"
```

---

### Task 6: 文档 + gitignore + 全量回归

**Files:**
- Modify: `docs/technical/42-chat-multi-agent-orchestration.md`
- Modify: `backend/orchestration/chat_dispatcher.py`（模块 docstring）
- Modify: `.gitignore`
- Test: 全量 backend pytest

- [ ] **Step 1: .gitignore 增 scratch**

追加到根 `.gitignore`：

```gitignore
# 编排子任务隔离目录（运行时产物）
data/orch_scratch/
```

- [ ] **Step 2: 更新 42 章节**

`docs/technical/42-chat-multi-agent-orchestration.md` 增 §11「执行控制层（Wave 1 P0，2026-08-13）」并归档 plans 文件说明。§11 记录：
- 子任务经 `LaneExecutor` 执行（`SubagentRunner` 真实 runner + `run_lane_with_retry` 重试循环）；
- `task_status` 事件增 `retry_count` 字段（前端松散字段，兼容）；
- lane 镜像事实落地（Wave 1 即写 lane/task 表，P2-10 收窄为 board 端点 + API `/lanes` 可执行）；
- scratch 隔离 `data/orch_scratch/<run_id>/<task_id>/`（ToolPolicy.workspace_root 作用域）；
- reviewer 角色 + 聚合后验证环（ReviewReport 落库 + markdown 进 conductor 上下文）；`task_review` NDJSON 事件延后 Wave 2（前端 assertNever 限制）；
- `ChatDispatcher` 模块 docstring 同步更新（不再"不建 lane/不写 lane 表"）。

- [ ] **Step 3: 全量回归**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests -q`
Expected: 全绿（既有用例无回归；本波新增 ~20 用例）。

- [ ] **Step 4: Commit**

```bash
git add docs/technical/42-chat-multi-agent-orchestration.md backend/orchestration/chat_dispatcher.py .gitignore
git commit -m "docs(orch): 42 章节记录执行控制层 P0 接线"
```

---

## 执行收尾（本波）

1. 本地全量 `pytest backend/tests -q` 绿；
2. 推分支 `git push -u origin feat/orchestration-execution-control-wave1`；
3. `gh pr create --title "feat(orch): 编排执行控制 Wave 1 — retry/reviewer/scratch" --body "<计划 + 测试摘要>"`；
4. CI 绿后 AI 检阅 + 用户 merge；
5. 合并后生成 Wave 2 计划（P1 计划生命周期，spec §6）。

## 自审记录

- **Spec 覆盖**：P0-1（Task 2+3+5 接线）、P0-2（Task 4+5）、P0-3（Task 1+3）全覆盖；spec §5.4 四项测试清单（重试单测 / LaneExecutor+subagent_runner 集成 / reviewer 复核 / scratch）逐一映射到 Task 3 / Task 2 `test_lane_executor_runs_real_subagent_runner` / Task 5 / Task 1+3；spec §8 降级链（reviewer 失败跳过、retry 耗尽进聚合）在测试断言。
- **范围修正已在 Global Constraints 声明**：lane 镜像提前（repo 无内存模式）；`task_review` 事件延后（前端 assertNever 断裂）。
- **类型一致性（实测核对）**：
  - `LaneExecutor.__init__(lane_registry, task_registry, event_recorder=None, agent_runner=None)`；成功返回 `{"status":"succeeded","lane_id",...,"result": <runner 返回>}` → SubagentRunner 返回 `{"status","output"}` 落 `result` 键，ChatDispatcher 读 `result["result"]["output"]` 一致。
  - `TaskRegistry.create_task(Task)` 接受预构建 Task；`mark_running(task_id)` 存在；review/子任务任务都先 `mark_running`（`mark_completed`/`mark_failed` 均要求 RUNNING 态）。
  - `_get_recovery_policy` 对 `task.packet is None` 返回 `{on_failure:"fail", max_retries:0}` → review 任务无 packet 安全（失败 fail-fast 不重试）。
  - `_validate_permissions` 走默认 `implement` preset → 所有角色（含 reviewer）通过。
  - `LaneEventRepository` 仅 SQLite（无内存模式）→ Task 5 断言 review lane SUCCEEDED 而非事件内部；REVIEW_SUBMITTED 事件本体由既有 executor 测试覆盖。
  - `LaneStatus.CREATED/READY/RUNNING/SUCCEEDED`、`TaskStatus.COMPLETED` 枚举成员确认存在。
  - scratch 边界拒绝（`path_outside_workspace`）已有工具级测试（`test_file_tool_hardening.py:146`、`test_edit_tool.py:217`）→ 本波只测 ToolPolicy 透传（Task 1）+ scratch 目录创建（Task 3），不重复测 file_tool。
