# Planning Visibility Design

> **Date**: 2026-11-25
> **Status**: Draft
> **Author**: Claude + User

## Background

When a user submits a request that triggers multi-agent orchestration, Sage enters a planning phase that can take **tens of seconds to several minutes**. During this phase, the user sees **no progress, no thinking, no research steps** — only a long wait followed by the sudden appearance of a task plan.

The user reported this as: "LLM 出规划的过程中的思考、调研的过程都没看到，在进行一段时间比较长的思考后，直接出现了编排计划。"

This design addresses both problems:
1. **Invisibility** — the planning process produces no visible signals (root cause: application-level, not API-level)
2. **Slowness** — utility LLM calls (classification, planning) inherit reasoning parameters from the main chat endpoint, wasting time on deep thinking for simple classification tasks

The design aligns with mainstream AI applications (Claude Code plan flow, ChatGPT Deep Research, Manus execution cards) where the planning process is fully visible: thinking stream, tool calls, stage progress, and elapsed time are all shown in real-time.

## Goals

1. **Full visibility** — every planning stage (mode classify, complexity classify, clarify, scout, decompose) emits progress events that are rendered in the UI
2. **Inline in message bubble** — planning progress appears as a collapsible block inside the assistant message, collapsing to a one-line summary once the plan card arrives
3. **Live research steps** — scout tool calls and thinking are mirrored in real-time (throttled to avoid flooding)
4. **Streaming planner reasoning** — the Planner's LLM reasoning stream is forwarded to the UI (throttled, collapsible)
5. **Faster utility calls** — classification and planning calls disable reasoning parameters by default; optional auto-routing to faster models via `task_type`
6. **Cancellation** — users can cancel the planning phase mid-stream
7. **Phased delivery** — split into 3 PRs (P1 visibility minimum, P2 live research, P3 streaming planner + utility optimization)

## Non-Goals

- Replacing the canonical `orch_runs`/`orch_tasks` model with a "planning as pseudo-run" approach (over-engineering; planning is not a run)
- Changing the plan approval flow (PlanApprovalBar remains for plan confirmation, but its preflight indicator is replaced by PlanningTimeline)
- Modifying the Scout agent's tool selection or behavior (only mirror its existing events)
- Adding a separate "planning model" setting (auto-routing via `task_type` is sufficient)

## Current State Analysis

### Root Cause Chain

The planning phase executes **2–5 serial blocking LLM calls** before emitting `task_plan`:

| Step | Code Location | Visibility | Latency |
|---|---|---|---|
| Mode classification | `legacy_routes.py:921` → `chat_dispatcher.py:160` `complete()` | **Zero events** | Inherits reasoning params → slow |
| Complexity classification | `plan_preflight.py:217` → `complexity_classifier.py:122` `complete()` | Emits `orch_preflight`, but frontend **never receives it** (field mismatch) | Inherits reasoning params → slow |
| Clarification (QuestionGate) | `plan_preflight.py:353` `complete()` | Same field mismatch bug | Inherits reasoning params → slow |
| Scout (lite) | `plan_preflight.py:491` subagent `run_loop` | **Intermediate events discarded** | Tool calls + thinking lost |
| Scout (deep) | `scout_deep.py:30` `deep_research()` | No progress callback; only `research_complete` at end | Up to 120s |
| Planner decomposition | `planner.py:484` `complete()` | **Non-streaming, reasoning discarded** | Inherits reasoning params → slow |

### Three Application-Level Bugs

1. **Dead indicator (field name mismatch)**:
   - Backend emits `{"state":"orch_preflight","phase":"clarify"}` (`plan_preflight.py:223,338,429`)
   - Frontend gates on `evt.preflight_phase` (`orchestrationEvents.ts:42`, type `chatAndEventTypes.ts:788`)
   - `PlanApprovalBar.tsx:310` indicator **never renders**
   - Both test suites pass because each tests its own field name

2. **Non-streaming planning calls**:
   - `llm_client.chat()` request body has no `stream` key (`llm_client.py:779-784`)
   - Reasoning params (`reasoning_effort`/`thinking_budget`) are forwarded (`llm_client.py:797-800`)
   - Reasoning models must generate all thinking tokens before returning → black screen for 30–120s
   - Dynamic timeout up to 300s (`compute_dynamic_timeout`)

