# 42 · Chat-Native Multi-Agent Orchestration（聊天链路多 agent 编排）

> Chapter 42 覆盖聊天链路的多 agent 协作：`/chat/stream` 依据语义判定进入编排模式，主 LLM（conductor）经 `dispatch_subagents` 工具把子任务并行派发给子 SageAgent，进度以 `task_plan`/`task_status` 事件实时推送到前端任务树。这是对既有 [`27-multi-agent-orchestration.md`](./27-multi-agent-orchestration.md)（lane 看板编排层）的**聊天链路补充**——两个编排体系共存：lane 层处理"预脚本化 DAG + 看板"，聊天层用轻量 dispatcher 处理"conductor 依据中间结果再决策"。基线分支 `feat/multi-agent-orchestration`，2026-08-11。

## 1. 概述

Sage 已有一套成熟编排层（Planner / Router / LaneExecutor / TaskRegistry 等），但聊天链路**从未接入**：`/chat/stream` 永远是单 `SageAgent.run_loop`，无多 agent 协作。本章的聊天原生编排（方案 C 混合编排）解决三件事：

1. **语义判定**：请求进来先做轻量 LLM 二分类（`multi`/`single`），决定是否进编排；
2. **预规划 + 动态执行**：`multi` 时用 Planner 拆解出任务计划，conductor（主 LLM）依据计划调用 `dispatch_subagents` 工具，把子任务**并行**派发给子 agent——subagent 数、执行方式由 conductor 依据中间结果再决策（不是预脚本化 DAG）；
3. **实时进度**：计划与子任务状态通过 `task_plan`/`task_status` 事件走 NDJSON 流，前端渲染任务树（子任务 x/y 完成 + 状态图标 + 展开预览）。

**关键架构约束（tool-toggle 门）**：

| 硬约束 | 含义 |
|---|---|
| mode=`single` → 不注册 `dispatch_subagents` 工具 | 简单任务在**结构上**无法被过度拆解 |
| mode=`multi` → 必出 `task_plan` + 必注册工具 | 复杂任务**必须**走编排，不允许"判了 multi 却跑单 agent" |

## 2. 架构

```text
/chat/stream (POST, NDJSON)
      │
      ▼
_classify_orchestration_mode(message, orchestration_mode, llm_client)
      │  auto → LLM 二分类; force_multi/force_single → 用户 override
      │  失败/无 client → single（fail-safe 降级）
      ▼
mode = single ──► SageAgent.run_loop（普通单 agent 流，零改动）
      │
      ▼ mode = multi
Planner.decompose_request(message)  ──►  Plan.tasks (TaskRegistry/TeamRegistry 独立实例, 不建 lane)
      │  len(plan_tasks) <= 1 → 降级 single（LLM 没拆开）
      ▼
ChatDispatcher(stream_id, entry_queue, run_id, llm_config)
      │  注册 DispatchSubagentsTool(dispatcher) 到 agent.tool_registry
      │  agent.profile["tools"].append("dispatch_subagents")
      │  plan_block 注入 system prompt（plan 先行, 可展示/可取消）
      │  先推 task_plan 事件
      ▼
SageAgent.run_loop（conductor）
      │  依据计划调用 dispatch_subagents(agent_id, goal)
      ▼
ChatDispatcher.dispatch(tasks)
      │  每任务 ChatTaskState(queued→running→done/failed)
      │  MAX_CONCURRENT_SUBAGENTS=4 并发; 多出的排队
      │  每状态迁移推 task_status 事件
      │  子 agent 结果截断(50KB) + output_preview(500字)
      ▼
聚合 markdown → 返回 conductor → 自然语言收尾 → 最终 done
```

## 3. 语义判定（tool-toggle 门判定源）

`_classify_orchestration_mode`（`backend/orchestration/chat_dispatcher.py`）是门的判定源：

- `force_multi` → 直接 `multi`（跳过 LLM）
- `force_single` → 直接 `single`
- `auto`（默认）→ 轻量 LLM 二分类，prompt 只要求回答 `multi` 或 `single`；**无 client / 异常 → 降级 `single`**（绝不阻塞聊天）

