# 165 · 智能体编排对标

> 适用范围：Sage 聊天侧的智能体编排内核（Planner → ChatDispatcher → SubagentRunner）及其子代理调度、过程回看、失败重规划、统一运行视图、通知与成本账本。
> 状态：已落地（main 与 release/win7 双分支同步）。
> 相关代码：`backend/orchestration/`、`backend/tools/subagent_roles.py`、`backend/tools/agent_background.py`、`backend/api/orch_run_control.py`、`backend/api/orch_pause_routes.py`、`backend/services/orch_run_notifications.py`、`backend/data/usage_cost_repo.py`、`backend/data/migrations/v20_usage_run_id.py`、`backend/data/migrations/v21_orch_tasks_composite_pk.py`、`src/features/task-center/`、`src/entities/orchestration/runDirectoryStore.ts`、`electron/orchNotifications.ts`
> 相关文档：[42 聊天多智能体编排](./42-chat-multi-agent-orchestration.md)、[140 插话暂存面板](./140-steer-staging-panel.md)、[148 侧边栏任务中心](./148-sidebar-task-center.md)、用户手册 [56 智能体编排](../user-manual/56-agent-orchestration.md)

---

## 1. 背景与目标

Sage 的聊天编排早已具备 Planner → ChatDispatcher → SubagentRunner 主链路，但对标 Claude Code 的子代理能力仍有多处缺口：`subagent_type` 字段被忽略、后台派发只能单飞、子代理过程不可回看、失败只重试不重规划、`TaskCenter`/右栏/LaneBoard 三套视图各自为政、成本不可见，且任务行以 `task_id` 为主键会在同会话多次运行时互相覆盖。

本里程碑按 M0–M4.3b 与 §15 分段补齐，核心目标：

| 目标 | 落地方式 |
| --- | --- |
| 子代理可分工、可后台、可暂停 | `subagent_type` 角色 + 后台派发/并发上限 + `PauseState` 闸门 |
| 过程可回看 | `orch_task_messages` 全量落盘 + 分页 transcript 端点 |
| 失败可自愈 | 失败终态向主控注入 re-plan 提示 |
| 视图统一 | Canonical Run 目录端点 + 统一任务模型收敛 |
| 成本透明 | `usage_events.run_id` 现场聚合（金额不入 `orch_tasks`） |
| 跨 run 数据隔离 | `orch_tasks` 复合主键 `(run_id, task_id)` + v21 迁移 |

---

## 2. 里程碑总览

| 里程碑 | 能力 | 主要落地位置 |
| --- | --- | --- |
| M0 | 编排事件接线修复（任务详情时间线、插话回退提示） | `src/pages/Chat.tsx`、`orchSteer` |
| M1 | Transcript 落盘与回看 | `backend/orchestration/transcript.py`、`backend/data/orch_transcript_repo.py` |
| M2.1 | 后台子代理（`background=true`） | `backend/tools/agent_background.py` |
| M2.2 | 同轮并发 + 多后台派发 | `chat_dispatcher.py`、`core/legacy/agent.py` |
| M2.3 | 继续追问（followup） | `ChatDispatcher.start_followup` + `POST .../followup` |
| M2.4 | 子代理线程进入任务中心 | `src/features/task-center/unifiedTaskModel.ts` |
| M2.5 | 任务 / 运行级暂停恢复 | `backend/orchestration/pause_state.py`、`backend/api/orch_pause_routes.py` |
| M3.1 | 子代理角色 `subagent_type` | `backend/tools/subagent_roles.py` |
| M3.2 | 失败驱动重规划 | `chat_dispatcher.py::_inject_replan_hint` |
| M3.3 | 计划估算与深分解开关 | `backend/orchestration/planner.py`、`orch_settings.py` |
| M4.1 | 工具耗时 + 全文引用 + 落盘脱敏 | `backend/orchestration/subagent_events.py`、`backend/services/permission_gate.py` |
| M4.2 | Canonical Run 目录 / 统一运行视图 | `backend/api/orch_run_control.py`、`src/entities/orchestration/runDirectoryStore.ts` |
| M4.3a | 编排通知 + 任务深链 | `backend/services/orch_run_notifications.py`、`src/features/orch-notify/orchNotify.ts` |
| M4.3b | 成本透明（`usage_events.run_id`） | `backend/data/usage_cost_repo.py`、`backend/services/usage_tracker.py` |
| §15 | `orch_tasks` 复合主键 + v21 迁移 | `backend/data/database.py`、`backend/data/migrations/v21_orch_tasks_composite_pk.py` |

