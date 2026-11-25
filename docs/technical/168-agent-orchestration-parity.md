# 168 智能体编排协作对标

> 面向后端与前端开发者。说明 Sage 多代理编排的运行模型、真相层、事件流、用量账本、统一任务视图与人工干预接口。早期分层 lane 与计划生命周期实现见 [27](27-multi-agent-orchestration.md)、[36](36-orchestration-e2e.md)、[42](42-chat-multi-agent-orchestration.md)。

Sage 把一次复杂请求拆成「计划 → 并行子代理 → 汇总」的编排 run：计划先由用户确认，任务按依赖调度，执行过程以 canonical 事件流和消息级 transcript 落盘，花费记入可归因的用量账本，前端在会话右栏与任务中心两个入口呈现同一份真相。

## 1. 能力范围与设计约束

| 能力 | 主要实现 | 行为 |
|---|---|---|
| 计划生成与确认 | `backend/orchestration/planner.py`、`src/components/PlanCard.tsx` | 计划卡可编辑，确认后写入 `confirmed_at` 并开始执行 |
| 任务生命周期 | `backend/orchestration/chat_dispatcher.py`、`backend/domain/orch_events.py` | 统一状态机，终态映射为 `task.succeeded/failed/cancelled/skipped` |
| 事件流 | `backend/api/orch_run_control.py` | `orch_events` 追加写，NDJSON 支持 `after_seq` 续传 |
| 消息级过程记录 | `backend/orchestration/transcript.py` | 每次代理迭代落一条 `orch_task_messages`，参数脱敏后入库 |
| 花费归因 | `backend/services/usage_tracker.py`、`backend/data/usage_cost_repo.py` | `usage_events` 带 `run_id` / `task_id`，只统计已知定价行 |
| canonical run 目录 | `backend/api/orch_run_control.py`、`src/entities/orchestration/runDirectoryStore.ts` | 直接投影 `orch_runs` / `orch_tasks`，跨会话可见 |
| 统一任务视图 | `src/features/task-center/unifiedTaskModel.ts` | 目录行与内存任务板按 id 合并，DB 状态优先 |
| 后台子代理 | `backend/tools/agent_tool.py`、`backend/tools/agent_background.py` | `background=true` 独立线程运行，受并发上限约束 |
| 人工干预 | `backend/api/orch_run_control.py`、`backend/api/orch_pause_routes.py` | 暂停/恢复、跳过、重试、续聊、插话（steer） |
| 桌面通知 | `electron/schedulerNotifications.ts`、`electron/orchNotifications.ts` | run 终态入通知队列，点击深链回到会话进度 |

设计上遵守四条边界：

- **数据库是状态真相**。前端 `taskBoard` 只保存实时细节，任务与 run 的权威状态以 `orch_runs` / `orch_tasks` 为准。
- **任务标识必须带 run 维度**。所有任务读写使用 `(run_id, task_id)` 复合键，避免不同 run 复用 `t1`、`t2` 时互相覆盖。
- **金额不写入任务表**。花费单独落在 `usage_events`，任务表只保留 token 与耗时等执行事实。
- **事件只追加、可续传**。`orch_events` 以 `(run_id, seq)` 唯一约束保证顺序，客户端断线后用 `after_seq` 重连。

本 worktree 为 `release/win7`（Python 3.8、pydantic 1.x），相关后端代码避免 PEP 585 / 604 类型语法；前端沿用既有 React + Electron IPC 架构。

## 2. 总体架构与数据流

```text
用户消息
  │
  ├─ Planner 生成计划 ── plan_json / orch_tasks(status=planned)
  │        │
  │        └─ PlanCard 确认 ── confirmed_at，计划锁定
  │
  └─ ChatDispatcher
        ├─ 调度：depends_on 拓扑 + 并发信号量
        ├─ SubagentRunner：每轮迭代写 orch_task_messages
        ├─ EventHub ── orch_events ── NDJSON(/events?after_seq=N)
        ├─ UsageTracker：每次 LLM 调用写 usage_events(run_id, task_id)
        └─ 终态 ── run.completed / run.failed / run.cancelled
```

主要模块：