3. **Scout events discarded by design**:
   - `_run_scout_agent` consumes subagent events but only takes `done`/`failed` terminal states
   - Tool calls, thinking, tool results are all dropped (`plan_preflight.py:491`)

### API-Level Amplifier

Internal reasoning models generate deep thinking for every call. A mode classification that only needs to output "multi" (2 characters) still runs with full reasoning budget, taking 20–40s per call. Serialized 4–5 times = 2–3 minutes of invisible waiting.

## Design Overview

The design introduces a **unified `plan_progress` event family** that covers all planning stages, with a new `PlanningTimeline` component that renders inline in the assistant message bubble.

```
┌─────────────────────────────────────────────────────────────┐
│                    User Message Bubble                       │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ PlanningTimeline (collapsible)                         │ │
│  │  ✓ 分析任务复杂度 (simple) · 1.2s                      │ │
│  │  ✓ 澄清需求 (已跳过：意图明确) · 0s                    │ │
│  │  ⟳ 侦察中 · 已等待 8s                                 │ │
│  │    ├─ 🔍 读取 README.md                                │ │
│  │    ├─ 🔍 搜索相关文档                                  │ │
│  │    └─ 💭 思考：用户可能需要… (折叠)                   │ │
│  │  ○ 生成计划 · 等待中                                   │ │
│  │  [取消规划]                                            │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ PlanCard (appears after task_plan)                     │ │
│  │  任务计划 · 3 个任务 · ≈5 轮迭代                       │ │
│  │  [批准] [修改] [取消]                                  │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

After `task_plan` arrives, PlanningTimeline collapses to:

```
  已规划 3 个任务 · 总耗时 42s · 调研 5 次工具调用  [展开]
```

## §1. Event Protocol: `plan_progress`

### Event Shape

```typescript
interface PlanProgressEvent {
  state: 'plan_progress';
  session_id: string;
  stage:
    | 'mode_classify'       // semantic binary classification (multi/single)
    | 'complexity_classify' // complexity classification (simple/medium/complex)
    | 'clarify'             // QuestionGate clarification
    | 'scout'               // read-only scout (lite)
    | 'scout_deep'          // deep research
    | 'decompose';          // Planner decomposition
  status: 'started' | 'progress' | 'done' | 'skipped' | 'failed';
  elapsed_ms?: number;      // elapsed time since stage started (done/skipped = total)
  payload?: PlanProgressPayload;
  usage?: {                 // only on status='done'
    input_tokens: number;
    output_tokens: number;
  };
}

type PlanProgressPayload =
  | { kind: 'message'; text: string }                     // user-visible description
  | { kind: 'thinking'; delta: string }                   // subagent thinking stream
  | { kind: 'tool_call'; name: string; args_summary: string; id: string }
  | { kind: 'tool_result'; id: string; summary: string; duration_ms: number }
  | { kind: 'reasoning'; delta: string }                  // Planner reasoning stream
  | { kind: 'heartbeat' }                                 // long-call keepalive
  | { kind: 'skip_reason'; reason: string }               // why skipped
  | { kind: 'error'; error: string };                     // failure reason
