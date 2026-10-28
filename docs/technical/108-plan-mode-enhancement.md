# Plan Mode 增强：复杂度驱动 + 深度调研 + 智能确认

**日期**：2026-10-28
**分支**：feat/plan-mode-enhancement
**相关计划**：[`docs/plans/2026-10-28_plan-mode-enhancement.md`](../plans/2026-10-28_plan-mode-enhancement.md)

---

## 1. 背景与目标

Sage 原有 plan 基础设施（`/plan` 斜杠命令、`PlanApprovalBar`、`PlanCard`、`plan_preflight.scout` 4 轮轻量侦察）对**所有任务一视同仁**：

- 调研深度固定，复杂任务调研不充分；
- 确认点固定为执行前 1 次，无法覆盖破坏性步骤；
- 执行模式（单 agent / 编排）需用户手动选择，无智能推荐。

本增强引入**复杂度驱动**的 plan 流程，三个正交能力：

| 能力 | 模块 | 解决的问题 |
|------|------|-----------|
| 复杂度分类 | `complexity_classifier` | 决定调研深度与确认策略 |
| 执行模式分类 | `execution_mode_classifier` | 给出 single/multi/ask_user 推荐 |
| 步骤级确认 | `confirm_marker` + dispatcher 门控 | 破坏性步骤执行前暂停 |

复杂度矩阵（最终落地语义）：

| complexity | 调研策略 | 确认策略 | 示例 |
|------------|----------|----------|------|
| `simple` | 跳过 scout | 0 确认点 | 修 typo、改颜色 |
| `medium` | scout_lite（4 轮） | 1 确认点（整体确认） | 加按钮、重构函数 |
| `complex` | scout_deep（WikiResearch） | N 确认点（命中规则的步骤前） | 设计认证系统、性能优化 |

> **实现偏差说明**：原计划写的是"仅 complex 任务启用步骤确认"，落地时改为**由请求参数 `step_confirm` 显式开启**，再由 `confirm_marker` 规则引擎决定哪些步骤命中。原因：复杂度分类在前端 `/plan` 阶段完成，而 dispatcher 运行在另一条流上，把复杂度隐式传导到 dispatcher 会引入额外状态耦合；显式开关更可测、可回滚。

---

## 2. 架构总览

```
用户 /plan 目标
      │
      ▼
┌──────────────────────────┐
│ complexity_classifier    │  LLM ~500 token → simple/medium/complex
│ (backend/orchestration)  │
└──────────┬───────────────┘
           │ complex & research_needed
           ▼
┌──────────────────────────┐      ┌────────────────────┐
│ scout_deep               │─────▶│ ResearchReport     │
│ (复用 WikiResearch 后端) │      │ findings/sources/  │
└──────────┬───────────────┘      │ confidence/effort  │
           │ 降级：超时/无配置     └─────────┬──────────┘
           ▼                                  ▼
┌──────────────────────────┐      ┌────────────────────┐
│ plan_preflight.scout     │      │ ResearchSummaryCard│ (前端审阅)
└──────────┬───────────────┘      └─────────┬──────────┘
           ▼                                │ [基于调研生成 Plan]
┌──────────────────────────┐◀───────────────┘
│ planner：生成 plan_items │
└──────────┬───────────────┘
           ▼
┌──────────────────────────┐   LLM ~300 token
│ execution_mode_classifier│──────────────▶ plan_execution_mode 事件
└──────────────────────────┘                       │
           ▼                                       ▼
   PlanApprovalBar 展示推荐模式 + 用户覆盖（ExecutionModePicker）
           │ 用户确认
           ▼
┌──────────────────────────────────────────────────────────┐
│ ChatDispatcher                                            │
│  per-run 状态：_pending_step_confirms / _step_confirm_enabled │
│  派发每个 task 前：                                        │
│    _plan_item_auto_confirm(task_id)                       │
│      → confirm_marker.mark(item)                          │
│      → True → awaiting_step_confirm 事件 → 等待用户        │
│      → continue / skip / abort / 600s 超时                │
└──────────────────────────────────────────────────────────┘
```

---

## 3. 后端模块

### 3.1 `backend/orchestration/complexity_classifier.py`（227 行）

