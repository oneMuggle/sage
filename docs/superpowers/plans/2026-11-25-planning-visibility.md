# 编排规划可见性（Planning Visibility）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让"用户发出请求 → 编排计划出现"之间的分类/澄清/侦察/调研/拆解过程在气泡内实时可见，并消除规划前哨小任务上的推理模型长思考浪费。

**Architecture:** 后端新增统一事件族 `plan_progress`（6 阶段 × 5 状态 × 8 载荷类型），由 `run_planning_stage()` 包装器驱动"开始/心跳/完成/跳过/失败"并复用既有 NDJSON producer 队列；前端新增纯 reducer + store 槽位 + `PlanningTimeline` 组件，内联在 assistant 气泡内。分三阶段交付：P1 可见性最小闭环（含修复 `orch_preflight` 字段名错配导致指示条从不渲染的根因），P2 深度调研与只读侦察的中间事件透出，P3 拆解阶段流式推理 + 前哨小任务默认关思考。

**Tech Stack:** Python 3.10（main）/ Python 3.8（release/win7）+ FastAPI + asyncio + pytest；React 18 + TypeScript + Zustand + Vitest；NDJSON 流（POST 建流 + GET 附着），非 SSE。

**Spec:** `docs/superpowers/specs/2026-11-25-planning-visibility-design.md`

## Global Constraints

- **双分支强制**：先在 `main` 完成并合并，再 `git cherry-pick` 到 `release/win7`；**禁止** `git merge release/win7` 到 main，**禁止**删除 `release/win7`。win7 分支不得改 `backend/requirements.txt`，main 分支不得改 `backend/requirements-py38.txt`。
- **py38 兼容（win7）**：新后端代码只用 `typing.Optional/Dict/List/Tuple/Callable`，禁止 `X | None`、`list[str]`、`asyncio.TaskGroup`。`asyncio.wait()` 只能接收 Task 集合（py3.10 传 coroutine 会 `TypeError`）。
- **环境**：后端测试/运行只用 `/home/fz/anaconda3/envs/sage-backend/bin/python`（win7：`/home/fz/anaconda3/envs/sage-backend-py38/bin/python`）；**禁止**系统 python/pip。前端用 `npx vitest run <path>` 与 `npm run typecheck`。
- **可见性事件永不阻塞规划**：任何 `emit` 失败一律吞掉并记 debug；`run_planning_stage` 的包装不得改变原有降级语义（原函数抛错仍抛错，由既有 try/except 兜底）。
- **事件形状固定**：所有进度事件为 `{"state": "plan_progress", "plan_progress": {"stage", "status", "kind", "text", "detail", "elapsed_ms"}}`。`detail` 恒为对象（缺省 `{}`）；`elapsed_ms` 仅在已知时存在且为 int。
- **文本上限**：任何进入 `text` 的思维/工具文本截断到 500 字符；单阶段前端最多保留 20 行、每行 240 字符。
- **不使用启发式判断模型能力**（见 `sage-vision-model-detection-fix` 教训）：关思考通过显式配置参数实现，失败时整体回退不带参数的普通客户端。
- **i18n 例外**：`PlanningTimeline` 使用中文直写字面量（与 `SubagentLivePanel` 同款），不新增 locale key。
- **安全**：日志/聊天中不得出现原始 `SAGE_LOCAL_AUTH_TOKEN`。
- **代码规范**：ruff 双引号（Q000）、中文注释避免 ERA001 误判；提交前 `npm run verify:pre-push`（lint + architecture-check）。
- **文档编号**：落盘时以目标分支 `ls docs/technical/ docs/user-manual/` 的实际最大编号 +1 为准（并发 PR 会抢占编号，memory 记录过多次顺延）。

## 根因（实现者必读）

1. **粗粒度指示条从不渲染**：`backend/orchestration/plan_preflight.py` 发的是 `{"state":"orch_preflight","phase":...}`（键名 `phase`），前端 `src/features/send-message/orchestrationEvents.ts:42` 却判 `evt.preflight_phase`，永远 `undefined`。
2. **调研过程全丢**：`scout_deep.research` 只在终态发 `research_complete`；`_run_scout_agent` 只取 `done` 内容，`thinking/acting/observing` 事件全部丢弃。
3. **拆解推理全丢**：`Planner._decompose_with_llm` 调用非流式 `complete(prompt)`，推理内容不可见。
4. **规划前哨被推理放大**：`_classify_orchestration_mode`、`classify_complexity`、`_clarify` 都用 `complete()` 且继承推理模型默认思考，几秒的判定变成几十秒。

## File Structure

**后端**
- Create `backend/orchestration/plan_progress.py` — 协议常量、异步 emitter、阶段包装器、跳过批量事件、流式节流器。
- Modify `backend/orchestration/plan_preflight.py` — 用 `run_planning_stage` 包裹复杂度分类/澄清/侦察/深度调研；simple 分支发 `skipped`；`_run_scout_agent` 增 `emit` 并透出中间事件（P2）。
- Modify `backend/api/legacy_routes.py` — 模式判定包裹 + 单智能体路径 `skipped`；拆解包裹；P3 传入流式进度回调。
- Modify `backend/orchestration/planner.py` — `decompose_request(..., progress=None)` 与 `_decompose_with_llm(..., progress=None)`；新增 `_stream_decomposition`（P3）。
- Modify `backend/orchestration/llm_factory.py` — `build_utility_llm_client()`、`_apply_utility_overrides()`、`complete_utility()`（P3）。
- Modify `backend/orchestration/complexity_classifier.py` — 两处客户端改用 utility 装配（P3）。
- Modify `backend/wiki/deep_research.py` — 新增可选 `progress` 回调与各步骤进度点（P2）。
- Modify `backend/orchestration/scout_deep.py` — `research(..., progress=None)` 透传（P2）。
- Tests: `backend/tests/orchestration/test_plan_progress.py`、`test_plan_preflight_progress.py`、`test_plan_progress_wiring.py`、`test_planner_streaming.py`、`test_llm_factory_utility.py`、`test_deep_research_progress.py`（无 `backend/tests/wiki/` 时统一放 orchestration 目录）。

**前端**
- Modify `src/shared/api/types/chatAndEventTypes.ts` — `'plan_progress'` 加入 `AgentState`；新增 `PlanProgressItem` 等类型与 `plan_progress?` 载荷；补 `phase?` 兼容字段；`preflight_phase` 联合加入 `'scout_deep'`。
- Modify `src/shared/lib/agentStateMapping.ts` — 两个 switch 增加 `plan_progress → null`。
- Create `src/features/send-message/planProgress.ts` — 纯 reducer + `isPlanningActive`。
- Modify `src/features/send-message/chatStreamStore.ts` — `planProgress` 槽位 + `setPlanProgress` + `startStream` 重置（并补 `preflightPhase` 重置）；`preflightPhase` 联合加 `'scout_deep'`。
- Modify `src/features/send-message/orchestrationEvents.ts` — `plan_progress` 分支；`orch_preflight` 读 `evt.preflight_phase ?? evt.phase`。
- Create `src/widgets/chat/PlanningTimeline.tsx` — 气泡内联阶段时间线。
- Modify `src/widgets/chat/Message.tsx` — 在 `ThinkingDisplay` 之后、`RetryBanner` 之前注入。
- Tests: `src/features/send-message/__tests__/planProgress.test.ts`、`chatStreamStore.planProgress.test.ts`、`orchestrationEvents.planProgress.test.ts`、`src/widgets/chat/__tests__/PlanningTimeline.test.tsx`、`Message.planningTimeline.test.tsx`。

**文档**
- Create `docs/technical/<next>-planning-visibility.md`、`docs/user-manual/<next>-planning-visibility.md`；更新两份 `README.md` 目录表。

## 交付边界

- **PR 1（P1）**：Task 1–8，可见性最小闭环（含根因修复）。独立可验收：规划时气泡内出现阶段条并有开始/完成/跳过。
- **PR 2（P2）**：Task 9–11，调研与侦察的中间过程实时可见。前端无需改动（`PlanningTimeline` 已按 `kind` 通用渲染）。
- **PR 3（P3）**：Task 12–16，拆解流式推理 + 前哨小任务默认关思考 + 文档/基线收尾 + win7 同步。
- 每个 PR 结束都执行一次完整验收（后端相关测试 + `npm run typecheck` + 相关 vitest + `npm run verify:pre-push`），通过后再开下一个。

---

## PR 1 · P1 可见性最小闭环

### Task 1: 后端进度协议模块

**Files:**
- Create: `backend/orchestration/plan_progress.py`
- Test: `backend/tests/orchestration/test_plan_progress.py`

**Interfaces:**
- Produces:
  - 常量：`PLAN_STAGE_MODE_CLASSIFY`、`PLAN_STAGE_COMPLEXITY_CLASSIFY`、`PLAN_STAGE_CLARIFY`、`PLAN_STAGE_SCOUT`、`PLAN_STAGE_SCOUT_DEEP`、`PLAN_STAGE_DECOMPOSE`；`STATUS_STARTED/PROGRESS/DONE/SKIPPED/FAILED`；`KIND_MESSAGE/THINKING/TOOL_CALL/TOOL_RESULT/REASONING/HEARTBEAT/SKIP_REASON/ERROR`。
  - `async def emit_plan_progress(emit, *, stage, status, kind=KIND_MESSAGE, text="", detail=None, elapsed_ms=None) -> None`
  - `async def emit_planning_skipped(emit, *, stages: List[str], reason: str) -> None`
  - `async def run_planning_stage(emit, *, stage, runner, heartbeat_interval_s=5.0, describe_result=None) -> Any`
  - `def make_stream_progress_emitter(emit, *, stage, flush_chars=200, flush_interval_s=0.6) -> Callable[[str, str], Awaitable[None]]`

- [ ] **Step 1: 写失败测试**

`backend/tests/orchestration/test_plan_progress.py`：

