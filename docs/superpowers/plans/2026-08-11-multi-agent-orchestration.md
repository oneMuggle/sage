# Chat-Native Multi-Agent Orchestration 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Sage 聊天链路接通真正的多 agent 协作 —— 用户在 `/chat/stream` 发复杂任务时，语义判定进编排 → planner 拆解 → conductor 经 `dispatch_subagents` 工具并行派发子 agent → 聊天右侧任务树 + Artifacts 展示；简单任务保持单 agent 零改动。

**Architecture:** 方案 C 混合（复用现有编排资产，不建 lane）：`Planner.decompose_request` 复用做预规划 → producer 把 plan 注入 conductor（`SageAgent("primary")` + `dispatch_subagents` 工具）→ conductor 依据中间结果再决策 → ChatDispatcher 并行跑子 `SageAgent.run_loop` → 结果聚合回传 conductor。mode 判定用独立轻量 LLM 二分类（tool-toggle 门），复杂任务结构上必有 plan + 工具，简单任务结构上无 dispatch 工具。

**Tech Stack:** Python 3.11 + FastAPI + asyncio（后端）；React + TypeScript + vitest（前端）；Electron IPC bridge。

## Global Constraints

- **测试环境**：后端一律用 `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest`，前端用 `npx vitest`。禁止污染 conda base。
- **分支**：本功能全程在 `feat/multi-agent-orchestration` 分支开发，走 PR 流程，不直推 main。
- **复用约束**：`backend/orchestration/` 的 lane 编排层（LaneExecutor/Router/Registries/看板）、`/orchestration` API、LaneBoard 页面**一律不动**。只复用 `Planner.decompose_request` / `SageAgent.run_loop` / `ToolExecutionContext` / `AgentProfile`。
- **tool-toggle 门（双失败模式硬约束）**：
  - mode=`single` → 不注册 `dispatch_subagents` 工具、不跑 `decompose_request`（简单任务结构上无法被拆解）。
  - mode=`multi` → `task_plan` 事件必出 + `dispatch_subagents` 工具必注册（复杂任务结构上必进编排）。
- **事件协议**：新增 NDJSON state `task_plan`（run_id + plan[]）与 `task_status`（run_id, task_id, status `queued|running|done|failed`, agent_id, goal, error, output_preview）。不改 `AgentEvent` 既有 state 语义，这两个事件由 producer/dispatcher 直接 `entry.queue.put(dict)`。
- **task_id 契约**：producer 把 `plan.tasks` 映射为 `t{index+1}`；`ChatDispatcher.dispatch` 按传入顺序编号 `t{index+1}`。前端按 `task_id` 合并，status 的 goal/agent 覆盖 plan，plan 无 status 的行显示 queued。
- **dispatch schema 钳制**：`tasks` `minItems=1, maxItems=4`；`goal` `maxLength=2000`；并发上限 `MAX_CONCURRENT_SUBAGENTS=4`（asyncio.Semaphore）。
- **截断**：单子结果截断 `MAX_SUBAGENT_RESULT_CHARS=50*1024` 进 conductor；`output_preview` ≤ `MAX_OUTPUT_PREVIEW_CHARS=500` 字。
- **run_loop 工具执行**：`dispatch_subagents` 走新增 `elif tc.name == "dispatch_subagents": result = await tool.execute_async(**args)` special-case（对齐现有 `agent` tool 先例；同步 `execute` 无法并发跑子 agent）。
- **ContextVar 继承**：`asyncio.gather` 子 Task 自动继承父 Task 的 `ToolExecutionContext` → 子 agent 的 file 工具（writer 的 `write_file`）自动落 artifacts 到同一 session，零改动。子 agent 构造须用非 bare `SageAgent(agent_id=...)`（bare=True 会留空 tool_registry）。
- **writer 工具名**：profile `tools` 用 registry 实际注册名 `read_file`/`write_file`（不是 coder 种子遗留的过时 `file_read`/`file_write`）。
- **权限**：`dispatch_subagents` 未登记 → `classify_tool` 回退 WRITE；默认 `workspace_write` 模式放行 WRITE → 默认不触发审批。read_only/prompt 模式会 deny/ask（记录为已知风险，错误处理表已含）。
- **测试验收口径**：简单任务复杂化 = 0 由"single 无 dispatch 工具 + 无编排事件"测试兜底；复杂任务简单化 = 0 由"multi 必出 task_plan + 必注册工具"测试兜底。两者都必须编码进测试。

---

### Task 1: ChatDispatcher —— 轻量子 agent 调度器

**Files:**
- Create: `backend/orchestration/chat_dispatcher.py`
- Test: `backend/tests/unit/test_chat_dispatcher.py`

**Interfaces:**
- Consumes: `SageAgent.run_loop`（async generator，yield AgentEvent，`evt.state.value == "done"` 时 `evt.content` 为最终回复）、`LLMConfig` / `LLMClient`（`run_loop(messages, llm_config=dict)` 动态配置）、`AgentProfile`（`get_enabled_agent(agent_id)` 返回 dict，`system_prompt` 字段）
- Produces:
  - `class ChatDispatcher(stream_id: str, entry_queue: "asyncio.Queue[Dict]", run_id: str, llm_config: Optional[Dict] = None)`
  - `async def ChatDispatcher.dispatch(self, tasks: List[Dict[str, str]]) -> str` —— 并行执行子任务，返回聚合 markdown
  - `@dataclass ChatTaskState`（task_id, agent_id, goal, status, output, error, started_at, finished_at）
  - 模块常量 `MAX_CONCURRENT_SUBAGENTS = 4`、`MAX_SUBAGENT_RESULT_CHARS = 50 * 1024`、`MAX_OUTPUT_PREVIEW_CHARS = 500`

- [ ] **Step 1: 写失败测试**

`backend/tests/unit/test_chat_dispatcher.py`：

```python
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

        return AgentEvent(state=AgentState(state), content=content)


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
        await dispatcher.dispatch([{"agent_id": "r", "goal": f"g{i}"} for i in range(5)])

    assert fake.max_active == MAX_CONCURRENT_SUBAGENTS


@pytest.mark.asyncio()
async def test_dispatch_truncates_results_to_50kb():
    """单子结果超长 → 聚合截断到 MAX_SUBAGENT_RESULT_CHARS。"""
    queue = _make_queue()
    big = "x" * (MAX_SUBAGENT_RESULT_CHARS + 10_000)
    fake = _FakeSageAgent(results=[big])

    with patch("backend.orchestration.chat_dispatcher.SageAgent", return_value=fake):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        aggregated = await dispatcher.dispatch([{"agent_id": "r", "goal": "g"}])

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
        aggregated = await dispatcher.dispatch([{"agent_id": "r", "goal": "g"}])

    events = _collect_events(queue, 2)
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
            [{"agent_id": "r", "goal": f"g{i}"} for i in range(3)]
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

    with patch(
        "backend.agents.profiles.get_enabled_agent", return_value=None
    ), patch(
        "backend.orchestration.chat_dispatcher.SageAgent",
        return_value=_ShouldNotRun(),
    ):
        dispatcher = ChatDispatcher(stream_id="s1", entry_queue=queue, run_id="orch-test")
        aggregated = await dispatcher.dispatch(
            [{"agent_id": "ghost_agent", "goal": "g"}]
        )

    events = _collect_events(queue, 2)
    assert events[0]["status"] == "queued"
    assert events[-1]["status"] == "failed"
    assert "ghost_agent" in aggregated
    # 修复前：child 被构造、run_loop 抛 AssertionError → 错误信息不符 → 本断言 RED
    assert "不存在或已禁用" in aggregated
```

- [ ] **Step 2: 跑测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher.py -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.orchestration.chat_dispatcher'`

- [ ] **Step 3: 写最小实现**

`backend/orchestration/chat_dispatcher.py`：

```python
"""ChatDispatcher — 轻量子 agent 执行器（Multi-Agent Orchestration 方案 C）。

conductor（主 LLM）经 ``dispatch_subagents`` 工具调用本 dispatcher，把
``[{agent_id, goal}]`` 并行派发给子 ``SageAgent``。纯内存，单次聊天 run
生命周期内存在，不持久化 —— 与 ``backend/orchestration/`` 的 lane 编排层
互不干扰（不建 lane、不写 lane 表）。

子 agent 用 ``SageAgent(agent_id=...)`` 非 bare 构造：bare=True 会留空
tool_registry（子 agent 需要 profile 白名单工具，如 researcher 的
web_search / writer 的 write_file）。

本模块还导出 ``_classify_orchestration_mode``（tool-toggle 门的语义判定，
Task 3 实现），供 ``/chat/stream`` producer 复用 —— 放在这里便于单元测试，
与 producer 解耦。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 并发上限 —— 子 agent 同时执行数（多出的排队等待）。
MAX_CONCURRENT_SUBAGENTS = 4

#: 单子结果截断上限 —— 聚合 markdown 进 conductor 上下文，防止灌爆。
MAX_SUBAGENT_RESULT_CHARS = 50 * 1024

#: task_status.output_preview 上限（UI 展开预览）。
MAX_OUTPUT_PREVIEW_CHARS = 500


@dataclass
class ChatTaskState:
    """单个子任务的可变状态（dispatcher 内存态，不落库）。"""

    task_id: str
    agent_id: str
    goal: str
    status: str = "queued"  # queued|running|done|failed
    output: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


class ChatDispatcher:
    """并行执行子任务并向聊天流推送 task_status 事件的轻量调度器。"""

    def __init__(
        self,
        stream_id: str,
        entry_queue: "asyncio.Queue[Dict[str, Any]]",
        run_id: str,
        llm_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.stream_id = stream_id
        self.entry_queue = entry_queue
        self.run_id = run_id
        self.llm_config = llm_config
        self._states: Dict[str, ChatTaskState] = {}
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_SUBAGENTS)

    async def dispatch(self, tasks: List[Dict[str, str]]) -> str:
        """并行执行子任务，返回聚合 markdown（截断后进 conductor 上下文）。

        Args:
            tasks: ``[{"agent_id": ..., "goal": ...}]``。按传入顺序编号
                ``t{index+1}``（与 producer 的 task_plan 契约一致）。

        Returns:
            聚合 markdown：每个子结果截断 MAX_SUBAGENT_RESULT_CHARS 后拼接；
            单任务失败以错误摘要参与聚合，其余任务继续（错误隔离）。
        """
        states: List[ChatTaskState] = []
        for index, raw in enumerate(tasks):
            state = ChatTaskState(
                task_id=f"t{index + 1}",
                agent_id=raw.get("agent_id", "primary"),
                goal=raw.get("goal", ""),
            )
            self._states[state.task_id] = state
            states.append(state)
            self._emit_task_status(state)  # queued

        async def _run_one(state: ChatTaskState) -> None:
            async with self._semaphore:
                state.status = "running"
                state.started_at = time.time()
                self._emit_task_status(state)
                try:
                    content = await self._run_subagent(state)
                    state.status = "done"
                    state.output = content
                except Exception as exc:  # noqa: BLE001 — 单任务失败隔离
                    state.status = "failed"
                    state.error = str(exc)
                    logger.warning("subagent %s failed: %s", state.task_id, exc)
                finally:
                    state.finished_at = time.time()
                    self._emit_task_status(state)

        await asyncio.gather(*(_run_one(s) for s in states))
        return self._aggregate(states)

    async def _run_subagent(self, state: ChatTaskState) -> str:
        """跑单个子 SageAgent.run_loop，收集 DONE content。"""
        from backend.agents.profiles import build_system_base, get_enabled_agent
        from backend.core.legacy.agent import SageAgent

        # spec §5.1: agent_id 不合法（不存在/禁用）→ 快速失败，错误进聚合
        # （conductor 可改派/重试），而不是拿 base prompt 跑一个无身份的 child。
        child_profile = get_enabled_agent(state.agent_id)
        if child_profile is None:
            raise RuntimeError(
                f"agent {state.agent_id!r} 不存在或已禁用，无法派发"
            )
        child_system = build_system_base()
        if child_profile.get("system_prompt"):
            child_system += "\n\n" + child_profile["system_prompt"]

        child = SageAgent(agent_id=state.agent_id)
        messages = [
            {"role": "system", "content": child_system},
            {"role": "user", "content": state.goal},
        ]
        collected: List[str] = []
        async for evt in child.run_loop(messages, llm_config=self.llm_config):
            if evt.state.value == "done" and evt.content:
                collected.append(evt.content)
        if not collected:
            raise RuntimeError("子 agent 未产出 DONE content")
        return "\n\n".join(collected)

    def _emit_task_status(self, state: ChatTaskState) -> None:
        """推 task_status 事件；队列满/关闭静默降级（进度尽力而为）。"""
        event: Dict[str, Any] = {
            "state": "task_status",
            "run_id": self.run_id,
            "task_id": state.task_id,
            "status": state.status,
            "agent_id": state.agent_id,
            "goal": state.goal,
            "error": state.error,
            "output_preview": self._preview(state),
        }
        try:
            self.entry_queue.put_nowait(event)
        except Exception:  # noqa: BLE001
            logger.debug("task_status 推送失败（队列满/关闭），忽略")

    def _preview(self, state: ChatTaskState) -> Optional[str]:
        """done → output 前 500 字；failed → error 前 500 字。"""
        if state.status == "done" and state.output:
            return state.output[:MAX_OUTPUT_PREVIEW_CHARS]
        if state.status == "failed" and state.error:
            return state.error[:MAX_OUTPUT_PREVIEW_CHARS]
        return None

    def _aggregate(self, states: List[ChatTaskState]) -> str:
        """聚合 markdown：成功子结果 + 失败摘要，每项截断。"""
        blocks: List[str] = []
        for state in states:
            header = f"## 子任务 {state.task_id}（{state.agent_id}）"
            if state.status == "done" and state.output:
                body = state.output[:MAX_SUBAGENT_RESULT_CHARS]
                blocks.append(f"{header}\n\n{body}")
            elif state.status == "failed":
                err = (state.error or "未知错误")[:MAX_SUBAGENT_RESULT_CHARS]
                blocks.append(f"{header}\n\n[失败] {err}")
            else:
                blocks.append(f"{header}\n\n[状态: {state.status}]")
        return "\n\n".join(blocks)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_dispatcher.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/orchestration/chat_dispatcher.py backend/tests/unit/test_chat_dispatcher.py
git commit -m "feat(orchestration): ChatDispatcher 轻量子 agent 调度器

- 纯内存、单次聊天 run 生命周期，不持久化、不建 lane
- 并发上限 4（asyncio.Semaphore）+ 单任务失败隔离
- 子结果截断 50KB 聚合回传 conductor；output_preview ≤500 字
- task_id 契约 t{index+1}，task_status 事件实时推 entry.queue"
```