```python
@dataclass
class ComplexityClassification:
    complexity: ComplexityLevel        # "simple" | "medium" | "complex"
    research_needed: bool
    reasoning: str
```

- `ComplexityClassifier.classify(message, context)`：单次 LLM 调用，同时判定复杂度与是否需调研。
- 便捷函数 `classify_complexity(...)` 供 `plan_preflight` 调用。
- 解析容错：剥离 ```` ```json ```` / ```` ``` ```` 围栏；JSON 解析失败或取值越界 → 保守降级为 `medium`。

### 3.2 `backend/orchestration/execution_mode_classifier.py`（256 行）

```python
@dataclass
class ExecutionModeClassification:
    mode: ExecutionMode        # "single" | "multi" | "ask_user"
    confidence: float          # 0-1
    reasoning: str
```

- 输入为计划全文，截断至 `MAX_PLAN_TEXT_CHARS = 4000` 后注入 prompt。
- 决策规则固化在 prompt：步骤 < 3 或无并行可能 → `single`；≥ 3 且有独立步骤 / 跨文件 > 5 → `multi`；强依赖链 → `single`；confidence < 0.7 → `ask_user`。
- 便捷函数 `classify_execution_mode(plan)`；解析失败 → `ask_user`（保守，让用户决定）。

### 3.3 `backend/orchestration/research_report.py`（269 行）

| 数据类 | 字段 |
|--------|------|
| `ResearchFinding` | `title`, `summary`, `relevance`（high/medium/low）, `sources: List[str]` |
| `ResearchSource` | `url`, `title`, `snippet` |
| `ResearchReport` | `topic`, `findings[]`, `sources[]`, `confidence: float`, `estimated_effort`（低/中/高）, `synthesis` |

- `build_report_from_research_task(task)`：把 WikiResearch 的 `ResearchTask` 投影为 `ResearchReport`。
- `_estimate_confidence(synthesis, web_results)` / `_estimate_effort(...)`：启发式打分（非 LLM）。
- `to_planner_context(max_chars=4000)`：产出喂给 planner 的紧凑文本，避免整段 synthesis 挤占上下文。

### 3.4 `backend/orchestration/scout_deep.py`（132 行）

```python
SCOUT_DEEP_TIMEOUT_S = 120

async def research(topic: str, project_path: Path, settings: Any = None) -> ResearchReport
```

- 复用 WikiResearch 的 `deep_research()` 后端（不经过前端 UI）。
- 降级铁律：LLM 配置缺失 / `deep_research()` 抛异常 / `task.status == "error"` / `synthesis` 为空 → 一律返回空报告（`confidence=0`），由调用方回落 scout_lite。

### 3.5 `backend/orchestration/confirm_marker.py`（186 行）

纯正则规则引擎，零 LLM、零 I/O：

```python
def mark(step: StepLike) -> bool
def mark_batch(steps: List[StepLike]) -> List[bool]
def matched_categories(step: StepLike) -> List[str]
```

`StepLike` 兼容 `dict`（`goal` / `title` / `description` / `content` 等键）与普通对象；`_extract_goal()` 归一化取文本。

规则类别（编译一次，模块级 `_RULES` 复用）：

| 类别 | 触发示例 |
|------|----------|
| `file_delete` | `rm -rf` / `rm -r` / `rm <path>` / `unlink` / `shred` / 删除文件 / 移除文件 / 永久删除 / 批量删除 / 清空目录 |
| `external_api` | 调用 API / HTTP 请求 / webhook / `fetch(` / `requests.` / `httpx.` / `curl ` / `POST https://` / `PUT https://` |
| `db_write` | 数据库写操作类关键词（INSERT/UPDATE/DELETE/迁移等） |
| `privileged` | force push / publish / 发布 / 提权类操作 |

### 3.6 `backend/orchestration/chat_dispatcher.py`（2418 行）

Phase 3 新增的 per-run 状态与门控：

- 构造参数 `step_confirm: bool = False` → `self._step_confirm_enabled`；
- `self._pending_step_confirms: Dict[str, asyncio.Future]` 保存待确认任务；
- 派发前 `_run_one_inner` 调用 `_plan_item_auto_confirm(task_id)`：