```python
import asyncio

from backend.orchestration.plan_progress import (
    KIND_HEARTBEAT,
    PLAN_STAGE_SCOUT,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PROGRESS,
    STATUS_SKIPPED,
    emit_plan_progress,
    emit_planning_skipped,
    make_stream_progress_emitter,
    run_planning_stage,
)


def test_emit_plan_progress_nests_payload():
    events = []

    async def emit(event):
        events.append(event)

    asyncio.run(
        emit_plan_progress(
            emit,
            stage=PLAN_STAGE_SCOUT,
            status=STATUS_PROGRESS,
            kind=KIND_HEARTBEAT,
            text="still working",
            elapsed_ms=1200,
        )
    )

    assert len(events) == 1
    assert events[0]["state"] == "plan_progress"
    payload = events[0]["plan_progress"]
    assert payload["stage"] == "scout"
    assert payload["status"] == "progress"
    assert payload["kind"] == "heartbeat"
    assert payload["text"] == "still working"
    assert payload["detail"] == {}
    assert payload["elapsed_ms"] == 1200


def test_emit_plan_progress_truncates_text_and_swallows_emit_error():
    events = []

    async def emit(event):
        events.append(event)

    asyncio.run(
        emit_plan_progress(
            emit, stage=PLAN_STAGE_SCOUT, status=STATUS_DONE, text="x" * 900
        )
    )
    assert len(events[0]["plan_progress"]["text"]) == 500

    async def broken_emit(event):
        raise RuntimeError("queue closed")

    # 不抛异常即为通过
    asyncio.run(
        emit_plan_progress(broken_emit, stage=PLAN_STAGE_SCOUT, status=STATUS_DONE)
    )


def test_emit_planning_skipped_marks_each_stage():
    events = []

    async def emit(event):
        events.append(event)

    asyncio.run(
        emit_planning_skipped(
            emit, stages=[PLAN_STAGE_SCOUT, "scout_deep"], reason="simple task"
        )
    )

    assert [e["plan_progress"]["stage"] for e in events] == ["scout", "scout_deep"]
    assert all(e["plan_progress"]["status"] == STATUS_SKIPPED for e in events)
    assert all(e["plan_progress"]["text"] == "simple task" for e in events)


def test_run_planning_stage_emits_started_and_done():
    events = []

    async def emit(event):
        events.append(event)

    async def runner():
        return "medium"

    result = asyncio.run(
        run_planning_stage(
            emit,
            stage="complexity_classify",
            runner=runner,
            describe_result=lambda value: str(value),
        )
    )

    assert result == "medium"
    statuses = [e["plan_progress"]["status"] for e in events]
    assert statuses[0] == "started"
    assert statuses[-1] == STATUS_DONE
    assert events[-1]["plan_progress"]["text"] == "medium"
    assert isinstance(events[-1]["plan_progress"]["elapsed_ms"], int)


def test_run_planning_stage_emits_heartbeat_then_done():
    events = []

    async def emit(event):
        events.append(event)

    async def runner():
        await asyncio.sleep(0.05)
        return "ok"

    asyncio.run(
        run_planning_stage(
            emit, stage="scout", runner=runner, heartbeat_interval_s=0.01
        )
    )

    kinds = [e["plan_progress"]["kind"] for e in events]
    assert KIND_HEARTBEAT in kinds
    assert events[-1]["plan_progress"]["status"] == STATUS_DONE


def test_run_planning_stage_emits_failed_and_reraises():
    events = []

    async def emit(event):
        events.append(event)

    async def runner():
        raise ValueError("boom")

    try:
        asyncio.run(run_planning_stage(emit, stage="scout", runner=runner))
    except ValueError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected ValueError")

    assert events[-1]["plan_progress"]["status"] == STATUS_FAILED
    assert events[-1]["plan_progress"]["text"] == "boom"


def test_run_planning_stage_cancels_inner_task_on_outer_cancel():
    cancelled = {"value": False}

    async def emit(event):
        return None

    async def runner():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled["value"] = True
            raise

    async def scenario():
        task = asyncio.ensure_future(
            run_planning_stage(
                emit, stage="scout", runner=runner, heartbeat_interval_s=0.01
            )
        )
        await asyncio.sleep(0.03)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert cancelled["value"] is True


def test_stream_progress_emitter_throttles_and_flushes():
    events = []

    async def emit(event):
        events.append(event)

    async def scenario():
        on_delta = make_stream_progress_emitter(
            emit, stage="decompose", flush_chars=10, flush_interval_s=10
        )
        await on_delta("reasoning", "12345")
        await on_delta("reasoning", "67890")
        await on_delta("message", "abc")

    asyncio.run(scenario())

    texts = [e["plan_progress"]["text"] for e in events]
    assert texts == ["1234567890", "abc"]
    assert events[0]["plan_progress"]["kind"] == "reasoning"
    assert events[-1]["plan_progress"]["kind"] == "message"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_plan_progress.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.orchestration.plan_progress'`

- [ ] **Step 3: 实现模块**

`backend/orchestration/plan_progress.py`：

```python
"""统一的编排规划进度事件协议（2026-11-25）。

供 plan_preflight / legacy_routes / planner 共用：把"分类→澄清→侦察→
调研→拆解"各阶段的开始、心跳、完成、跳过、失败统一成 ``plan_progress``
事件，前端 PlanningTimeline 据此渲染气泡内时间线。

纪律：本模块的所有 emit 都不得阻断或改变规划主流程 —— 推送失败只记
debug；包装器对 runner 的异常原样上抛，由调用方既有降级逻辑处理。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

PLAN_STAGE_MODE_CLASSIFY = "mode_classify"
PLAN_STAGE_COMPLEXITY_CLASSIFY = "complexity_classify"
PLAN_STAGE_CLARIFY = "clarify"
PLAN_STAGE_SCOUT = "scout"
PLAN_STAGE_SCOUT_DEEP = "scout_deep"
PLAN_STAGE_DECOMPOSE = "decompose"

STATUS_STARTED = "started"
STATUS_PROGRESS = "progress"
STATUS_DONE = "done"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

KIND_MESSAGE = "message"
KIND_THINKING = "thinking"
KIND_TOOL_CALL = "tool_call"
KIND_TOOL_RESULT = "tool_result"
KIND_REASONING = "reasoning"
KIND_HEARTBEAT = "heartbeat"
KIND_SKIP_REASON = "skip_reason"
KIND_ERROR = "error"

MAX_PROGRESS_TEXT = 500

Emit = Callable[[Dict[str, Any]], Awaitable[None]]


async def emit_plan_progress(
    emit: Optional[Emit],
    *,
    stage: str,
    status: str,
    kind: str = KIND_MESSAGE,
    text: str = "",
    detail: Optional[Dict[str, Any]] = None,
    elapsed_ms: Optional[int] = None,
) -> None:
    """推送单条 plan_progress；emit 缺失/失败一律静默。"""
    if emit is None:
        return
    payload: Dict[str, Any] = {
        "stage": stage,
        "status": status,
        "kind": kind,
        "text": text[:MAX_PROGRESS_TEXT],
        "detail": detail or {},
    }
    if elapsed_ms is not None:
        payload["elapsed_ms"] = int(elapsed_ms)
    try:
        await emit({"state": "plan_progress", "plan_progress": payload})
    except Exception:  # noqa: BLE001 — 进度事件绝不阻断规划
        logger.debug("plan_progress emit 失败: %s/%s", stage, status, exc_info=True)


async def emit_planning_skipped(
    emit: Optional[Emit],
    *,
    stages: List[str],
    reason: str,
) -> None:
    """批量标记若干阶段为 skipped（捷径路径：模板/计划模式/简单任务）。"""
    for stage in stages:
        await emit_plan_progress(
            emit,
            stage=stage,
            status=STATUS_SKIPPED,
            kind=KIND_SKIP_REASON,
            text=reason,
        )


async def run_planning_stage(
    emit: Optional[Emit],
    *,
    stage: str,
    runner: Callable[[], Awaitable[Any]],
    heartbeat_interval_s: float = 5.0,
    describe_result: Optional[Callable[[Any], str]] = None,
) -> Any:
    """包裹单个规划阶段：started → (heartbeat…) → done/failed。

    runner 的返回值原样返回；异常原样上抛（调用方保留既有降级语义）。
    外层取消时取消内层 task 并补发 failed 事件后继续上抛 CancelledError。

    注意：``asyncio.wait`` 只接受 Task/Future 集合 —— py3.10 传 coroutine
    会直接 TypeError（py3.8 只是弃用告警），因此必须 ``ensure_future``。
    """
    interval = max(0.05, heartbeat_interval_s)
    started_at = time.monotonic()

    def _elapsed_ms() -> int:
        return int((time.monotonic() - started_at) * 1000)

    await emit_plan_progress(emit, stage=stage, status=STATUS_STARTED, text="")
    task: "asyncio.Future[Any]" = asyncio.ensure_future(runner())
    try:
        while True:
            done, _pending = await asyncio.wait({task}, timeout=interval)
            if task in done:
                result = task.result()
                text = describe_result(result) if describe_result is not None else ""
                await emit_plan_progress(
                    emit,
                    stage=stage,
                    status=STATUS_DONE,
                    text=text or "",
                    elapsed_ms=_elapsed_ms(),
                )
                return result
            await emit_plan_progress(
                emit,
                stage=stage,
                status=STATUS_PROGRESS,
                kind=KIND_HEARTBEAT,
                elapsed_ms=_elapsed_ms(),
            )
    except asyncio.CancelledError:
        task.cancel()
        await emit_plan_progress(
            emit,
            stage=stage,
            status=STATUS_FAILED,
            kind=KIND_ERROR,
            text="已取消",
            elapsed_ms=_elapsed_ms(),
        )
        raise
    except Exception as exc:  # noqa: BLE001 — 原样上抛给调用方降级
        await emit_plan_progress(
            emit,
            stage=stage,
            status=STATUS_FAILED,
            kind=KIND_ERROR,
            text=str(exc),
            elapsed_ms=_elapsed_ms(),
        )
        raise


def make_stream_progress_emitter(
    emit: Optional[Emit],
    *,
    stage: str,
    flush_chars: int = 200,
    flush_interval_s: float = 0.6,
) -> Callable[[str, str], Awaitable[None]]:
    """把逐 delta 的流式回调聚合成节流的 plan_progress progress 事件。"""
    buffer: List[str] = []
    state: Dict[str, float] = {"last_flush": time.monotonic()}

    async def _on_delta(kind: str, text: str) -> None:
        if not text:
            return
        buffer.append(text)
        now = time.monotonic()
        if (
            sum(len(part) for part in buffer) < flush_chars
            and now - state["last_flush"] < flush_interval_s
        ):
            return
        chunk = "".join(buffer).strip()
        buffer.clear()
        state["last_flush"] = now
        if chunk:
            await emit_plan_progress(
                emit,
                stage=stage,
                status=STATUS_PROGRESS,
                kind=kind,
                text=chunk,
            )

    return _on_delta
```

- [ ] **Step 4: 跑测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_plan_progress.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/orchestration/plan_progress.py backend/tests/orchestration/test_plan_progress.py
git commit -m "feat(orchestration): 新增 plan_progress 事件协议与阶段包装器"
```

---

### Task 2: 接入前置阶段（复杂度/澄清/侦察/深度调研）

**Files:**
- Modify: `backend/orchestration/plan_preflight.py`
- Test: `backend/tests/orchestration/test_plan_preflight_progress.py`（新建）

**Interfaces:**
- Consumes: Task 1 的常量与 `emit_plan_progress` / `run_planning_stage` / `emit_planning_skipped`。
- Produces: `run_plan_preflight(message, emit, session_id)` 行为不变，但会额外推送 6 阶段中的 4 个阶段事件。

- [ ] **Step 1: 写失败测试**

`backend/tests/orchestration/test_plan_preflight_progress.py`：

```python
import asyncio

from backend.orchestration import plan_preflight
from backend.orchestration.complexity_classifier import ComplexityClassification


class _Settings:
    plan_preflight_enabled = True
    plan_scout_enabled = True
    max_scout_iterations = 3


def _collect():
    events = []

    async def emit(event):
        events.append(event)

    return events, emit


def _patch_common(monkeypatch):
    """屏蔽外部依赖，只保留被测的接线逻辑。

    ``plan_preflight`` 在函数体内惰性 import ``build_llm_client_from_settings``，
    所以必须 patch ``llm_factory`` 模块属性而非 ``plan_preflight`` 上的名字；
    ``classify_complexity`` 同理。
    """
    import backend.orchestration.complexity_classifier as classifier_module
    import backend.orchestration.llm_factory as llm_factory_module

    monkeypatch.setattr(
        plan_preflight, "preflight_master_enabled", lambda: True, raising=False
    )
    monkeypatch.setattr(
        plan_preflight, "load_orch_settings", lambda: _Settings(), raising=False
    )
    monkeypatch.setattr(
        llm_factory_module, "build_llm_client_from_settings", lambda: object()
    )
    return classifier_module


def test_simple_task_skips_scout_and_emits_stages(monkeypatch):
    classifier_module = _patch_common(monkeypatch)

    async def fake_classify(message, context=None):
        return ComplexityClassification(
            complexity="simple", research_needed=False, reasoning=""
        )

    async def fake_clarify(client, message, emit):
        return []

    monkeypatch.setattr(classifier_module, "classify_complexity", fake_classify)
    monkeypatch.setattr(plan_preflight, "_clarify", fake_clarify)

    events, emit = _collect()
    asyncio.run(plan_preflight.run_plan_preflight("改个颜色", emit=emit))

    stages = [
        e["plan_progress"]["stage"] for e in events if e["state"] == "plan_progress"
    ]
    assert "complexity_classify" in stages
    assert "clarify" in stages
    scout_event = next(
        e
        for e in events
        if e["state"] == "plan_progress"
        and e["plan_progress"]["stage"] == "scout"
    )
    assert scout_event["plan_progress"]["status"] == "skipped"


def test_medium_task_wraps_scout(monkeypatch):
    classifier_module = _patch_common(monkeypatch)

    async def fake_classify(message, context=None):
        return ComplexityClassification(
            complexity="medium", research_needed=True, reasoning=""
        )

    async def fake_clarify(client, message, emit):
        return []

    async def fake_scout(client, message, emit, clarifications, max_iterations=3):
        return "- fact"

    monkeypatch.setattr(classifier_module, "classify_complexity", fake_classify)
    monkeypatch.setattr(plan_preflight, "_clarify", fake_clarify)
    monkeypatch.setattr(plan_preflight, "_scout", fake_scout)

    events, emit = _collect()
    result = asyncio.run(plan_preflight.run_plan_preflight("重构模块", emit=emit))

    assert result is not None
    scout_done = [
        e
        for e in events
        if e["state"] == "plan_progress"
        and e["plan_progress"]["stage"] == "scout"
        and e["plan_progress"]["status"] == "done"
    ]
    assert scout_done, events
