# 2026-10-26 编排计划体验优化

## 背景与目标

用户在主会话中提出复杂任务时，LLM 会进入多代理编排（multi-agent orchestration）流程。当前体验有三个问题：

1. **编排过程是黑盒** —— 计划卡片出现前，用户看不到任何 LLM 思考/拆解过程，只有一行"正在澄清需求…/正在侦察收集事实…"的脉冲文本。普通对话流里 `ThinkingPanel` 能显示 `reasoning_content`，编排路径没有对应通道。
2. **计划卡片执行后不消失** —— 点击"开始执行"后，卡片仍留在会话区底部占据大量视觉空间，直到收到第一个 `task_status` 事件才卸载。
3. **计划生成后无法对话调整** —— 用户只能逐行编辑 textarea、删除行，或整体"开始执行/取消"。无法用自然语言表达"把第 2 项拆成两步"这类修订意图。

本方案在一次改动内同时解决这三项，并顺带修复一个阻塞性缺陷（见下）。

## 阻塞性缺陷（本次必须一并修复）

**`POST /orch/runs/{id}/plan` 在确认窗口内的修改会被静默丢弃。**

`backend/api/legacy_routes.py` 的 producer 流程顺序为：

| 行号 | 动作 |
|------|------|
| ~759-820 | 构建内存变量 `plan_items` |
| ~904-955 | `system_content += plan_block` —— **计划文本在此刻已嵌入 system prompt** |
| ~981 | 推 `task_plan` 事件（前端 PlanCard 渲染） |
| ~1019 | **确认门控** `await asyncio.wait_for(confirm_event.wait())` |

用户在前端点击"开始执行"之前，`system_content` 已经构造完毕。用户在 PlanCard 里编辑 goal 或调用 `update_plan`，后端 `orch_routes.py:307-318` 只写 `orch_runs.plan_json`，而 producer 醒来后继续使用**旧的内存 `plan_items`**，从未回读数据库。

**后果**：PlanCard 的 textarea 编辑目前完全无效；问题 3 的修订通道若建立在 `update_plan` 之上同样无效。

**修复**：把计划块注入 `system_content` 的动作移到确认门控**之后**，并在门控通过时从 `orch_runs.plan_json` 回读用户修订后的计划；回读失败则回落到内存 `plan_items`。

## 涉及文件与模块

### 后端

| 文件 | 改动 |
|------|------|
| `backend/api/legacy_routes.py` | 计划块构建移到确认门控之后；门控后回读 DB 计划；`task_plan` 事件新增 `reasoning` 字段 |
| `backend/api/orch_routes.py` | `/plan` 更新保留原 reasoning；`/plan-items` 支持 `current_plan` 修订语义（新增修订 prompt） |
| `backend/data/orch_run_repo.py` | 无需改动（`get()` 已可读 `plan_json`） |

### 前端

| 文件 | 改动 |
|------|------|
| `src/shared/api/types/chatAndEventTypes.ts` | `TaskPlanEvent` 新增 `reasoning?: string` |
| `src/features/send-message/chatStreamStore.ts` | `TaskBoardState` 新增 `reasoning?: string` |
| `src/features/send-message/orchestrationEvents.ts` | `task_plan` 分支写入 `reasoning` |
| `src/components/PlanCard.tsx` | 乐观折叠态（含展开回看）；规划思路折叠块；修订说明输入区（`onRevise` 委托上层） |
| `src/pages/chat/PlanApprovalBar.tsx` | 透传 `reasoning`；接住 `planItemsFromText` 的 `reasoning`；修订结果落库 + 同步回 store |
| `src/shared/api/orchRunClient.ts` | `planItemsFromText` 增加 `currentPlan` 参数 |
| `electron/commandRoutes/orchestration.ts` | `orchestration_plan_items` 请求体透传 `current_plan` |

## 技术方案

### 方案一：编排推理可见（问题 1）

后端 `plan.reasoning` 已经存在（`backend/orchestration/planner.py:241`，由 `_build_decomposition_prompt` → `decompose_request` 产出），并在 `init_orch_run` 时写入了 `orch_runs.plan_json`，但**从未随事件下发**。

- 后端：`task_plan` 事件体增加 `"reasoning": reasoning`（复用 `legacy_routes.py:963-968` 已算好的局部变量）。
- 前端：`TaskPlanEvent.reasoning` → `TaskBoardState.reasoning` → PlanCard 顶部渲染"规划思路"折叠块（默认折叠，展示首行摘要，可展开全文）。