```python
def _plan_item_auto_confirm(self, task_id: str) -> bool:
    if not self._step_confirm_enabled:
        return False
    item = self._plan_by_id.get(task_id)
    if not item:
        return False
    try:
        from backend.orchestration.confirm_marker import mark
        return mark(item)
    except Exception as exc:  # noqa: BLE001 — 规则引擎故障不阻塞派发
        logger.debug("confirm_marker 求值失败 task=%s: %s", task_id, exc)
        return False
```

> **为何在派发时求值，而不是建计划时打标**：`update_plan` 会用前端回传的 items 覆盖 `plan_json`，建计划阶段写入的 `auto_confirm` 标记会被抹掉。派发时基于最新 goal 重新求值，天然免疫该覆盖问题。

- `_await_step_confirm(state, task_skip=None)`：`asyncio.wait` 三路竞速「用户响应 Future」/ run 级 `self._cancelled` / 单任务跳过事件 `task_skip`，`STEP_CONFIRM_TIMEOUT_SECONDS = 600`；超时/run 取消一律按 `abort` 收口，单任务跳过按 `skip` 收口（否则用户点了"跳过任务"还要等 10 分钟）。
- `resolve_step_confirm(task_id, action)`：设置 Future 结果；无 pending → 返回 False（路由层据此回 409）。
- `_resolve_all_step_confirms(action)`：run 取消时统一收口，避免 Future 泄漏。

### 3.7 传输链路

| 层 | 文件 | 改动 |
|----|------|------|
| 请求模型 | `backend/api/legacy_models.py` | `ChatRequest.step_confirm: Optional[bool] = None`（三态：`None` = 自动、`True`/`False` = 显式覆盖） |
| 流式入口 | `backend/api/legacy_routes.py` | `_resolve_step_confirm_flag()` 按 preflight complexity 推导（自动模式仅 `complex` 启用）后透传到 dispatcher 构造；`_emit_execution_mode_recommendation` 推 `plan_execution_mode`；`agent:research-complete` 推 `research_complete` |
| 构造器 | `backend/api/chat_stream_support.py` | `_build_orchestration_dispatcher(..., step_confirm=False)` |
| 确认端点 | `backend/api/orch_routes.py` | `POST /runs/{run_id}/step-confirm`，`StepConfirmRequest{task_id, action}` → `StepConfirmResponse{ok, run_id, task_id, action}` |

---

## 4. 前端模块

| 文件 | 职责 |
|------|------|
| `src/components/ExecutionModePicker.tsx` | `ask_user` 时弹出，用户强制 single/multi 或取消（取消 = 停止执行、保留 plan） |
| `src/components/ResearchSummaryCard.tsx` | 展示 `ResearchReport`：confidence 进度条、findings、折叠来源；底部 [基于调研生成 Plan] / [补充调研] / [放弃] |
| `src/components/StepConfirmDialog.tsx` | 展示当前步骤 + 影响 + 下一步预览；[继续] / [跳过此步] / [终止全部] |
| `src/pages/chat/PlanApprovalBar.tsx` | 展示推荐模式（绿色高亮）+ 下拉覆盖；在 PlanCard 前插入 ResearchSummaryCard |
| `src/features/send-message/chatStreamStore.ts` | 新增 `executionModeRecommendation` / `researchReport` / `stepConfirm` 三个 per-session 槽位 |
| `src/features/send-message/orchestrationEvents.ts` | 应用器：`plan_execution_mode` / `research_complete` / `awaiting_step_confirm` |
| `src/pages/Chat.tsx` | 订阅 `stepConfirm` 槽位，渲染 `StepConfirmDialog`，回调 `orchRunControlClient.confirmStep` |
| `src/shared/api/orchRunControlClient.ts` | `confirmStep({run_id, task_id, action})` → IPC `orchestration_step_confirm` |
| `electron/commandRoutes/orchestration.ts` | IPC 路由 → `POST /api/v1/orch/runs/{run_id}/step-confirm`，body `{task_id, action}` |
| `electron/ipc-manifest.json` | 登记 `orchestration_step_confirm`（由 `npm run ipc:manifest` 生成） |