```

### Relationship to Existing Events

- **Replaces** `orch_preflight` (with `phase: complexity_classify/clarify/scout/execution_mode_classify`). Frontend stops consuming `orch_preflight`; backend keeps emitting it for one release cycle (backward compat), then removes.
- **Mode classification** is now a `plan_progress` stage (not a separate event).
- `research_complete` (deep research summary) remains unchanged; `plan_progress(scout_deep, done)` is emitted just before `research_complete`, providing the stage completion signal while `research_complete` still feeds the `ResearchSummaryCard`.
- Heartbeat and `progress` are merged (payload `kind='heartbeat'`), no separate status.

### Why a Single Event Family

- Frontend consumption logic simplifies to one switch statement
- NDJSON replay merges by stage naturally
- Right panel and bubble inline share the same data source
- Cancellation can target any stage uniformly

### Backward Compatibility

During the transition (P1), backend emits **both** `orch_preflight` (with fixed field name `preflight_phase`) and `plan_progress`. Frontend consumes `plan_progress` for the new UI; `orch_preflight` handling is removed from PlanApprovalBar but the event type remains in the union for one release cycle.

## §2. Backend Event Emission

### Unified Stage Wrapper

All blocking planning LLM calls are wrapped in a helper:

```python
async def run_planning_stage(
    stage: str,
    fn: Callable[[], Awaitable[Any]],
    emit: Callable[[Dict], Awaitable[None]],
    session_id: str,
    llm_client: Any,
) -> Any:
    """Wrap a planning stage with started/done/skipped/failed events + heartbeat."""
    import asyncio
    import time

    start = time.monotonic()
    await emit({
        "state": "plan_progress",
        "session_id": session_id,
        "stage": stage,
        "status": "started",
    })

    # Heartbeat task: emit every 5s while stage is running
    heartbeat_task = asyncio.create_task(_emit_heartbeat(stage, emit, session_id, start))

    try:
        result = await fn()
        elapsed_ms = int((time.monotonic() - start) * 1000)
        await emit({
            "state": "plan_progress",
            "session_id": session_id,
            "stage": stage,
            "status": "done",
            "elapsed_ms": elapsed_ms,
            "usage": _extract_usage(result),
        })
        return result
    except asyncio.CancelledError:
        await emit({
            "state": "plan_progress",
            "session_id": session_id,
            "stage": stage,
            "status": "failed",
            "elapsed_ms": int((time.monotonic() - start) * 1000),
            "payload": {"kind": "error", "error": "cancelled"},
        })
        raise
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        await emit({
            "state": "plan_progress",
            "session_id": session_id,
            "stage": stage,
            "status": "failed",
            "elapsed_ms": elapsed_ms,
            "payload": {"kind": "error", "error": str(exc)},
        })
        return None  # caller handles degradation
    finally:
        heartbeat_task.cancel()


async def _emit_heartbeat(stage, emit, session_id, start):
    import asyncio
    import time
    while True:
        await asyncio.sleep(5)
        await emit({
            "state": "plan_progress",
            "session_id": session_id,
            "stage": stage,
            "status": "progress",
            "elapsed_ms": int((time.monotonic() - start) * 1000),
            "payload": {"kind": "heartbeat"},
        })
```

### Emission Points

| Location | Transformation |
|---|---|
| `legacy_routes.py:921` `_classify_orchestration_mode` | Wrap in `run_planning_stage('mode_classify', ...)`; emit before `run_plan_preflight` |
| `plan_preflight.py:217` `classify_complexity` | Wrap in `run_planning_stage('complexity_classify', ...)`; remove or keep existing `orch_preflight` emit as compat |
| `plan_preflight.py:353` `_clarify` | Wrap in `run_planning_stage('clarify', ...)`; multiple QuestionGate `complete()` calls merge into one stage |
| `plan_preflight.py:491` `_run_scout_agent` | Wrap in `run_planning_stage('scout', ...)`; **mirror subagent thinking/tool_call/tool_result as `plan_progress(progress, kind=...)`** with 100ms throttle |
| `scout_deep.py:30` `deep_research` | Add `on_progress` callback; progress events (file reads, searches, summaries) forwarded as `plan_progress(progress, kind=tool_call/tool_result)` |
| `planner.py:484` `_decompose_with_llm` | Switch `complete()` → `stream_chat()`; forward `reasoning_delta` as `plan_progress(progress, kind=reasoning)` with 50ms throttle; accumulate `content_delta` for JSON parsing; emit `plan_progress(decompose, done)` with usage |

### Throttling Strategy

- **Thinking/tool_call/tool_result (scout)**: 100ms debounce **per stage, per kind**; max 200 events per stage
- **Reasoning (Planner)**: 50ms debounce; max 500 events per stage
- **Heartbeat**: fixed 5s interval; cancelled on stage completion

Throttling prevents UI flooding while keeping the process visible. Event limits per stage are hard caps; exceeding them drops further events (logged but not emitted).

### Argument Sanitization

Mirror events for scout tool calls use `permission_gate.redact_sensitive_args` (M4.1 patch) to sanitize sensitive parameters before emission. The redaction preserves structure (no stringification, no truncation) using `_scrub_value` recursive cleaning.

### Planner Streaming Transformation

```python
async def _decompose_with_llm(self, request, context=None):
    prompt = self._build_decomposition_prompt(request, context)

    try:
        content_parts = []
        reasoning_parts = []
        async for event in self.llm_client.stream_chat([{"role": "user", "content": prompt}]):
            kind, value = event
            if kind == "reasoning_delta":
                # Throttled emission to frontend
                await self._emit_plan_progress(
                    stage="decompose",
                    status="progress",
                    payload={"kind": "reasoning", "delta": value}
                )
                reasoning_parts.append(value)
            elif kind == "response":
                # value.content is the full accumulated content
                content_parts.append(value.content)
                usage = {"input_tokens": value.input_tokens, "output_tokens": value.output_tokens}
    except Exception as exc:
        logger.warning("Planner streaming failed, falling back: %s", exc)
        return self._simple_decompose(request), None

    full_content = "".join(content_parts)
    parsed = self._parse_llm_response(full_content)
    if parsed is None:
        logger.warning("Planner: malformed LLM JSON, falling back to single task")
        return self._simple_decompose(request), None

    tasks, reasoning = parsed
    if not tasks:
        return self._simple_decompose(request), None
    return tasks, reasoning, usage