| 文件 | 职责 |
|---|---|
| `backend/orchestration/planner.py` | 生成计划项，校验 `estimated_iterations`、`complexity`，按设置决定是否允许 `parent_task_id` |
| `backend/orchestration/chat_dispatcher.py` | run 调度、任务状态推进、暂停/恢复、后台派发、续聊、事件 fan-out |
| `backend/orchestration/transcript.py` | `TaskTranscriptRecorder`，把代理迭代写成消息行并做脱敏与截断 |
| `backend/orchestration/subagent_events.py` | 子代理实时事件过滤与转发（工具调用、审批、提问、失败） |
| `backend/domain/orch_events.py` | run / task 状态与事件类型枚举 |
| `backend/api/orch_run_control.py` | run 目录、快照、事件流、transcript、steer、cancel、审批模式、步骤确认 |
| `backend/api/orch_routes.py` | 计划读取/更新、确认、重跑失败任务、单任务取消、plan-items |
| `backend/api/orch_pause_routes.py` | 任务级与 run 级暂停/恢复 |
| `backend/api/chat_stream_support.py` | 流结束时终结 run、发布终态事件、推送通知 |
| `backend/data/orch_task_repo.py` | 任务持久化，冲突目标为 `(run_id, task_id)` |
| `backend/data/usage_cost_repo.py` | 按 `run_id` / `task_id` 聚合已定价金额，失败时 fail-open |
| `src/features/task-center/` | canonical 目录、统一任务模型、任务中心面板 |
| `src/widgets/chat/progress/` | 会话右栏进度面板、任务详情、transcript、steer 输入 |

## 3. 数据模型与迁移

### 3.1 核心表

| 表 | 主键 | 关键列 | 说明 |
|---|---|---|---|
| `orch_runs` | `run_id` | `session_id`、`status`、`created_at`、`plan_json`、`final_summary`、`dispatched_at`、`original_request`、`confirmed_at` | run 级真相；`confirmed_at` 记录用户确认时间 |
| `orch_tasks` | `(run_id, task_id)` | `agent_id`、`goal`、`status`、`parent_task_id`、`depth`、`retry_of`、`used_tokens`、`duration_ms`、`error`、`output_preview` | 任务级真相；同一 `task_id` 可在不同 run 共存 |
| `orch_events` | `event_id` | `run_id`、`seq`、`event_type`、`task_id`、`lane_id`、`occurred_at`、`payload`、`visibility`、`command_id` | 追加事件；`UNIQUE(run_id, seq)`、`UNIQUE(command_id)` |
| `orch_task_messages` | `(run_id, task_id, seq)` | `role`、`message_type`、`content`、`reasoning`、`tool_name`、`tool_call_id`、`tool_args`、`tool_result`、`is_error`、`duration_ms` | 消息级 transcript |
| `orch_context_messages` | 自增 id | `run_id`、`task_id`、`content` 等 | 外键 `(run_id, task_id)` 指向 `orch_tasks` 复合主键 |
| `usage_events` | `id` | `session_id`、`model`、`prompt_tokens`、`completion_tokens`、`total_tokens`、`estimated_cost_usd`、`cached_tokens`、`run_id`、`task_id` | 用量与花费账本；`task_id` / `run_id` 由迁移后置补齐 |

`orch_tasks` 的复合主键是编排正确性的基础。历史上该表以 `task_id` 单列为主键，不同 run 都使用 `t1`、`t2` 时后写覆盖先写，导致旧 run 的任务行被抹掉。

### 3.2 迁移

| 版本 | 名称 | 内容 |
|---|---|---|
| 20 | `usage_events_run_id` | 给 `usage_events` 增加 `run_id`，建立 `idx_usage_events_run(run_id, task_id, created_at)`；仅回填 `run_id IS NULL` 的历史行，来源为 `orch_tasks` 与会话执行时间窗，且要求任务 `started_at` 非空 |
| 21 | `orch_tasks_composite_pk` | 重建 `orch_tasks` 为 `PRIMARY KEY (run_id, task_id)`，重建 `orch_context_messages` 为复合外键；若主键已是 `{run_id, task_id}` 或核心列缺失则跳过 |

两者在 `backend/data/migrations/runner.py` 中注册：