```

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_plan_preflight_progress.py -v`
Expected: FAIL — 无 `plan_progress` 事件。

- [ ] **Step 3: 接入 wrapper**

在 `backend/orchestration/plan_preflight.py` 的 import 区新增：

```python
from backend.orchestration.plan_progress import (
    PLAN_STAGE_CLARIFY,
    PLAN_STAGE_COMPLEXITY_CLASSIFY,
    PLAN_STAGE_SCOUT,
    PLAN_STAGE_SCOUT_DEEP,
    emit_planning_skipped,
    run_planning_stage,
)
```

将复杂度分类调用（当前 `classification = await classify_complexity(message)`）替换为：

```python
        classification = await run_planning_stage(
            emit,
            stage=PLAN_STAGE_COMPLEXITY_CLASSIFY,
            runner=lambda: classify_complexity(message),
            describe_result=lambda value: getattr(value, "complexity", ""),
        )
```

将澄清调用（当前 `clarifications = await _clarify(client, message, emit)`）替换为：

```python
        clarifications = await run_planning_stage(
            emit,
            stage=PLAN_STAGE_CLARIFY,
            runner=lambda: _clarify(client, message, emit),
            describe_result=lambda value: (
                "无需澄清" if not value else f"收集到 {len(value)} 条澄清"
            ),
        )
```

在 simple 分支（`if classification.complexity == "simple":`）的 `logger.info(...)` 之前插入：

```python
                await emit_planning_skipped(
                    emit,
                    stages=[PLAN_STAGE_SCOUT, PLAN_STAGE_SCOUT_DEEP],
                    reason="简单任务无需事实侦察",
                )
```

把 complex 分支的 `report = await asyncio.wait_for(scout_deep.research(...), timeout=...)` 整段替换为：

```python
                    report = await run_planning_stage(
                        emit,
                        stage=PLAN_STAGE_SCOUT_DEEP,
                        runner=lambda: asyncio.wait_for(
                            scout_deep.research(
                                topic=message,
                                project_path=_resolve_preflight_workspace(session_id),
                                settings=settings,
                            ),
                            timeout=scout_deep.SCOUT_DEEP_TIMEOUT_S,
                        ),
                        describe_result=lambda value: (
                            "调研无结果"
                            if value is None
                            else f"调研完成 confidence={getattr(value, 'confidence', 0)}"
                        ),
                    )
```

把 `_fallback_scout_lite` 内的 `facts = await _scout(...)` 与 medium 分支的 `facts = await _scout(...)` 分别替换为（注意两处缩进不同）：

```python
                    facts = await run_planning_stage(
                        emit,
                        stage=PLAN_STAGE_SCOUT,
                        runner=lambda: _scout(
                            client,
                            message,
                            emit,
                            clarifications,
                            max_iterations=settings.max_scout_iterations,
                        ),
                        describe_result=lambda value: (
                            "已收集事实" if value else "未收集到事实"
                        ),
                    )
```

```python
                facts = await run_planning_stage(
                    emit,
                    stage=PLAN_STAGE_SCOUT,
                    runner=lambda: _scout(
                        client,
                        message,
                        emit,
                        clarifications,
                        max_iterations=settings.max_scout_iterations,
                    ),
                    describe_result=lambda value: (
                        "已收集事实" if value else "未收集到事实"
                    ),
                )
```

> `_scout` 内部原有的 `orch_preflight` emit 与 `_emit` 保持不变（PlanApprovalBar 粗粒度指示条仍依赖它；Task 6 修复其字段名读取）。

- [ ] **Step 4: 跑测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_plan_preflight_progress.py backend/tests/orchestration/test_complexity_classifier.py backend/tests/orchestration/test_scout_deep.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/orchestration/plan_preflight.py backend/tests/orchestration/test_plan_preflight_progress.py
git commit -m "feat(preflight): 前置阶段发射 plan_progress 事件（复杂度/澄清/侦察/深调）"
```

---

### Task 3: 接入模式判定、单智能体跳过与拆解阶段

**Files:**
- Modify: `backend/api/legacy_routes.py:905-1000`
- Test: `backend/tests/orchestration/test_plan_progress_wiring.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 emitter/wrapper；`PLAN_STAGE_MODE_CLASSIFY`、`PLAN_STAGE_DECOMPOSE` 及各阶段常量。
- Produces: 生产者对 `mode_classify` 与 `decompose` 两阶段发事件；单智能体路径发 5 个阶段 `skipped`。

- [ ] **Step 1: 写失败测试**

`backend/tests/orchestration/test_plan_progress_wiring.py`：

```python
import asyncio

from backend.orchestration.plan_progress import PLAN_STAGE_DECOMPOSE, run_planning_stage


def test_decompose_stage_describes_task_count():
    events = []

    async def emit(event):
        events.append(event)

    class _Plan:
        tasks = [1, 2, 3]

    async def runner():
        return _Plan()

    result = asyncio.run(
        run_planning_stage(
            emit,
            stage=PLAN_STAGE_DECOMPOSE,
            runner=runner,
            describe_result=lambda plan: (
                f"拆解为 {len(getattr(plan, 'tasks', []) or [])} 个任务"
            ),
        )
    )

    assert len(result.tasks) == 3
    assert events[-1]["plan_progress"]["text"] == "拆解为 3 个任务"
```

- [ ] **Step 2: 跑测试**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_plan_progress_wiring.py -v`
Expected: PASS（依赖 Task 1 已完成；本测试固化拆解阶段的描述文案）

- [ ] **Step 3: 接线（legacy_routes.py）**

在编排块现有 import 之后新增：

```python
            from backend.orchestration.plan_progress import (
                PLAN_STAGE_CLARIFY,
                PLAN_STAGE_COMPLEXITY_CLASSIFY,
                PLAN_STAGE_DECOMPOSE,
                PLAN_STAGE_MODE_CLASSIFY,
                PLAN_STAGE_SCOUT,
                PLAN_STAGE_SCOUT_DEEP,
                emit_planning_skipped,
                run_planning_stage,
            )