```

Note: `stream_chat` yields `("content_delta", str)`, `("reasoning_delta", str)`, and finally `("response", LLMResponse)`. We accumulate `content_delta` but don't emit it (the final `response.content` is the authoritative value). We only emit `reasoning_delta` for UI visibility.

## §3. Utility LLM Client

### New Factory Function

```python
# backend/orchestration/llm_factory.py

def build_utility_llm_client(task_type: Optional[str] = None) -> Optional[Any]:
    """Build an LLM client for utility calls (classification, planning).

    Defaults: reasoning_effort=None, thinking_budget=None (no deep thinking).
    Optional: auto-route to a faster model by task_type when routing.mode=auto.

    Returns:
        LLMClient configured for utility use, or None if no endpoint configured.
    """
    cfg = load_llm_config_from_settings()
    if cfg is None:
        return None
    try:
        from backend.core.legacy.lm_client import LLMClient, LLMConfig

        # Force reasoning off (utility calls don't need deep thinking)
        cfg = {**cfg, "reasoning_effort": None, "thinking_budget": None}

        # Optional: auto-route to a faster model by task_type
        if task_type:
            cfg = apply_auto_routing_overlay(cfg, task_type=task_type)

        return LLMClient(LLMConfig(**cfg))
    except Exception as exc:
        logger.warning("llm_factory: failed to build utility LLMClient: %s", exc)
        return None
```

### Replacement Sites

| Call Site | `task_type` | Rationale |
|---|---|---|
| `legacy_routes.py:921` `_classify_orchestration_mode` | `"classification"` | Binary classification (multi/single); reasoning not needed |
| `plan_preflight.py:217` `classify_complexity` | `"classification"` | Complexity classification (simple/medium/complex); reasoning not needed |
| `plan_preflight.py:353` `_clarify` | `"planning"` | QuestionGate clarification; structured output, no deep reasoning |
| `plan_preflight.py:491` scout agent | None (use utility client but no routing) | Scout needs tool-calling capability; can't downgrade to a lightweight model, but still disable reasoning |
| `planner.py` default client | `"planning"` | Plan decomposition; structured output, no deep reasoning |

### Safety Guardrails

- Default `task_type=None` means no routing (uses main model), only disables reasoning
- User can enable `routing.mode=auto` in settings and configure faster models for `classification`/`planning` in the model catalog
- If routing fails or yields no model, falls back to main model (with reasoning disabled)

### Expected Latency Improvement

| Call | Before (with reasoning) | After (no reasoning) | With auto-routing |
|---|---|---|---|
| Mode classify | 20–40s | 2–5s | 1–3s |
| Complexity classify | 20–40s | 2–5s | 1–3s |
| Clarify (QuestionGate) | 30–60s | 5–10s | 3–7s |
| Planner | 30–90s | 10–20s | 5–15s |

Total planning phase: **~3 minutes → ~30 seconds** (with auto-routing enabled).

## §4. Frontend Data Layer

### New Store Slot

```typescript
// src/features/send-message/chatStreamStore.ts