---

### Task 2: dispatch_subagents 工具 + run_loop special-case

**Files:**
- Create: `backend/tools/subagent_tool.py`
- Modify: `backend/core/legacy/agent.py`（run_loop 工具执行处，`if tc.name == "agent":` 分支后加 `elif tc.name == "dispatch_subagents"`）
- Test: `backend/tests/unit/test_subagent_tool.py`

**Interfaces:**
- Consumes: `ChatDispatcher`（Task 1 的 `dispatch(tasks) -> str`）、`BaseTool`（`_build_schema()` / `execute(**kwargs)` / `ToolResult`）
- Produces:
  - `class DispatchSubagentsTool(BaseTool)` —— `_build_schema()` 返回 `ToolSchema(name="dispatch_subagents", parameters=INPUT_SCHEMA)`；`execute(**kwargs)` 返回提示"异步工具"的失败 ToolResult；`async execute_async(**kwargs) -> ToolResult` 委托 `self._dispatcher.dispatch`
  - 模块级 `INPUT_SCHEMA`（tasks minItems 1 / maxItems 4 / goal maxLength 2000）

- [ ] **Step 1: 写失败测试**

`backend/tests/unit/test_subagent_tool.py`：

```python
"""dispatch_subagents 工具单元测试。

- schema 名称/参数钳制（minItems 1 / maxItems 4 / goal maxLength 2000）
- execute_async 委托 dispatcher.dispatch 并包装 ToolResult
- execute() 同步调用返回明确错误（提示走 run_loop special-case）
- run_loop 对 dispatch_subagents 走 execute_async（而非同步 execute）
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.tools.subagent_tool import INPUT_SCHEMA, DispatchSubagentsTool


def _make_dispatcher(aggregated: str = "聚合结果"):
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=aggregated)
    return dispatcher


class TestSchema:
    def test_schema_name_and_parameters(self):
        tool = DispatchSubagentsTool(_make_dispatcher())
        assert tool.name == "dispatch_subagents"
        assert tool.schema.parameters == INPUT_SCHEMA

    def test_schema_tasks_cardinality(self):
        tasks = INPUT_SCHEMA["properties"]["tasks"]
        assert tasks["minItems"] == 1
        assert tasks["maxItems"] == 4
        assert tasks["items"]["properties"]["goal"]["maxLength"] == 2000
        assert tasks["items"]["required"] == ["agent_id", "goal"]


class TestExecuteAsync:
    @pytest.mark.asyncio()
    async def test_execute_async_delegates_to_dispatcher(self):
        dispatcher = _make_dispatcher("调研完毕")
        tool = DispatchSubagentsTool(dispatcher)
        tasks = [{"agent_id": "researcher", "goal": "搜集资料"}]

        result = await tool.execute_async(tasks=tasks)

        assert result.success is True
        assert result.content == "调研完毕"
        dispatcher.dispatch.assert_awaited_once_with(tasks)

    @pytest.mark.asyncio()
    async def test_execute_async_passes_errors_through(self):
        dispatcher = _make_dispatcher()
        dispatcher.dispatch = AsyncMock(side_effect=RuntimeError("dispatch boom"))
        tool = DispatchSubagentsTool(dispatcher)

        result = await tool.execute_async(tasks=[{"agent_id": "r", "goal": "g"}])

        assert result.success is False
        assert "dispatch boom" in result.error


class TestExecuteSync:
    def test_execute_returns_clear_async_error(self):
        """同步 execute 不假装能跑 —— 明确提示走 run_loop special-case。"""
        tool = DispatchSubagentsTool(_make_dispatcher())
        result = tool.execute(tasks=[{"agent_id": "r", "goal": "g"}])
        assert result.success is False
        assert "execute_async" in result.error


class TestRunLoopSpecialCase:
    """真实 run_loop：mock LLM 返回 dispatch_subagents 工具调用 → 断言走 execute_async。"""

    @pytest.mark.asyncio()
    async def test_run_loop_dispatches_via_execute_async(self):
        from backend.core.legacy.agent import SageAgent
        from backend.core.legacy.agent_state import AgentEvent, AgentState
        from backend.core.legacy.llm_client import LLMResponse, LLMToolCall

        dispatcher = _make_dispatcher("子 agent 聚合结果")

        # bare 构造（跳过 register_all_tools），手动注册 dispatch 工具
        agent = SageAgent(agent_id=None, bare=True)
        agent.tool_registry.register(DispatchSubagentsTool(dispatcher))

        # mock llm_client.chat：第一轮工具调用，第二轮 DONE
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="",
                    finish_reason="tool_calls",
                    tool_calls=[
                        LLMToolCall(
                            id="call_1",
                            name="dispatch_subagents",
                            arguments=json.dumps(
                                {"tasks": [{"agent_id": "researcher", "goal": "调研"}]}
                            ),
                        )
                    ],
                ),
                LLMResponse(content="最终答案", finish_reason="stop", tool_calls=[]),
            ]
        )
        agent.llm_client = mock_client

        events = []
        async for evt in agent.run_loop(
            [{"role": "user", "content": "复杂任务"}], max_iterations=2
        ):
            events.append(evt)

        assert events[-1].state == AgentState.DONE
        assert events[-1].content == "最终答案"
        dispatcher.dispatch.assert_awaited_once()  # execute_async 被调（不是 execute）
        observed = [e for e in events if e.state == AgentState.OBSERVING]
        assert observed, "run_loop 应产出 OBSERVING 事件（含 dispatch 结果）"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_subagent_tool.py -v
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.tools.subagent_tool'`

- [ ] **Step 3: 写最小实现**

`backend/tools/subagent_tool.py`：

```python
"""``dispatch_subagents`` 工具 —— conductor 并行派发子 agent 的原语。

方案 C（multi-agent orchestration spec §5.2）：conductor（主 LLM）在
multi 模式下拿到 ``task_plan`` 后，按计划调用本工具，把
``[{agent_id, goal}]`` 交给 ``ChatDispatcher`` 并行执行。

关键约束：
- 本工具是**异步**的（子 agent 需在事件循环上并发 + 直接推 entry.queue），
  因此必须经 run_loop 的 ``execute_async`` special-case 调用，不能走同步
  ``execute``。同步调用会返回明确的错误提示。
- 仅 multi 模式注册到 conductor 的 tool_registry（tool-toggle 门）。
- 默认权限：未登记 → ``classify_tool`` 回退 WRITE；``workspace_write``
  模式放行，read_only/prompt 模式按矩阵 deny/ask（M1 硬化语义不变）。
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.tools.base import BaseTool, ToolResult, ToolSchema

#: 工具参数 schema —— 钳制子任务数量 ≤4（与并发上限 4 对齐）。
INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "minItems": 1,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "goal": {"type": "string", "maxLength": 2000},
                },
                "required": ["agent_id", "goal"],
            },
        }
    },
    "required": ["tasks"],
}

_TOOL_DESCRIPTION = (
    "并行派发子 agent 执行任务。适用于已拆解为多个子任务的复杂目标："
    "传入 [{agent_id, goal}] 列表（最多 4 个），每个子 agent 独立运行并把"
    "结果聚合返回。agent_id 必须是已启用的角色（如 researcher / writer）。"
)


class DispatchSubagentsTool(BaseTool):
    """把子任务派发给 ChatDispatcher 的异步工具。"""

    def __init__(self, dispatcher: Any) -> None:
        """Args:
            dispatcher: 实现了 ``async dispatch(tasks) -> str`` 的 ChatDispatcher。
        """
        super().__init__()
        self._dispatcher = dispatcher

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="dispatch_subagents",
            description=_TOOL_DESCRIPTION,
            parameters=INPUT_SCHEMA,
        )

    async def execute_async(self, **kwargs: Any) -> ToolResult:
        """异步执行 —— 子 agent 在事件循环上并发（ChatDispatcher 内 gather）。"""
        tasks: List[Dict[str, str]] = kwargs.get("tasks", [])
        try:
            aggregated = await self._dispatcher.dispatch(tasks)
            return ToolResult(success=True, content=aggregated)
        except Exception as exc:  # noqa: BLE001 — 错误回传 conductor 决策
            return ToolResult(success=False, error=f"dispatch_subagents 失败: {exc}")

    def execute(self, **kwargs: Any) -> ToolResult:
        """同步调用不可行（子 agent 需并发）—— 返回明确错误。"""
        return ToolResult(
            success=False,
            error="dispatch_subagents 是异步工具，必须经 run_loop 的 "
            "execute_async special-case 调用",
        )
```

`backend/core/legacy/agent.py` —— run_loop 工具执行处，在 `if tc.name == "agent":` 分支后加：

```python
                                    elif tc.name == "dispatch_subagents":
                                        # Multi-agent orchestration: this tool is
                                        # async by design — child agents run
                                        # concurrently on the event loop
                                        # (ChatDispatcher gather) and push
                                        # task_status straight to the stream
                                        # queue. Sync execute() cannot do that.
                                        # Same minimal special-case as "agent";
                                        # general tool dispatch stays inline.
                                        result = await tool.execute_async(**args)
```

> 注：`execute_async` 的权限检查在 `enforcer.check(tc.name, args)`（已先于 try 块执行）——默认 workspace_write 放行 WRITE 能力，不触发审批。read_only/prompt 模式的 deny/ask 行为与其它 WRITE 工具一致。

- [ ] **Step 4: 跑测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_subagent_tool.py -v
```

Expected: 5 passed（schema 2 + execute_async 2 + execute_sync 1 + run_loop special-case 1）

- [ ] **Step 5: Commit**

```bash
git add backend/tools/subagent_tool.py backend/core/legacy/agent.py backend/tests/unit/test_subagent_tool.py
git commit -m "feat(tools): dispatch_subagents 工具 + run_loop execute_async special-case