同时把 `PlanApprovalBar.tsx:84` 丢弃的 `planItemsFromText()` 返回 `reasoning` 接住并展示 —— 该字段后端已返回，属于零成本信息回收。

**不做**：把 planner / classifier 的 LLM 调用改成流式（后端是 `llm_client.complete()` 非流式调用）。成本高、收益边际，折叠块已经能回答"为什么这样拆解"。

### 方案二：计划卡片乐观折叠（问题 2）

- `PlanCard` 增加本地 `collapsed` 状态。
- 点击"开始执行"成功后**立即**置 `collapsed=true`（乐观更新，不等 `task_status` 事件）。折叠态渲染为一行摘要：`编排计划 · N 项 · 已开始执行`，右侧一个"展开"按钮。
- 派发后 `taskBoard.dispatchedAt` 被置位 → `PlanApprovalBar` 卸载 PlanCard → 卡片彻底离开会话区（现有行为）。
- 折叠态与展开态之间的高度差 ≈ 200px → 60px，解决"占据大量视觉区域"。

**不做**：把卡片整体迁移到右栏任务树。右栏 `TaskTreeSection` 已承担"派发后的计划视图"，会话区底部也已有 `SubagentLivePanel`（运行中）+ `RunSummaryPanel`（结束后）在消息区**之外**渲染。迁移属于结构调整，收益与风险不匹配。

### 方案三：计划修订通道（问题 3）

复用已有的 `POST /api/v1/orch/plan-items` 端点（LLM 把计划文本结构化成任务项）。当前该端点只支持"文本 → 任务列表"，语义是**首次拆解**，不适合"修订"。

- 后端：`PlanItemsRequest` 增加可选字段 `current_plan: Optional[List[PlanItem]]`。
  - `current_plan` 为空 → 走现有 `_PLAN_ITEMS_PROMPT`（首次拆解语义，行为不变，向后兼容）。
  - `current_plan` 非空 → 走新增 `_PLAN_REVISION_PROMPT`：给定当前计划 + 用户修订说明，输出修订后的任务列表，保持未提及的任务原样。
- 前端：PlanCard 增加"修订说明"textarea + "应用修订"按钮：
  1. 收集当前 items + 用户输入 → 调 `orchRunClient.planItemsFromText(instruction, currentPlan=items)`；
  2. 拿到新 items → `orchRunClient.updatePlan(runId, newItems)` 落库；
  3. 更新 store 的 `taskBoard.plan` 并刷新卡片。
- 配合上文的缺陷修复：producer 在确认门控后回读 DB，用户修订后的计划才会真正进入 system prompt。

失败路径：LLM 未配置（503）→ toast 提示；解析失败（502）→ toast 提示并保留原计划，卡片不变。

## 实施步骤

- [x] 步骤 0：新建 worktree `feat/orchestration-plan-ux`（base `origin/main`），端口 8773/1428
- [x] 步骤 1：后端 —— `update_plan` 保留 reasoning；`/plan-items` 增加 `current_plan` + 修订 prompt；补后端测试
- [x] 步骤 2：后端 —— 计划块构建移到确认门控之后 + 门控后回读 DB 计划；`task_plan` 事件带 `reasoning`；补后端测试
- [x] 步骤 3：前端 —— 类型与 store 扩展（`TaskPlanEvent.reasoning` / `TaskBoardState.reasoning`）
- [x] 步骤 4：前端 —— `PlanCard` 折叠态 + 规划思路折叠块 + 修订说明区
- [x] 步骤 5：前端 —— `PlanApprovalBar` 接线（reasoning 展示、修订结果同步回 store）；`orchRunClient` / electron 命令透传 `current_plan`
- [x] 步骤 6：验证 —— 前端 `tsc` + `vitest`；后端 `pytest` + `ruff`；修测试
- [x] 步骤 6b：code review 复查轮 —— 修 2 HIGH / 4 MEDIUM / 4 LOW（见下方风险表「复查新增」段）
- [x] 步骤 7：提交（本地 commit `b47a0ba57`）→ 推送 + 开 PR #2567
- [x] 步骤 8：修 CI Architecture 红灯 —— 本功能给 `legacy_routes.py` 净增 57 行，超过 baseline 2455 的棘轮上限。把三个编排计划助手（`PLAN_OVERRIDE_REASONING` / `build_orch_plan_block` / `load_confirmed_plan_items`）原样拆到新模块 `backend/api/orch_plan_block.py`，`legacy_routes.py` 降回 2420 行（门禁计 2421 < 2455），**不改 baseline**（commit `dbf9d052d`）
- [x] 步骤 9：修第二个 Architecture 超限项 —— `backend/tests/integration/test_chat_orchestration_stream.py` 被本功能加到 843 行（门禁计数，> 800 全局上限）。把「reasoning 下发」与「确认窗口内改计划回读」两个测试连同私有助手迁到 `test_chat_orchestration_plan_confirm.py`，原文件回落到 710 行（commit `90effbad6`）
- [x] 步骤 10：修步骤 8 引入的回归 —— `test_chat_dispatcher_budget.py::test_background_guide_documents_snapshot_strategy` 仍扫描 `legacy_routes.py` 源码找 `wait=false` / `提前汇总`，而这些文案已随计划块迁入 `orch_plan_block.py`；改扫描新模块（commit `5460b0186`）