```python
register_migration(20, "usage_events_run_id", _v20_usage_events_run_id)
register_migration(21, "orch_tasks_composite_pk", _v21_orch_tasks_composite_pk)
```

迁移版本记录在 `schema_version` 台账。v21 会执行 `foreign_key_check`，发现异常只告警、不阻断启动；已经被历史覆盖掉的任务行无法恢复，只能保证升级后不再发生覆盖。

## 4. 计划、确认与任务生命周期

### 4.1 计划项

Planner 为每个任务生成：

| 字段 | 取值 | 约束 |
|---|---|---|
| `task_id` | `t1`、`t2`… | run 内唯一 |
| `goal` | 自然语言目标 | 计划卡可编辑 |
| `agent_id` | 代理标识 | 缺省由调度层补 |
| `depends_on` | 任务 id 列表 | 形成执行依赖 |
| `estimated_iterations` | 整数 | 限制在 1–15（`MAX_ESTIMATED_ITERATIONS`） |
| `complexity` | `low` / `medium` / `high` | 非法值被丢弃 |
| `parent_task_id` | 父任务 id 或空 | 仅当设置 `allow_deep_decomposition=true` 时由 prompt 允许生成 |

`allow_deep_decomposition` 默认为 `false`，对应设置页「允许深层拆分」。关闭时 Planner 的 prompt 明确要求输出扁平任务列表。

计划卡展示复杂度徽章（高/中/低）与每项「≈N 轮」，并在计划层汇总预估轮次；预估只是提示，不参与调度硬限制。

### 4.2 确认与锁定

- 用户在计划卡点击「开始执行」后，前端先落库计划（`updatePlan`），再调用 `confirmRun`。
- 后端 `confirm` 端点要求 run 处于可执行状态，成功后写入 `confirmed_at` 并唤醒等待中的生产逻辑。
- 派发后计划进入锁定态：计划更新端点返回 409（`plan locked after dispatch`），前端计划卡变为只读摘要，可手动展开回看。
- `confirmed_at` 与 `dispatched_at` 随 run 详情返回，前端据此在重新加载后恢复「已确认/已派发」的锁定态。

### 4.3 审批模式与步骤确认

- **审批模式**：`ask`（逐次弹窗）或 `auto`（自动放行非危险工具，破坏性操作与工作区越界仍确认）。切换通过 `/approval-mode` 写入活动 run，成功后聊天流回推 `approval_mode` 事件供界面回显。
- **步骤确认**：`StepConfirmDialog` 提供「继续 / 跳过此步 / 中止」，通过 `/step-confirm` 提交 `continue|skip|abort`。跳过会把当前任务标记为 `skipped` 并继续后续任务；中止结束本次 run。

### 4.4 状态机

run 状态（`backend/domain/orch_events.py`）：

```text
draft → queued → running → completed
                    │  └──→ failed
                    ├──→ paused → running
                    ├──→ cancelling → cancelled
                    └──→ recovery_required
```

任务状态：

```text
planned → queued → running → succeeded
                      ├──→ failed
                      ├──→ cancelled
                      ├──→ blocked / interrupted
                      ├──→ waiting_input / waiting_approval
                      ├──→ retrying
                      ├──→ paused → running
                      └──→ skipped（步骤确认跳过）
```

调度层把状态推进映射为生命周期事件：

| 任务状态 | 事件 |
|---|---|
| `queued` | `task.queued` |
| `running` | `task.started` |
| `done` | `task.succeeded` |
| `failed` | `task.failed` |
| `cancelled` | `task.cancelled` |
| `skipped` | `task.skipped` |

同一个事件 fan-out 给两个消费者：状态投影（前端任务板）和 transcript 记录器。

流结束时由 `chat_stream_support._finalize_orch_run` 收尾：先快照旧状态，再由数据库终态决定最终结果（用户取消的 `cancelled` 不会被覆盖），发布 `run.completed/failed/cancelled`，最后推送桌面通知。

## 5. 消息级 Transcript

### 5.1 写入

`TaskTranscriptRecorder` 在每次代理迭代时写入 `orch_task_messages`，记录类型包括 `goal`、`reasoning`、`assistant`、`tool_call`、`tool_result`、`error`。写入前执行三类约束：