实现注意：classify prompt 用 `str.replace("{message}", message)` **而非 `.format()`**——用户消息可能含字面 `{`/`}`（JSON / 代码片段 / 模板字符串），`.format()` 会抛 KeyError/IndexError 并静默降级 single。

## 4. 事件协议（NDJSON）

编排走既有 `/chat/stream` NDJSON 通道，新增 3 个中间态事件：

| 事件 | state | 字段 | 触发 |
|---|---|---|---|
| 计划 | `task_plan` | `run_id`, `plan: [{task_id, agent_id, goal}]` | multi 模式子 agent 跑之前推一次（可展示、可取消） |
| 进度概览 | `task_progress` | `run_id`, `total`, `done`, `running`, `queued`, `failed`（5 元组） | `task_plan` 之后、首个 `task_status` 之前推一次初始化（前端在子任务跑之前就拿到 total）。后续 5 元组由前端 reducer 从 `task_status` 实时聚合覆盖，后端不重复 emit |
| 子任务状态 | `task_status` | `run_id`, `task_id`, `status: queued/running/done/failed`, `agent_id`, `goal`, `error`, `output_preview` | 每个子任务每次状态迁移推一次 |

- `task_id` 约定 `t1..tN`（与 ChatDispatcher `t{index+1}` 契约一致）
- `output_preview` 上限 500 字符（UI 展开预览）
- 队列满/关闭时 `task_status` 推送**静默降级**（进度尽力而为，不阻塞聊天主流程）
- 顺序硬约束：`task_plan → task_progress → first task_status`（集成测试 `test_chat_orchestration_stream.py` 断言）；single 路径三事件都不 emit

## 5. 后端组件

### 5.1 ChatDispatcher（`backend/orchestration/chat_dispatcher.py`）

轻量子 agent 执行器，单次聊天 run 生命周期内存在。Wave 1（P0-1/P0-3，2026-08-13）起子任务不再内联 `SageAgent.run_loop`，而是经 `LaneExecutor` 执行并**写 lane/task 镜像表**（与 lane 编排层共享同一执行语义，详见 §11；§5.1 旧文"不建 lane、不写 lane 表"已修正）。子 agent 用 `SageAgent(agent_id=...)` 非 bare 构造（bare 会留空 tool_registry，子 agent 需要 profile 白名单工具，如 researcher 的 web_search / writer 的 write_file）。

关键常量：`MAX_CONCURRENT_SUBAGENTS=4`（并发上限，多出的排队）、`MAX_SUBAGENT_RESULT_CHARS=50*1024`（聚合 markdown 进 conductor 上下文的截断上限）、`MAX_OUTPUT_PREVIEW_CHARS=500`。

### 5.2 dispatch_subagents 工具（`backend/tools/subagent_tool.py`）

conductor 的工具入口，`execute_async` 调 `ChatDispatcher.dispatch`。工具参数 schema 钳制子任务数量 ≤4（与并发上限对齐）。

### 5.3 编排分支（`backend/api/legacy_routes.py` `/chat/stream`）

- `data.orchestration_mode: str = "auto"`（`force_multi`/`force_single` override）
- classify 判定 + Planner 预规划；`len(plan_tasks) <= 1` → 降级 single
- multi：注册工具 + 计划块注入 system prompt + 先推 `task_plan`、再推 `task_progress` 初始化
- 计划注入块含**全量执行约束**：`必须执行完计划中的全部 N 个子任务，等到所有子任务都返回结果后才能输出最终汇总；若本次 dispatch 只执行了部分子任务，继续调用工具执行剩余任务，不要提前给出结论`（防 conductor 分批派发时误判"全部完成"而提前总结）
- `run_id = "orch-{uuid4()}"`

### 5.4 writer 角色种子 + POST /agents（US-4）

`POST /agents` 创建端点 + `_VALID_AGENT_ROLES` 白名单（`general`/`researcher`/`writer` 等）。**writer 种子工具必须用 registry 正确名 `read_file`/`write_file`**（pre-existing：coder 种子用旧名 `file_read`，不在本计划修）。