```

将 `if data.plan_mode: ... elif data.plan_override: ... else: try: mode = await _classify...` 整块替换为：

```python
            if data.plan_mode:
                # PM1: 计划模式与编排互斥 —— 主对话内只读调研。
                mode = "single"
                await emit_planning_skipped(
                    entry.queue.put,
                    stages=[PLAN_STAGE_MODE_CLASSIFY],
                    reason="计划模式跳过编排判定",
                )
            elif data.plan_override:
                mode = "multi"
                await emit_planning_skipped(
                    entry.queue.put,
                    stages=[PLAN_STAGE_MODE_CLASSIFY],
                    reason="沿用既有计划，跳过编排判定",
                )
            else:
                try:
                    mode = await run_planning_stage(
                        entry.queue.put,
                        stage=PLAN_STAGE_MODE_CLASSIFY,
                        runner=lambda: _classify_orchestration_mode(
                            data.message,
                            data.orchestration_mode or "auto",
                            llm_client=build_llm_client_from_settings(),
                        ),
                        describe_result=lambda value: (
                            "多智能体编排" if value == "multi" else "单智能体执行"
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 — 编排判定失败必须降级 single
                    logger.warning("编排语义判定失败，降级 single: %s", exc)
                    mode = "single"
```

把模板分支的 `plan = await Planner(...).decompose_from_template(template_id, data.message)` 包裹为：

```python
                            plan = await run_planning_stage(
                                entry.queue.put,
                                stage=PLAN_STAGE_DECOMPOSE,
                                runner=lambda: Planner(
                                    task_registry=TaskRegistry(),
                                    team_registry=TeamRegistry(),
                                    llm_client=build_llm_client_from_settings(),
                                ).decompose_from_template(template_id, data.message),
                                describe_result=lambda value: (
                                    f"模板拆解为 {len(getattr(value, 'tasks', []) or [])} 个任务"
                                ),
                            )
```

把非模板分支的 `plan = await Planner(...).decompose_request(data.message, context=preflight_context)` 包裹为：

```python
                            plan = await run_planning_stage(
                                entry.queue.put,
                                stage=PLAN_STAGE_DECOMPOSE,
                                runner=lambda: Planner(
                                    task_registry=TaskRegistry(),
                                    team_registry=TeamRegistry(),
                                    llm_client=build_llm_client_from_settings(),
                                ).decompose_request(
                                    data.message, context=preflight_context
                                ),
                                describe_result=lambda value: (
                                    f"拆解为 {len(getattr(value, 'tasks', []) or [])} 个任务"
                                ),
                            )
```

在 `if mode == "multi": ...` 整块**之后**新增 `else` 分支（与 `if mode == "multi":` 平级，不要把 skipped 写进 multi 块内部）：

```python
            else:
                await emit_planning_skipped(
                    entry.queue.put,
                    stages=[
                        PLAN_STAGE_COMPLEXITY_CLASSIFY,
                        PLAN_STAGE_CLARIFY,
                        PLAN_STAGE_SCOUT,
                        PLAN_STAGE_SCOUT_DEEP,
                        PLAN_STAGE_DECOMPOSE,
                    ],
                    reason="单智能体执行，无需编排拆解",
                )
```

- [ ] **Step 4: 跑测试与导入冒烟**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_plan_progress_wiring.py backend/tests/orchestration/test_plan_progress.py -v
/home/fz/anaconda3/envs/sage-backend/bin/python -c "import backend.api.legacy_routes"
```
Expected: PASS；import 无异常（验证缩进/名称正确）。

- [ ] **Step 5: 提交**

```bash
git add backend/api/legacy_routes.py backend/tests/orchestration/test_plan_progress_wiring.py
git commit -m "feat(chat): 模式判定与拆解阶段接入 plan_progress"
```

---

### Task 4: 前端类型与 state 映射

**Files:**
- Modify: `src/shared/api/types/chatAndEventTypes.ts`（`AgentState` 约 :352-438；载荷约 :780-825）
- Modify: `src/shared/lib/agentStateMapping.ts:66-120, :130-186`
- Test: `src/features/send-message/__tests__/planProgress.test.ts`（本任务先只建一个类型冒烟用例；reducer 用例在 Task 5 扩充）

**Interfaces:**
- Produces:
  - `type PlanProgressStage = 'mode_classify' | 'complexity_classify' | 'clarify' | 'scout' | 'scout_deep' | 'decompose'`
  - `type PlanProgressStatus = 'started' | 'progress' | 'done' | 'skipped' | 'failed'`
  - `type PlanProgressKind = 'message' | 'thinking' | 'tool_call' | 'tool_result' | 'reasoning' | 'heartbeat' | 'skip_reason' | 'error'`
  - `interface PlanProgressItem { stage; status; kind; text; detail?: Record<string, unknown>; elapsed_ms?: number }`
  - `AgentEvent.plan_progress?: PlanProgressItem`；`AgentEvent.phase?: 'clarify'|'scout'|'complexity_classify'|'execution_mode_classify'|'scout_deep'`；`preflight_phase` 联合含 `'scout_deep'`

- [ ] **Step 1: 加类型（这一步会故意打破 typecheck）**

在 `chatAndEventTypes.ts` 的 `AgentState` 联合内加入 `| 'plan_progress'`（紧邻 `'orch_preflight'`）。

在 `AgentEvent` 载荷区新增：

```ts
export type PlanProgressStage =
  | 'mode_classify'
  | 'complexity_classify'
  | 'clarify'
  | 'scout'
  | 'scout_deep'
  | 'decompose';

export type PlanProgressStatus = 'started' | 'progress' | 'done' | 'skipped' | 'failed';

export type PlanProgressKind =
  | 'message'
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'reasoning'
  | 'heartbeat'
  | 'skip_reason'
  | 'error';

export interface PlanProgressItem {
  stage: PlanProgressStage;
  status: PlanProgressStatus;
  kind: PlanProgressKind;
  text: string;
  detail?: Record<string, unknown>;
  elapsed_ms?: number;
}
```

在 `AgentEvent` 接口内（`preflight_phase` 附近）新增：

```ts
  /** 2026-11-25: 统一规划进度事件（state === 'plan_progress'）。 */
  plan_progress?: PlanProgressItem;
  /** 后端 orch_preflight 事件历史的实际字段名（与 preflight_phase 并存，读取时优先 preflight_phase）。 */
  phase?:
    | 'clarify'
    | 'scout'
    | 'complexity_classify'
    | 'execution_mode_classify'
    | 'scout_deep';
```

并把 `preflight_phase?` 的联合改为：

```ts
  preflight_phase?:
    | 'clarify'
    | 'scout'
    | 'complexity_classify'
    | 'execution_mode_classify'
    | 'scout_deep';
```

- [ ] **Step 2: 跑 typecheck 确认失败**

Run: `npm run typecheck`
Expected: FAIL — `agentStateMapping.ts` 两个 switch 的 `default: return assertNever(state)` 报 `'plan_progress'` 未处理。

- [ ] **Step 3: 补映射并写类型冒烟用例**

在 `agentStateMapping.ts` 第一个 switch（`agentStateToText`）的 `return null` 组内（`case 'orch_preflight':` 之后）加：

```ts
    case 'plan_progress':
      // 2026-11-25: 规划进度由气泡内 PlanningTimeline 渲染，不进占位文本
      return null;
```

在第二个 switch（`agentStateToPhase`）的 `return null` 组内（`case 'orch_preflight':` 之后）加：

```ts
    case 'plan_progress':
      // 2026-11-25: 规划进度由气泡内 PlanningTimeline 渲染，无独立阶段指示
      return null;
```

创建 `src/features/send-message/__tests__/planProgress.test.ts`（此时仅一个冒烟用例，Task 5 会补全）：

```ts
import { describe, expect, it } from 'vitest';

import { agentStateToPhase, agentStateToText } from '../../../shared/lib/agentStateMapping';

describe('plan_progress state 映射', () => {
  it('不进占位文本、不产生阶段指示', () => {
    expect(agentStateToText('plan_progress')).toBeNull();
    expect(agentStateToPhase('plan_progress')).toBeNull();
  });
});
```

- [ ] **Step 4: 跑 typecheck 与用例**

Run: `npm run typecheck && npx vitest run src/features/send-message/__tests__/planProgress.test.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/shared/api/types/chatAndEventTypes.ts src/shared/lib/agentStateMapping.ts src/features/send-message/__tests__/planProgress.test.ts
git commit -m "feat(types): 新增 plan_progress 事件类型与 state 映射"
```

---

### Task 5: 规划进度 reducer

**Files:**
- Create: `src/features/send-message/planProgress.ts`
- Test: `src/features/send-message/__tests__/planProgress.test.ts`（在 Task 4 基础上追加）

**Interfaces:**
- Consumes: Task 4 的 `PlanProgressItem`、`PlanProgressStage`。
- Produces:
  - `interface PlanStageLine { kind; text }`、`interface PlanStageState { stage; status; lines: PlanStageLine[]; elapsedMs? }`
  - `reducePlanProgress(prev: PlanStageState[] | null, item: PlanProgressItem): PlanStageState[]`
  - `isPlanningActive(stages: PlanStageState[] | null): boolean`

- [ ] **Step 1: 写失败测试（追加到现有测试文件）**

把 `src/features/send-message/__tests__/planProgress.test.ts` 扩充为：

```ts
import { describe, expect, it } from 'vitest';

import { agentStateToPhase, agentStateToText } from '../../../shared/lib/agentStateMapping';
import {
  isPlanningActive,
  reducePlanProgress,
  type PlanStageState,
} from '../planProgress';
import type { PlanProgressItem } from '../../../shared/api/types/chatAndEventTypes';

function item(over: Partial<PlanProgressItem> = {}): PlanProgressItem {
  return {
    stage: 'scout',
    status: 'progress',
    kind: 'message',
    text: '',
    ...over,
  };
}

describe('plan_progress state 映射', () => {
  it('不进占位文本、不产生阶段指示', () => {
    expect(agentStateToText('plan_progress')).toBeNull();
    expect(agentStateToPhase('plan_progress')).toBeNull();
  });
});

describe('reducePlanProgress', () => {
  it('首次事件创建阶段并置为 started', () => {
    const out = reducePlanProgress(null, item({ status: 'started' }));
    expect(out).toHaveLength(1);
    expect(out[0].stage).toBe('scout');
    expect(out[0].status).toBe('started');
  });

  it('追加非心跳文本行', () => {
    const first = reducePlanProgress(null, item({ kind: 'thinking', text: 'a' }));
    const second = reducePlanProgress(first, item({ kind: 'tool_call', text: 'b' }));
    expect(second[0].lines.map((l) => l.text)).toEqual(['a', 'b']);
  });

  it('心跳不追加文本行但更新耗时', () => {
    const first = reducePlanProgress(null, item({ kind: 'message', text: 'a' }));
    const second = reducePlanProgress(
      first,
      item({ kind: 'heartbeat', status: 'progress', elapsed_ms: 5000 }),
    );
    expect(second[0].lines.map((l) => l.text)).toEqual(['a']);
    expect(second[0].elapsedMs).toBe(5000);
  });

  it('重复文本不重复追加', () => {
    const first = reducePlanProgress(null, item({ kind: 'thinking', text: 'same' }));
    const second = reducePlanProgress(first, item({ kind: 'thinking', text: 'same' }));
    expect(second[0].lines).toHaveLength(1);
  });

  it('按阶段顺序排序', () => {
    let stages: PlanStageState[] | null = null;
    stages = reducePlanProgress(stages, item({ stage: 'decompose', status: 'started' }));
    stages = reducePlanProgress(
      stages,
      item({ stage: 'complexity_classify', status: 'started' }),
    );
    expect(stages.map((s) => s.stage)).toEqual(['complexity_classify', 'decompose']);
  });

  it('终态更新 status', () => {
    const first = reducePlanProgress(null, item({ status: 'started' }));
    const done = reducePlanProgress(first, item({ status: 'done', text: 'ok' }));
    expect(done[0].status).toBe('done');
    expect(done[0].lines.at(-1)?.text).toBe('ok');
  });

  it('单阶段最多保留 20 行', () => {
    let stages: PlanStageState[] | null = null;
    for (let i = 0; i < 30; i += 1) {
      stages = reducePlanProgress(stages, item({ kind: 'message', text: `line-${i}` }));
    }
    expect(stages?.[0].lines).toHaveLength(20);
    expect(stages?.[0].lines.at(-1)?.text).toBe('line-29');
  });

  it('超长文本截断到 240 字符', () => {
    const out = reducePlanProgress(null, item({ kind: 'message', text: 'x'.repeat(400) }));
    expect(out[0].lines[0].text).toHaveLength(241); // 240 + 省略号
  });
});

describe('isPlanningActive', () => {
  it('有 started/progress 时为真', () => {
    expect(isPlanningActive([{ stage: 'scout', status: 'started', lines: [] }])).toBe(true);
    expect(isPlanningActive([{ stage: 'scout', status: 'done', lines: [] }])).toBe(false);
    expect(isPlanningActive(null)).toBe(false);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/features/send-message/__tests__/planProgress.test.ts`
Expected: FAIL — `../planProgress` 模块不存在。

- [ ] **Step 3: 实现 reducer**

创建 `src/features/send-message/planProgress.ts`：

```ts
// src/features/send-message/planProgress.ts
import type {
  PlanProgressItem,
  PlanProgressStage,
} from '../../shared/api/types/chatAndEventTypes';

export interface PlanStageLine {
  kind: PlanProgressItem['kind'];
  text: string;
}

export interface PlanStageState {
  stage: PlanProgressStage;
  status: PlanProgressItem['status'];
  lines: PlanStageLine[];
  elapsedMs?: number;
}

export const PLAN_STAGE_ORDER: PlanProgressStage[] = [
  'mode_classify',
  'complexity_classify',
  'clarify',
  'scout',
  'scout_deep',
  'decompose',
];

const MAX_LINES_PER_STAGE = 20;
const MAX_TEXT_LENGTH = 240;

function trimText(text: string): string {
  const trimmed = text.trim();
  return trimmed.length > MAX_TEXT_LENGTH
    ? `${trimmed.slice(0, MAX_TEXT_LENGTH)}…`
    : trimmed;
}

export function reducePlanProgress(
  prev: PlanStageState[] | null,
  item: PlanProgressItem,
): PlanStageState[] {
  const current = prev ?? [];
  const index = current.findIndex((stage) => stage.stage === item.stage);
  const base: PlanStageState =
    index >= 0
      ? current[index]
      : { stage: item.stage, status: 'started', lines: [] };

  const text = item.text ? trimText(item.text) : '';
  const lastLine = base.lines[base.lines.length - 1];
  const shouldAppend =
    text.length > 0 && item.kind !== 'heartbeat' && lastLine?.text !== text;

  const lines = shouldAppend
    ? [...base.lines, { kind: item.kind, text }].slice(-MAX_LINES_PER_STAGE)
    : base.lines;

  const next: PlanStageState = {
    stage: base.stage,
    status: item.status,
    lines,
    elapsedMs: item.elapsed_ms ?? base.elapsedMs,
  };

  const merged =
    index >= 0
      ? current.map((stage, i) => (i === index ? next : stage))
      : [...current, next];

  return [...merged].sort(
    (a, b) => PLAN_STAGE_ORDER.indexOf(a.stage) - PLAN_STAGE_ORDER.indexOf(b.stage),
  );
}

export function isPlanningActive(stages: PlanStageState[] | null): boolean {
  if (!stages || stages.length === 0) return false;
  return stages.some((stage) => stage.status === 'started' || stage.status === 'progress');
}
```

- [ ] **Step 4: 跑测试与类型检查**

Run: `npx vitest run src/features/send-message/__tests__/planProgress.test.ts && npm run typecheck`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/features/send-message/planProgress.ts src/features/send-message/__tests__/planProgress.test.ts
git commit -m "feat(chat): 新增 plan_progress 纯 reducer"
```

---

### Task 6: store 槽位（含重置修复）

**Files:**
- Modify: `src/features/send-message/chatStreamStore.ts`（槽位 :261；`EMPTY_SLOTS` :314-329；setter 声明 :390-412；`startStream` :500-533；setter 实现 :679-680）
- Test: `src/features/send-message/__tests__/chatStreamStore.planProgress.test.ts`

**Interfaces:**
- Consumes: Task 5 的 `PlanStageState`、`reducePlanProgress`。
- Produces: `SessionStreamSlots.planProgress: PlanStageState[] | null`；`setPlanProgress(sessionId, item)`；`preflightPhase` 联合含 `'scout_deep'`。

- [ ] **Step 1: 写失败测试**

`src/features/send-message/__tests__/chatStreamStore.planProgress.test.ts`：

```ts
import { beforeEach, describe, expect, it } from 'vitest';

import { selectSessionSlots, useChatStreamStore } from '../chatStreamStore';

describe('chatStreamStore · planProgress', () => {
  beforeEach(() => {
    useChatStreamStore.setState({ sessions: {} });
  });

  it('setPlanProgress 累积同一阶段', () => {
    const store = useChatStreamStore.getState();
    store.setPlanProgress('s1', {
      stage: 'scout',
      status: 'progress',
      kind: 'thinking',
      text: 'a',
    });
    store.setPlanProgress('s1', {
      stage: 'scout',
      status: 'done',
      kind: 'message',
      text: 'b',
    });
    const slots = selectSessionSlots(useChatStreamStore.getState(), 's1');
    expect(slots.planProgress).toHaveLength(1);
    expect(slots.planProgress?.[0].status).toBe('done');
    expect(slots.planProgress?.[0].lines.map((l) => l.text)).toEqual(['a', 'b']);
  });

  it('startStream 重置 planProgress 与 preflightPhase', () => {
    const store = useChatStreamStore.getState();
    store.setPlanProgress('s1', {
      stage: 'scout',
      status: 'started',
      kind: 'message',
      text: '',
    });
    store.setPreflightPhase('s1', 'scout');
    store.startStream('s1', 'm1');
    const slots = selectSessionSlots(useChatStreamStore.getState(), 's1');
    expect(slots.planProgress).toBeNull();
    expect(slots.preflightPhase).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/features/send-message/__tests__/chatStreamStore.planProgress.test.ts`
Expected: FAIL — `setPlanProgress` 不存在；`preflightPhase` 未重置。

- [ ] **Step 3: 加槽位、setter、重置**

在 `chatStreamStore.ts` import 区加入：

```ts
import type { PlanProgressItem } from '../../shared/api/types/chatAndEventTypes';
import { reducePlanProgress, type PlanStageState } from './planProgress';
```

把 `SessionStreamSlots.preflightPhase` 的联合改为：

```ts
  preflightPhase:
    | 'clarify'
    | 'scout'
    | 'complexity_classify'
    | 'execution_mode_classify'
    | 'scout_deep'
    | null;
```

紧接其后新增：

```ts
  /**
   * 2026-11-25: 统一规划进度时间线。每次 plan_progress 事件由 reducer
   * 合并入对应阶段；startStream 重置。null = 本轮尚无进度事件。
   */
  planProgress: PlanStageState[] | null;
```

在 `EMPTY_SLOTS` 中 `preflightPhase: null,` 之后加：

```ts
  planProgress: null,
```

在 `ChatStreamStoreState` 的 setter 声明区（`setPreflightPhase` 附近）新增：

```ts
  /** 2026-11-25: 合并一条 plan_progress 到会话的规划时间线。 */
  setPlanProgress: (sessionId: string, item: PlanProgressItem) => void;
```

在 `setPreflightPhase` 实现（约 :679）之后新增：

```ts
  setPlanProgress: (sessionId, item) =>
    set((prev) => {
      const slots = selectSessionSlots(prev, sessionId);
      return {
        sessions: writeSlots(prev.sessions, sessionId, {
          planProgress: reducePlanProgress(slots.planProgress, item),
        }),
      };
    }),
```

在 `startStream` 的重置 draft 中 `budgetCheckpoint: null,` 之后补：

```ts
        // 2026-11-25: 新一轮清掉上一轮的规划进度与前置阶段指示 —— 二者都是
        // 本轮规划过程的瞬态；preflightPhase 此前遗漏重置，会跨轮残留。
        planProgress: null,
        preflightPhase: null,
```

- [ ] **Step 4: 跑测试与类型检查**

Run:
```bash
npx vitest run src/features/send-message/__tests__/chatStreamStore.planProgress.test.ts src/features/send-message/__tests__/planProgress.test.ts
npm run typecheck
```
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/features/send-message/chatStreamStore.ts src/features/send-message/__tests__/chatStreamStore.planProgress.test.ts
git commit -m "feat(chat): store 新增 planProgress 槽位并重置 preflightPhase"
```

---

### Task 7: 事件分发（新分支 + 修复 preflight 字段名）

**Files:**
- Modify: `src/features/send-message/orchestrationEvents.ts:28-70`
- Test: `src/features/send-message/__tests__/orchestrationEvents.planProgress.test.ts`

**Interfaces:**
- Consumes: Task 6 的 `setPlanProgress` / `setPreflightPhase`。
- Produces: `applyOrchestrationEventToBoard` 对 `plan_progress` 返回 `true`；`orch_preflight` 在 `phase` 字段下也能生效。

- [ ] **Step 1: 写失败测试**

`src/features/send-message/__tests__/orchestrationEvents.planProgress.test.ts`：

```ts
import { beforeEach, describe, expect, it } from 'vitest';

import { applyOrchestrationEventToBoard } from '../orchestrationEvents';
import { useChatStreamStore } from '../chatStreamStore';

describe('applyOrchestrationEventToBoard · plan_progress', () => {
  beforeEach(() => {
    useChatStreamStore.setState({ sessions: {} });
  });

  it('plan_progress 写入槽位并消费事件', () => {
    const handled = applyOrchestrationEventToBoard(
      {
        state: 'plan_progress',
        iteration: 0,
        plan_progress: {
          stage: 'mode_classify',
          status: 'started',
          kind: 'message',
          text: '',
        },
      },
      's1',
    );
    expect(handled).toBe(true);
    const slots = useChatStreamStore.getState().sessions['s1'];
    expect(slots?.planProgress?.[0].stage).toBe('mode_classify');
  });

  it('orch_preflight 兼容后端 phase 字段', () => {
    const handled = applyOrchestrationEventToBoard(
      { state: 'orch_preflight', iteration: 0, phase: 'scout_deep' },
      's1',
    );
    expect(handled).toBe(true);
    expect(useChatStreamStore.getState().sessions['s1']?.preflightPhase).toBe('scout_deep');
  });

  it('缺载荷时不消费事件', () => {
    const handled = applyOrchestrationEventToBoard(
      { state: 'plan_progress', iteration: 0 },
      's1',
    );
    expect(handled).toBe(false);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/features/send-message/__tests__/orchestrationEvents.planProgress.test.ts`
Expected: FAIL — 事件未处理 / `phase` 不识别。

- [ ] **Step 3: 加分发分支并修复字段读取**

在 `orchestrationEvents.ts` 的 `applyOrchestrationEventToBoard` 内（artifact 分支之后、orch_preflight 之前）插入：

```ts
  // 2026-11-25: 统一规划进度 → 气泡内 PlanningTimeline 槽位。
  if (evt.state === 'plan_progress' && evt.plan_progress) {
    board.setPlanProgress(sid, evt.plan_progress);
    return true;
  }
```

把原 orch_preflight 分支替换为：

```ts
  // Round 3 (2026-09-19): 编排拆解前置进度（需求澄清/事实侦察）——先于
  // task_plan 到达时任务板尚不存在，写独立槽位供指示条消费。
  // 2026-11-25: 后端实际发的是 `phase`，前端历史上只读 `preflight_phase`
  // 导致指示条从不渲染；两者都读。
  const preflightPhase = evt.preflight_phase ?? evt.phase;
  if (evt.state === 'orch_preflight' && preflightPhase) {
    board.setPreflightPhase(sid, preflightPhase);
    return true;
  }
```

- [ ] **Step 4: 跑测试**

Run: `npx vitest run src/features/send-message/__tests__/orchestrationEvents.planProgress.test.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/features/send-message/orchestrationEvents.ts src/features/send-message/__tests__/orchestrationEvents.planProgress.test.ts
git commit -m "feat(chat): 分发 plan_progress 并修复 preflight 阶段字段名"
```

---

### Task 8: PlanningTimeline 组件 + 注入气泡 + P1 文档

**Files:**
- Create: `src/widgets/chat/PlanningTimeline.tsx`
- Modify: `src/widgets/chat/Message.tsx`（`ThinkingDisplay` :360-369；`RetryBanner` :371-373）
- Create: `docs/technical/<next>-planning-visibility.md`
- Create: `docs/user-manual/<next>-planning-visibility.md`
- Modify: `docs/technical/README.md`、`docs/user-manual/README.md`
- Test: `src/widgets/chat/__tests__/PlanningTimeline.test.tsx`、`src/widgets/chat/__tests__/Message.planningTimeline.test.tsx`

**Interfaces:**
- Consumes: Task 5 的 `isPlanningActive`/`PlanStageState`、Task 6 的 `selectSessionSlots`。
- Produces: `PlanningTimeline({ sessionId })`；`data-testid="planning-timeline"`、`planning-timeline-toggle`、`planning-stage-<stage>`。

- [ ] **Step 1: 写失败测试（组件）**

`src/widgets/chat/__tests__/PlanningTimeline.test.tsx`：

```tsx
import { beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { PlanningTimeline } from '../PlanningTimeline';
import { useChatStreamStore } from '../../../features/send-message/chatStreamStore';

function seed() {
  const store = useChatStreamStore.getState();
  store.setPlanProgress('s1', {
    stage: 'complexity_classify',
    status: 'done',
    kind: 'message',
    text: 'medium',
    elapsed_ms: 1200,
  });
  store.setPlanProgress('s1', {
    stage: 'scout',
    status: 'progress',
    kind: 'tool_call',
    text: 'read_file',
  });
}

describe('PlanningTimeline', () => {
  beforeEach(() => {
    useChatStreamStore.setState({ sessions: {} });
  });

  it('无进度时不渲染', () => {
    const { container } = render(<PlanningTimeline sessionId="s1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('渲染阶段、耗时与最近行', () => {
    seed();
    render(<PlanningTimeline sessionId="s1" />);
    expect(screen.getByTestId('planning-timeline')).toBeInTheDocument();
    expect(screen.getByTestId('planning-stage-complexity_classify')).toHaveTextContent(
      '评估任务复杂度',
    );
    expect(screen.getByTestId('planning-stage-complexity_classify')).toHaveTextContent('1.2s');
    expect(screen.getByTestId('planning-stage-scout')).toHaveTextContent('read_file');
    expect(screen.getByTestId('planning-timeline')).toHaveTextContent('规划中');
  });

  it('可折叠', () => {
    seed();
    render(<PlanningTimeline sessionId="s1" />);
    fireEvent.click(screen.getByTestId('planning-timeline-toggle'));
    expect(screen.queryByTestId('planning-stage-scout')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/widgets/chat/__tests__/PlanningTimeline.test.tsx`
Expected: FAIL — 组件不存在。

- [ ] **Step 3: 实现组件**

`src/widgets/chat/PlanningTimeline.tsx`：

```tsx
// src/widgets/chat/PlanningTimeline.tsx
import { ChevronDown } from 'lucide-react';
import { useState } from 'react';

import {
  selectSessionSlots,
  useChatStreamStore,
} from '../../features/send-message/chatStreamStore';
import {
  isPlanningActive,
  type PlanStageState,
} from '../../features/send-message/planProgress';

const STAGE_LABELS: Record<PlanStageState['stage'], string> = {
  mode_classify: '识别处理方式',
  complexity_classify: '评估任务复杂度',
  clarify: '澄清需求',
  scout: '事实侦察',
  scout_deep: '深度调研',
  decompose: '拆解任务',
};

const STATUS_DOT: Record<PlanStageState['status'], string> = {
  started: 'bg-primary animate-pulse',
  progress: 'bg-primary animate-pulse',
  done: 'bg-emerald-500',
  skipped: 'bg-muted',
  failed: 'bg-red-500',
};

export function PlanningTimeline({ sessionId }: { sessionId: string | null | undefined }) {
  const stages = useChatStreamStore((s) => selectSessionSlots(s, sessionId).planProgress);
  const [collapsed, setCollapsed] = useState(false);

  if (!stages || stages.length === 0) return null;

  const active = isPlanningActive(stages);
  const settled = stages.filter(
    (stage) => stage.status === 'done' || stage.status === 'skipped',
  ).length;

  return (
    <div
      data-testid="planning-timeline"
      aria-live="polite"
      className="mb-2 px-3 py-2 rounded-radius-sm border border-border bg-bg-subtle text-ui-xs leading-relaxed"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-text-muted">
          {active ? '规划中' : '规划完成'} · {settled}/{stages.length} 步
        </span>
        <button
          type="button"
          data-testid="planning-timeline-toggle"
          aria-expanded={!collapsed}
          aria-label={collapsed ? '展开规划进度' : '折叠规划进度'}
          onClick={() => setCollapsed((value) => !value)}
          className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-text-muted hover:text-text hover:bg-bg-hover transition-colors"
        >
          <span>{collapsed ? '展开' : '收起'}</span>
          <ChevronDown
            className={`w-3 h-3 transition-transform ${collapsed ? '' : 'rotate-180'}`}
          />
        </button>
      </div>

      {!collapsed && (
        <ol className="mt-1.5 space-y-1">
          {stages.map((stage) => (
            <li key={stage.stage} data-testid={`planning-stage-${stage.stage}`}>
              <div className="flex items-center gap-1.5">
                <span
                  className={`w-1.5 h-1.5 rounded-full ${STATUS_DOT[stage.status]}`}
                  aria-hidden="true"
                />
                <span className="font-medium">{STAGE_LABELS[stage.stage]}</span>
                {stage.status === 'skipped' && (
                  <span className="text-text-muted">已跳过</span>
                )}
                {stage.status === 'failed' && <span className="text-red-500">失败</span>}
                {typeof stage.elapsedMs === 'number' && stage.elapsedMs > 0 && (
                  <span className="text-text-muted">
                    {(stage.elapsedMs / 1000).toFixed(1)}s
                  </span>
                )}
              </div>
              {stage.lines.length > 0 && (
                <ul className="ml-3 mt-0.5 space-y-0.5 text-text-muted">
                  {stage.lines.slice(-3).map((line, index) => (
                    <li key={`${line.kind}-${index}`} className="truncate">
                      {line.text}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
```

- [ ] **Step 4: 跑组件测试**

Run: `npx vitest run src/widgets/chat/__tests__/PlanningTimeline.test.tsx`
Expected: PASS

- [ ] **Step 5: 写注入失败测试**

`src/widgets/chat/__tests__/Message.planningTimeline.test.tsx`：

```tsx
import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { Message } from '../Message';
import { useChatStreamStore } from '../../../features/send-message/chatStreamStore';

const assistantMessage = {
  id: 'm1',
  session_id: 's1',
  role: 'assistant',
  content: '',
  created_at: Date.now(),
} as never;

describe('Message · PlanningTimeline', () => {
  beforeEach(() => {
    useChatStreamStore.setState({ sessions: {} });
  });

  it('assistant 气泡渲染规划时间线', () => {
    useChatStreamStore.getState().setPlanProgress('s1', {
      stage: 'mode_classify',
      status: 'started',
      kind: 'message',
      text: '',
    });
    render(<Message message={assistantMessage} />);
    expect(screen.getByTestId('planning-timeline')).toBeInTheDocument();
  });
});
```

Run: `npx vitest run src/widgets/chat/__tests__/Message.planningTimeline.test.tsx`
Expected: FAIL — 未注入。

> 若 `Message` 需要大量必需 props，沿用同目录既有测试的 render helper；断言目标不变：`planning-timeline` 出现在 assistant 分支内。

- [ ] **Step 6: 注入组件**

在 `Message.tsx` 顶部 import 区（`ThinkingDisplay` 之后）加入：

```tsx
import { PlanningTimeline } from './PlanningTimeline';
```

在 `<ThinkingDisplay ... />` 之后、`{isAssistant && retryInfo && <RetryBanner .../>}` 之前插入：

```tsx
        {/* 2026-11-25: 规划过程实时可见 —— 内联在 assistant 气泡内，
            位于思考面板之下、重试横幅之上。 */}
        {isAssistant && <PlanningTimeline sessionId={message.session_id ?? null} />}
```

Run: `npx vitest run src/widgets/chat/__tests__/Message.planningTimeline.test.tsx`
Expected: PASS

- [ ] **Step 7: 写文档并更新目录**

先取目标分支下一个编号：

```bash
ls docs/technical/ | sed 's/^\([0-9]\+\).*/\1/' | sort -n | tail -1
ls docs/user-manual/ | sed 's/^\([0-9]\+\).*/\1/' | sort -n | tail -1
```

按实际值 +1 命名（main 当前约技术 172 / 手册 59；以落盘时 `ls` 为准，win7 在 cherry-pick 时重取）。

`docs/technical/<next>-planning-visibility.md` 内容：

```markdown
# 编排规划可见性（plan_progress）

## 事件协议

`state = "plan_progress"`，载荷固定为 `plan_progress` 对象：
- `stage`：mode_classify | complexity_classify | clarify | scout | scout_deep | decompose
- `status`：started | progress | done | skipped | failed
- `kind`：message | thinking | tool_call | tool_result | reasoning | heartbeat | skip_reason | error
- `text`：人类可读单行（≤500 字符）
- `detail`：结构化附加信息（默认 `{}`）
- `elapsed_ms`：阶段耗时（可缺省）

## 后端

- `backend/orchestration/plan_progress.py` 提供 `emit_plan_progress` / `run_planning_stage` / `emit_planning_skipped`。
- `run_planning_stage` 每 5 秒发心跳；异常原样上抛；取消时补发 failed 后继续上抛。
- 接入点：`legacy_routes.py`（模式判定、拆解）、`plan_preflight.py`（复杂度、澄清、侦察、深度调研）。

## 前端

- `planProgress.ts` 纯 reducer 合并事件（同阶段 20 行上限）。
- `chatStreamStore` 新增 `planProgress` 槽位。
- `PlanningTimeline` 内联在 assistant 气泡。

## 已知修复

- `orch_preflight` 历史字段名为 `phase`，前端现同时读取 `phase` 与 `preflight_phase`，粗粒度指示条恢复渲染。
```

`docs/user-manual/<next>-planning-visibility.md` 内容：

```markdown
# 规划过程可视化

当你发出一个复杂请求后，Sage 会在对话气泡内显示规划进度：

1. 识别处理方式 —— 判断单智能体还是多智能体编排
2. 评估任务复杂度 —— 决定调研深度
3. 澄清需求 —— 必要时向你提问
4. 事实侦察 / 深度调研 —— 收集可核实的背景事实
5. 拆解任务 —— 生成最终编排计划

- 正在进行的阶段显示为蓝色呼吸点；已完成为绿点；跳过为灰点；失败为红点。
- 每一步显示已用时间与最近三条过程记录（思考、工具调用、调研结果）。
- 点击右上角"收起/展开"可折叠时间线。
- 简单任务会直接执行，时间线中对应阶段标记"已跳过"。
```

在两份 `README.md` 的目录表中各加一行（编号 + 链接 + 一句话简介）。

- [ ] **Step 8: 全量验收并提交**

Run:
```bash
npx vitest run src/widgets/chat/__tests__/Message.planningTimeline.test.tsx src/widgets/chat/__tests__/PlanningTimeline.test.tsx src/features/send-message/__tests__/planProgress.test.ts src/features/send-message/__tests__/orchestrationEvents.planProgress.test.ts src/features/send-message/__tests__/chatStreamStore.planProgress.test.ts
npm run typecheck
npm run verify:pre-push
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_plan_progress.py backend/tests/orchestration/test_plan_preflight_progress.py -v
```
Expected: 全绿。

```bash
git add src/widgets/chat/PlanningTimeline.tsx src/widgets/chat/Message.tsx src/widgets/chat/__tests__/PlanningTimeline.test.tsx src/widgets/chat/__tests__/Message.planningTimeline.test.tsx docs/technical docs/user-manual
git commit -m "feat(chat): 气泡内联规划时间线并补 P1 文档"
```

- [ ] **Step 9: 开 PR 1**

```bash
git switch -c feat/planning-visibility-p1
git push -u origin feat/planning-visibility-p1
gh pr create --base main --title "feat(chat): 编排规划过程实时可见（P1 最小闭环）" --body "实现 plan_progress 统一事件 + PlanningTimeline，修复 orch_preflight 字段名错配。Spec: docs/superpowers/specs/2026-11-25-planning-visibility-design.md"
```

---

## PR 2 · P2 实时调研

> 前端无需改动：`PlanningTimeline` 已按 `kind` 通用渲染 `thinking/tool_call/tool_result`。

### Task 9: deep_research 进度回调

**Files:**
- Modify: `backend/wiki/deep_research.py:144-215`
- Test: `backend/tests/orchestration/test_deep_research_progress.py`

**Interfaces:**
- Produces: `deep_research(..., progress: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None)`；按顺序推送单参 `{"text": ...}` 载荷。

- [ ] **Step 1: 写失败测试**

`backend/tests/orchestration/test_deep_research_progress.py`：

```python
import asyncio
from pathlib import Path

import backend.wiki.deep_research as dr


class _Task:
    topic = "topic"
    status = "pending"
    queries = []
    web_results = []
    synthesis = ""
    error = None


class _Provider:
    name = "fake"


def test_deep_research_emits_step_progress(monkeypatch):
    async def fake_queries(topic, llm_call):
        return ["q1", "q2"]

    async def fake_search(**kwargs):
        return [{"title": "t", "url": "u", "snippet": "s"}]

    async def fake_synth(topic, results, llm_call):
        return "# synthesis"

    monkeypatch.setattr(dr, "generate_search_queries", fake_queries)
    monkeypatch.setattr(dr, "multi_query_search", fake_search)
    monkeypatch.setattr(dr, "synthesize_research", fake_synth)

    progress = []

    async def on_progress(payload):
        progress.append(payload["text"])

    task = _Task()
    asyncio.run(
        dr.deep_research(
            task=task,
            project_root=Path("."),
            search_provider=_Provider(),
            llm_call=lambda *args, **kwargs: None,
            auto_ingest=False,
            progress=on_progress,
        )
    )

    assert task.synthesis == "# synthesis"
    assert any("检索" in text for text in progress)
    assert any("搜索" in text for text in progress)
    assert any("综合" in text for text in progress)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_deep_research_progress.py -v`
Expected: FAIL — `unexpected keyword argument 'progress'`。

- [ ] **Step 3: 实现回调**

`deep_research` 签名（末尾 `http_post` 之后）加：

```python
    progress: Optional[Callable[..., Any]] = None,
```

在 `if llm_call is None:` 之前加：

```python
    async def _notify(text: str) -> None:
        if progress is not None:
            await progress({"text": text})
```

在各步骤插入进度点（按现有顺序）：

```python
        task.status = "searching"
        await _notify("生成检索词…")
```

```python
        task.queries = await generate_search_queries(task.topic, llm_call)
        await _notify(f"生成 {len(task.queries)} 个检索词")
```

```python
        await _notify("执行网络搜索…")
        task.web_results = await multi_query_search(
```

```python
        await _notify(f"收集到 {len(task.web_results)} 条搜索结果")
```

```python
        task.status = "synthesizing"
        await _notify("综合调研结果…")
```

```python
        task.synthesis = await synthesize_research(task.topic, task.web_results, llm_call)
        await _notify("调研综合完成")
```

```python
        if auto_ingest and ingest_config is not None:
            task.status = "ingesting"
            await _notify("写入知识库…")
```

> 若顶层缺 `Any/Callable/Optional`，补齐 `from typing import Any, Callable, Optional`。

- [ ] **Step 4: 跑测试**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_deep_research_progress.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/wiki/deep_research.py backend/tests/orchestration/test_deep_research_progress.py
git commit -m "feat(wiki): deep_research 支持进度回调"
```

---

### Task 10: scout_deep 透传进度

**Files:**
- Modify: `backend/orchestration/scout_deep.py`（`research` 约 :30-100）
- Test: `backend/tests/orchestration/test_scout_deep.py`（追加）

**Interfaces:**
- Consumes: Task 9 的 `deep_research(progress=...)`。
- Produces: `research(topic, project_path, settings=None, progress=None)`。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/orchestration/test_scout_deep.py` 追加：

```python
def test_research_forwards_progress_to_deep_research(monkeypatch):
    import asyncio
    from pathlib import Path

    import backend.orchestration.scout_deep as sd

    captured = {}

    class _Ctx:
        llm_call = staticmethod(lambda *args, **kwargs: None)

    monkeypatch.setattr(sd, "load_llm_config_from_settings", lambda: {"model": "x"})
    # make_llm_context 若不 patch 可能抛错并在第 2 步提前返回空报告，
    # 根本走不到 deep_research，progress 透传就无从验证。
    monkeypatch.setattr(sd, "make_llm_context", lambda **kwargs: _Ctx())

    async def fake_deep_research(**kwargs):
        captured.update(kwargs)

        class _Task:
            status = "done"
            synthesis = "# ok"

        return _Task()

    monkeypatch.setattr(sd, "deep_research", fake_deep_research)
    monkeypatch.setattr(
        sd, "build_report_from_research_task", lambda *args, **kwargs: object()
    )

    async def on_progress(payload):
        return None

    asyncio.run(sd.research("topic", Path("."), progress=on_progress))

    assert callable(captured.get("progress"))
```

> 若既有测试已 patch `make_llm_context` / `SearchProvider`，把上述 monkeypatch 合并进现有 helper；核心断言是 `captured["progress"]` 可调用。

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_scout_deep.py -v`
Expected: FAIL — `unexpected keyword argument 'progress'`。

- [ ] **Step 3: 透传**

签名改为：

```python
async def research(
    topic: str,
    project_path: Path,
    settings: Any = None,
    progress: Any = None,
) -> ResearchReport:
```

在 `task = await deep_research(` 调用中追加：

```python
            progress=progress,
```

- [ ] **Step 4: 跑测试**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_scout_deep.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/orchestration/scout_deep.py backend/tests/orchestration/test_scout_deep.py
git commit -m "feat(scout): scout_deep 透传调研进度回调"
```

---

### Task 11: 只读侦察中间事件 + 深度调研接线

**Files:**
- Modify: `backend/orchestration/plan_preflight.py`（`_run_scout_agent` :451-501、`_scout` :421-448、complex 分支 :261-270）
- Test: `backend/tests/orchestration/test_plan_preflight_progress.py`（追加）

**Interfaces:**
- Consumes: Task 9/10 的 `progress` 参数；Task 1 的 `emit_plan_progress`。
- Produces: `_run_scout_agent(client, goal, max_iterations=..., emit=None)`；`_scout_event_to_progress(event) -> Optional[Dict[str, str]]`。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/orchestration/test_plan_preflight_progress.py` 追加：

```python
def test_scout_event_to_progress_maps_thinking_and_tool():
    from backend.orchestration.plan_preflight import _scout_event_to_progress

    class _Event:
        def __init__(self, state, **kwargs):
            self.state = state
            self.__dict__.update(kwargs)

    assert _scout_event_to_progress(_Event("thinking", reasoning="分析中")) == {
        "kind": "thinking",
        "text": "分析中",
    }
    assert _scout_event_to_progress(
        _Event("acting", tool_call={"name": "read_file"})
    ) == {"kind": "tool_call", "text": "read_file"}
    assert _scout_event_to_progress(
        _Event("observing", tool_result={"ok": True})
    ) == {"kind": "tool_result", "text": "工具返回结果"}
    assert _scout_event_to_progress(_Event("done", content="x")) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_plan_preflight_progress.py -v`
Expected: FAIL — `_scout_event_to_progress` 不存在。

- [ ] **Step 3: 实现映射与接线**

在 `plan_preflight.py` 的 `plan_progress` import 块（Task 2 已加）中补充：

```python
    KIND_MESSAGE,
    KIND_THINKING,
    KIND_TOOL_CALL,
    KIND_TOOL_RESULT,
    STATUS_PROGRESS,
    emit_plan_progress,
```

在 `_scout` 之前新增：

```python
def _tool_name(tool_call: Any) -> str:
    if isinstance(tool_call, dict):
        name = tool_call.get("name")
        return str(name) if name else ""
    return str(getattr(tool_call, "name", "") or "")


def _scout_event_to_progress(event: Any) -> Optional[Dict[str, str]]:
    """把侦察子代理事件映射为一条 plan_progress 载荷；无需展示返回 None。"""
    state = getattr(event, "state", None)
    state_value = getattr(state, "value", state)
    if state_value == "thinking":
        text = (
            getattr(event, "reasoning", "") or getattr(event, "content", "") or ""
        ).strip()
        if text:
            return {"kind": KIND_THINKING, "text": text[:500]}
        return None
    if state_value == "acting":
        name = _tool_name(getattr(event, "tool_call", None))
        if name:
            return {"kind": KIND_TOOL_CALL, "text": name}
        return None
    if state_value == "observing" and getattr(event, "tool_result", None):
        return {"kind": KIND_TOOL_RESULT, "text": "工具返回结果"}
    return None
```

把 `_run_scout_agent` 签名改为：

```python
async def _run_scout_agent(
    client: Any,
    goal: str,
    max_iterations: int = SCOUT_MAX_ITERATIONS,
    emit: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
) -> str:
```

在事件循环 `state_value = getattr(state, "value", state)` 之后插入：

```python
            mapped = _scout_event_to_progress(event)
            if mapped is not None:
                await emit_plan_progress(
                    emit,
                    stage=PLAN_STAGE_SCOUT,
                    status=STATUS_PROGRESS,
                    kind=mapped["kind"],
                    text=mapped["text"],
                )
```

把 `_scout` 内的 `_run_scout_agent(client, goal, max_iterations)` 改为：

```python
            _run_scout_agent(client, goal, max_iterations, emit=emit),
```

把 complex 分支 `scout_deep.research(...)` 调用（在 Task 2 的 `run_planning_stage` runner 内）追加单参回调：

```python
                                progress=lambda payload: emit_plan_progress(
                                    emit,
                                    stage=PLAN_STAGE_SCOUT_DEEP,
                                    status=STATUS_PROGRESS,
                                    kind=KIND_MESSAGE,
                                    text=str(payload.get("text", "")),
                                ),
```

> P2 的 `deep_research` 进度是**单参** `payload`；`make_stream_progress_emitter` 是**两参** `(kind, text)`，只服务于 P3 的 `Planner` 流式 delta。此处不要混用。

- [ ] **Step 4: 跑测试**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_plan_preflight_progress.py backend/tests/orchestration/test_scout_deep.py backend/tests/orchestration/test_deep_research_progress.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/orchestration/plan_preflight.py backend/tests/orchestration/test_plan_preflight_progress.py
git commit -m "feat(preflight): 只读侦察与深度调研中间过程实时可见"
```

- [ ] **Step 6: 开 PR 2**

```bash
git switch -c feat/planning-visibility-p2
git push -u origin feat/planning-visibility-p2
gh pr create --base main --title "feat(orchestration): 规划调研过程实时可见（P2）" --body "deep_research 进度回调 + 侦察子代理 thinking/tool 事件透出。依赖 P1 已合并。"
```

---

## PR 3 · P3 流式拆解 + 前哨优化

### Task 12: utility 客户端（默认关思考 + 回退）

**Files:**
- Modify: `backend/orchestration/llm_factory.py`（`build_llm_client_from_settings` 约 :261 之后）
- Test: `backend/tests/orchestration/test_llm_factory_utility.py`

**Interfaces:**
- Produces:
  - `_apply_utility_overrides(cfg: Dict[str, Any]) -> Dict[str, Any]`
  - `build_utility_llm_client(task_type: str = "classification") -> Optional[Any]`
  - `async def complete_utility(prompt, *, task_type="classification", llm_client=None) -> str`

- [ ] **Step 1: 写失败测试**

`backend/tests/orchestration/test_llm_factory_utility.py`：

```python
import asyncio

import pytest

from backend.orchestration import llm_factory


def test_apply_utility_overrides_does_not_mutate_input():
    cfg = {"model": "m", "reasoning_effort": "high"}
    out = llm_factory._apply_utility_overrides(cfg)
    assert cfg == {"model": "m", "reasoning_effort": "high"}
    assert out["reasoning_effort"] == "low"
    assert out["thinking_budget"] == 0
    assert out["model"] == "m"


def test_complete_utility_uses_injected_client():
    calls = []

    class _Client:
        async def complete(self, prompt):
            calls.append(prompt)
            return "multi"

    result = asyncio.run(llm_factory.complete_utility("classify", llm_client=_Client()))
    assert result == "multi"
    assert calls == ["classify"]


def test_complete_utility_does_not_retry_injected_client():
    class _Boom:
        async def complete(self, prompt):
            raise RuntimeError("bad request")

    with pytest.raises(RuntimeError):
        asyncio.run(llm_factory.complete_utility("x", llm_client=_Boom()))


def test_complete_utility_without_client_raises(monkeypatch):
    monkeypatch.setattr(
        llm_factory, "build_utility_llm_client", lambda task_type="classification": None
    )
    with pytest.raises(RuntimeError):
        asyncio.run(llm_factory.complete_utility("x"))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_llm_factory_utility.py -v`
Expected: FAIL — 函数不存在。

- [ ] **Step 3: 实现**

在 `llm_factory.py` 的 `build_llm_client_from_settings` 之后新增：

```python
def _apply_utility_overrides(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """为规划前哨小任务关掉思考（不改动入参）。"""
    out = dict(cfg)
    out["reasoning_effort"] = "low"
    out["thinking_budget"] = 0
    return out


def build_utility_llm_client(task_type: str = "classification") -> Optional[Any]:
    """构建规划前哨（模式/复杂度分类、澄清）专用客户端。

    与 ``build_llm_client_from_settings`` 的差异：
    1. 应用按用途路由（``routing.mode == "auto"`` 时才生效）；
    2. 默认关思考 —— 二分类/澄清无需长推理，可省数十秒。
    """
    cfg = load_llm_config_from_settings()
    if cfg is None:
        return None
    try:
        cfg = apply_auto_routing_overlay(cfg, task_type=task_type)
        from backend.core.legacy.llm_client import LLMClient, LLMConfig

        return LLMClient(LLMConfig(**_apply_utility_overrides(cfg)))
    except Exception as exc:  # noqa: BLE001 — 构造失败按无配置降级
        logger.warning("llm_factory: failed to build utility LLMClient: %s", exc)
        return None


async def complete_utility(
    prompt: str,
    *,
    task_type: str = "classification",
    llm_client: Any = None,
) -> str:
    """前哨小任务统一入口：注入优先，否则 utility 客户端。

    未注入时若调用失败，回退一次"不带思考参数"的普通客户端 —— 覆盖
    上游拒绝 ``reasoning_effort`` 的兼容场景。注入客户端失败直接上抛，
    避免测试/调用方被双重请求。
    """
    client = llm_client if llm_client is not None else build_utility_llm_client(task_type)
    if client is None:
        raise RuntimeError("no usable LLM endpoint configured")
    try:
        return await client.complete(prompt)
    except Exception as exc:  # noqa: BLE001 — 仅对配置拒绝做一次回退
        if llm_client is not None:
            raise
        logger.warning(
            "llm_factory: utility LLM call failed, retrying without thinking overrides: %s",
            exc,
        )
        fallback = build_llm_client_from_settings()
        if fallback is None:
            raise
        return await fallback.complete(prompt)
```

- [ ] **Step 4: 跑测试**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_llm_factory_utility.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/orchestration/llm_factory.py backend/tests/orchestration/test_llm_factory_utility.py
git commit -m "feat(llm): 新增前哨小任务客户端（默认关思考 + 兼容回退）"
```

---

### Task 13: 流式拆解

**Files:**
- Modify: `backend/orchestration/planner.py:297-330, :475-500`
- Test: `backend/tests/orchestration/test_planner_streaming.py`

**Interfaces:**
- Consumes: 无（复用 `llm_client.chat_stream_events`）。
- Produces: `decompose_request(request, context=None, progress=None)`；`_decompose_with_llm(request, context=None, progress=None)`；`_stream_decomposition(prompt, progress) -> str`。

- [ ] **Step 1: 写失败测试**

`backend/tests/orchestration/test_planner_streaming.py`：

```python
import asyncio

from backend.orchestration.planner import Planner


class _FakeStreamingClient:
    def __init__(self):
        self.complete_calls = 0

    async def chat_stream_events(self, messages):
        yield ("reasoning_delta", "思考1")
        yield ("reasoning_delta", "思考2")
        yield ("content_delta", '{"tasks": []}')
        yield ("response", type("R", (), {"content": '{"tasks": []}'})())

    async def complete(self, prompt):
        self.complete_calls += 1
        return '{"tasks": []}'


def test_stream_decomposition_collects_content_and_reports_deltas():
    client = _FakeStreamingClient()
    planner = Planner(
        task_registry=object(),
        team_registry=object(),
        llm_client=client,
        auto_configure=False,
    )
    seen = []

    async def progress(kind, text):
        seen.append((kind, text))

    result = asyncio.run(planner._stream_decomposition("prompt", progress))
    assert result == '{"tasks": []}'
    assert ("reasoning", "思考1") in seen
    assert ("message", '{"tasks": []}') in seen
    assert client.complete_calls == 0


class _EmptyContentClient(_FakeStreamingClient):
    async def chat_stream_events(self, messages):
        yield ("reasoning_delta", "只有思考")


def test_decompose_falls_back_to_complete_when_stream_empty(monkeypatch):
    monkeypatch.setattr(
        Planner,
        "_build_decomposition_prompt",
        lambda self, request, context=None: "prompt",
    )
    client = _EmptyContentClient()
    planner = Planner(
        task_registry=object(),
        team_registry=object(),
        llm_client=client,
        auto_configure=False,
    )

    async def progress(kind, text):
        return None

    async def scenario():
        return await planner._decompose_with_llm("do it", progress=progress)

    tasks, _reasoning = asyncio.run(scenario())
    assert client.complete_calls == 1
    assert isinstance(tasks, list)
```

> `_build_decomposition_prompt` 不访问注册表，但用 `object()` 占位仍是零成本保险；回退测试直接 monkeypatch 该私有方法，避免依赖 prompt 模板细节。

- [ ] **Step 2: 跑测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_planner_streaming.py -v`
Expected: FAIL — `_stream_decomposition` 不存在 / `progress` 未知参数。

- [ ] **Step 3: 实现**

`planner.py` 顶部 typing import 补 `Callable`（若缺）：

```python
from typing import Any, Callable, Dict, List, Optional, Tuple
```

`decompose_request` 签名与转发改为：

```python
    async def decompose_request(
        self,
        request: str,
        context: Optional[Dict[str, Any]] = None,
        progress: Optional[Callable[[str, str], Any]] = None,
    ) -> Plan:
```

```python
        if self.llm_client is not None:
            tasks, reasoning = await self._decompose_with_llm(
                request, context, progress
            )
```

`_decompose_with_llm` 改为：

```python
    async def _decompose_with_llm(
        self,
        request: str,
        context: Optional[Dict[str, Any]] = None,
        progress: Optional[Callable[[str, str], Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], str]:
        """Decompose request via the LLM; any failure → single-task fallback."""
        prompt = self._build_decomposition_prompt(request, context)

        response: Optional[str] = None
        if progress is not None and hasattr(self.llm_client, "chat_stream_events"):
            try:
                response = await self._stream_decomposition(prompt, progress)
            except Exception as exc:  # noqa: BLE001 — 流式失败回退非流式
                logger.warning("Planner streaming failed, falling back: %s", exc)
                response = None

        if not response:
            try:
                response = await self.llm_client.complete(prompt)
            except Exception as exc:
                logger.warning("Planner LLM call failed, falling back: %s", exc)
                return self._simple_decompose(request)

        if not response or not isinstance(response, str):
            return self._simple_decompose(request)

        parsed = self._parse_llm_response(response)
        if parsed is None:
            logger.warning("Planner: malformed LLM JSON, falling back to single task")
            return self._simple_decompose(request)

        tasks, reasoning = parsed
        if not tasks:
            return self._simple_decompose(request)
        return tasks, reasoning

    async def _stream_decomposition(
        self,
        prompt: str,
        progress: Callable[[str, str], Any],
    ) -> str:
        """流式拆解：把 reasoning/content delta 交给进度回调，返回终态内容。"""
        messages = [{"role": "user", "content": prompt}]
        content = ""
        async for kind, payload in self.llm_client.chat_stream_events(messages):
            if kind == "reasoning_delta" and payload:
                await progress("reasoning", str(payload))
            elif kind == "content_delta" and payload:
                content += str(payload)
                await progress("message", str(payload))
            elif kind == "response":
                final = getattr(payload, "content", None)
                if final:
                    content = str(final)
        return content
```

- [ ] **Step 4: 跑测试**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_planner_streaming.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/orchestration/planner.py backend/tests/orchestration/test_planner_streaming.py
git commit -m "feat(planner): 拆解阶段流式推理"
```

---

### Task 14: 前哨调用点切换到 utility 客户端 + 拆解流式接线

**Files:**
- Modify: `backend/api/legacy_routes.py`（拆解 progress）
- Modify: `backend/orchestration/plan_preflight.py`（preflight 客户端）
- Modify: `backend/orchestration/complexity_classifier.py:104-106, :283-285`

**Interfaces:**
- Consumes: Task 12 的 `build_utility_llm_client`；Task 13 的 `decompose_request(..., progress=...)`；Task 1 的 `make_stream_progress_emitter`。

- [ ] **Step 1: `plan_preflight.py` 切换客户端**

把函数内的惰性 import：

```python
        from backend.orchestration.llm_factory import build_llm_client_from_settings
```

改为：

```python
        from backend.orchestration.llm_factory import build_utility_llm_client
```

把 `client = build_llm_client_from_settings()` 改为：

```python
        client = build_utility_llm_client(task_type="plan_preflight")
```

- [ ] **Step 2: `complexity_classifier.py` 切换两处**

`complexity_classifier.classify`（约 :104-106）：

```python
            from backend.orchestration.llm_factory import build_utility_llm_client

            client = build_utility_llm_client(task_type="complexity_classify")
```

`estimate_budget_level`（约 :283-285）同样改为：

```python
            from backend.orchestration.llm_factory import build_utility_llm_client

            client = build_utility_llm_client(task_type="budget_estimate")
```

- [ ] **Step 3: `legacy_routes.py` 拆解传入流式回调**

在 `legacy_routes.py` 的 `plan_progress` import 块中追加 `make_stream_progress_emitter`（按现有 12 空格缩进）。

把非模板分支的拆解（Task 3 包裹后的 `run_planning_stage(...)`）runner 改为带 progress：

```python
                            decompose_progress = make_stream_progress_emitter(
                                entry.queue.put, stage=PLAN_STAGE_DECOMPOSE
                            )
                            plan = await run_planning_stage(
                                entry.queue.put,
                                stage=PLAN_STAGE_DECOMPOSE,
                                runner=lambda: Planner(
                                    task_registry=TaskRegistry(),
                                    team_registry=TeamRegistry(),
                                    llm_client=build_llm_client_from_settings(),
                                ).decompose_request(
                                    data.message,
                                    context=preflight_context,
                                    progress=decompose_progress,
                                ),
                                describe_result=lambda value: (
                                    f"拆解为 {len(getattr(value, 'tasks', []) or [])} 个任务"
                                ),
                            )
```

> 拆解本身用**完整**客户端（`build_llm_client_from_settings`）——这里需要推理质量；只有前哨判定用 utility 客户端。

- [ ] **Step 4: 跑测试与导入冒烟**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration/test_planner_streaming.py backend/tests/orchestration/test_llm_factory_utility.py backend/tests/orchestration/test_complexity_classifier.py -v
/home/fz/anaconda3/envs/sage-backend/bin/python -c "import backend.api.legacy_routes, backend.orchestration.plan_preflight, backend.orchestration.planner"
```
Expected: PASS；import 无异常。

- [ ] **Step 5: 提交**

```bash
git add backend/api/legacy_routes.py backend/orchestration/plan_preflight.py backend/orchestration/complexity_classifier.py
git commit -m "feat(planner): 前哨小任务默认关思考 + 拆解流式接线"
```

---

### Task 15: 文档收尾 + CHANGELOG + 门禁

**Files:**
- Modify: `docs/technical/<next>-planning-visibility.md`（补 P2/P3 章节）
- Modify: `docs/user-manual/<next>-planning-visibility.md`（补"为什么更快"）
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 补技术文档**

在技术文档追加：

```markdown
## P2：调研实时化

- `deep_research(..., progress=...)` 在每个步骤（检索词/搜索/综合/入库）推送单参 `{"text": ...}`。
- `scout_deep.research(..., progress=...)` 透传。
- 只读侦察 `_run_scout_agent` 把 `thinking/acting/observing` 事件映射为 `thinking/tool_call/tool_result`。

## P3：流式拆解与前哨优化

- `Planner.decompose_request(..., progress=...)` 使用 `chat_stream_events` 流式消费拆解推理；无内容时回退 `complete()`。
- `build_utility_llm_client(task_type=...)`：应用按用途路由 + `reasoning_effort="low"` + `thinking_budget=0`。
- `complete_utility()`：未注入客户端失败时回退一次普通客户端，覆盖上游拒绝思考参数的兼容场景。
```

在用户手册追加：

```markdown
## 为什么现在更快

分类、澄清、侦察这类小任务不再触发推理模型的长思考（默认关闭），
只有真正需要推理的任务拆解才保留思考，并实时显示在时间线中。
```

- [ ] **Step 2: CHANGELOG**

在 `CHANGELOG.md` 的 `[Unreleased]` 下按 Keep a Changelog 各加一行：

```markdown
### Added
- 编排规划过程实时可见：plan_progress 统一事件 + 气泡内 PlanningTimeline

### Changed
- 规划前哨小任务（模式/复杂度分类、澄清）默认关闭思考；拆解阶段流式展示推理
```

- [ ] **Step 3: 跑门禁**

Run:
```bash
npm run verify:pre-push
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/orchestration -v
npx vitest run src/features/send-message/__tests__ src/widgets/chat/__tests__/PlanningTimeline.test.tsx
```
Expected: 全绿；若 architecture-check 报行数红线，只更新**当前分支**的基线（main 与 win7 数值独立，勿交叉套用）。

- [ ] **Step 4: 提交并开 PR 3**

```bash
git add docs CHANGELOG.md
git commit -m "docs: 规划可见性 P2/P3 技术文档与用户手册"
git switch -c feat/planning-visibility-p3
git push -u origin feat/planning-visibility-p3
gh pr create --base main --title "feat(planner): 拆解流式推理与前哨关思考（P3）" --body "Planner 流式拆解 + utility 客户端默认关思考。依赖 P1/P2 已合并。"
```

---

### Task 16: cherry-pick 到 release/win7

**Files:**
- All of the above on `release/win7`（py38 适配）

- [ ] **Step 1: 建 win7 分支**

```bash
git fetch origin release/win7
git switch -c feat/planning-visibility-win7 origin/release/win7
```

- [ ] **Step 2: cherry-pick 三个 PR 的合并提交**

```bash
git log --oneline main --grep "planning-visibility" -n 30
git cherry-pick <p1_merge_sha> <p2_merge_sha> <p3_merge_sha>
```

冲突处理原则：
- `backend/orchestration/*`：保留本计划版本；若 win7 有 py38 变体，手工合并。
- `docs/*`：按 win7 实际编号重命名（以 `ls` 为准），README 冲突保留两侧行。
- 绝不修改 `backend/requirements.txt`（win7 只允许 `requirements-py38.txt`，且本功能不新增依赖）。

- [ ] **Step 3: py38 兼容检查**

Run:
```bash
grep -rn " | None\|list\[\|dict\[\|tuple\[\|asyncio.TaskGroup" \
  backend/orchestration/plan_progress.py backend/wiki/deep_research.py \
  backend/orchestration/planner.py backend/orchestration/llm_factory.py
```
Expected: 无输出（本功能新增行内不允许）。

- [ ] **Step 4: py38 全量测试**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/orchestration -v
npx vitest run src/features/send-message/__tests__ src/widgets/chat/__tests__/PlanningTimeline.test.tsx
npm run typecheck
```
Expected: 全绿。

- [ ] **Step 5: 提交并开 PR**

```bash
git push -u origin feat/planning-visibility-win7
gh pr create --base release/win7 --title "feat: 编排规划过程实时可见（win7 同步）" --body "cherry-pick main P1–P3，py38/pydantic v1 适配；文档编号按 win7 顺延。"
```

---

## 验收清单（每个 PR 都必须全绿）

- [ ] 后端相关 pytest 通过（main 用 `sage-backend`，win7 用 `sage-backend-py38`）
- [ ] `npm run typecheck` 通过（`AgentState` 两个 `assertNever` 分支已补）
- [ ] 相关 vitest 通过（reducer / store / 事件分发 / 组件 / Message 注入）
- [ ] `npm run verify:pre-push` 通过（lint + architecture-check；基线按分支实测）
- [ ] 手动冒烟（正常模式）：启动 Vite + Electron，发一个复杂请求，确认气泡内出现时间线、阶段依次推进、心跳期间不空白、最终计划出现后时间线仍在
- [ ] 手动冒烟（降级）：无 LLM 配置时不崩溃、不发事件、正常降级
- [ ] 日志中无原始 `SAGE_LOCAL_AUTH_TOKEN`
- [ ] win7 cherry-pick 后文档编号顺延且双分支测试各自独立通过

## 自审（spec 覆盖）

- **统一事件协议**：Task 1。
- **6 阶段**：Task 2、3、13。
- **5 状态**：Task 1 常量；simple/模板/计划模式/单智能体 → Task 2、3。
- **心跳**：Task 1 `run_planning_stage`。
- **气泡区内联**：Task 8。
- **修复不可见根因**：Task 7（`phase`/`preflight_phase`）。
- **调研实时化**：Task 9–11。
- **拆解流式**：Task 13、14。
- **前哨默认关思考 + 可选路由**：Task 12、14。
- **双分支**：Task 16。