> 落地 PR（main 侧）：M0 #3172、M1 #3180、M2.1/M2.2 #3184、M2.3 #3188、M2.4 #3191、M2.5 #3197、M3.1 #3210、M3.2 #3215、M3.3 #3219、M4.1 #3223、M4.3a #3225、M4.2 #3227、M4.3b #3243、§15 #3253；win7 同步 PR 见各模块提交。

---

## 3. 计划阶段：估算与深分解（M3.3）

Planner 产出的每个计划任务现在可携带两个提示字段：

| 字段 | 取值 | 校验 |
| --- | --- | --- |
| `estimated_iterations` | 整数 1–15（`MAX_ESTIMATED_ITERATIONS = 15`） | 越界或非整型由 `sanitize_llm_plan_tasks` 静默丢弃该字段 |
| `complexity` | `low` / `medium` / `high` | 非法值（含非字符串）静默丢弃 |

提示词与校验共用同一个 `MAX_ESTIMATED_ITERATIONS` 常量，避免两处漂移。计划卡据此渲染逐任务复杂度徽章（`text-error` / `text-warning` / `text-success` 主题 token）与「≈N 轮」；标题汇总的轮数只累加**确实提供了预估**的任务，缺失者不参与合计。

深分解由编排设置 `allowDeepDecomposition` 控制（规范化键 `allow_deep_decomposition`，默认 `False`）：

- **关闭**：提示词要求平铺计划，禁用 `parent_task_id`；
- **开启**：允许子任务层级，但层级只表达「归属」，不产生依赖边。

设置读取失败按「关闭」处理。该开关必须四处齐备才生效：`settings_canonicalizer` 的 `ALIASES` + `LEGAL_ORCH_KEYS`、`_RAW_KEYS`、以及前端设置注册表 / 搜索 / 审计；任一处缺项会让整段编排设置保存返回 `400 invalid_settings_shape`，且前端会静默吞掉错误。

---

## 4. 子代理分发与执行

### 4.1 子代理角色（M3.1）

`backend/tools/subagent_roles.py` 定义三类内置角色，并通过 `agent` 工具的 `subagent_type` 动态枚举暴露：

| 角色 | 能力 | 说明 |
| --- | --- | --- |
| `explore` | 只读 | 默认角色，也是空值时的行为（历史行为不变） |
| `plan` | 只读 + 规划 | 定位与规划，不写文件 |
| `general-purpose` | 读写 / 编辑 / 打补丁 / 执行命令 / 网络检索 | 受权限策略审批约束 |

数据库中标为可用的 profile 也可作为 `subagent_type`（按 tools 白名单过滤、`compose_system_prompt`、`max_iterations` 生效），schema 中最多注入 `MAX_PROFILE_ROLES_IN_SCHEMA = 12` 个 profile 角色。解析规则：

- 空值 → `explore`，`known=True`；
- 显式未知类型 → 回落到 `explore`，`known=False`，调用方据此返回 `unknown_subagent_type` 错误。

### 4.2 后台子代理（M2.1）

`agent(background=true)` 立即返回 `{"status": "running", "handle_id": "bg-…"}`，不阻塞当前回合。后台任务完成 / 失败 / 取消后，经主 agent 的系统提示队列在**下一迭代边界**注入一条提示（如 `【后台子代理完成】…`），不写数据库、不发 `STEER_CONSUMED`。

每个 stream 同时运行的后台子代理上限为 `MAX_BACKGROUND_AGENTS_PER_STREAM = 4`，超限返回错误 `background_agent_limit (limit=4)`。

### 4.3 同轮并发与多后台派发（M2.2）

同轮多个 `agent` 调用在满足「无钩子 / 免审批 / 预算足」时组成并发执行组 `agents`，并发上限沿用 `core/legacy/agent.py` 的 `_AGENT_CONCURRENT_LIMIT = 4`；不满足条件时回落为串行。事件与工具消息仍按模型给出的顺序呈现。

ChatDispatcher 的派发从「单在飞互斥」改为最多 `MAX_CONCURRENT_BACKGROUND_DISPATCHES = 4` 个后台派发并存：达到上限时后台启动方法返回 `None`，由工具层（`backend/tools/subagent_tool.py`）转成 `background_dispatch_limit` 错误；`wait_background` 一次收集全部在飞派发。

