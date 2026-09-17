# 编码代理对标差距分析·第二十四轮：任务级消耗准确性与时长可见性（BU13）

- **状态**：批次 A 交付中（分支 `feat-parity-r24-batch-a`，基线 origin/main d9b515ff = #1084）
- **上游文档**：round20（BU9 run 窗口累计）、round23（RT23 task_id 归因管道）
- **对标对象**：Claude Code（每个 Task 工具调用报告自身 token 消耗与时长）、Cursor（agent 步骤耗时）
- **编号约定**：延续 BU 系

## 0. 结论速览

RT23 打通了 usage_events.task_id 归因管道并新增 `task_usage_since()` 查询，但
`_emit_task_status` 终态事件仍在用 `session_usage_since`（run 窗口累计）——
**前端每个任务拿到的是整 run 累计值而非本任务消耗**；且 `used_tokens` 被
`run_token_budget > 0` 门槛挡住（预算关闭时完全不可见）；终态事件无时长。
本轮收口三件事。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| BU13-a | 终态 `used_tokens` 用 run 窗口累计而非 per-task 查询 | `chat_dispatcher._emit_task_status` 调 `session_usage_since`；`task_usage_since` 零调用 | Claude Code per-task token | **P1** |
| BU13-b | `used_tokens` 事件被 `run_token_budget > 0` 门槛挡住 | 同上 if 条件 | Claude Code 始终可见 | **P2** |
| BU13-c | 终态事件无 `duration_ms` | event dict 无时长字段；state.started_at/finished_at 已有 | Cursor 步骤耗时 | **P2** |

## 2. 设计（批次 A：BU13）

- **per-task 查询**：终态事件改调 `task_usage_since(session_id, task_id, since_ms)`，
  since = run 首派发时间（窗口仍约束本 run，跨 run 不串）。preset 回放任务
  零 LLM 调用 → 查询得 0，如实上报。lane 内重试共享 task_id → 重试消耗计入本任务。
- **门槛解除**：`used_tokens` 仅要求 `session_id` + `first_dispatch_at` 就绪
  （预算关闭也带键）；查询 fail-open 不带键，语义与 BU9 一致。
- **时长**：`duration_ms = (finished_at - started_at) * 1000`，二者齐备才带键。
- **前端**：
  - 进度行总量 `Math.max`（累计语义）→ **求和**（per-task 语义，值互不重叠）；
  - 展示门槛从 `runTokenBudget > 0` 放宽为 `usedTokens > 0`；
  - 任务行终态徽章：`· N tokens`（>=1000 显 k）+ `· M.Ms`；
  - `TaskStatusEvent` 类型补 `duration_ms?: number`。

## 3. 批次 A 实施与验证记录

- **chat_dispatcher._emit_task_status**：终态事件改调
  `UsageTracker().task_usage_since(session_id, task_id, first_dispatch_at*1000)`
  （per-task 归因，窗口不跨 run）；去掉 `run_token_budget > 0` 门槛（预算关闭
  也带键）；终态补 `duration_ms`（started_at/finished_at 齐备才带键）。
- **RT23 补测回填**：发现 #1049（main 落地 RT23 代码）未携带其 6 例测试——
  本轮补齐 `task_usage_since` 窗口/任务过滤、fail-open、ContextVar→落库归因三测。
- **前端**：`TaskStatusEvent` 补 `duration_ms?`；进度行总量 Math.max（累计语义）
  → reduce 求和（per-task 语义），展示门槛从 `runTokenBudget > 0` 放宽为
  `usedTokens > 0`；任务行新增 `task-tree-usage-<id>` 徽章（tokens k 格式化 +
  时长 ms/s 自适应）；移除组件内不再使用的 `useSettings`/`runTokenBudget`。
- 验证：backend `test_chat_dispatcher_budget.py` 12 例（含 5 例新增）+ 相邻
  persistence/wall_clock/usage_tracker 49 例全绿；ruff 全过；前端 vitest 10 例
  全绿、`tsc --noEmit` 干净、eslint 改动文件零告警。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