- schema 钳制 tasks ≤4 / goal ≤2000，与并发上限对齐
- 同步 execute 返回明确错误；run_loop 对 dispatch_subagents 走 execute_async
- 默认 workspace_write 放行（未登记 WRITE 能力），M1 硬化语义不变"
```

---

### Task 3: orchestration_mode 字段 + 语义二分类（tool-toggle 门判定源）

**Files:**
- Modify: `backend/api/legacy_routes.py`（`ChatRequest` 加 `orchestration_mode` 字段）
- Modify: `backend/orchestration/chat_dispatcher.py`（加 `_classify_orchestration_mode` 模块函数 + `_CLASSIFY_PROMPT`）
- Test: `backend/tests/unit/test_classify_orchestration_mode.py`

**Interfaces:**
- Consumes: `LLMClient.complete(prompt) -> str`（`build_llm_client_from_settings()` 返回）
- Produces:
  - `async def _classify_orchestration_mode(message: str, orchestration_mode: str, llm_client: Optional[Any] = None) -> str` —— 返回 `"multi" | "single"`
  - `ChatRequest.orchestration_mode: str = "auto"`（`auto | force_multi | force_single`）

- [ ] **Step 1: 写失败测试**

`backend/tests/unit/test_classify_orchestration_mode.py`：

```python
"""_classify_orchestration_mode 单元测试 —— tool-toggle 门的判定源。

- force_multi / force_single 短路（跳过 LLM）
- auto：LLM 返回 multi/single 透传
- auto：无 client → single（= 没开编排）
- auto：LLM 异常 → single（降级不阻塞聊天）
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.orchestration.chat_dispatcher import _classify_orchestration_mode


def _client_returning(text: str):
    client = MagicMock()
    client.complete = AsyncMock(return_value=text)
    return client


@pytest.mark.asyncio()
async def test_force_multi_short_circuits():
    client = _client_returning("single")  # 即使 LLM 说 single，force 也赢
    assert await _classify_orchestration_mode("hi", "force_multi", client) == "multi"
    client.complete.assert_not_awaited()


@pytest.mark.asyncio()
async def test_force_single_short_circuits():
    client = _client_returning("multi")
    assert await _classify_orchestration_mode("hi", "force_single", client) == "single"
    client.complete.assert_not_awaited()


@pytest.mark.asyncio()
async def test_auto_passes_through_multi():
    client = _client_returning("multi")
    assert (
        await _classify_orchestration_mode("学习量化交易先搜集资料", "auto", client)
        == "multi"
    )


@pytest.mark.asyncio()
async def test_auto_passes_through_single():
    client = _client_returning("single")
    assert await _classify_orchestration_mode("今天天气怎么样", "auto", client) == "single"


@pytest.mark.asyncio()
async def test_auto_no_client_falls_back_single():
    assert await _classify_orchestration_mode("复杂任务", "auto", None) == "single"


@pytest.mark.asyncio()
async def test_auto_llm_error_falls_back_single():
    client = MagicMock()
    client.complete = AsyncMock(side_effect=RuntimeError("llm down"))
    assert await _classify_orchestration_mode("复杂任务", "auto", client) == "single"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_classify_orchestration_mode.py -v
```

Expected: FAIL —— `ImportError: cannot import name '_classify_orchestration_mode'`

- [ ] **Step 3: 写最小实现**

在 `backend/orchestration/chat_dispatcher.py` 顶部（`MAX_OUTPUT_PREVIEW_CHARS` 之后）加：

```python
_CLASSIFY_PROMPT = """判断以下用户消息是否需要多 agent 协作（拆解为多个子任务、由不同角色并行执行）才能最好地完成。
只需返回一个词：multi 或 single。
- multi：复杂任务、多步骤、需要搜集资料/研究/并行工作。例如"我需要学习量化交易，先搜集相关资料后，整理一份学习资料和操作指南"。
- single：简单问答、单步请求。例如"今天天气怎么样"、"解释什么是递归"。

用户消息: {message}

答案:"""


async def _classify_orchestration_mode(
    message: str,
    orchestration_mode: str,
    llm_client: Optional[Any] = None,
) -> str:
    """语义判定消息是否进编排（multi）还是单 agent（single）。

    - ``force_multi`` / ``force_single``：用户 override，直接定，跳过 LLM
    - ``auto``：轻量 LLM 二分类；无 client / 失败 → ``single``（= 没开编排）

    这是 tool-toggle 门的判定源：mode=single 时 producer 不注册
    dispatch_subagents 工具（简单任务在结构上无法被过度拆解）。
    """
    if orchestration_mode == "force_multi":
        return "multi"
    if orchestration_mode == "force_single":
        return "single"
    if llm_client is None:
        return "single"
    try:
        response = await llm_client.complete(_CLASSIFY_PROMPT.format(message=message))
        return "multi" if "multi" in (response or "").strip().lower() else "single"
    except Exception as exc:  # noqa: BLE001 — 判定失败必须降级，绝不阻塞聊天
        logger.warning("编排语义判定失败，降级 single: %s", exc)
        return "single"
```

`backend/api/legacy_routes.py` —— `ChatRequest` 加字段（`office_refs` 之后）：

```python
    office_refs: Optional[list] = None

    # Multi-Agent Orchestration (spec 2026-08-11): 编排模式开关。
    # auto（默认）—— 轻量 LLM 二分类决定；force_multi / force_single ——
    # 用户斜杠命令 /orchestrate / /single 覆盖，跳过语义判定。
    orchestration_mode: str = "auto"
```

- [ ] **Step 4: 跑测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_classify_orchestration_mode.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/orchestration/chat_dispatcher.py backend/api/legacy_routes.py backend/tests/unit/test_classify_orchestration_mode.py
git commit -m "feat(chat): orchestration_mode 字段 + 语义二分类

- ChatRequest.orchestration_mode: auto|force_multi|force_single
- force 短路跳过 LLM；auto 轻量二分类；无 LLM/失败降级 single
- 编排判定失败绝不阻塞聊天（tool-toggle 门的安全网）"
```

---

### Task 4: /chat/stream multi 编排分支（核心集成）

**Files:**
- Modify: `backend/api/legacy_routes.py`（producer 内，`agent = SageAgent(...)` 之后插入 multi 分支）
- Test: `backend/tests/integration/test_chat_orchestration_stream.py`

**Interfaces:**
- Consumes: `_classify_orchestration_mode`（Task 3）、`Planner.decompose_request(message)`（返回 `Plan{tasks:[Task]}`，`Task.parameters["agent_hint"]`）、`ChatDispatcher`（Task 1）、`DispatchSubagentsTool`（Task 2）、`SageAgent.tool_registry.register`、`build_system_base()`
- Produces:
  - producer multi 分支行为：
    1. `mode = await _classify_orchestration_mode(data.message, data.orchestration_mode, build_llm_client_from_settings())`
    2. `mode == "multi"` → `plan = await Planner(task_registry=TaskRegistry(), team_registry=TeamRegistry(), llm_client=build_llm_client_from_settings()).decompose_request(data.message)`
    3. `len(plan.tasks) <= 1` → 降级 single（没拆开 = 没开编排）
    4. 否则 `run_id = f"orch-{uuid.uuid4()}"`；`dispatcher = ChatDispatcher(stream_id, entry.queue, run_id, llm_config)`；`agent.tool_registry.register(DispatchSubagentsTool(dispatcher))`；`agent.profile["tools"].append("dispatch_subagents")`；`system_content += plan 块`；`await entry.queue.put(task_plan 事件)`

- [ ] **Step 1: 写失败测试**

`backend/tests/integration/test_chat_orchestration_stream.py`：

```python
"""/chat/stream multi-agent 编排集成测试 —— 双失败模式硬约束。

测试 5（复杂任务简单化=0）: force_multi → task_plan 必出 + dispatch 工具必注册
测试 6（简单任务复杂化=0）: single 路径无 task_plan/task_status + 无 dispatch 工具
测试 7: force_single 时复杂消息也不进编排
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport

from backend.main import app

CHAT_STREAM_PATH = "/api/v1/chat/stream"


def _mock_plan(agent_hints=("researcher", "writer")):
    """返回 2-task 的 fake Plan（绕过真实 Planner LLM 调用）。"""

    def _decompose(message, context=None):
        from backend.orchestration.models import Task

        return type(
            "Plan",
            (),
            {
                "plan_id": "p1",
                "team_id": "team1",
                "tasks": [
                    Task(
                        task_id=f"t{i + 1}",
                        name=f"任务 {i + 1}",
                        description=f"目标：{hint}",
                        parameters={"agent_hint": hint},
                    )
                    for i, hint in enumerate(agent_hints)
                ],
                "original_request": message,
                "reasoning": "test",
            },
        )()

    return _decompose


async def _stream_events(ac: httpx.AsyncClient, payload: dict) -> list[dict]:
    create_resp = await ac.post(CHAT_STREAM_PATH, json=payload)
    assert create_resp.status_code == 200, create_resp.text
    stream_id = create_resp.json()["streamId"]
    attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
    assert attach_resp.status_code == 200
    return [line for line in attach_resp.text.splitlines() if line.strip()]


@pytest.mark.asyncio()
async def test_multi_mode_emits_task_plan_and_registers_dispatch_tool():
    """复杂任务必进编排：task_plan 事件必出 + dispatch_subagents 工具必注册。"""
    registered_tools: list = []

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.DONE, iteration=0, content="已完成量化交易学习资料整理"
        )

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        instance = MockAgent.return_value
        instance.run_loop = mock_run_loop
        instance.tool_registry = type(
            "TR", (), {"register": lambda tool: registered_tools.append(tool.name)}
        )()
        instance.profile = {"tools": ["calculator"]}

        with patch("backend.orchestration.planner.Planner") as MockPlanner:
            MockPlanner.return_value.decompose_request = _mock_plan()

            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                events = await _stream_events(
                    ac,
                    {
                        "session_id": "s",
                        "message": "我需要学习量化交易，先搜集相关资料后整理学习资料和操作指南",
                        "orchestration_mode": "force_multi",
                        "api_key": "sk-test",
                        "api_url": "https://example.com/v1",
                    },
                )

    states = [e["state"] for e in events]
    assert "task_plan" in states, f"task_plan 必出，实际 events={states}"
    plan_event = next(e for e in events if e["state"] == "task_plan")
    assert plan_event["run_id"].startswith("orch-")
    assert len(plan_event["plan"]) == 2
    assert [p["task_id"] for p in plan_event["plan"]] == ["t1", "t2"]
    # 子 agent 跑之前 task_plan 先到（计划先展示）
    assert states.index("task_plan") < states.index("done")

    assert "dispatch_subagents" in registered_tools, (
        "force_multi 必须注册 dispatch 工具（硬约束 1）"
    )


@pytest.mark.asyncio()
async def test_single_mode_has_no_orchestration_events_or_tool():
    """简单任务复杂化=0：single 路径无编排事件 + 无 dispatch 工具。"""
    registered_tools: list = []

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        yield AgentEvent(state=AgentState.DONE, iteration=0, content="今天晴，22 度")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        instance = MockAgent.return_value
        instance.run_loop = mock_run_loop
        instance.tool_registry = type(
            "TR", (), {"register": lambda tool: registered_tools.append(tool.name)}
        )()
        instance.profile = {"tools": ["calculator"]}

        with patch(
            "backend.api.legacy_routes._classify_orchestration_mode",
            return_value="single",
        ):
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                events = await _stream_events(
                    ac,
                    {
                        "session_id": "s",
                        "message": "今天天气怎么样",
                        "orchestration_mode": "auto",
                    },
                )

    states = [e["state"] for e in events]
    assert "task_plan" not in states, f"single 路径不应有 task_plan: {states}"
    assert "task_status" not in states, f"single 路径不应有 task_status: {states}"
    assert "dispatch_subagents" not in registered_tools, (
        "single 路径必须不注册 dispatch 工具（硬约束 2）"
    )


@pytest.mark.asyncio()
async def test_force_single_skips_orchestration_even_for_complex_message():
    """用户 /single override：复杂消息也不进编排。"""
    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        yield AgentEvent(state=AgentState.DONE, iteration=0, content="直接回答")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        instance = MockAgent.return_value
        instance.run_loop = mock_run_loop
        instance.tool_registry = type("TR", (), {"register": lambda tool: None})()
        instance.profile = {"tools": ["calculator"]}

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            events = await _stream_events(
                ac,
                {
                    "session_id": "s",
                    "message": "我需要学习量化交易，先搜集相关资料后整理学习资料",
                    "orchestration_mode": "force_single",
                },
            )

    states = [e["state"] for e in events]
    assert "task_plan" not in states
    assert "task_status" not in states


@pytest.mark.asyncio()
async def test_multi_degrades_to_single_when_plan_has_one_task():
    """Planner 降级为单任务（LLM 没拆开）→ 视为没开编排，无 task_plan。"""
    registered_tools: list = []

    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        yield AgentEvent(state=AgentState.DONE, iteration=0, content="单任务输出")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        instance = MockAgent.return_value
        instance.run_loop = mock_run_loop
        instance.tool_registry = type(
            "TR", (), {"register": lambda tool: registered_tools.append(tool.name)}
        )()
        instance.profile = {"tools": ["calculator"]}

        with patch("backend.orchestration.planner.Planner") as MockPlanner:
            MockPlanner.return_value.decompose_request = _mock_plan(
                agent_hints=("researcher",)
            )

            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                events = await _stream_events(
                    ac,
                    {
                        "session_id": "s",
                        "message": "我有个问题",
                        "orchestration_mode": "force_multi",
                    },
                )

    states = [e["state"] for e in events]
    assert "task_plan" not in states
    assert "dispatch_subagents" not in registered_tools