### 4.4 暂停 / 恢复（M2.5）

`PauseState`（`backend/orchestration/pause_state.py`）以 `asyncio.Event` 实现暂停闸门，`request_pause` / `request_resume` 幂等。`SageAgent` 在每个迭代边界调用 `wait_if_paused()`，与中断竞争；暂停期间不消耗 token。

REST 端点集中在 `backend/api/orch_pause_routes.py`：

| 端点 | 作用 | 失败语义 |
| --- | --- | --- |
| `POST /orch/runs/{run_id}/tasks/{task_id}/pause` | 暂停单个子任务 | 任务不可暂停返回失败 |
| `POST /orch/runs/{run_id}/tasks/{task_id}/resume` | 恢复单个子任务 | 未知 / 未暂停返回失败 |
| `POST /orch/runs/{run_id}/pause` | 暂停该 run 全部运行中任务 | 无运行中任务返回 `409` |
| `POST /orch/runs/{run_id}/resume` | 恢复该 run 全部暂停任务 | 无暂停任务返回 `409` |

状态变化通过 canonical 事件 `task.paused` / `task.resumed` / `run.paused` / `run.resumed` 广播，前端快照同步应用 `paused` / `resumed`。

### 4.5 继续追问（M2.3）

对已完成的子任务可继续对话。`ChatDispatcher.start_followup(parent_task_id, content)` 生成唯一跟进编号 `fuN`，以 `followup_of` 关系后台派发，并复用父任务的子代理历史 `_histories[parent]`，实现上下文延续。

后端端点 `POST /orch/runs/{run_id}/tasks/{task_id}/followup`（`backend/api/orch_routes.py`）；前端在任务详情「对话」tab 对终态任务展示「继续追问这个子代理…」输入框，派发成功后切换到新任务的 `activeTaskId`，transcript 轮询随之跟随。

### 4.6 工具调用耗时与全文引用（M4.1）

工具事件补齐两个字段：

- `tool_call_id`：把 `tool_call` 行与其 `tool_result` 行关联；
- `duration_ms`：工具实际执行耗时（canonical 的 `task.step.completed` 原本已有，`task.step.started` 载荷补 `tool_call_id`）。

前端据此在过程时间线渲染 `· 1.2s`（仅在 `payload.duration_ms` 为数值时），在对话面板里按 `tool_call_id` 把 `tool_result` 的耗时回填到对应 `tool_call` 行（`tool_call` 行在 OBSERVING 阶段尚不知道耗时）。耗时格式化统一到共享的 `progressFormat.formatDuration`。

> 接线修复：M1 期间 ChatDispatcher 建了 `TaskTranscriptRecorder` 包装器 `_event_sink`，却把裸 `sink` 传给了 `SubagentRunner`，导致 `orch_task_messages` 在生产环境恒空、「全文引用」不可用。M4.1 改为传 `event_sink=_event_sink`，状态投影与 transcript 落盘并行扇出；审批专用第二处 sink 无 recorder，保持原样。

---

## 5. Transcript 落盘与脱敏（M1 + M4.1）

### 5.1 数据与记录器

新表 `orch_task_messages` 以 `(run_id, task_id, seq)` 为复合主键，只追加不修改。`TaskTranscriptRecorder`（`backend/orchestration/transcript.py`）与 `SubagentEventSink` 并行消费子代理 `run_loop`，在迭代边界聚合 reasoning / content / tool 全文，`seq` 从当前 `max_seq` 续接。

消息类型：`goal` / `reasoning` / `assistant` / `tool_call` / `tool_result` / `error`。容量上限：

| 常量 | 值 | 作用 |
| --- | --- | --- |
| `MAX_ROWS_PER_TASK` | 2000 | 单任务行数封顶 |
| `MAX_TEXT_CHARS` | 32000 | 正文 / 思考 / 错误文本截断 |
| `MAX_TOOL_ARGS_CHARS` | 8000 | 工具参数截断 |
| `MAX_TOOL_RESULT_CHARS` | 16000 | 工具结果截断 |

记录器吞掉自身异常，落盘失败不影响子代理执行。

### 5.2 回看端点

`GET /orch/runs/{run_id}/tasks/{task_id}/transcript?after_seq=&limit=`（`limit` 默认 200、范围 1–500）。与 `/events`（canonical NDJSON 状态流）互补：本端点返回消息级过程记录，运行中按 `after_seq` 增量轮询续接。响应含 `messages` / `next_seq` / `has_more`。前端 `useTaskTranscript` 做增量轮询，`TaskTranscriptPanel` 在任务详情「对话」tab 渲染。