### 4.1 `skipped` 状态贯穿

Phase 3 新增 `TaskStatusValue` 的第六个值 `skipped`，需要同步所有 exhaustive 映射：

| 位置 | 处理 |
|------|------|
| `src/shared/api/types/chatAndEventTypes.ts` / `src/shared/api/llmStream.ts` | 两处重复定义同时扩宽 |
| `src/widgets/chat/progress/TaskTreeSection.tsx` | `STATUS_ICON.skipped = '↷'`、`STATUS_TITLE.skipped = 'skipped'` |
| `src/widgets/chat/progress/TodoListSection.tsx` | `ORCH_GLYPH.skipped = '↷'`、`ORCH_LABEL.skipped = '已跳过'` |
| `src/features/send-message/orchestrationEvents.ts` | 进度计数 `counts.skipped` |
| `src/features/send-message/chatStreamStore.ts` | `TaskBoardState.progress.skipped?: number` |
| `src/widgets/chat/RunSummaryPanel.tsx` | 摘要行追加 ` · 跳过 N` |

---

## 5. 事件契约

### 5.1 `plan_execution_mode`（后端 → 前端，SSE 事件）

```jsonc
{
  "state": "plan_execution_mode",
  "session_id": "sess-001",
  "execution_mode": "single" | "multi" | "ask_user",
  "execution_mode_confidence": 0.85,
  "execution_mode_reasoning": "有独立步骤可并行"
}
```

由 `legacy_routes._emit_execution_mode_recommendation` 在 plan 生成后推送。应用器写入 `executionModeRecommendation` 槽位，`PlanApprovalBar` 据此显示推荐。

### 5.2 `research_complete`（后端 → 前端）

```jsonc
{
  "state": "research_complete",
  "research_report": { /* ResearchReport.to_dict() */ }
}
```

`AgentState` 新增 `research_complete`；`agentStateMapping.ts` 中两个 exhaustive switch 各加 case（返回 `null`，不映射为忙碌态）。

### 5.3 `awaiting_step_confirm`（后端 → 前端）

```jsonc
{
  "state": "awaiting_step_confirm",
  "step_confirm": {
    "goal": "删除旧迁移脚本",
    "stepId": "task-3",
    "categories": ["file_delete"],
    "impact": "将删除 3 个文件",          // 可选
    "previousOutput": "…",              // 可选
    "nextStepPreview": "…"              // 可选
  }
}
```

`AgentState` 新增 `awaiting_step_confirm`。前端写入 `stepConfirm` 槽位 → `Chat.tsx` 渲染 `StepConfirmDialog`。

### 5.4 `POST /api/v1/orch/runs/{run_id}/step-confirm`

| 请求 | 说明 |
|------|------|
| body `{task_id, action}` | `action ∈ {continue, skip, abort}` |
| 200 | `{ok: true, run_id, task_id, action}` |
| 404 | run 不在 `_ACTIVE_DISPATCHERS` 中 |
| 409 | 该 task_id 无 pending 确认 |
| 422 | action 非法 |

前端失败处理：即便提交失败也清空本地槽位，避免对话框永久卡死；dispatcher 侧 600s 超时会以 `abort` 收口。

---

## 6. 失败降级

| 失败点 | 行为 |
|--------|------|
| 复杂度分类 LLM 失败 / JSON 解析失败 | 降级 `medium` + `research_needed=false` |
| `scout_deep` 超时（120s）/ 配置缺失 / task error | 返回空报告 → 回落 scout_lite，用户看到轻量调研结果 |
| 执行模式分类失败 | 降级 `ask_user`，让用户选择 |
| `confirm_marker` 抛异常 | **放行**（返回 False，不阻塞派发），`debug` 日志记录 |
| 步骤确认超时 600s | 按 `abort` 处理，run 收口 |
| 等待确认期间单任务跳过（`cancel_task`） | 立即按 `skip` 收口，不等 600s 超时 |
| 步骤确认 IPC 提交失败 | 前端清槽位 + toast；后端靠超时兜底 |
| 前端收到确认事件但缺 runId | toast 提示并清槽位，避免对话框卡死 |