```

- [ ] **Step 2: 跑测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_orchestration_stream.py -v
```

Expected: FAIL —— 4 个测试因 producer 无 multi 分支而失败

- [ ] **Step 3: 写最小实现**

`backend/api/legacy_routes.py` —— 在 `system_content = build_system_base()`（该行先于 multi 分支执行、负责 base prompt）**之后**、`try:`（diagram 块）之前插入 multi 分支：

```python
            system_content = build_system_base()

            # ===== Multi-Agent Orchestration (spec 2026-08-11) =====
            # tool-toggle 门: 语义判定（独立轻量 LLM 二分类）决定 mode。
            # single → 不注册 dispatch_subagents 工具、不跑 decompose_request
            #          （简单任务结构上无法被过度拆解 — 硬约束 2）
            # multi  → 复用 Planner 预规划 + conductor 经 dispatch 工具执行
            #          （复杂任务必出 task_plan + 必注册工具 — 硬约束 1）
            from backend.orchestration.llm_factory import (
                build_llm_client_from_settings,
            )

            mode = await _classify_orchestration_mode(
                data.message,
                data.orchestration_mode or "auto",
                llm_client=build_llm_client_from_settings(),
            )
            run_id: Optional[str] = None
            if mode == "multi":
                from backend.orchestration.chat_dispatcher import ChatDispatcher
                from backend.orchestration.planner import Planner
                from backend.orchestration.task_registry import TaskRegistry
                from backend.orchestration.team_registry import TeamRegistry
                from backend.tools.subagent_tool import DispatchSubagentsTool

                plan = await Planner(
                    task_registry=TaskRegistry(),
                    team_registry=TeamRegistry(),
                    llm_client=build_llm_client_from_settings(),
                ).decompose_request(data.message)
                plan_tasks = list(plan.tasks if plan else [])
                if len(plan_tasks) <= 1:
                    # LLM 没拆开（或降级单任务）→ 视为没开编排
                    mode = "single"
                else:
                    run_id = f"orch-{uuid.uuid4()}"
                    dispatcher = ChatDispatcher(
                        stream_id=stream_id,
                        entry_queue=entry.queue,
                        run_id=run_id,
                        llm_config=llm_config,
                    )
                    agent.tool_registry.register(DispatchSubagentsTool(dispatcher))
                    if (
                        agent.profile is not None
                        and agent.profile.get("tools") is not None
                    ):
                        agent.profile["tools"].append("dispatch_subagents")
                    # 计划块注入 system prompt —— conductor 依据计划调用工具
                    # 注: system_content 已在插入点之前由 build_system_base()
                    # 赋值（L1598），这里只追加计划块，不再重新赋值（否则覆盖）。
                    plan_block = "\n".join(
                        f"- {i}. [{t.parameters.get('agent_hint', 'primary')}] "
                        f"{t.name}: {t.description}"
                        for i, t in enumerate(plan_tasks, 1)
                    )
                    system_content += (
                        "\n\n以下为已确认的任务计划，请调用 dispatch_subagents "
                        "工具并行执行这些子任务（可合并/调整）。不要复述计划，直接执行。\n"
                        + plan_block
                    )
                    # 计划先行：子 agent 跑之前先推 task_plan（可展示、可取消）
                    await entry.queue.put(
                        {
                            "state": "task_plan",
                            "run_id": run_id,
                            "plan": [
                                {
                                    "task_id": f"t{i}",
                                    "agent_id": t.parameters.get(
                                        "agent_hint", "primary"
                                    ),
                                    "goal": t.description or t.name,
                                }
                                for i, t in enumerate(plan_tasks, 1)
                            ],
                        }
                    )
```

并在文件顶部 import 区加：

```python
from backend.orchestration.chat_dispatcher import _classify_orchestration_mode
```

> 注：`uuid` **已在** `legacy_routes.py` L23 `import uuid`，multi 分支 `uuid.uuid4()` 无需新增 import。`chat_dispatcher` / `planner` / `task_registry` / `team_registry` / `subagent_tool` 走 producer 内局部 import（L1154-1158），避免顶部循环依赖。

> 注：插入点在 `system_content = build_system_base()`（L1598）之后 —— base prompt 已赋值，multi 分支只 `+=` 计划块，不会覆盖。后续 diagram（L1611）/ `M6 PROJECT CONTEXT`（L1631）继续 `+=`，顺序不变；`messages` 构造（L1637）自然包含计划块。`agent = SageAgent(...)` 在 L1593（插入点前）已执行，`agent.tool_registry`/`agent.profile` 可直接用。

- [ ] **Step 4: 跑测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_orchestration_stream.py -v
```

Expected: 4 passed

- [ ] **Step 5: 跑既有回归确认无破坏**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_stream.py backend/tests/unit/test_agent_loop.py -q
```

Expected: 全绿（single 路径零回归 —— 编排不得破坏简单对话）

- [ ] **Step 6: Commit**

```bash
git add backend/api/legacy_routes.py backend/tests/integration/test_chat_orchestration_stream.py
git commit -m "feat(chat): /chat/stream multi 编排分支（方案 C）

- classify → Planner.decompose_request → task_plan 先发 → conductor 注入
  dispatch_subagents 工具 + 计划块 → run_loop
- 单任务降级 / force_single → 视为没开编排，单 agent 路径零回归
- 集成测试钉死双失败模式：multi 必出 plan+工具，single 必无编排事件"
```

---

### Task 5: writer 角色种子 + POST /agents 创建端点（US-4）

**Files:**
- Modify: `backend/agents/profiles.py`（`create_default_agents()` 加 `writer`；加 `ensure_default_agents()`）
- Modify: `backend/api/legacy_routes.py`（`POST /agents` 路由 + `AgentCreate` model + role 白名单共享常量）
- Modify: `backend/main.py`（lifespan 用 `ensure_default_agents` 替换 `seed_defaults_if_empty`）
- Test: `backend/tests/unit/test_agent_crud_orchestration.py`

**Interfaces:**
- Consumes: `AgentRepository.upsert(profile: dict)`（INSERT OR REPLACE，已支持新增）、`AgentProfile.to_dict()`
- Produces:
  - `AgentProfile(id="writer", tools=["read_file", "write_file", "memory_search"], ...)` 种子
  - `ensure_default_agents() -> int`（增量补插缺失的默认角色）
  - `AgentCreate` Pydantic model（id/name 必填；role/system_prompt/tools/memory_access/model_config_data/max_iterations/enabled/description 可选）
  - `POST /agents` 路由（200 + 新 profile；409 id 已存在；422 role 校验）

- [ ] **Step 1: 写失败测试**

`backend/tests/unit/test_agent_crud_orchestration.py`：

```python
"""writer 种子 + POST /agents 创建端点（US-4 角色可扩展）。

- create_default_agents 含 writer，tools 用 registry 正确名（read_file/write_file）
- ensure_default_agents 增量补插（已存在 DB 也能拿到 writer）
- POST /agents 创建成功 → 200 + 完整 profile
- POST /agents 重复 id → 409
- POST /agents 非法 role → 422
"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from backend.data.agent_repo import AgentRepository
from backend.main import app


@pytest.mark.asyncio()
async def test_writer_is_in_default_agents_with_correct_tool_names():
    from backend.agents.profiles import create_default_agents

    writers = [a for a in create_default_agents() if a.id == "writer"]
    assert writers, "create_default_agents 必须含 writer 种子"
    writer = writers[0]
    assert "read_file" in writer.tools  # registry 实际注册名（非过时 file_read）
    assert "write_file" in writer.tools
    assert "memory_search" in writer.tools


@pytest.mark.asyncio()
async def test_ensure_default_agents_inserts_writer_into_existing_db():
    """已存在 DB（非空表）也要有 writer —— seed_defaults_if_empty 只覆盖空表。

    幂等断言：无论 conftest 是否已把含 writer 的默认集 seed 进表，本测试都成立。
    """
    from backend.agents.profiles import ensure_default_agents

    # 第一次：确保所有默认角色在位（含 writer）
    ensure_default_agents()
    assert AgentRepository().get("writer") is not None
    # 第二次应为 no-op（全部已存在）—— 不依赖 conftest 是否已 seed writer
    assert ensure_default_agents() == 0


@pytest.mark.asyncio()
async def test_create_agent_endpoint_creates_custom_role():
    payload = {
        "id": "quant_analyst",
        "name": "量化分析师",
        "role": "researcher",
        "system_prompt": "你是一名量化交易分析师",
        "tools": ["web_search", "memory_search"],
        "description": "分析量化交易数据",
    }
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post("/api/v1/agents", json=payload)
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["id"] == "quant_analyst"
    assert created["tools"] == ["web_search", "memory_search"]
    # 落库可读
    assert AgentRepository().get("quant_analyst")["name"] == "量化分析师"


@pytest.mark.asyncio()
async def test_create_agent_endpoint_rejects_duplicate_id():
    payload = {
        "id": "researcher",  # 已存在默认角色
        "name": "重复",
        "role": "researcher",
        "system_prompt": "x",
    }
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post("/api/v1/agents", json=payload)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["type"] == "agent_already_exists"


@pytest.mark.asyncio()
async def test_create_agent_endpoint_validates_role():
    payload = {
        "id": "bad_role",
        "name": "坏角色",
        "role": "not_a_real_role",
        "system_prompt": "x",
    }
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post("/api/v1/agents", json=payload)
    assert resp.status_code == 422, resp.text
```

- [ ] **Step 2: 跑测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_agent_crud_orchestration.py -v
```

Expected: FAIL —— writer 不在默认种子 / `ensure_default_agents` 不存在 / POST /agents 404

- [ ] **Step 3: 写最小实现**

`backend/agents/profiles.py` —— `create_default_agents()` 列表末尾（`memory_manager` 之后）加：

```python
        AgentProfile(
            id="writer",
            name="写作 Agent",
            role="writer",
            description="负责把研究资料整理成结构化的学习资料/操作指南等 markdown 文档",
            system_prompt=(
                "你是一个专业的写作 Agent。负责把资料整理成结构清晰、可执行的 "
                "学习资料、操作指南等 markdown 文档。产出文档请用 write_file 工具落盘。"
            ),
            tools=["read_file", "write_file", "memory_search"],
            memory_access=["semantic"],
            model_config=AgentModelConfig(model="gpt-4", temperature=0.4),
            max_iterations=10,
        ),
```

`backend/agents/profiles.py` 追加 `ensure_default_agents`：

```python
def ensure_default_agents() -> int:
    """确保所有默认 agent（含 writer）都存在。

    ``seed_defaults_if_empty`` 只在表为空时插，已存在的 DB 不会自动补
    writer —— 本函数逐个检查缺失的默认 id 并补插。返回补插条数。
    """
    from backend.data.agent_repo import AgentRepository

    repo = AgentRepository()
    inserted = 0
    for agent in create_default_agents():
        if repo.get(agent.id) is None:
            repo.upsert(agent.to_dict())
            inserted += 1
    return inserted
```

`backend/api/legacy_routes.py`：

1. 加共享 role 白名单常量（`update_agent` 内 `valid_roles = {...}` 替换为引用它）：

```python
#: agent role 白名单（PATCH/POST 共用）。
_VALID_AGENT_ROLES = {
    "coordinator",
    "researcher",
    "coder",
    "memory_manager",
    "writer",
}
```

2. 新增 `AgentCreate` model：

```python
class AgentCreate(BaseModel):
    """POST /agents 请求体（US-4 角色可扩展）。

    id / name 必填；其余字段带默认值。
    ``model_config_data`` 字段名避开 Pydantic 保留名（同 AgentUpdate）。
    """

    model_config = {"protected_namespaces": ()}

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=64)
    role: str = "general"
    system_prompt: str = ""
    tools: Optional[List[str]] = None
    memory_access: Optional[List[str]] = None
    model_config_data: Optional[dict] = None
    max_iterations: Optional[int] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None
```

3. 新增路由（`toggle_agent` 之后）：

```python
@router.post("/agents")
@with_db_lock
def create_agent(data: AgentCreate):
    """创建自定义 agent（US-4）。

    - 200 + 完整 profile
    - 409 + 结构化 detail（id 已存在）
    - 422 — role 白名单 / max_iterations 范围
    """
    from backend.data.agent_repo import AgentRepository

    if data.role not in _VALID_AGENT_ROLES and data.role != "general":
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_role",
                "message": (
                    f"role must be one of {sorted(_VALID_AGENT_ROLES)} "
                    f"or 'general', got {data.role!r}"
                ),
            },
        )

    if data.max_iterations is not None and not (1 <= data.max_iterations <= 50):
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_max_iterations",
                "message": f"max_iterations must be in 1..50, got {data.max_iterations}",
            },
        )

    repo = AgentRepository()
    if repo.get(data.id) is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "type": "agent_already_exists",
                "message": f"agent {data.id!r} already exists",
            },
        )

    payload = data.model_dump(exclude_none=True)
    if "model_config_data" in payload:
        payload["model_config"] = payload.pop("model_config_data")
    payload.setdefault("tools", [])
    payload.setdefault("memory_access", [])
    payload.setdefault("model_config", {})
    payload.setdefault("max_iterations", 10)
    payload.setdefault("enabled", True)
    payload.setdefault("description", "")

    repo.upsert(payload)
    return repo.get(data.id)