| 常量 | 值 | 作用 |
|---|---|---|
| `MAX_ROWS_PER_TASK` | 2000 | 单任务最多消息行数，超出停止追加 |
| `MAX_TEXT_CHARS` | 32000 | 正文 / 思考 / 错误文本截断 |
| `MAX_TOOL_ARGS_CHARS` | 8000 | 工具参数截断 |
| `MAX_TOOL_RESULT_CHARS` | 16000 | 工具结果截断 |

工具参数在落库前经过 `redact_sensitive_args` 脱敏，再序列化截断。这一点与早期计划中「参数尚未脱敏」的记录不同，以当前代码为准。

### 5.2 读取

`GET /api/v1/orch/runs/{run_id}/tasks/{task_id}/transcript` 支持：

- `after_seq`：从指定序号之后续读，默认 0。
- `limit`：每页条数，默认 200，范围 1–500（注意参数名是 `limit`，不是 `page_size`）。

响应带 `has_more` 与 `next_seq`。前端 `useTaskTranscript` 在任务运行中以 2 秒间隔轮询，每页 200 条，每次同步最多追 5 页；任务进入终态后停止轮询。

### 5.3 展示

任务详情「对话」页签按行渲染：目标、思考（遵守全局/会话思考展示档位）、助手正文、工具调用（参数可展开，耗时按 `tool_call_id` 关联工具结果行）、工具结果、错误。完成后可在底部输入框对该子代理「继续追问」。

## 6. 用量账本与成本归因

### 6.1 写入链路

`backend/services/usage_tracker.py` 维护两个 ContextVar：`current_run_id` 与 `current_task_id`。子代理执行期间设置，`_persist` 写入 `usage_events` 时一并落库。因此每条模型调用都能回溯到具体 run 与任务。

### 6.2 聚合

`UsageCostRepository` 只统计 `estimated_cost_usd IS NOT NULL` 的行：

| 方法 | 返回 |
|---|---|
| `task_cost_usd(run_id, task_id)` | 单任务金额；无已定价行返回 `None` |
| `run_costs_usd(run_id)` | `{"total": float|None, "tasks": {task_id: float}}` |

查询失败时 fail-open，返回空结果而不是让详情接口 500。金额为 `None` 表示「定价未知」，前端隐藏金额，而不是显示 `$0`。

### 6.3 为何不写入 `orch_tasks`

任务表保存执行事实（token、耗时、状态），金额则由账本表聚合。这样可以避免：

- 同一任务多次重试时金额被覆盖；
- 价格表更新后需要回写历史任务行；
- 任务表承担与本表职责无关的财务口径。

run 详情接口（`/orch/runs/{run_id}`）额外返回每个任务的 `cost_usd` 与 run 级 `cost_usd`；前端用 `formatCostUsd` 渲染为 `≈ $0.0123` 或 `≈<$0.0001`，明确是估算值而非账单。

## 7. Canonical Run 目录与统一任务视图

### 7.1 目录接口

`GET /api/v1/orch/runs/directory` 是**数据库投影**，不是文件系统目录：

| 参数 | 取值 | 默认 |
|---|---|---|
| `scope` | `active` / `failed` / `finished` / `all` | `active` |
| `limit` | 1–200 | 50 |

返回每个 run 的状态、时间戳、`plan_json` 解析出的计划、任务行（含 `parent_task_id`、`depth`、`retry_of`、`used_tokens`、`duration_ms`）。前端 `runDirectoryStore` 以 `limit=50` 每 3 秒刷新一次，带加载互斥；请求失败时保留上一份数据。

注意它与「运行目录」文件概念的区别：真正的文件落盘只有子代理临时目录 `<data_dir>/orch_scratch/<run_id>/<task_id>`（`SCRATCH_ROOT = "orch_scratch"`）。编排 run 本身没有独立的文件系统目录。

### 7.2 统一任务模型

`unifiedTaskModel.ts` 把多种来源归一为 `UnifiedTaskEntry`，与编排相关的有：