### 5.3 落盘脱敏

`tool_call` 参数此前直接 `json.dumps` 落盘，密钥类参数会明文进入 `orch_task_messages`（实时镜像的 `summarize_tool_args` 脱敏不覆盖持久化）。现已补齐 `permission_gate.redact_sensitive_args`：

- **结构保留式**：不将容器整体字符串化、不在脱敏阶段截断；
- 复用 `_scrub_value` 递归清洗，以 `MAX_SCRUB_DEPTH = 5` 封顶，超出深度的容器整体替换为占位；
- `_dump_args` 的 `json.dumps` 与 `str()` 兜底两条路径都先脱敏再落盘。

脱敏覆盖 `tool_call` 参数落盘；`tool_result` 行走独立的 `MAX_TOOL_RESULT_CHARS` 截断路径。

---

## 6. 失败重规划（M3.2）

子任务进入失败终态后，ChatDispatcher 通过域层的 `(session_id → 主 agent)` resolver 向主控（conductor）注入一条 re-plan 提示：

> `【编排提示】子任务 {task_id}（{goal}）经重试后仍失败：{error}。`
> 建议先 `add_task_to_plan` / `update_pending_task` 调整计划后重新 dispatch，或直接汇总。

约束：

- 按 task 去重（`_replan_hinted_tasks`），避免同一任务反复刷提示；
- 每 run 上限 `MAX_REPLAN_HINTS_PER_RUN = 3`；
- 在任务收尾 `finally` 中当 `state.status == "failed"` 时触发；
- 注入失败不影响执行本身。

域层新增的 session resolver 由 `chat_stream_state` 注册，tools 层只读，维持 hexagonal 分层（`backend.tools` 不 import `backend.api`）。

---

## 7. Canonical Run 目录与统一运行视图（M4.2 / M4.3a）

### 7.1 后端真相层与目录端点

为消除三套数据源不同步，后端提供统一目录端点：

`GET /api/v1/orch/runs/directory?scope=active|failed|finished|all&limit=1..200`（默认 `active` / `50`）

scope 映射（`_DIRECTORY_SCOPES`）：

| scope | 对应 `orch_runs.status` |
| --- | --- |
| `active` | `running` |
| `failed` | `failed` |
| `finished` | `completed` + `cancelled` |
| `all` | 上述全部四态 |

底层复用 `OrchRunRepository.list_by_statuses()`（跨会话状态过滤，新→旧，带 limit）与 `OrchTaskRepository.list_by_runs()`（`IN` 查询，空列表短路）。端点投影每个 run 及其 plan 与子任务，每个任务 15 个字段（`task_id` / `run_id` / `agent_id` / `goal` / `status` / `retry_count` / `error` / `output_preview` / `started_at` / `finished_at` / `used_tokens` / `duration_ms` / `parent_task_id` / `depth` / `retry_of`）。

> 注册顺序：`/directory` 必须早于 legacy `/orch/runs/{run_id}`。`orch_run_control` 在 `backend/main.py` 中先于 `legacy_router` 挂载，故 `/directory` 不会被当成 run_id 落入 catch-all。

### 7.2 前端收敛

- `runDirectoryStore`（zustand）：`RUN_DIRECTORY_LIMIT = 50`，3s 轮询，`loading` 并发去重，失败保留上一轮数据；提供 `findActiveRunForSession`。
- `buildCanonicalTaskBoard` 把目录投影为 `TaskBoardState`：plan 为空时用任务行兜底；计划中已确认但尚未落库的任务按 `queued` 合成；`paused` 计入 `queued`。
- 收敛规则：**canonical 定状态，内存补实时细节**；`awaiting_approval` 是唯一由内存侧压过 canonical 的状态（数据库不存待审批）；子任务 id 统一为 `subagent:<session_id>:<run_id>:<task_id>`。
- `Chat.tsx`：`effectiveTaskBoard = taskBoard ?? canonicalTaskBoard`，只做渲染期投影，**不写回** `chatStreamStore`（内存板一旦出现即优先，含 `liveStep`）；`useOrchEventSubscription` 以合成板 runId 继续接管事件订阅。
- 任务中心统一模型新增 `subagent` 源，把各会话子代理任务展开进 TaskCenter（`queued` / `running` / `failed` 可见，等待审批 → `awaiting_approval`），shell 轮询 `SHELL_TASK_POLL_MS = 3_000`。