interface ChatStreamSlot {
  // ... existing fields ...
  planProgress: PlanProgressEvent[];  // new: planning progress events (time-ordered)
  planningDone: boolean;              // new: true once decompose stage completes
}

// Initial state
planProgress: [],
planningDone: false,
```

### Event Consumer

```typescript
// src/features/send-message/orchestrationEvents.ts

export function applyOrchestrationEventToBoard(evt: AgentEvent, sid: string): boolean {
  const board = useChatStreamStore.getState();

  // ... existing handlers ...

  // Plan progress (new): append to planProgress array
  if (evt.state === 'plan_progress' && evt.session_id === sid) {
    board.appendPlanProgress(sid, evt as PlanProgressEvent);
    if (evt.stage === 'decompose' && evt.status === 'done') {
      board.setPlanningDone(sid, true);
    }
    return true;
  }

  // task_plan: clear planProgress (keep summary for collapsed state)
  if (evt.state === 'task_plan' && evt.run_id && evt.plan) {
    const runId = evt.run_id;
    const plan = evt.plan;
    board.setPreflightPhase(sid, null);  // legacy cleanup
    board.setPlanProgressSummary(sid, buildPlanProgressSummary(board.getPlanProgress(sid)));
    board.clearPlanProgress(sid);  // clear detailed events
    board.updateTaskBoard(sid, runId, (prev) =>
      prev && prev.runId === runId
        ? prev
        : { runId, plan, reasoning: evt.reasoning, statuses: {}, live: {} }
    );
    return true;
  }

  return false;
}
```

### Field Contract Fix

Backend `plan_preflight.py` currently emits `{"state":"orch_preflight","phase":"..."}`. Frontend expects `preflight_phase`. Fix:

**Option A (recommended)**: Rename backend field to `preflight_phase` (matches frontend). Update `plan_preflight.py` emit calls and `test_plan_preflight.py` assertions.

**Option B**: Rename frontend type/consumer to read `phase`. Update `orchestrationEvents.ts` and `chatAndEventTypes.ts`.

Choose **Option A** because `preflight_phase` is more descriptive and already in the frontend type system.

### Type Definitions

```typescript
// src/shared/api/types/chatAndEventTypes.ts

export interface PlanProgressEvent {
  state: 'plan_progress';
  session_id: string;
  stage:
    | 'mode_classify'
    | 'complexity_classify'
    | 'clarify'
    | 'scout'
    | 'scout_deep'
    | 'decompose';
  status: 'started' | 'progress' | 'done' | 'skipped' | 'failed';
  elapsed_ms?: number;
  payload?: PlanProgressPayload;
  usage?: { input_tokens: number; output_tokens: number };
}

export type PlanProgressPayload =
  | { kind: 'message'; text: string }
  | { kind: 'thinking'; delta: string }
  | { kind: 'tool_call'; name: string; args_summary: string; id: string }
  | { kind: 'tool_result'; id: string; summary: string; duration_ms: number }
  | { kind: 'reasoning'; delta: string }
  | { kind: 'heartbeat' }
  | { kind: 'skip_reason'; reason: string }
  | { kind: 'error'; error: string };

// Add to AgentEvent union
export type AgentEvent =
  | /* existing events */
  | PlanProgressEvent;
```

### Replay Support

NDJSON stream attach (`reattachActiveStream`) replays all events. `plan_progress` events are replayed in order, allowing `PlanningTimeline` to restore its state. The `append PlanProgress` action handles deduplication by stage+status (if the same stage emits multiple `progress` events, only the latest is kept).

## §5. Frontend Presentation: PlanningTimeline

### New Component

```
src/widgets/chat/PlanningTimeline.tsx
```

### Rendering Location

In `Chat.tsx`, inject `PlanningTimeline` **above the PlanCard** (or above where the PlanCard will appear) inside the assistant message bubble:

```tsx
// src/pages/Chat.tsx

{planProgress.length > 0 && (
  <PlanningTimeline
    events={planProgress}
    summary={planProgressSummary}
    collapsed={planningDone}
    onCancel={() => cancelPlanning(sid)}
  />
)}