| 来源 | 生成函数 | 可见性 |
|---|---|---|
| `subagent` | `normalizeSubagentTask` | `queued/running/paused/failed` |
| `run` | `normalizeCanonicalRun` | `running/failed`，且没有可见子任务时才有 run 行 |

关键映射：

- `SUBAGENT_STATUS_MAP`：`paused → paused`、`done → succeeded`、`skipped → cancelled`。
- `CANONICAL_RUN_STATUS_MAP`：`running/completed/failed/cancelled → running/succeeded/failed/cancelled`。
- `mergeSubagentEntries`：同 id 时 canonical（DB）定状态，内存行只在存在待审批时覆盖为 `awaiting_approval`，并补 `liveStep` 与会话标题。
- `STATUS_PRIORITY` 决定排序：失败 → 待审批 → 运行中 → 暂停 → 排队 → 成功 → 取消。

`useUnifiedTasks` 先取 canonical 条目，再把同 id 的内存条目合并进来，最后追加未合并的目录行。这样会话从未在前端加载过、或跨窗口运行时，任务中心仍能看到运行中的 run。

### 7.3 任务中心

侧栏「任务」与 `/tasks` 页面共用 `TaskCenterPanel`：

- 分组：进行中 / 失败 / 已完成。
- 来源标签：页面任务、后台会话、编排、子代理、编排运行、闲时目标、待办、定时任务。
- 子代理行点击打开 `subagent-thread`（会话 + 右栏进度 + 指定任务详情）；run 行点击打开 `run-progress`。
- run 行可取消；子代理行不可直接取消（需进入任务详情）。
- 侧栏角标口径为「进行中 + 失败」，与聊天侧「需要你操作」角标不同。

## 8. 子代理执行与人工干预

### 8.1 角色与后台运行

`backend/tools/subagent_roles.py` 内置三种角色：

| `subagent_type` | 用途 |
|---|---|
| `explore` | 只读调研与检索，默认值 |
| `plan` | 规划拆解 |
| `general-purpose` | 通用执行 |

未知或空值回落到 `explore`；显式传入未知类型时工具返回错误。`background=true` 时走 `start_background`，返回 handle_id，调用方不被阻塞。并发约束：

- `MAX_BACKGROUND_AGENTS_PER_STREAM = 4`：每个聊天流最多 4 个后台代理。
- `MAX_CONCURRENT_BACKGROUND_DISPATCHES = 4`：调度器同时在飞的后台派发上限。

### 8.2 续聊

已完成任务可通过 `/tasks/{task_id}/followup` 继续对话：复用原子代理历史，后台派发新任务并返回新 `task_id`，前端自动切到新任务的 transcript。

错误语义：空内容或超过 8192 字符返回 400；run 不在活动注册表返回 404；任务不可续聊或达到并发上限返回 409。活动注册表在进程内，应用重启后旧 run 的续聊不可用。

### 8.3 暂停、恢复、跳过、重试

- **暂停**：任务级与 run 级都支持。暂停在下一迭代边界生效，暂停期间不消耗 LLM token。run 级暂停返回受影响任务数。
- **恢复**：恢复被暂停的任务，从边界继续。
- **跳过**：单任务取消端点；`queued` 任务直接短路为 `skipped`，`running` 任务软中断，其他子任务不受影响。
- **重试**：run 终态后可按失败任务重跑；已成功任务以结果回放方式写入新计划，不重新执行。单任务重试会重建该任务及其下游未完成闭包。

### 8.4 插话（steer）

`POST /tasks/{task_id}/steer` 允许在任务运行中补充约束、澄清、上下文、纠正、优先级或引用。约束：

- `source`、`message_type`、`apply_mode` 有白名单。
- `content_redacted` 上限 8 KB。
- 必须带 `expected_task_revision` 做 CAS；不匹配返回 409 `task_state_changed`，任务已终态返回 409 `task_terminal`。
- 每 60 秒窗口最多 10 次，超限返回 `rate_limited` 与重试秒数。

成功后审计 revision 在快照锁内自增，后续写入按新 revision 继续。

## 9. 前端交互面