### 7.3 运行终态通知与任务深链（M4.3a）

后端新增第六路通知队列 `backend/services/orch_run_notifications.py`：有界 `deque(maxlen=100)`，统一入口 `push_run_notification`（吞错），`resolve_session_id` 从 run 反查会话，摘要截断 `SUMMARY_MAX_CHARS = 120`。通知种类：`orch_run_completed` / `orch_run_failed` / `orch_run_cancelled` / `orch_run_awaiting_approval`。

`_finalize_orch_run`（`backend/api/chat_stream_support.py`，`legacy_routes` 复用同名 seam）在收尾时发布 canonical `run.completed` / `run.failed` / `run.cancelled`（EventHub 未装配时降级）并推终态通知。**终态以 `orch_runs` 行的最终状态为准**：取消端点先写 `cancelled`，且对终态 run 返回 `409`，因此「finalize 前已 cancelled」代表用户主动取消，迟到的 producer `finally` 不会误报 failed。`task.waiting_approval` 后另推审批通知。

Electron 侧 `schedulerNotifications.ts` 把编排运行并入既有通知源（第六路），载荷补 `run_id` / `task_id`，轮询从 15s 收紧到 `SCHEDULER_NOTIFICATION_POLL_MS = 4_000`。点击通知经 `sage:event:orch-notify-click` 回发渲染进程：`src/features/orch-notify/orchNotify.ts` 调 `focusThread` + 右栏切到 progress + 路由跳 `/chat?session=…`，直达对应会话与任务。

---

## 8. 用量账本与成本透明（M4.3b）

**金额不落 `orch_tasks`**。该表早期以 `task_id` 为主键，而计划编号 `t1..tN` 跨 run 复用，`ON CONFLICT(task_id) DO UPDATE` 会让同会话第二个 run 的 `t1` 覆盖第一个 run 的行（金额 / `used_tokens` / `duration_ms` / `goal` / `status` 全部串 run）。因此唯一真相源改为 `usage_events.estimated_cost_usd`，一切按 `run_id` 现场聚合（uuid 主键 + 显式 `run_id` 列，天然免疫跨 run 串扰）。

### 8.1 Schema 与迁移

- `usage_events` 增 `run_id TEXT`：新库与旧库同走 `init_db` 防御性 `ALTER`（与 `task_id` 同款做法）；
- 新增索引 `idx_usage_events_run(run_id, task_id, created_at)`（须在 `ALTER` 之后建）；
- 迁移 `v20_usage_run_id`：对 `task_id` 非空且 `run_id` 为空的历史行，按任务的 `[started_at, finished_at]` 时间窗回填；`started_at IS NULL` 的行不归因。

### 8.2 归因链路

`current_run_id` / `current_task_id` 两个 `ContextVar` + 对应 setter；`_persist` 写入 `run_id`（18 列，尾列）。dispatcher 在 preset 回放早退**之后**再设置两个 `ContextVar`（更早设置会泄漏到下一任务），并在 `finally` 一并清除。读侧 `_task_cost_usd(task_id)` 按 `(run_id, task_id)` 查账本并在 run 内 memoize，fail-open。

### 8.3 账本读层与展示

`backend/data/usage_cost_repo.py`：

| 方法 | 返回 | 口径 |
| --- | --- | --- |
| `task_cost_usd(run_id, task_id)` | `Optional[float]` | 无已定价行 → `None`（未知 ≠ 免费） |
| `run_costs_usd(run_id)` | `{"total": float \| None, "tasks": {task_id: amount}}` | 只聚合 `estimated_cost_usd IS NOT NULL` 的行 |

数据库故障 fail-open。API 侧 `GET /orch/runs/{id}` 为每个任务附 `cost_usd`、并为 run 附 `cost_usd`（均为 `Optional`）；终态事件带 `used_cost_usd`。前端 `formatCostUsd` 统一格式：正常显示 `≈ $0.0123`，低于 `$0.0001` 显示 `≈<$0.0001`（避免误读为免费），无金额则不显示。展示位置：StatusBar、任务树、任务详情、会话运行历史（历史列表用后端聚合的 run 级值）。

> 口径：run 成本 = 子任务 LLM 调用中**已定价**部分的合计；主控（conductor）与未知定价模型不计入。

---

## 9. `orch_tasks` 复合主键与 v21 迁移（§15）