```

`backend/main.py` —— lifespan 中 `AgentRepository().seed_defaults_if_empty()` 替换为：

```python
            # 种子化默认 agents（首次 + 增量补 writer 等新增默认角色）
            from backend.agents.profiles import ensure_default_agents

            ensure_default_agents()
```

- [ ] **Step 4: 跑测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_agent_crud_orchestration.py -v
```

Expected: 5 passed

- [ ] **Step 5: 跑既有 agent 测试回归**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_agent_repo.py -q
```

Expected: 全绿（role 白名单共享常量 + writer 种子不破坏既有断言）

- [ ] **Step 6: Commit**

```bash
git add backend/agents/profiles.py backend/api/legacy_routes.py backend/main.py backend/tests/unit/test_agent_crud_orchestration.py
git commit -m "feat(agents): writer 种子 + POST /agents 创建端点（US-4）

- writer 用 registry 正确工具名 read_file/write_file/memory_search
- ensure_default_agents 增量补插（已存在 DB 也能拿到 writer）
- role 白名单共享常量 + writer；POST /agents 409 重复 id"
```

---

### Task 6: Electron agent_* IPC 命令补齐 + agentsApi.create（修复 pre-existing 损坏）

**Files:**
- Modify: `electron/commands.ts`（COMMAND_ROUTES 补 5 个 agent_* 命令）
- Modify: `src/shared/api/agentsApi.ts`（加 `createAgent`）
- Modify: `src/shared/api/types.ts`（加 `AgentCreate`）
- Test: `electron/commands.test.ts`（guard：所有 agent 命令 path 前缀 /api/v1）

**Interfaces:**
- Consumes: 后端 `POST /api/v1/agents`、`GET /api/v1/agents`、`GET /api/v1/agents/{id}`、`PATCH /api/v1/agents/{id}`、`PATCH /api/v1/agents/{id}/toggle`
- Produces:
  - COMMAND_ROUTES 新增：`list_agents`(GET `/agents`)、`get_agent`(GET `/agents/{id}`)、`update_agent`(PATCH)、`toggle_agent`(PATCH `/agents/{id}/toggle`)、`create_agent`(POST)
  - `agentsApi.createAgent(payload: AgentCreate)` → invoke('create_agent', payload)

- [ ] **Step 1: 写失败测试**

`electron/commands.test.ts`（追加）：

```typescript
import { describe, expect, it } from 'vitest';
import { COMMAND_ROUTES } from './commands';

describe('agent_* IPC commands', () => {
  it('registers all five agent commands with /api/v1-prefixed paths', () => {
    const required = ['list_agents', 'get_agent', 'update_agent', 'toggle_agent', 'create_agent'];
    for (const cmd of required) {
      const route = COMMAND_ROUTES[cmd];
      expect(route).toBeDefined();
      // path 签名统一 (args: Record<string, unknown>) => string —— 传 { id: 'test' }
      //（list/create 的实现忽略参数）
      expect(route.path({ id: 'test' })).toMatch(/^\/api\/v1\//);
    }
  });

  it('strips id from update_agent body (extra=forbid)', () => {
    const route = COMMAND_ROUTES['update_agent'];
    expect(route.path({ id: 'x' })).toBe('/api/v1/agents/x');
    expect(route.body?.({ id: 'x', update: { systemPrompt: 'p' } })).toEqual({
      systemPrompt: 'p',
    });
  });

  it('strips id from toggle_agent body', () => {
    const route = COMMAND_ROUTES['toggle_agent'];
    expect(route.path({ id: 'x' })).toBe('/api/v1/agents/x/toggle');
    expect(route.body?.({ id: 'x', enabled: false })).toEqual({ enabled: false });
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage && npx vitest run electron/commands.test.ts
```

Expected: FAIL —— `COMMAND_ROUTES[cmd]` undefined（list_agents 等缺失）

- [ ] **Step 3: 写最小实现**

`electron/commands.ts` —— COMMAND_ROUTES 中 `agent_chat_stream` 附近补：

```typescript
  agent_chat_stream: { method: 'POST', path: () => '/api/v1/chat/stream' },
  list_agents: { method: 'GET', path: () => '/api/v1/agents' },
  get_agent: {
    method: 'GET',
    path: (a) => `/api/v1/agents/${encodeURIComponent(String(a.id))}`,
  },
  update_agent: {
    method: 'PATCH',
    path: (a) => `/api/v1/agents/${encodeURIComponent(String(a.id))}`,
    // 后端 update body 是 extra="forbid" — id 是路径参数，必须从 body 剥掉，
    // 否则 422（与 permissions_answer 剥 requestId 同理）。显式 body 后
    // invoke 仍会递归 camelToSnakeKeys（electron/invoke.ts L68-69），
    // update 内部 systemPrompt → system_prompt 自动转换。
    body: (a) => (a.update as Record<string, unknown>) ?? {},
  },
  toggle_agent: {
    method: 'PATCH',
    path: (a) => `/api/v1/agents/${encodeURIComponent(String(a.id))}/toggle`,
    body: (a) => ({ enabled: a.enabled }),
  },
  create_agent: { method: 'POST', path: () => '/api/v1/agents' },
```

> 注：`create_agent` 走无显式 body —— invoke 会把整个 payload 作为 body 并递归 camelToSnakeKeys（`modelConfigData` → 后端 `model_config_data`，自动对齐 AgentCreate 字段）。`path`/`body` 签名对照既有 `agent_chat_stream`（L41）/`permissions_answer`（L166-173）确认。

`src/shared/api/types.ts` —— 加 `AgentCreate`：

```typescript
/** POST /agents 请求体（US-4 角色可扩展）。 */
export interface AgentCreate {
  id: string;
  name: string;
  role?: string;
  system_prompt?: string;
  tools?: string[];
  memory_access?: string[];
  modelConfigData?: Record<string, unknown>;
  maxIterations?: number;
  enabled?: boolean;
  description?: string;
}
```

`src/shared/api/agentsApi.ts` —— `update()` 方法之后、`};` 闭合前加：

```typescript
  /**
   * 创建自定义 agent（US-4 角色可扩展）。
   *
   * 后端 `POST /api/v1/agents`：200 + 完整 profile；409 id 已存在；422 role 校验。
   * 走无显式 body 的 IPC 路由 —— invoke 把 payload 整对象递归 camelToSnakeKeys
   * （`modelConfigData` → `model_config_data`，自动对齐后端 AgentCreate 字段）。
   *
   * @throws 后端 409 / 422 经 handleApiError 包装
   */
  async create(payload: AgentCreate): Promise<AgentProfile> {
    return withRetry(async () => {
      try {
        return await invoke<AgentProfile>('create_agent', payload);
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
```

（与 `list`/`toggle`/`update` 同为对象方法，`AgentCreate`/`AgentProfile` 从 `./types` 导入。）

`src/shared/api/agentsApi.ts` import 行同步更新：

```typescript
import type { AgentCreate, AgentProfile, AgentUpdate } from './types';
```

- [ ] **Step 4: 跑测试确认通过 + 全量 electron test**

```bash
cd /home/fz/project/sage && npx vitest run electron/
```

Expected: 全绿（含 guard 测试）

- [ ] **Step 5: Commit**

```bash
git add electron/commands.ts src/shared/api/types.ts src/shared/api/agentsApi.ts electron/commands.test.ts
git commit -m "fix(electron): 补齐 agent_* IPC 命令 + agentsApi.createAgent

- 修复桌面 Agents 页 pre-existing 损坏（list_agents 等命令缺失抛
  UnknownIpcCommandError）
- 新增 create_agent POST 路由映射（US-4 角色可扩展的前端入口）"
```

---

### Task 7: llmStream 事件类型 + ChatConfig.orchestrationMode

**Files:**
- Modify: `src/shared/api/llmStream.ts`（AgentState union + AgentEvent 加 task_plan/task_status 字段；新增 TaskPlanEvent/TaskStatusEvent 窄接口）
- Modify: `src/shared/api/types.ts`（**双处定义的另一处** —— useChat 实际 import 的 AgentState/AgentEvent 来自 `shared/api/index.ts → types.ts`，必须同步扩展，否则 tsc 失败；加 TaskPlanItem/TaskStatusValue/TaskPlanEvent/TaskStatusEvent；ChatConfig 加 orchestrationMode）
- Modify: `src/shared/api/index.ts`（`export type { ... } from './types'` 显式列表加 4 个新类型名）
- Test: `src/shared/api/__tests__/llmStream.test.ts`

**Interfaces:**
- Consumes: 后端 NDJSON 事件（state `task_plan` / `task_status`）
- Produces:
  - `AgentState` 联合类型新增 `'task_plan' | 'task_status'`
  - `TaskPlanEvent` / `TaskStatusEvent` 接口
  - `ChatConfig.orchestrationMode?: 'auto' | 'force_multi' | 'force_single'`

- [ ] **Step 1: 写失败测试**

`src/shared/api/__tests__/llmStream.test.ts`：

```typescript
import { describe, expect, it } from 'vitest';
import { parseNDJSONStream } from '../llmStream';

describe('llmStream orchestration events', () => {
  it('parses task_plan events', async () => {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            '{"state":"task_plan","run_id":"orch-1","plan":[{"task_id":"t1","agent_id":"researcher","goal":"调研"},{"task_id":"t2","agent_id":"writer","goal":"写作"}]}\n',
          ),
        );
        controller.close();
      },
    });
    const events = await collect(parseNDJSONStream(stream));
    expect(events[0].state).toBe('task_plan');
    if (events[0].state === 'task_plan') {
      expect(events[0].run_id).toBe('orch-1');
      expect(events[0].plan).toHaveLength(2);
    }
  });

  it('parses task_status events with all statuses', async () => {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            '{"state":"task_status","run_id":"orch-1","task_id":"t1","status":"running","agent_id":"researcher","goal":"调研","error":null,"output_preview":null}\n',
          ),
        );
        controller.close();
      },
    });
    const events = await collect(parseNDJSONStream(stream));
    expect(events[0].state).toBe('task_status');
  });
});