| 位置 | 内容 |
|---|---|
| 会话右栏「进度」 | 三个子页签：概览（状态栏 + 焦点卡 + 任务清单 + 历史）、任务（任务树，点击进入详情）、轨迹（完整事件时间线） |
| 任务详情 | 「过程」展示当前步骤、审批、错误、结果预览与实时动态；「对话」展示消息级 transcript。顶部提供暂停/恢复、跳过、重试与成本信息 |
| 计划卡 | 任务目标可编辑、可删除、可增行；复杂度徽章与「≈N 轮」；「开始执行 / 取消」；确认后折叠为只读摘要；支持自然语言修订 |
| 状态栏 | run 级「全部暂停 / 全部恢复」「自动批准：开/关」「取消执行」，以及 run 成本合计（仅累加已知金额） |
| 任务树 | 每个任务的 tokens、耗时、暂停/恢复、待审批提示与单任务取消 |
| 设置 - 编排 | 「允许深层拆分」等编排旋钮；「思考展示档位」影响 transcript 中 reasoning 行的展开方式 |

事件订阅只对 `orch-` 前缀的 run 开启；普通会话的 run 不建立编排事件流。`Chat.tsx` 优先使用后端任务板，缺省时用 `canonicalTaskBoard` 从目录数据合成。

`TaskTranscriptPanel` 通过 `lazy()` 按需加载，避免 transcript 面板与轮询逻辑进入主 chunk、触发前端 bundle 体积门禁。

## 10. HTTP 接口一览

以下路径均以 `/api/v1` 为前缀。

| 方法与路径 | 用途 | 关键参数 / 错误 |
|---|---|---|
| `GET /orch/runs` | 会话 run 列表 | `session_id`、`limit` |
| `GET /orch/runs/{run_id}` | run 详情 | 含 `cost_usd`、`confirmed_at`、`dispatched_at` |
| `GET /orch/runs/directory` | canonical 目录投影 | `scope`、`limit` |
| `GET /orch/runs/{run_id}/snapshot` | 状态快照 | — |
| `GET /orch/runs/{run_id}/events` | NDJSON 事件流 | `after_seq` |
| `GET /orch/runs/{run_id}/tasks/{task_id}/transcript` | 消息级过程记录 | `after_seq`、`limit`（≤500） |
| `POST /orch/runs/{run_id}/plan` | 更新计划 | 派发后 409 |
| `POST /orch/runs/{run_id}/confirm` | 确认计划 | 需 run 可执行 |
| `POST /orch/runs/{run_id}/rerun-failed` | 重跑失败任务 | 可带 `task_ids` |
| `POST /orch/runs/{run_id}/tasks/{task_id}/cancel` | 跳过单任务 | 409 已终态 / 不在本批 |
| `POST /orch/runs/{run_id}/tasks/{task_id}/followup` | 续聊 | 400 / 404 / 409 |
| `POST /orch/runs/{run_id}/tasks/{task_id}/pause` | 暂停任务 | — |
| `POST /orch/runs/{run_id}/tasks/{task_id}/resume` | 恢复任务 | — |
| `POST /orch/runs/{run_id}/pause` | 暂停 run | 返回受影响数 |
| `POST /orch/runs/{run_id}/resume` | 恢复 run | 返回受影响数 |
| `POST /orch/runs/{run_id}/cancel` | 取消 run | 409 `run_terminal` |
| `POST /orch/runs/{run_id}/approval-mode` | 切换审批模式 | `ask` / `auto` |
| `POST /orch/runs/{run_id}/step-confirm` | 步骤确认 | `continue` / `skip` / `abort` |
| `POST /orch/runs/{run_id}/tasks/{task_id}/steer` | 插话 | revision CAS、8 KB、限流 |
| `POST /orch/plan-items` | 自然语言计划 → 结构化任务 | 503 未配置 LLM / 502 解析失败 |

## 11. 通知与深链

run 终态由 `chat_stream_support` 推入 Electron 通知队列：

1. `schedulerNotifications.ts` 每 4 秒轮询，新增第六个队列 `orch_runs`，消息体带 `run_id` / `task_id`。
2. 点击通知时 `orchNotifications.ts` 聚焦窗口并 `webContents.send('sage:event:orch-notify-click', payload)`。
3. 渲染进程 `orchNotify.ts` 监听该事件，聚焦对应会话、把右栏切到「进度」，必要时打开指定任务。