彻底修复 M4.3b 记录的跨 run 覆盖：`orch_tasks` 主键由 `task_id` 改为复合主键 `(run_id, task_id)`，同会话第二个 run 复用 `t1..tN` 不再覆盖第一个 run 的任务行。

### 9.1 新库 DDL

- `orch_tasks`：`PRIMARY KEY (run_id, task_id)`；
- `orch_context_messages`：单列 FK 改为表级复合 FK `FOREIGN KEY (run_id, task_id) REFERENCES orch_tasks(run_id, task_id)`。原因：`PRAGMA foreign_keys=ON` 时父键单列不再唯一，旧单列 FK 会报 `foreign key mismatch`。

### 9.2 迁移 v21

`backend/data/migrations/v21_orch_tasks_composite_pk.py`，注册于 `runner.py` 的 v20 之后。SQLite 不能改主键，故整表重建：建新表 → 列名交集复制 → `DROP` → `RENAME` → 重建 `idx_orch_tasks_run` / `idx_orch_tasks_status`；`orch_tasks` 与 `orch_context_messages` 两表都重建。

关键点：

- `PRAGMA foreign_keys` **必须在事务外**切换（事务内是 no-op）；
- 收尾 `foreign_key_check` 只告警、不 `raise`，历史脏行不阻断迁移；
- 缺表或缺核心列 `{task_id, run_id, agent_id, goal, status}` 的精简 fixture 直接跳过；
- **复合 FK 检测**：`PRAGMA foreign_key_list` 每列对一行，复合 FK 的 `(run_id, task_id)` 两行共享同一 `id`，必须按 `row[0]` 分组，只有 from 列集合恰为 `{"task_id"}` 的组才是旧单列 FK（否则会误判「仍需重建」导致重复重建）。

### 9.3 仓储适配

`backend/data/orch_task_repo.py`：`ON CONFLICT(run_id, task_id) DO UPDATE`；`get(run_id, task_id)` 与 `bump_revision_for_steer(run_id, task_id)` 双参化；`orch_run_control.py` 的 steer 路径同步。所有单参调用点（含测试）一并适配。

---

## 10. 遗留与后续

`orch_tasks` 的**历史视图**仍缺，需要产品决策（展示口径）才能实现。运行级历史目前可经目录端点 `scope=finished|all` 与会话运行历史查看；面向单条任务行、跨 run 的长历史明细如何呈现（保留时长、分页、与 run 目录 / 会话历史的关系）属于展示口径，需产品决策后再落地。

---

## 11. 相关文件

| 模块 | 路径 | 说明 |
| --- | --- | --- |
| 子代理角色 | `backend/tools/subagent_roles.py` | 内置 explore / plan / general-purpose + DB profile 角色 |
| 后台子代理 | `backend/tools/agent_background.py` | `background=true` 后台派发与上限 |
| 调度器 | `backend/orchestration/chat_dispatcher.py` | 多后台派发、重规划、成本归因 |
| 暂停闸门 | `backend/orchestration/pause_state.py` | `asyncio.Event` 暂停 / 恢复 |
| Transcript | `backend/orchestration/transcript.py`、`backend/data/orch_transcript_repo.py` | 落盘记录器与读层 |
| 工具事件 | `backend/orchestration/subagent_events.py` | `tool_call_id` / `duration_ms` / 审批通知 |
| 脱敏 | `backend/services/permission_gate.py` | `redact_sensitive_args` |
| 目录端点 | `backend/api/orch_run_control.py` | `/directory` + transcript 端点 |
| 暂停路由 | `backend/api/orch_pause_routes.py` | 任务 / run 级暂停恢复 |
| 通知队列 | `backend/services/orch_run_notifications.py` | 第六路通知 |
| 成本账本 | `backend/data/usage_cost_repo.py`、`backend/services/usage_tracker.py` | run 维度聚合与归因 |
| 迁移 | `backend/data/migrations/v20_usage_run_id.py`、`v21_orch_tasks_composite_pk.py` | 回填 + 复合主键重建 |
| 前端目录 | `src/entities/orchestration/runDirectoryStore.ts` | 3s 轮询目录 |
| 统一任务模型 | `src/features/task-center/unifiedTaskModel.ts`、`canonicalTaskBoard.ts` | canonical 收敛 |
| 通知桥 | `src/features/orch-notify/orchNotify.ts`、`electron/orchNotifications.ts` | 点击深链 |