### 5.5 Electron IPC 命令补齐（修复 pre-existing 损坏）

`agent_*` IPC 命令补齐 + `agentsApi.create`（`invoke('create_agent', payload as unknown as Record<string, unknown>)`），修复此前损坏的 agent 创建链路。

## 6. 前端链路

| 组件 | 职责 |
|---|---|
| `llmStream.ts` + `types.ts` | `AgentState` 增 `task_plan`/`task_status`/`task_progress`；`TaskPlanItem`/`TaskPlanEvent`/`TaskStatusValue`/`TaskStatusEvent`/`TaskProgressEvent` 五窄类型；`AgentEvent` 6 个松散字段（`run_id`/`plan`/`task_id`/`status`/`goal`/`output_preview`）+ 5 元组松散字段（`total`/`done`/`running`/`queued`/`failed`）；`ChatConfig.orchestrationMode`。**双声明模式**：两文件需保持同步（useChat 经 `shared/api/index.ts` → `types.ts`） |
| `chatApi.chatStream` | invoke payload 增 `orchestrationMode: config?.orchestrationMode ?? null`（undefined → null → 后端默认 auto） |
| `useChat` | `sendMessage(content, sessionId, officeRefs, orchestrationMode)` 第 4 参透传；`TaskBoard` state（`{runId, plan, statuses, progress?}`）：`task_plan` 初始化板、`task_progress` 初始化 5 元组、`task_status` 按 `run_id` 匹配才合并（旧 run 忽略）且**实时重算 5 元组**（`total = max(prev.total, statuses 去重数)`）、新消息清空 |
| `TaskTreeSection` | 任务树：每子任务一行 = 状态图标（queued ○ / running ◐ / done ✓ / failed ✗）+ agent_id 徽标 + goal；done/failed 可展开看 `output_preview`/`error`；头部"已拆解为 N 个子任务,等待结果中…"(全部完成时省略) + "完成 X/N · K 个进行中 · (F 失败)" |
| `ProgressSection` / `RightPanel` | `taskBoard` prop 非空时渲染 TaskTreeSection，否则回落既有 tool-call 列表（简单任务零视觉噪音）；编排进行中显示"编排任务 X/N 完成 · K 个进行中"(K = queued+running)取代"等待输入..." |
| 斜杠命令 | `/orchestrate` → `force_multi`、`/single` → `force_single` 手动 override（tool-toggle 门的用户逃生门）；纯命令无正文 → `用法：/cmd 你的任务描述` |

## 7. 已知限制与延后项

- `dispatch_subagents` 权限：read_only 模式 deny / prompt 模式 ask；默认 `workspace_write` 放行（不触发审批）。read_only 下 conductor 拿到"权限拒绝"文本自行降级；prompt 下会弹审批框（已知残余，接受）
- `_classify_orchestration_mode` 用 `"multi" in ...` 子串匹配，LLM 回复"需要 multi agent"会误判（parked，accuracy follow-up）
- 用户加载名为 `orchestrate`/`single` 的 SKILL.md 时，动态 skill 优先，override 分支不触发（与既有"用户显式加载的 skill 优先"设计一致）
- `task_status` 事件含必填 `agent_id`，会命中 useChat 前端 `if (evt.agent_id || evt.iteration)` 块把 UI"当前 agent"指示器改为子 agent id（大概率良性显示活跃子 agent）
- `evt as TaskStatusEvent` 依赖后端 task_status 全字段不变式（注释已声明；后端若放宽字段可改 `Partial<TaskStatusEvent>`）

## 8. 相关章节

- [`22-agents-crud.md`](./22-agents-crud.md) — agent list/update/toggle/CRUD
- [`23-chat-streaming.md`](./23-chat-streaming.md) — NDJSON 协议 + Electron IPC 事件桥接
- [`27-multi-agent-orchestration.md`](./27-multi-agent-orchestration.md) — lane 编排层（M1 typed 化）
- [`36-orchestration-e2e.md`](./36-orchestration-e2e.md) — Planner LLM 注入 + lane 创建 + 循环内子代理（M5）