async function collect(iter: AsyncIterable<unknown>): Promise<unknown[]> {
  const out: unknown[] = [];
  for await (const item of iter) out.push(item);
  return out;
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/llmStream.test.ts
```

Expected: FAIL —— TypeScript 编译错误（`AgentState` 无 `task_plan`/`task_status`）

- [ ] **Step 3: 写最小实现**

`src/shared/api/llmStream.ts`：

```typescript
export type AgentState =
  | 'idle'
  | 'thinking'
  | 'reasoning'
  | 'reasoning_delta'
  | 'acting'
  | 'observing'
  | 'content_delta'
  | 'done'
  | 'failed'
  // Multi-Agent Orchestration (2026-08-11)
  | 'task_plan'
  | 'task_status';

// 窄类型事件接口 —— useChat taskBoard 状态机的数据类型。
// AgentState / AgentEvent（宽松字段）见 types.ts —— 双处保持一致。
export interface TaskPlanItem {
  task_id: string;
  agent_id: string;
  goal: string;
}

export interface TaskPlanEvent {
  state: 'task_plan';
  run_id: string;
  plan: TaskPlanItem[];
}

export type TaskStatusValue = 'queued' | 'running' | 'done' | 'failed';

export interface TaskStatusEvent {
  state: 'task_status';
  run_id: string;
  task_id: string;
  status: TaskStatusValue;
  agent_id: string;
  goal: string;
  error: string | null;
  output_preview: string | null;
}

export interface AgentEvent {
  state: AgentState;
  iteration: number;
  content?: string;
  tool_call?: ToolCallRequestFE;
  tool_result?: ToolCallResultFE;
  error?: string;
  /** 阶段 4: 当前执行 agent 的 ID (供前端显示"当前处理 agent") */
  agent_id?: string;
  // Multi-Agent Orchestration (2026-08-11): 宽松字段（与 types.ts AgentEvent 同步）
  run_id?: string;
  plan?: TaskPlanItem[];
  task_id?: string;
  status?: TaskStatusValue;
  goal?: string;
  output_preview?: string | null;
}
```

> 注：`AgentEvent` 是**宽松字段 interface**（非联合判别）—— 直接加可选字段，onEvent 分支 `evt.run_id` / `evt.plan` / `evt.task_id` / `evt.status` 才有类型。

`src/shared/api/types.ts` —— **双处定义的另一处（useChat 经 `shared/api/index.ts` 实际 import 的类型源）**，必须同步：

1. `AgentState` union（L118-129）末尾追加：

```typescript
  | 'failed'
  // Multi-Agent Orchestration (2026-08-11)
  | 'task_plan'
  | 'task_status';
```

2. `AgentEvent`（L202-220）加与 llmStream.ts 相同的宽松字段（`run_id?` / `plan?: TaskPlanItem[]` / `task_id?` / `status?: TaskStatusValue` / `goal?` / `output_preview?: string | null`），并把 `TaskPlanItem` / `TaskPlanEvent` / `TaskStatusValue` / `TaskStatusEvent` 四个窄类型定义到 types.ts（与 llmStream.ts 内容一致）。

3. `ChatConfig`（L233-247）加：

```typescript
  /** Multi-Agent Orchestration: auto | force_multi | force_single（缺省 auto） */
  orchestrationMode?: 'auto' | 'force_multi' | 'force_single';
```

`src/shared/api/index.ts` —— `export type { ... } from './types'` 显式列表（L28-78）加：

```typescript
  TaskPlanEvent,
  TaskPlanItem,
  TaskStatusEvent,
  TaskStatusValue,
```

- [ ] **Step 4: 跑测试确认通过 + tsc**

```bash
cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/llmStream.test.ts && npx tsc --noEmit
```

Expected: 全绿 + 0 TS 错误

- [ ] **Step 5: Commit**

```bash
git add src/shared/api/llmStream.ts src/shared/api/types.ts src/shared/api/index.ts src/shared/api/__tests__/llmStream.test.ts
git commit -m "feat(frontend): llmStream task_plan/task_status 事件类型

- AgentState 联合新增 task_plan/task_status（types.ts + llmStream.ts 双处）
- AgentEvent 宽松字段 + TaskPlanEvent/TaskStatusEvent 窄接口 + index re-export
- ChatConfig.orchestrationMode（auto|force_multi|force_single）"
```

---

### Task 8: orchestration_mode 前端 plumbing（ChatApi → IPC → 后端）

**Files:**
- Modify: `src/shared/api/chatApi.ts`（`chatStream` 传 orchestrationMode）
- Modify: `src/features/send-message/useChat.ts`（`sendMessage` 签名 + invoke args 带 orchestrationMode）
- Test: `src/shared/api/__tests__/chatApi.orchestration.test.ts`

**Interfaces:**
- Consumes: `ChatConfig.orchestrationMode`（Task 7）、invoke.ts `camelToSnakeKeys`（`orchestrationMode` → `orchestration_mode` 自动映射）
- Produces: `/chat/stream` 请求体带 `orchestration_mode`

- [ ] **Step 1: 写失败测试**

`src/shared/api/__tests__/chatApi.orchestration.test.ts`：

```typescript
import { describe, expect, it, vi } from 'vitest';
import { chatStream } from '../chatApi';

vi.mock('../desktopInvoke', () => ({
  invoke: vi.fn(async () => 'stream-id'),
}));

import { invoke } from '../desktopInvoke';

describe('chatStream orchestration mode', () => {
  it('passes orchestrationMode through to invoke', async () => {
    const handlers = { onEvent: () => {}, onDone: () => {}, onError: () => {} };
    await chatStream('s1', 'hi', handlers, { orchestrationMode: 'force_multi' });
    const args = vi.mocked(invoke).mock.calls[0][1] as Record<string, unknown>;
    expect(args.orchestrationMode).toBe('force_multi');
  });

  it('passes null orchestrationMode when undefined', async () => {
    const handlers = { onEvent: () => {}, onDone: () => {}, onError: () => {} };
    await chatStream('s1', 'hi', handlers, {});
    const args = vi.mocked(invoke).mock.calls[0][1] as Record<string, unknown>;
    expect(args.orchestrationMode).toBeNull();
  });
});
```

> 注：mock 目标是 `./desktopInvoke`（chatApi 实际 import 源），不是 `./invoke`（别名导出）。第二个测试断言 `toBeNull()` —— 对齐 chatApi 现有 payload 的 `?? null` 模式（后端 `ChatRequest.orchestration_mode: str = "auto"` 对 null 走默认值，见 Task 4）。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/chatApi.orchestration.test.ts
```

Expected: FAIL —— chatStream 未透传 orchestrationMode

- [ ] **Step 3: 写最小实现**

`src/shared/api/chatApi.ts` —— `chatStream` 的 invoke 对象加（对齐现有 `?? null` 模式，紧跟在 `officeRefs` 行后）：

```typescript
      officeRefs: officeRefs ?? [],
      // Multi-Agent Orchestration: undefined → null,后端默认 auto
      orchestrationMode: config?.orchestrationMode ?? null,
```

> 注：`invoke.ts` 的 `camelToSnakeKeys` 会把 `orchestrationMode` 自动映射为后端 `orchestration_mode`（已确认 invoke.ts 对无显式 body 的命令自动转 snake_case）。

`src/features/send-message/useChat.ts` —— 三处最小改动（已核实现有代码：config 构造 L187-197 已传给 `chatStream` 第 4 参，无需动调用点）：

**(a) `sendMessage` 签名加第 4 参**（`ChatConfig['orchestrationMode']` 复用 Task 7 类型）：

```typescript
  const sendMessage = useCallback(
    async (
      content: string,
      sessionId?: string,
      officeRefs?: readonly ChatOfficeRef[],
      orchestrationMode?: ChatConfig['orchestrationMode'],
    ) => {
```

**(b) config 构造并入 `orchestrationMode`**（在 `provider` 行后加）：

```typescript
      const config: ChatConfig = {
        apiKey: chatEndpoint.apiKey,
        apiUrl: chatEndpoint.baseUrl,
        model: settings.modelSelections.chatModel.modelId ?? undefined,
        maxContext: settings.maxContext,
        temperature: settings.temperature,
        provider: inferProviderFromBaseUrl(chatEndpoint.baseUrl),
        // 由 /orchestrate /single 斜杠命令传入;普通消息 undefined → 后端 auto
        orchestrationMode,
      };
```

**(c) `useCallback` 依赖数组加 `orchestrationMode`**（防止闭包捕获旧值）：

```typescript
    [currentSessionId, isLoading, chatEndpoint, settings, addMessage, updateMessage, orchestrationMode],
```

> 注：`chatApi.chatStream(sid, content, handlers, config, officeRefs)` 调用点（L296）已传 `config`，config 内并入 `orchestrationMode` 后自动生效，无需改调用点签名。

- [ ] **Step 4: 跑测试确认通过 + tsc**

```bash
cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/chatApi.orchestration.test.ts && npx tsc --noEmit
```

Expected: 全绿 + 0 TS 错误

- [ ] **Step 5: Commit**

```bash
git add src/shared/api/chatApi.ts src/features/send-message/useChat.ts src/shared/api/__tests__/chatApi.orchestration.test.ts
git commit -m "feat(frontend): orchestration_mode 透传到 /chat/stream

- chatStream + useChat.sendMessage 透传 orchestrationMode（?? null 对齐现有模式）
- camelToSnakeKeys 自动映射 orchestration_mode，后端字段零适配
- sendMessage 加第 4 参 + config 构造并入 + 依赖数组更新"
```

---

### Task 9: useChat taskBoard（消费 task_plan/task_status）

**Files:**
- Modify: `src/features/send-message/useChat.ts`（事件循环加 task_plan/task_status 分支 + `taskBoard` state + 新消息清空 + 返回对象暴露 + `TaskBoard` 类型导出）
- Test: `src/features/send-message/__tests__/useChat.test.ts`（追加 `describe('useChat taskBoard')` 块，复用既有 seedActiveEndpoint + invokeMock + listenMock 基建）

**Interfaces:**
- Consumes: `TaskPlanEvent` / `TaskStatusEvent`（Task 7）
- Produces:
  - `TaskBoard` state：`{ runId: string; plan: TaskPlanItem[]; statuses: Record<string, TaskStatusEvent> } | null`
  - `taskBoard` + `setTaskBoard` 暴露给调用方（Chat.tsx → RightPanel → TaskTreeSection）
  - 事件处理：`task_plan` 初始化 board；`task_status` 合并（run_id 匹配才合并，否则忽略）；新消息开始时清空

- [ ] **Step 1: 写失败测试**

`src/features/send-message/__tests__/useChat.test.ts` —— 文件末尾追加 `describe('useChat taskBoard')` 块。复用既有基建：`seedActiveEndpoint()`（L51）+ `invokeMock`/`listenMock`（L20-27）+ `waitForSettingsLoaded()`（L40）。追加真实测试（mock `agent_chat_stream` 返回 stream id + `listen` 按序推 `task_plan → task_status → done` 事件）：

```typescript
describe('useChat taskBoard', () => {
  it('accumulates task_plan then task_status into board', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-1' });
    listenMock.mockImplementationOnce(
      async (
        _name: string,
        cb: (e: {
          payload: {
            state: string;
            iteration: number;
            content?: string;
            run_id?: string;
            plan?: Array<{ task_id: string; agent_id: string; goal: string }>;
            task_id?: string;
            status?: string;
          };
        }) => void,
      ) => {
        Promise.resolve().then(() => {
          cb({
            payload: {
              state: 'task_plan',
              iteration: 0,
              run_id: 'orch-1',
              plan: [
                { task_id: 't1', agent_id: 'researcher', goal: 'g1' },
                { task_id: 't2', agent_id: 'writer', goal: 'g2' },
              ],
            },
          });
          cb({ payload: { state: 'task_status', iteration: 0, run_id: 'orch-1', task_id: 't1', status: 'running' } });
          cb({ payload: { state: 'task_status', iteration: 0, run_id: 'orch-1', task_id: 't1', status: 'done' } });
          cb({ payload: { state: 'done', iteration: 0, content: 'done' } });
        });
        return vi.fn();
      },
    );

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();
    await act(async () => {
      await result.current.sendMessage('complex task');
    });

    await waitFor(() => {
      expect(result.current.taskBoard).not.toBeNull();
    });
    expect(result.current.taskBoard?.runId).toBe('orch-1');
    expect(result.current.taskBoard?.plan).toHaveLength(2);
    expect(result.current.taskBoard?.statuses.t1?.status).toBe('done');
  });

  it('ignores task_status with mismatched run_id', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValueOnce({ streamId: 'stream-2' });
    listenMock.mockImplementationOnce(
      async (
        _name: string,
        cb: (e: {
          payload: {
            state: string;
            iteration: number;
            content?: string;
            run_id?: string;
            plan?: Array<{ task_id: string; agent_id: string; goal: string }>;
            task_id?: string;
            status?: string;
          };
        }) => void,
      ) => {
        Promise.resolve().then(() => {
          cb({
            payload: {
              state: 'task_plan',
              iteration: 0,
              run_id: 'orch-1',
              plan: [{ task_id: 't1', agent_id: 'researcher', goal: 'g1' }],
            },
          });
          // 旧 run 的 task_status → 应被忽略（statuses 保持空）
          cb({ payload: { state: 'task_status', iteration: 0, run_id: 'orch-OLD', task_id: 't1', status: 'done' } });
          cb({ payload: { state: 'done', iteration: 0, content: 'done' } });
        });
        return vi.fn();
      },
    );

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();
    await act(async () => {
      await result.current.sendMessage('complex');
    });

    await waitFor(() => {
      expect(result.current.taskBoard).not.toBeNull();
    });
    expect(Object.keys(result.current.taskBoard?.statuses ?? {})).toHaveLength(0);
  });

  it('clears taskBoard on new message', async () => {
    seedActiveEndpoint();
    invokeMock.mockResolvedValue({ streamId: 'stream-3' });
    listenMock
      .mockImplementationOnce(
        async (
          _name: string,
          cb: (e: {
            payload: {
              state: string;
              iteration: number;
              content?: string;
              run_id?: string;
              plan?: Array<{ task_id: string; agent_id: string; goal: string }>;
            };
          }) => void,
        ) => {
          Promise.resolve().then(() => {
            cb({
              payload: {
                state: 'task_plan',
                iteration: 0,
                run_id: 'orch-1',
                plan: [{ task_id: 't1', agent_id: 'researcher', goal: 'g1' }],
              },
            });
            cb({ payload: { state: 'done', iteration: 0, content: 'r1' } });
          });
          return vi.fn();
        },
      )
      // 第二条消息不推 task_plan → taskBoard 保持 null
      .mockImplementationOnce(
        async (_name: string, cb: (e: { payload: { state: string; iteration: number; content?: string } }) => void) => {
          Promise.resolve().then(() => {
            cb({ payload: { state: 'done', iteration: 0, content: 'r2' } });
          });
          return vi.fn();
        },
      );

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.sendMessage('m1');
    });
    await waitFor(() => {
      expect(result.current.taskBoard).not.toBeNull();
    });

    // 第二条消息开始时 taskBoard 被清空（streamingToolCalls 清空同处）
    await act(async () => {
      await result.current.sendMessage('m2');
    });
    await waitFor(() => {
      expect(result.current.taskBoard).toBeNull();
    });
  });
});
```

> 注：mock 目标是对齐既有文件的 `vi.mock('../../../shared/api/desktopInvoke')`（L22）+ `vi.mock('../../../shared/api/desktopEvent')`（L25）。`cb` 收到的 `{ payload }` 经 chatStream listener 转发为 `onEvent(payload)`，故 useChat 里 `evt.state === 'task_plan'` 分支能读到 `evt.run_id` / `evt.plan`。新增 describe 块直接追加到既有文件末尾，天然复用顶层 mock 与 beforeEach 重置。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage && npx vitest run src/features/send-message/__tests__/useChat.test.ts
```

Expected: FAIL —— taskBoard 状态不存在（TS 错误）或事件未消费

- [ ] **Step 3: 写最小实现**

`src/features/send-message/useChat.ts` —— 模块顶层加 `TaskBoard` 类型导出（供 Chat.tsx / RightPanel / TaskTreeSection 消费）：

```typescript
/** Multi-Agent Orchestration: 编排任务板聚合状态（task_plan/task_status 消费结果） */
export interface TaskBoard {
  runId: string;
  plan: TaskPlanItem[];
  statuses: Record<string, TaskStatusEvent>;
}
```

> 注：`TaskPlanItem` / `TaskStatusEvent` 来自 `shared/api`（Task 7 已在 index.ts re-export）；useChat 已有 import，直接引用。

hook 内加 state：

```typescript
  const [taskBoard, setTaskBoard] = useState<TaskBoard | null>(null);
```

新消息清空处（`streamingToolCallsRef.current = []` 同处）：

```typescript
      // 新消息开始时清空编排任务板（与 streamingToolCalls 清空同处）
      setTaskBoard(null);
```

onEvent 循环里（与 `permission_request`/`ask_user_question` 同样"先消费、不进内容累加器"模式）：

```typescript
      if (evt.state === 'task_plan') {
        setTaskBoard({ runId: evt.run_id, plan: evt.plan, statuses: {} });
        return;
      }
      if (evt.state === 'task_status') {
        setTaskBoard((prev) =>
          prev && prev.runId === evt.run_id
            ? { ...prev, statuses: { ...prev.statuses, [evt.task_id]: evt } }
            : prev,
        );
        return;
      }
```

返回对象（`streamingToolCalls` 后加）：

```typescript
    /** P0: 当前流式工具调用列表 (供 ProgressSection 显示实时工具进度) */
    streamingToolCalls,
    /** Multi-Agent Orchestration: 编排任务板 (供 TaskTreeSection 渲染任务树) */
    taskBoard,
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

```bash
cd /home/fz/project/sage && npx vitest run src/features/send-message/ && npx tsc --noEmit
```

Expected: 全绿 + 0 TS 错误

- [ ] **Step 5: Commit**

```bash
git add src/features/send-message/useChat.ts src/features/send-message/__tests__/useChat.test.ts
git commit -m "feat(frontend): useChat taskBoard 消费 task_plan/task_status

- task_plan 初始化板；task_status 按 run_id 合并（旧 run 忽略）
- 新消息清空；简单任务无编排事件 → taskBoard 保持 null（零视觉噪音）"
```

---

### Task 10: TaskTreeSection + ProgressSection + RightPanel 渲染

**Files:**
- Create: `src/widgets/chat/progress/TaskTreeSection.tsx`
- Modify: `src/widgets/chat/progress/ProgressSection.tsx`（加 taskBoard prop + TaskTreeSection 渲染）
- Modify: `src/widgets/chat/RightPanel.tsx`（加 taskBoard prop）
- Modify: `src/pages/Chat.tsx`（把 useChat.taskBoard 传给 RightPanel）
- Test: `src/widgets/chat/__tests__/TaskTreeSection.test.tsx`

**Interfaces:**
- Consumes: `TaskBoard`（Task 9）、`TaskStatusEvent`/`TaskStatusValue`（Task 7）
- Produces:
  - `function TaskTreeSection({ board }: { board: TaskBoard })` —— 任务树：每子任务一行 = 状态图标（queued ○ / running ◐ / done ✓ / failed ✗）+ agent_id 徽标 + goal；done/failed 可展开看 output_preview/error；顶部汇总"子任务 x/y 完成"
  - `ProgressSection` 接收 `taskBoard: TaskBoard | null`，非空时渲染 TaskTreeSection，否则回落现有 tool-call 列表

- [ ] **Step 1: 写失败测试**

`src/widgets/chat/__tests__/TaskTreeSection.test.tsx`（colocated 测试目录；`TaskBoard` import 自 useChat，组件 import 自 `../progress/`）：

```tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TaskTreeSection } from '../progress/TaskTreeSection';
import type { TaskBoard } from '../../../features/send-message/useChat';

function makeBoard(overrides: Partial<TaskBoard> = {}): TaskBoard {
  return {
    runId: 'orch-1',
    plan: [
      { task_id: 't1', agent_id: 'researcher', goal: '搜集资料' },
      { task_id: 't2', agent_id: 'writer', goal: '整理学习资料' },
    ],
    statuses: {},
    ...overrides,
  };
}

describe('TaskTreeSection', () => {
  it('renders plan rows with agent badges and goals', () => {
    render(<TaskTreeSection board={makeBoard()} />);
    expect(screen.getByText('researcher')).toBeInTheDocument();
    expect(screen.getByText('writer')).toBeInTheDocument();
    expect(screen.getByText('搜集资料')).toBeInTheDocument();
    expect(screen.getByText('整理学习资料')).toBeInTheDocument();
  });

  it('shows completion summary', () => {
    const board = makeBoard({
      statuses: {
        t1: { state: 'task_status', run_id: 'orch-1', task_id: 't1', status: 'done', agent_id: 'researcher', goal: '搜集资料', error: null, output_preview: '完成' },
      },
    });
    render(<TaskTreeSection board={board} />);
    expect(screen.getByText(/子任务 1\/2 完成/)).toBeInTheDocument();
  });

  it('renders running spinner for in-flight task', () => {
    const board = makeBoard({
      statuses: {
        t1: { state: 'task_status', run_id: 'orch-1', task_id: 't1', status: 'running', agent_id: 'researcher', goal: '搜集资料', error: null, output_preview: null },
      },
    });
    render(<TaskTreeSection board={board} />);
    expect(screen.getByTitle('running')).toBeInTheDocument();
  });

  it('shows output_preview expandable for done task', () => {
    const board = makeBoard({
      statuses: {
        t1: { state: 'task_status', run_id: 'orch-1', task_id: 't1', status: 'done', agent_id: 'researcher', goal: '搜集资料', error: null, output_preview: '调研结论摘要' },
      },
    });
    render(<TaskTreeSection board={board} />);
    expect(screen.getByText('调研结论摘要')).toBeInTheDocument();
  });

  it('plan row without status falls back to queued', () => {
    render(<TaskTreeSection board={makeBoard()} />);
    expect(screen.getByTitle('queued')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/TaskTreeSection.test.tsx
```

Expected: FAIL —— 组件不存在

- [ ] **Step 3: 写最小实现**

`src/widgets/chat/progress/TaskTreeSection.tsx`：

```tsx
// src/widgets/chat/progress/TaskTreeSection.tsx
import type { TaskBoard } from '../../../features/send-message/useChat';
// TaskStatusValue 定义在 shared/api（Task 7 已 re-export），不从 useChat import
import type { TaskStatusValue } from '../../../shared/api';

const STATUS_ICON: Record<TaskStatusValue, string> = {
  queued: '○',
  running: '◐',
  done: '✓',
  failed: '✗',
};

const STATUS_TITLE: Record<TaskStatusValue, string> = {
  queued: 'queued',
  running: 'running',
  done: 'done',
  failed: 'failed',
};

interface TaskTreeSectionProps {
  board: TaskBoard;
}

export function TaskTreeSection({ board }: TaskTreeSectionProps) {
  const doneCount = board.plan.filter(
    (p) => board.statuses[p.task_id]?.status === 'done',
  ).length;
  const total = board.plan.length;

  return (
    <div className="space-y-1" data-testid="task-tree">
      <div className="text-xs text-text-secondary">子任务 {doneCount}/{total} 完成</div>
      {board.plan.map((item) => {
        const st = board.statuses[item.task_id];
        const status: TaskStatusValue = st?.status ?? 'queued';
        const preview = st?.output_preview ?? st?.error ?? null;
        return (
          <div key={item.task_id} className="flex flex-col gap-1 px-2 py-1 rounded text-xs bg-bg-hover">
            <div className="flex items-center gap-2">
              <span title={STATUS_TITLE[status]} className="w-4 text-center">{STATUS_ICON[status]}</span>
              <span className="px-1 rounded bg-primary/10 text-primary">{item.agent_id}</span>
              <span className="text-text-secondary flex-1">{item.goal}</span>
            </div>
            {preview && status !== 'queued' && (
              <details className="pl-6 text-muted">
                <summary>{status === 'failed' ? '错误详情' : '结果预览'}</summary>
                <pre className="mt-1 whitespace-pre-wrap">{preview}</pre>
              </details>
            )}
          </div>
        );
      })}
    </div>
  );
}
```

`src/widgets/chat/progress/ProgressSection.tsx` —— 现有 props（L4-9）加 `taskBoard`，渲染体 taskBoard 非空时顶替 tool-call 列表（spec §7.2：空 plan → 回落现有列表）：

```tsx
// 现有 ToolCall import 保留
import type { ToolCall } from '../../../shared/lib/store';
// 新增
import type { TaskBoard } from '../../../features/send-message/useChat';
import { TaskTreeSection } from './TaskTreeSection';

interface ProgressSectionProps {
  iteration: number;
  streamingState: string | null;
  toolCalls: ToolCall[];
  isLoading: boolean;
  taskBoard: TaskBoard | null;   // 新增：编排任务板（null = 无编排）
}

export function ProgressSection({
  iteration,
  streamingState,
  toolCalls,
  isLoading,
  taskBoard,
}: ProgressSectionProps) {
  // ...stateLabel 计算不变...
  return (
    <div className="p-3 space-y-2 text-sm">
      {/* stateLabel + iteration 行保留 */}
      {taskBoard ? (
        <TaskTreeSection board={taskBoard} />
      ) : (
        // 既有 toolCalls 列表（简单任务不变，零视觉噪音）
        toolCalls.length > 0 && (
          <div className="space-y-1">
            {toolCalls.map((tc, i) => (
              <div key={tc.id ?? `${tc.name}-${i}`} className="flex items-center gap-2 px-2 py-1 rounded text-xs bg-bg-hover">
                <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                <span className="text-text-secondary">{tc.name}</span>
              </div>
            ))}
          </div>
        )
      )}
    </div>
  );
}
```

`src/widgets/chat/RightPanel.tsx` —— props 加 `taskBoard`（import + 接口 + 解构 + 传参四处）：

```tsx
import type { TaskBoard } from '../../features/send-message/useChat';

interface RightPanelProps {
  open: boolean;
  onToggle: () => void;
  iteration: number;
  streamingState: string | null;
  toolCalls: ToolCall[];
  isLoading: boolean;
  sessionId: string | null;
  taskBoard: TaskBoard | null;   // 新增
}

export function RightPanel({
  open, iteration, streamingState, toolCalls, isLoading, sessionId, taskBoard,
}: RightPanelProps) {
  // ...
  <ProgressSection
    iteration={iteration}
    streamingState={streamingState}
    toolCalls={toolCalls}
    isLoading={isLoading}
    taskBoard={taskBoard}
  />
  // ...
}
```

`src/pages/Chat.tsx` —— useChat 解构（L27-40）加 `taskBoard`，RightPanel 调用（L284-293）加 prop：

```tsx
  const {
    messages,
    isLoading,
    error,
    clearError,
    sendMessage,
    interrupt,
    loadMessages,
    currentAgentId,
    streamingMessageId,
    iteration,
    streamingState,
    streamingToolCalls,
    taskBoard,   // Multi-Agent Orchestration: 编排任务板
  } = useChat();
  // ...
  <RightPanel
    open={rightPanelOpen}
    onToggle={() => setRightPanelOpen((v) => !v)}
    iteration={iteration}
    streamingState={streamingState}
    toolCalls={streamingToolCalls ?? []}
    isLoading={isLoading}
    sessionId={currentSessionId}
    taskBoard={taskBoard ?? null}
  />
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

```bash
cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ && npx tsc --noEmit
```

Expected: 全绿 + 0 TS 错误

- [ ] **Step 5: Commit**

```bash
git add src/widgets/chat/progress/TaskTreeSection.tsx src/widgets/chat/__tests__/TaskTreeSection.test.tsx src/widgets/chat/progress/ProgressSection.tsx src/widgets/chat/RightPanel.tsx src/pages/Chat.tsx
git commit -m "feat(frontend): TaskTreeSection 任务树渲染

- 状态图标 queued/running/done/failed + agent 徽标 + goal
- done/failed 可展开 output_preview/error；顶部汇总进度
- 无编排 → 回落既有 tool-call 列表（简单任务零视觉噪音）"
```

---

### Task 11: /orchestrate + /single 斜杠命令（手动 override）

**Files:**
- Modify: `src/widgets/chat/slashCommands.ts`（新增 2 个命令：`orchestrate` + `single`）
- Modify: `src/widgets/chat/ChatInput.tsx`（handleSlashSelect 特判 → onSend 带 orchestrationMode）
- Modify: `src/pages/Chat.tsx`（handleSendMessage options 加 orchestrationMode → 透传 sendMessage 第 4 参）
- Test: `src/widgets/chat/__tests__/slashCommands.test.ts`（追加 describe）+ `src/widgets/chat/__tests__/ChatInput.orchestration.test.tsx`（新建，对齐 ChatInput.learn.test.tsx 模式）

**Interfaces:**
- Consumes: `useChat.sendMessage(content, sessionId, officeRefs, orchestrationMode)`（Task 8）、`ChatConfig.orchestrationMode`
- Produces:
  - 斜杠命令 `orchestrate`（name 不含 `/`）→ `force_multi`；`single` → `force_single`；若消息纯命令无正文 → 给出使用提示

- [ ] **Step 1: 写失败测试**

`src/widgets/chat/__tests__/slashCommands.test.ts` —— 文件末尾追加 describe（对齐既有 `slashCommands` 导出名 + `c.name` 不含 `/` 的用法）：

```typescript
describe('orchestration slash commands', () => {
  it('registers orchestrate with prompt mode', () => {
    const cmd = slashCommands.find((c) => c.name === 'orchestrate');
    expect(cmd).toBeDefined();
    expect(cmd!.mode).toBe('prompt');
    expect(cmd!.description).toMatch(/编排|子任务|multi/i);
  });

  it('registers single with prompt mode', () => {
    const cmd = slashCommands.find((c) => c.name === 'single');
    expect(cmd).toBeDefined();
    expect(cmd!.mode).toBe('prompt');
    expect(cmd!.description).toMatch(/单 agent|单任务|关闭/i);
  });
});
```

`src/widgets/chat/__tests__/ChatInput.orchestration.test.tsx` —— 新建，对齐 `ChatInput.learn.test.tsx` 模式（mock useFileUpload + I18nProvider + 打开 slash 菜单选命令）：

```tsx
/**
 * Multi-Agent Orchestration: /orchestrate + /single slash command tests。
 * 两个命令是 tool-toggle 门的用户 override 逃生门:
 *  /orchestrate → force_multi（复杂消息必进编排）
 *  /single → force_single（简单消息强制走单 agent）
 * 链路: slash 菜单选中 → ChatInput.onSend(content, { orchestrationMode }) →
 *       Chat.tsx handleSendMessage 透传 → useChat.sendMessage 第 4 参 → chatStream。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';

vi.mock('../../../shared/lib/hooks/useFileUpload', () => ({
  useFileUpload: () => ({
    files: [],
    images: [],
    addFile: vi.fn(),
    addImage: vi.fn(),
    removeFile: vi.fn(),
    removeImage: vi.fn(),
    clearAll: vi.fn(),
    handleDrop: vi.fn(),
    handleDragOver: vi.fn(),
    isDragOver: false,
  }),
}));

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

function typeAndSelectSlash(command: string, onSend: ReturnType<typeof vi.fn>) {
  const input = screen.getByPlaceholderText(/输入消息/);
  fireEvent.change(input, { target: { value: command } });
  // SlashCommandMenu items fire onSelect via onMouseDown
  const menuItem = screen.getByRole('button', { name: new RegExp(command.replace('/', '\\/')) });
  fireEvent.mouseDown(menuItem);
  return input;
}

describe('ChatInput — /orchestrate override', () => {
  it('sends args with orchestrationMode force_multi when body present', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    const input = screen.getByPlaceholderText(/输入消息/);
    fireEvent.change(input, { target: { value: '/orchestrate 学习量化交易并整理指南' } });
    fireEvent.mouseDown(screen.getByRole('button', { name: /\/orchestrate/ }));

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenCalledWith('学习量化交易并整理指南', {
      orchestrationMode: 'force_multi',
    });
    expect((input as HTMLInputElement).value).toBe('');
  });

  it('shows usage hint when command has no body', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    fireEvent.change(screen.getByPlaceholderText(/输入消息/), { target: { value: '/orchestrate' } });
    fireEvent.mouseDown(screen.getByRole('button', { name: /\/orchestrate/ }));

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend.mock.calls[0][0]).toMatch(/用法/);
  });
});

describe('ChatInput — /single override', () => {
  it('sends args with orchestrationMode force_single when body present', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    fireEvent.change(screen.getByPlaceholderText(/输入消息/), { target: { value: '/single 今天天气' } });
    fireEvent.mouseDown(screen.getByRole('button', { name: /\/single/ }));

    expect(onSend).toHaveBeenCalledWith('今天天气', { orchestrationMode: 'force_single' });
  });

  it('shows usage hint when command has no body', () => {
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    fireEvent.change(screen.getByPlaceholderText(/输入消息/), { target: { value: '/single' } });
    fireEvent.mouseDown(screen.getByRole('button', { name: /\/single/ }));

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend.mock.calls[0][0]).toMatch(/用法/);
  });
});
```

> 注：`/orchestrate` / `/single` 在 slash 菜单里以 `name`（不含 `/`）注册，菜单项 label 由 SlashCommandMenu 拼 `/${name}` —— 测试用 `name: /\/orchestrate/` 匹配。`onSend` 第二参 options 传 `{ orchestrationMode }`（ChatInputProps onSend options 需加该字段，见 Step 3）。无正文纯命令 → `用法：/cmd 你的任务描述`。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage && npx vitest run src/widgets/chat/
```

Expected: FAIL —— 命令未注册 / ChatInput 未处理

- [ ] **Step 3: 写最小实现**

`src/widgets/chat/slashCommands.ts` —— import 加图标，`slashCommands` 数组末尾追加 2 个命令（对齐 `SlashCommand` 完整字段：name 不含 `/` + label + description + icon: LucideIcon + mode）：

```typescript
// lucide-react import 里追加（Network = 编排网络,UserRound = 单 agent）
import { ..., Network, UserRound } from 'lucide-react';
```

```typescript
  {
    name: 'orchestrate',
    label: '多 agent 编排',
    description: '强制多 agent 编排：拆解子任务并行执行',
    icon: Network,
    mode: 'prompt',
  },
  {
    name: 'single',
    label: '单 agent',
    description: '强制单 agent 回答，跳过编排',
    icon: UserRound,
    mode: 'prompt',
  },
```

`src/widgets/chat/ChatInput.tsx` —— 两处：

**(a) `ChatInputProps.onSend` options 加 `orchestrationMode`**（`officeRefs` 字段后）：

```typescript
      officeRefs?: readonly ChatOfficeRef[];
      /**
       * Multi-Agent Orchestration: /orchestrate → force_multi、/single → force_single。
       * 普通消息不传（undefined → 后端 auto）。
       */
      orchestrationMode?: 'auto' | 'force_multi' | 'force_single';
```

**(b) `handleSlashSelect` 特判，插在 prompt 分支（`const parts = value.split(/\s+/)`）之前** —— `cmd.name` 是 `'orchestrate'` / `'single'`（不含 `/`）：

```typescript
      // Multi-Agent Orchestration override（tool-toggle 门的手动逃生门）:
      // /orchestrate → force_multi、/single → force_single。正文随消息发送；
      // 纯命令无正文 → 用法提示（对齐 help/skill 命令的处理模式）。
      if (cmd.name === 'orchestrate' || cmd.name === 'single') {
        const parts = value.split(/\s+/);
        const args = parts.slice(1).join(' ');
        setValue('');
        if (!args) {
          onSend(`用法：/${cmd.name} 你的任务描述`);
          return;
        }
        onSend(args, {
          orchestrationMode: cmd.name === 'orchestrate' ? 'force_multi' : 'force_single',
        });
        return;
      }
```

`src/pages/Chat.tsx` —— `handleSendMessage` options 加 `orchestrationMode`，透传给 `sendMessage` 第 4 参：

```typescript
  const handleSendMessage = async (
    content: string,
    options?: {
      knowledgeRefs?: { id: string; title: string }[];
      attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
      images?: { name: string; size: number; type: string; dataUrl?: string }[];
      officeRefs?: readonly ChatOfficeRef[];
      orchestrationMode?: 'auto' | 'force_multi' | 'force_single';
    },
  ) => {
    clearError();
    const officeRefs = options?.officeRefs;
    const orchestrationMode = options?.orchestrationMode;
    if (!currentSessionId) {
      const sessionId = await createSession();
      await sendMessage(content, sessionId, officeRefs, orchestrationMode);
    } else {
      await sendMessage(content, undefined, officeRefs, orchestrationMode);
    }
  };
```

- [ ] **Step 4: 跑测试确认通过 + 全量前端回归**

```bash
cd /home/fz/project/sage && npx vitest run src/widgets/chat/ src/pages/__tests__/Chat* && npx tsc --noEmit
```

Expected: 全绿 + 0 TS 错误

- [ ] **Step 5: Commit**

```bash
git add src/widgets/chat/slashCommands.ts src/widgets/chat/ChatInput.tsx src/pages/Chat.tsx src/widgets/chat/__tests__/slashCommands.test.ts src/widgets/chat/__tests__/ChatInput.orchestration.test.tsx
git commit -m "feat(frontend): /orchestrate + /single 斜杠命令

- force_multi / force_single 手动 override —— 双失败模式的最终逃生门
- 纯命令无正文 → 用法提示；正文随消息发送（onSend options 透传）"
```

---

### 全局收尾（不属于单个 task）

- [ ] **全量后端测试**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/ -q
```

Expected: 全绿（含既有 3200+ 测试，编排不破坏简单对话 / planner / 权限硬化）

- [ ] **全量前端测试 + tsc**

```bash
cd /home/fz/project/sage && npx vitest run && npx tsc --noEmit
```

Expected: 全绿 + 0 TS 错误

- [ ] **ruff 检查**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/
```

Expected: 0 error

- [ ] **文档归档**

`docs/superpowers/specs/2026-08-11-multi-agent-orchestration-design.md` 状态改为 `已实施`（保留在 specs 目录作为"设计 vs 实际"基线）；新功能点并入 `docs/technical/` 对应章节（聊天链路多 agent 编排）。

- [ ] **Commit**

```bash
git add docs/superpowers/specs/2026-08-11-multi-agent-orchestration-design.md
git commit -m "docs(specs): multi-agent orchestration 标记已实施"
```

---

### 风险与已知决策（实现时注意）

| 决策/风险 | 处置 |
|---|---|
| `Planner.decompose_request` 会创建 Team+Task 记录（SQLite orchestration 表） | **接受**：用独立 `TaskRegistry()`/`TeamRegistry()` 实例，记录落库但不建 lane，不影响 lane 编排层（DRY + 最小侵入） |
| `_classify_orchestration_mode` 与 planner 都从 settings 构造 LLM client，request 带了 api_key 而 settings 未配 → planner 降级单任务 | 降级路径符合 spec：`len(plan.tasks) <= 1` → 视为没开编排，走单 agent。用户配好 settings 即可正常编排 |
| `dispatch_subagents` 权限：read_only 模式 deny / prompt 模式 ask | 默认 `workspace_write` 放行（不触发审批）。read_only 下 conductor 拿到"权限拒绝"文本自行降级；prompt 下会弹审批框（已知残余，接受） |
| 子 agent profile 白名单与 registry 工具名不一致（coder 种子 `file_read` vs registry `read_file`） | pre-existing，不在本计划修。**新 writer 种子必须用正确名** `read_file`/`write_file` |
| 前端 useChat/ProgressSection 现签名 | 每个前端 task 先读对应文件确认现签名，按"最小改动 + 透传"处理；计划代码标注了需对齐的既有点 |

> 维护规则来源：`feature-development.md`（项目根）。本计划归档后删除；功能点并入 `docs/technical/`。