{taskBoard && <PlanCard taskBoard={taskBoard} ... />}
```

### Three States

1. **Expanded** (default while planning):
   - Stage rows: icon (spinner → ✓/✗) + Chinese label + elapsed time
   - Scout/decompose stages: expandable sub-rows for tool calls / thinking (collapsed by default, click to expand)
   - Bottom: live "已等待 Ns" heartbeat timer + cancel button
2. **Collapsed** (after `task_plan` arrives):
   - One-line summary: "已规划 N 个任务 · 总耗时 Xs · 调研 Y 次工具调用 [展开]"
   - Click to expand full history
3. **Hidden** (no `planProgress` and no summary):
   - Component doesn't render

### Stage Labels

```typescript
const STAGE_LABELS: Record<string, string> = {
  mode_classify: '分析任务类型',
  complexity_classify: '评估复杂度',
  clarify: '澄清需求',
  scout: '侦察收集事实',
  scout_deep: '深度调研',
  decompose: '生成任务计划',
};
```

### Reuse

- **Row rendering** for tool calls / thinking: reuse `SubagentLivePanel`'s `EventTimelineRow` component
- **Duration formatting**: reuse `progressFormat.formatDuration`
- **Cancel button**: reuse `runControlClient.cancelRun` (if planning has a `run_id`) or stream cancel (`/api/v1/chat/stream/{id}/cancel`)

### Relationship to PlanApprovalBar

- **PlanApprovalBar retains**: plan approval (confirm/edit/cancel), execution mode override, step_confirm
- **PlanApprovalBar loses**: preflight indicator (lines 310-324) — replaced by `PlanningTimeline`
- `preflightPhase` slot remains for internal logic but is not used as the primary UI indicator

## §6. Cancellation Mechanism

### Existing Capability

Stream cancellation already exists: `/api/v1/chat/stream/{id}/cancel` closes the queue consumer; the producer discovers the closed queue on the next `put` and exits.

### Planning-Phase Cancellation

The `PlanningTimeline` cancel button triggers:

1. Call existing stream cancel endpoint
2. Producer catches `CancelledError` → emits `plan_progress(failed, error='cancelled')`
3. Frontend displays "已取消" briefly, then fades out the timeline

### Behavior

- Any partial scout results or in-progress plan decomposition are **discarded** (aligned with Claude Code behavior)
- The user message remains in the chat; the user can re-submit or modify
- No orphaned tasks are created (planning happens before `task_plan`)

## §7. Phased Delivery Plan

### P1: Visibility Minimum (1 PR, main + cherry-pick win7)

**Backend**:
- Define `plan_progress` event type
- Implement `run_planning_stage` wrapper with heartbeat
- Wrap **6 stages**: `mode_classify`, `complexity_classify`, `clarify`, `scout`, `scout_deep`, `decompose`
- Emit `started/done/skipped/failed` events (no `progress` yet)
- Fix field bug: rename `phase` → `preflight_phase` in `orch_preflight` emit
- Keep `orch_preflight` emit for backward compat (1 release cycle)
- Planner still uses `complete()` (no streaming yet)

**Frontend**:
- Add `planProgress` slot to `chatStreamStore`
- Add `PlanProgressEvent` type to `chatAndEventTypes`
- Add consumer in `orchestrationEvents`
- New `PlanningTimeline` component (basic version):
  - Stage rows with status icons + elapsed time
  - Heartbeat timer
  - Cancel button
  - Collapse to summary on `task_plan`
- Remove PlanApprovalBar preflight indicator (lines 310-324)
- Fix field contract: backend `phase` → `preflight_phase`, update tests

**Tests**:
- Backend: 5-stage emit test (started/done/skipped/failed); heartbeat cancellation test
- Frontend: PlanningTimeline render/collapse/cancel tests
- Contract: e2e test verifying backend event shape matches frontend type

**Files** (estimated):
- `backend/orchestration/plan_progress.py` (new: wrapper + helpers)
- `backend/orchestration/plan_preflight.py` (modify: wrap stages, fix field name)
- `backend/orchestration/complexity_classifier.py` (modify: wrap stage)
- `backend/orchestration/chat_dispatcher.py` (modify: wrap mode classify)
- `backend/api/legacy_routes.py` (modify: emit mode_classify event)
- `backend/tests/unit/test_plan_progress.py` (new)
- `backend/tests/unit/test_plan_preflight.py` (modify: fix field assertions)
- `src/shared/api/types/chatAndEventTypes.ts` (modify: add PlanProgressEvent)
- `src/features/send-message/chatStreamStore.ts` (modify: add planProgress slot)
- `src/features/send-message/orchestrationEvents.ts` (modify: add consumer)
- `src/widgets/chat/PlanningTimeline.tsx` (new)
- `src/pages/Chat.tsx` (modify: inject PlanningTimeline)
- `src/pages/chat/PlanApprovalBar.tsx` (modify: remove preflight indicator)
- `src/features/send-message/__tests__/orchestrationEvents.test.ts` (modify: add plan_progress tests)
- `src/widgets/chat/__tests__/PlanningTimeline.test.tsx` (new)

### P2: Live Research Steps (1 PR)

**Backend**:
- `_run_scout_agent`: mirror subagent thinking/tool_call/tool_result as `plan_progress(progress, kind=...)` with 100ms throttle
- `scout_deep.py`: add `on_progress` callback; forward progress events (file reads, searches, summaries) as `plan_progress(progress, kind=tool_call/tool_result)`
- Apply `redact_sensitive_args` to mirrored tool call arguments

**Frontend**:
- Enhance `PlanningTimeline`:
  - Add expandable sub-rows for scout/decompose stages
  - Render tool calls / thinking using `EventTimelineRow` (reuse from SubagentLivePanel)
  - Add right panel linkage (PlanningTimeline and SubagentLivePanel share data source)

**Tests**:
- Backend: mirror throttle test; deep research progress test
- Frontend: sub-row expand/collapse test; right panel sync test

### P3: Streaming Planner + Utility Optimization (1 PR)

**Backend**:
- `planner.py`: switch `complete()` → `stream_chat()`; forward `reasoning_delta` as `plan_progress(progress, kind=reasoning)` with 50ms throttle
- New `build_utility_llm_client(task_type)` factory in `llm_factory.py`
- Replace 5 call sites with utility client:
  - `legacy_routes.py:921` (mode classify) → `task_type="classification"`
  - `plan_preflight.py:217` (complexity classify) → `task_type="classification"`
  - `plan_preflight.py:353` (clarify) → `task_type="planning"`
  - `plan_preflight.py:491` (scout) → utility client, no routing
  - `planner.py` default client → `task_type="planning"`

**Frontend**:
- Enhance `PlanningTimeline`:
  - Add reasoning collapsible block (reference thinking display modes: detail/trace/result)

**Tests**:
- Backend: Planner streaming test; malformed JSON degradation test; utility client no-reasoning test
- Frontend: reasoning block render test

**Optional**:
- Expose setting `orch.disablePlanningReasoning` (default true)
- Document auto-routing integration with `routing.mode=auto`

## §8. Dual-Branch Alignment

### Strategy

- P1, P2, P3 each merge to `main` first, then cherry-pick to `release/win7`
- Win7 compatibility checks:
  - Use `Optional[str]` instead of `str | None` (PEP 483 vs PEP 604)
  - Use `Dict/List` instead of `dict/list` for type hints (PEP 585)
  - Verify py38 compatibility with `check_py38_compat` script
- Update architecture baseline per branch (ratchet values differ)

### Documentation

- `docs/technical/`: add a new section (number per branch实测) describing the `plan_progress` protocol
- `docs/user-manual/`: add a section "规划过程可视化" explaining the PlanningTimeline UI

## §9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Planner streaming breaks JSON parsing | Stream only forwards reasoning; content accumulates to full string before parsing; failure degrades to `_simple_decompose` |
| Event flood overwhelms frontend | Each stage's progress events are throttled (thinking 100ms, reasoning 50ms, tool calls unmerged but capped at 200 per stage) |
| Cancel planning leaks LLM request | Producer cancel → asyncio.Task cancelled → `stream_chat` closes underlying httpx request via `asyncio.CancelledError` |
| Field contract rename breaks existing tests | P1 updates `test_plan_preflight.py` + `orchestrationEvents.test.ts`; keeps 2-week compat emit |
| Scout mirror exposes sensitive args | Reuse M4.1 `redact_sensitive_args` sanitization |
| Win7 sync conflicts | Merge main first, cherry-pick with实测 ratchet values (follow historical PR pattern) |

## §10. Testing Strategy

### Backend Tests

**Unit tests**:
- `test_plan_progress.py`:
  - 5-stage emit test: verify `started/done/skipped/failed` events for each stage
  - Heartbeat test: verify heartbeat events emitted every 5s during long stage
  - Cancellation test: verify `CancelledError` triggers `failed` event with `error='cancelled'`
  - Throttle test: verify scout mirror respects 100ms throttle
  - Argument sanitization test: verify mirrored tool calls are redacted

**Integration tests**:
- `test_plan_preflight.py`: update field assertions from `phase` to `preflight_phase`
- `test_planner.py`: add streaming test (mock `stream_chat`, verify reasoning deltas forwarded)
- `test_llm_factory.py`: add `build_utility_llm_client` test (verify reasoning disabled by default)

**Contract test**:
- E2E test that sends a message, captures all NDJSON events, and verifies `plan_progress` event shapes match frontend type

### Frontend Tests

**Unit tests**:
- `PlanningTimeline.test.tsx`:
  - Render test: verify stage rows rendered for each status
  - Collapse test: verify collapse to summary on `task_plan`
  - Cancel test: verify cancel button calls stream cancel endpoint
  - Expand test: verify sub-rows expand/collapse for scout/decompose stages

**Integration tests**:
- `orchestrationEvents.test.ts`:
  - Add `plan_progress` consumer test: verify `appendPlanProgress` called, `planningDone` set on `decompose` done
  - Verify `task_plan` clears `planProgress` and sets summary

**Replay test**:
- Verify `reattachActiveStream` replays `plan_progress` events and restores `PlanningTimeline` state

### Test Coverage Target

- Backend: 80%+ coverage for new `plan_progress.py` module
- Frontend: 80%+ coverage for new `PlanningTimeline.tsx` component
- Contract: 100% coverage for event shape validation

## §11. Success Criteria

### Functional

- User sees **every planning stage** in real-time (mode classify, complexity classify, clarify, scout, decompose)
- User sees **scout tool calls and thinking** in real-time (throttled)
- User sees **Planner reasoning** in real-time (throttled, collapsible)
- User can **cancel planning** mid-stream
- Planning progress **collapses to summary** after plan card arrives
- Utility calls are **faster** (no reasoning overhead; optional auto-routing)

### Performance

- Total planning phase latency reduced by **50–80%** (from ~3 minutes to ~30 seconds with auto-routing)
- Event rate capped at **~10 events/second** (throttled)
- No UI jank during planning (events processed asynchronously)

### Compatibility

- Existing plan approval flow unchanged
- Existing `research_complete` / `ResearchSummaryCard` flow unchanged
- Backward compat for `orch_preflight` events (1 release cycle)

## §12. Future Extensions

- **Cost estimation during planning**: show estimated cost of the plan before approval (requires `orch_tasks` composite PK migration, already done)
- **Planning history**: persist `plan_progress` events to allow replay of past planning sessions (requires new `orch_plan_progress` table)
- **Multi-planner comparison**: generate multiple plans in parallel and let user choose (requires parallel `plan_progress` streams)
- **Planning quality metrics**: track which planning stages are most often skipped/failed to optimize the flow

## §13. References

- Mainstream AI applications:
  - Claude Code plan flow: inline thinking + tool calls + stage progress
  - ChatGPT Deep Research: real-time search steps + source cards
  - Manus execution cards: live tool execution + thinking stream
- Existing Sage infrastructure:
  - `SubagentLivePanel`: reusable row rendering for tool calls / thinking
  - `progressFormat.formatDuration`: duration formatting
  - `permission_gate.redact_sensitive_args`: argument sanitization (M4.1)
  - `runControlClient.cancelRun`: cancellation mechanism
  - `apply_auto_routing_overlay`: model routing by task_type
- Related Sage features:
  - M4.1 transcript sanitization (PR #3241/#3246)
  - M4.3b cost attribution (PR #3243/#3247)
  - §15 composite primary key migration (PR #3253/#3257)