通知队列是进程内内存态，应用退出后未消费的通知不会持久化。

## 12. 测试与门禁

### 12.1 后端单测

| 测试文件 | 覆盖点 |
|---|---|
| `backend/tests/unit/orchestration/test_task_transcript.py` | 记录器截断、脱敏、行数上限 |
| `backend/tests/unit/orchestration/test_orch_transcript_api.py` | transcript 分页、`after_seq`、`limit` |
| `backend/tests/unit/orchestration/test_run_directory.py` | 目录 scope、排序、计划解析 |
| `backend/tests/unit/orchestration/test_orch_cost_attribution.py` | `run_id` / `task_id` 归因与金额聚合 |
| `backend/tests/unit/orchestration/test_orch_run_notifications.py` | 终态通知载荷 |
| `backend/tests/unit/orchestration/test_orch_followup.py` | 续聊派发与错误码 |
| `backend/tests/unit/orchestration/test_orch_pause_resume.py` | 任务/run 暂停恢复 |
| `backend/tests/unit/orchestration/test_orch_task_repo.py` | 复合键冲突更新 |
| `backend/tests/unit/orchestration/test_subagent_events.py` | 实时事件过滤与转发 |
| `backend/tests/unit/orchestration/test_planner_estimates.py` | 预估与复杂度校验、深层拆分开关 |
| `backend/tests/unit/test_schema_migrations.py` | v20 / v21 迁移与幂等 |
| `backend/tests/unit/test_usage_persistence.py`、`test_usage_tracker.py` | 用量写入 ContextVar |
| `backend/tests/unit/test_orch_run_control*.py`、`test_orch_routes*.py` | 端点契约、steer CAS、错误码 |

### 12.2 前端测试

`runDirectoryStore`、`canonicalTaskBoard`、`unifiedTaskModel`、`useUnifiedTasks`、`TaskCenterRuntimeHost`、`PlanCard`、`TaskDetailView`、`TaskTranscriptPanel`、`costTransparency.m43b`、`EventTimeline.duration`、`orchNotify`、`OrchestrationTab` 等均有对应 vitest 用例，覆盖状态映射、合并优先级、轮询、成本展示与深链。

## 13. 已知限制与未完成项

- **canonical run 目录没有游标**。接口一次最多返回 200 条，前端固定取 50 条，历史更早的 run 需缩小 scope 或提高 limit。
- **自然语言计划通道不带预估**。`plan-items`（文本 → 结构化计划）使用的 prompt 不产出 `estimated_iterations` / `complexity`，只有 Planner 正常拆解路径才有这些字段。
- **续聊依赖进程内注册表**。应用重启后旧 run 的 followup 返回 404。
- **通知不持久化**。只有应用运行期间产生的终态通知能点击跳转。
- **Lane 维度任务板仍独立**。`/orchestration` 的 lane 看板尚未并入 canonical 统一视图；编排 run 与 lane 是两套执行路径。
- **实时状态映射存在缺口**。`runControlStore` 未登记 `task.paused` / `task.resumed` / `run.resumed`；事件流白名单 `EVENT_TYPES` 未包含 `task.skipped`。这些状态目前依赖任务板或目录刷新体现，而非实时事件。
- **合成任务板缺少实时步骤**。`canonicalTaskBoard` 从目录数据合成时没有 `liveStep`，只有内存任务板能提供当前步骤。
- **成本只覆盖已定价的子代理调用**。主控（conductor）自身调用与未知定价模型不进入归因金额；金额为 `None` 时界面隐藏。
- **v21 无法恢复被覆盖的历史任务**。迁移只保证今后不再发生同 `task_id` 跨 run 覆盖。
- **v20 迁移注释仍描述旧主键**。其 docstring 写的是 `orch_tasks` 以 `task_id` 为主键，属于 v21 之前的表述，阅读时以迁移代码与 v21 结果为准。
- **暂停是协作式边界**。当前迭代不会被打断，暂停只在下一迭代边界生效。
- **步骤确认与审批模式是两套机制**。前者控制计划步推进，后者控制子代理工具调用，二者不要混用。