## 风险评估与依赖

| 风险 | 等级 | 缓解 |
|------|------|------|
| 计划块构建位置调整影响既有编排行为 | 高 | 块内容逐字不变，只改执行时机；补一个"确认后 plan 变更生效"的集成测试 |
| `update_plan` 写库后 producer 回读，若 run 已被取消则读不到 | 中 | 回读失败静默回落到内存 `plan_items`（原行为）；兜底分支逐条单测 |
| 修订 prompt 与首次拆解 prompt 混用导致语义漂移 | 中 | 两个 prompt 完全分离；`current_plan` 为空走老路径，回归测试覆盖 |
| `POST /plan-items` 语义扩展影响既有调用方 | 低 | `current_plan` 为可选字段；前端唯一调用方 `PlanApprovalBar` 不传该字段时行为不变 |
| 折叠态丢失用户未提交的 textarea 编辑 | 低 | 折叠前先把本地 items 落库（复用 `updatePlan`），折叠只是视觉状态 |
| win7 分支需同步 | 中 | 本改动含后端 Python（pydantic v1/v2 差异需适配）+ 前端；合并到 main 后按 CLAUDE.md 双分支策略 cherry-pick 到 `release/win7` |

### 复查新增风险（步骤 6b，均已落地缓解）

| 风险 | 等级 | 缓解 |
|------|------|------|
| NDJSON 重放（reattach / 切会话）把同一 run 的 `task_plan` 再推一遍，无条件重建任务板会冲掉用户的 goal 编辑与自然语言修订 | 高 | `orchestrationEvents` 的 `task_plan` 分支改为「同 run 不覆盖、不同 run 才替换」；`PlanCard` 的 `initialPlan` 同步 effect 随之安全 |
| 修订（5-30s LLM 往返）与开始执行是同一个 `plan_json` 的竞争写者，并发时 conductor 可能执行旧计划而界面显示新计划 | 高 | 双向互斥：修订中禁用「开始执行」；开始执行飞行中拒绝修订并 toast |
| `current_plan` 无上限，病态 body 经 `json.dumps` 拼进 prompt 可撑出百万 token | 中 | 显式运行时校验 422（不用 pydantic `Field(max_items=)` —— v1/v2 参数名不同，会踩双版本差异） |
| 修订后 `task_progress.total` 仍是旧值，而前端聚合只增不减 → 5 项改 2 项后长期显示「0/5」 | 中 | `PlanApprovalBar` 回写 store 时同步修正 `progress.total` |
| `plan_override` 哨兵值经 `task_plan.reasoning` 外泄，被 PlanCard「规划思路」区块原文展示给用户 | 低 | 落库 `plan_json` 保留哨兵（后端内部标记），事件侧过滤成空串；集成测试断言 |
| 计划 prompt 占位符用链式 `.replace()`，注入值里的花括号字面量会被后续替换污染 | 低 | 改单遍 `re.sub` + 查表（`_fill_plan_prompt`），只扫模板不扫注入值 |


## 依赖

- 无新增第三方依赖。
- 后端测试使用 `sage-backend` conda 环境（Python 3.10）。
- 不改数据库 schema（`plan_json` 复用）。