## 9. 进度可视化（PR #300，2026-08-12）

> 归档自 `docs/plans/2026-08-12_multi-agent-progress-visibility.md`（已删除）。
> 背景现象：用户复杂任务被拆为 6 子任务，conductor 在 2 个完成时就给最终汇总，右侧 progress 区误显示"等待输入"。

### 9.1 数据流

`task_plan`(计划) → `task_progress`(5 元组初始化) → 多个 `task_status`(状态迁移,前端 reducer 实时重算 5 元组覆盖) → `done`。前端 `TaskBoard.progress` 是 5 元组快照的**单一数据源**,`ProgressSection` 与 `TaskTreeSection` 共享同一份,避免"总分不一致"的视觉冲突。

### 9.2 conductor 不提前汇总的约束

`ChatDispatcher.dispatch()` 阻塞 `asyncio.gather` 全部终态后才 `_aggregate`,聚合 markdown 头只能反映"本批已收到 X/X"。conductor 分批派发时(`dispatch_subagents` 工具 schema 钳制每批 ≤8,PR #302 后)会看到多个"本批 X/X 完成",可能误判"全部完成"而提前总结。**真正的杠杆在 plan 注入块的显式总数 N + 全量执行约束**(见 §5.3)。`_aggregate` 的 partial header 保留为防御性(单测覆盖),非生产可达路径。

### 9.3 已知局限

- **plan 数 ≠ 实际派发数**：conductor 可合并/调整任务，当派发数少于 plan 时 UI 可能停在 "X/N"(N 为 plan 数)。这是 LLM 行为边界，未强制收敛。
- **老客户端不向后兼容**：`task_progress` 是新增 `AgentState` 变体，旧前端 `agentStateToText`/`agentStateToPhase` 的 `assertNever` 会抛异常。bundled 部署下前后端同版本，不可达；若未来前后端分离部署需同版本升级。

## 10. 修复记录：task_id 碰撞 + artifacts 落库 + maxItems 解耦 + agent_hint 校验（PR #302，2026-08-12）

> 归档自 `docs/plans/2026-08-12_orchestration-task-id-and-artifacts.md`（已删除）。
> 背景现象：用户实测复杂任务（"学习量化交易…"）编排时 UI 任务板恒显"完成 3/6"、最终回复声称生成 `Quant_Trading_Comprehensive_Manual.md` 但 Artifacts 面板无入口、"4 轮"派发。

### 10.1 F1 — task_id 全局递增

**症状**：UI 恒显 3/6（6 任务真实完成）。**根因**：`ChatDispatcher` 每次 dispatch 调用从 `t1` 重编号（`task_id=f"t{index+1}"`，index 是本次调用内下标），而计划 task_id 是全局 `t1..tN`（§5.3）。前端 reducer 按 task_id 合并、任务板按 plan 的 task_id 查状态 → 计划里 t4/t5/t6 永远收不到 status 事件。

**修复**：`__init__` 加 `self._next_task_index = 0`，每分配一个任务用 `f"t{self._next_task_index + 1}"` 后 `+= 1`（**含 malformed KeyError 分支**，占位也消耗计数器，避免挤占后续合法编号）。conductor 同一 run 内多次派发 → task_id 全局唯一，与计划编号对齐。

### 10.2 F2 — 普通聊天 artifacts 落库

**症状**：回复声称生成 `Quant_Trading_Comprehensive_Manual.md`，Artifacts 面板无入口，仓库根却出现文件。**根因**：producer 只在 `_auth_result is not None`（有 office 授权）时 `set_tool_context`；普通聊天无 refs + 无 binding → ctx 为 None → `file_tool._record_artifact_safely` 因 `current_tool_context() is None` 静默早退 → artifacts 表恒空。

**修复**：producer 无条件设置 `ToolExecutionContext`。无授权分支用 `ToolExecutionContext(session_id=data.session_id, stream_id=stream_id, binding_generation=0, office_doc_scope=frozenset())`，finally 里 `reset_tool_context` 保证不泄漏。office 工具仍因空 scope 从 `get_schemas_for_llm` 隐藏（防御纵深保留）。

### 10.3 F3 — maxItems 与并发解耦 + 聚合总上限

**根因**：`maxItems:4` 与 `MAX_CONCURRENT_SUBAGENTS=4` 概念耦合。maxItems 管"单次调用任务数"，信号量管"同时运行数"，二者正交。计划上限 8 被派发钳到 4 → 6 任务强制 3 批（"4 轮"现象诱因）。

**修复**：`maxItems 4→8`（= `MAX_PLAN_TASKS`，注释说明解耦）；`ChatDispatcher` 新增 `MAX_AGGREGATE_CHARS=120KB`，`_aggregate` 返回前对整体截断 + 尾部"[聚合结果超过上限，已截断]"提示（保留头部进度摘要），防 8 项最坏 8×50KB=400KB 灌爆 conductor 上下文。

### 10.4 F4 — planner agent_hint 校验到可派发角色

**根因**：planner `_sanitize_tasks` 对 LLM 产出的 `agent_hint` 照单全收，`content_writer`/`editor` 等不存在角色 → `ChatDispatcher._run_subagent` 的 `get_enabled_agent()==None` 快速失败（spec §5.1）→ 整批子任务 failed。

**修复**：`_sanitize_tasks` 用 `_is_dispatchable_agent()`（延迟 import `get_enabled_agent()`，读 SQLite 运行时状态）校验，不在合法集 → 丢弃 hint，conductor 用默认角色。

> **实现要点**：不要用 `get_agent_registry()`（内存默认注册表）校验 —— 它不反映 SQLite enabled 状态（`toggle_agent` 禁用后仍残留），且不含自定义 agent（只存 SQLite）。`get_enabled_agent()` 与 `_run_subagent` 派发判定完全一致，保证 planner 放行的 hint 一定能成功派发。

### 10.5 已知遗留

- **task_id 对齐仅在连续按序整批派发时成立**：conductor 合并/乱序/跳过重试会错位（§9.3 plan≠派发 同族）。F3 放宽 maxItems 后 ≤8 任务可单批全派缓解，未根除；后续建议把计划 task_id 随工具调用传入或按 (agent_id, goal) 匹配。
- **无绑定会话 write_file 落 cwd**：普通聊天无 workspace_root 时 write_file 以相对路径落到进程 cwd（仓库根曾出现调试产物）。建议后续单独治理（如无绑定会话默认限制写入目录）。

## 11. 执行控制层（Wave 1 P0，2026-08-13）

> 归档自 `docs/superpowers/plans/2026-08-13-orchestration-execution-control-wave1.md`。
> 背景：§9/§10 时代子任务由 ChatDispatcher 内联 `SageAgent.run_loop` 直接执行——无 RecoveryPolicy 结构化重试、无复核、无文件隔离。本波把执行职责下沉到既有 lane 层：`SubagentRunner`（真实 agent runner）+ `LaneExecutor.execute_lane`（重试/事件已实现），并补 reviewer 验证环与 scratch 目录隔离。分支 `feat/orchestration-execution-control-wave1`，2026-08-13。

### 11.1 子任务经 LaneExecutor 执行（P0-1）

`ChatDispatcher._run_subagent` 不再内联 run_loop，而是为每个子任务建 Task + Lane，经 `LaneExecutor` 执行（`backend/orchestration/subagent_runner.py` 新建）：

- `TaskRegistry.create_task` + `mark_running`；`LaneRegistry.create_lane`（`lane-<task_id>`）
- TaskPacket 带 `RecoveryPolicy(on_failure="retry", max_retries=2)`——重试语义由 lane 执行循环承担
- `SubagentRunner` 作为 `LaneExecutor.agent_runner`：构造 `SageAgent(agent_id=..., policy=<ToolPolicy>)` 跑 `run_loop`，返回 `{"status":"succeeded","output":<DONE content>}`
- `run_lane_with_retry` 封装 `execute_lane` 重试循环：executor 返回 `{"status":"retrying"}` 时再调 `execute_lane`，`retry_count` 累积在 `lane.metadata`，max_retries 耗尽后 executor 返回 failed 终态

### 11.2 task_status 事件增 retry_count（P0-1 透传）

`ChatTaskState.retry_count` 回填自 `lane.metadata["retry_count"]`，`_emit_task_status` 把 `retry_count` 放进 `task_status` 事件。前端 `TaskStatusEvent` 接口（`src/shared/api/types.ts:225`）未声明 `retry_count`——SSE JSON 多出的运行时键被忽略，新字段天然兼容，不涉及前端改动。

### 11.3 lane 镜像事实落地（范围修正）

Wave 1 起 ChatDispatcher 子任务**确实写 lane/task 表**（§5.1 旧文"不建 lane、不写 lane 表"已修正）。原因：`LaneRepository`/`TaskRepository` 仅 SQLite（无内存模式），ChatDispatcher 路由 `LaneExecutor` 必然落库。spec 原计划 Wave 3 的 P2-10 相应收窄为 board 端点 + API `/lanes` 可执行。

### 11.4 scratch 隔离（P0-3）

每个子任务建隔离目录 `<data_dir>/orch_scratch/<run_id>/<task_id>/`（`data_dir = get_database().db_path` 的父目录，即 `<repo>/data/`），子 agent 以 `ToolPolicy(workspace_root=<scratch_dir>)` 构造——write_file 等文件工具被 `file_tool._path_within_workspace` 边界检查锁进 scratch，越界写返回 `path_outside_workspace` 拒绝。`data/orch_scratch/` 已加入根 `.gitignore`（运行时产物，不入库）。

### 11.5 reviewer 角色 + 聚合后验证环（P0-2）

- **reviewer profile**（Task 4）：`create_default_agents()` 增 `reviewer`（`backend/agents/profiles.py`，无工具，system prompt 要求输出 `[FACT|HYPOTHESIS|NEGATIVE_EVIDENCE] <断言> (confidence: 0-1)` assertions）；`_VALID_AGENT_ROLES` 增 `"reviewer"`（`backend/api/legacy_routes.py`）
- **验证环**（Task 5）：`ChatDispatcher` 增 `total_tasks` 构造参——`_next_task_index >= total_tasks`（本次派发已覆盖 plan 全部任务）时跑 `_run_review`：reviewer 子任务经 LaneExecutor 执行（不带 packet → `_get_recovery_policy` 给 `{on_failure:"fail", max_retries:0}`，复核失败 fail-fast 不重试），`_parse_assertions` 解析断言，`executor.submit_with_report` 落 `ReviewReport`（content-hashed + `lane.review.submitted` 事件），verdict markdown 块（pass/fail + 指令）追加进聚合 → 进 conductor 上下文；reviewer 失败降级跳过（绝不阻塞聊天）
- **`task_review` NDJSON 事件延后 Wave 2**：新增 `AgentState` 变体会触发前端 `agentStateToText`/`agentStateToPhase` 的 `assertNever` 断裂（§9.3 已知限制同族）。Wave 1 复核结论以 markdown 进聚合 + ReviewReport 落库，纯后端成立

### 11.6 模块 docstring 同步

`ChatDispatcher` 模块 docstring 同步更新——不再宣称"不建 lane/不写 lane 表"，如实描述 lane 镜像、`run_lane_with_retry` 重试、`retry_count` 回填、scratch 隔离、task_status 事件兼容。

### 11.7 已知限制与延后项

- **派发数 < plan 总数时 review 永不触发**：`total_tasks` 门控依赖 `_next_task_index >= total_tasks`，conductor 合并/跳过任务时复核跳过——P0-2 核心功能缺口，已知
- **多批派发边缘二次 create_lane IntegrityError → 静默降级**：gate 累计达 total_tasks 后再次 dispatch 会重复 `create_lane("lane-review-<run_id>")` 抛 IntegrityError，`dispatch` 捕获后跳过复核（正常单批路径不可达，`_reviewed` 守卫未做）
- **review task 必须手动 mark_running**：`mark_completed`/`mark_failed` 均要求 RUNNING 态，`_run_review` 中显式 `mark_running` 保证 review 任务状态机一致