设计原则：**分类/调研能力可失败，调度主链路不可被其阻塞**。

---

## 7. 测试

| 测试文件 | 数量 | 覆盖 |
|----------|------|------|
| `backend/tests/orchestration/test_complexity_classifier.py` | 16 | 解析、降级、便捷函数 |
| `backend/tests/orchestration/test_execution_mode_classifier.py` | 22 | 解析、降级、步骤提取 |
| `backend/tests/orchestration/test_research_report.py` | 22 | schema、投影、confidence/effort 启发式 |
| `backend/tests/orchestration/test_scout_deep.py` | 10 | 正常路径 + 4 类降级 |
| `backend/tests/orchestration/test_confirm_marker.py` | 44 | 4 类规则 + 正常步骤 + 输入形态 + 批量 |
| `backend/tests/api/test_legacy_routes_execution_mode.py` | 12 | `plan_execution_mode` 事件 + `_resolve_step_confirm_flag` 三态 8 例 |
| `backend/tests/unit/test_plan_preflight.py` | 22 | preflight 主流程 + scout_deep 降级回落 2 例 |
| `backend/tests/unit/test_chat_dispatcher_task_skip.py` | 5 | 跳过语义 + 确认等待期跳过立即收口 |
| `src/components/__tests__/ExecutionModePicker.test.tsx` | 7 | 渲染 + 交互 |
| `src/components/__tests__/ResearchSummaryCard.test.tsx` | 17 | 渲染 + 交互 + 折叠 |
| `src/components/__tests__/StepConfirmDialog.test.tsx` | 14 | 渲染 + 三按钮 + 条件渲染 |
| `src/pages/chat/__tests__/PlanApprovalBar.mode-recommendation.test.tsx` | 10 | 推荐展示 + 覆盖选择 |
| `src/features/send-message/__tests__/orchestrationEvents.test.ts` | 9 | store 应用器（执行模式 6 + 步骤确认 3） |

质量门禁：Python AST 解析、ruff、`tsc --noEmit`、architecture-check 全绿；orchestration / dispatcher / 前端相关测试共 250+ 用例通过。

---

## 8. 兼容性与已知限制

**兼容性**

- 所有新请求字段（`step_confirm`）默认 `None`（自动模式：仅 `complex` 任务启用），不改变既有会话行为；显式传 `True` / `False` 可覆盖；
- 新事件状态为增量，旧前端忽略未知 `state`；
- `skipped` 是 `TaskStatusValue` 的新增联合成员，旧事件流不会产生该值；
- `research_complete` / `awaiting_step_confirm` 在 `agentStateMapping` 中返回 `null`，不改变忙碌态判定。

**已知限制**

1. `confirm_marker` 是正则启发式，可能对同义表述漏判或对含关键词的良性步骤误判 —— 因此采用「仅 `complex` 任务自动启用 + 命中才暂停」；误判成本是用户多点一次"继续"。
2. `scout_deep` 依赖 WikiResearch 后端的 `deep_research()`，其质量取决于搜索 API 配置；无 key 时直接返回空报告。
3. 步骤确认目前挂在 `ChatDispatcher`（编排链路），主 agent 的单步执行尚未接入同类门控。
4. 复杂度分类结果暂不落库，刷新页面后需重新分类。

---

## 9. 关键设计决策

| 问题 | 决策 | 理由 |
|------|------|------|
| 复杂度分类器 | LLM 单次调用（~500 token） | 准确率高，成本相对 plan 本身可忽略 |
| 执行模式分类失败 | 降级 `ask_user` | 宁可多问一句，不擅自替用户选模式 |
| scout_deep 输出 | 先展示 ResearchSummaryCard 让用户审阅 | 用户可控，避免盲信调研结论直接进 plan |
| 用户跳过步骤 | 标记 `status: skipped`，继续下一任务 | 灵活，不阻断整条流水线 |
| 用户拒绝选择执行模式 | 停止执行，保留 plan 待审阅 | 安全，避免误操作 |
| 确认点触发 | 纯规则引擎（非 LLM） | 快速、确定、零成本、可单测 |
| 标记求值时机 | 派发时（而非建计划时） | 免疫 `update_plan` 覆盖 `plan_json` |
