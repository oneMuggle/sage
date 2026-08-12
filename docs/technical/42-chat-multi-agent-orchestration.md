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

轻量子 agent 执行器，纯内存、单次聊天 run 生命周期内存在，**不持久化、不建 lane、不写 lane 表**（与 lane 编排层互不干扰）。子 agent 用 `SageAgent(agent_id=...)` 非 bare 构造（bare 会留空 tool_registry，子 agent 需要 profile 白名单工具，如 researcher 的 web_search / writer 的 write_file）。

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

`ChatDispatcher.dispatch()` 阻塞 `asyncio.gather` 全部终态后才 `_aggregate`,聚合 markdown 头只能反映"本批已收到 X/X"。conductor 分批派发时(`dispatch_subagents` 工具 schema 钳制每批 ≤4)会看到多个"本批 X/X 完成",可能误判"全部完成"而提前总结。**真正的杠杆在 plan 注入块的显式总数 N + 全量执行约束**(见 §5.3)。`_aggregate` 的 partial header 保留为防御性(单测覆盖),非生产可达路径。

### 9.3 已知局限

- **plan 数 ≠ 实际派发数**：conductor 可合并/调整任务，当派发数少于 plan 时 UI 可能停在 "X/N"(N 为 plan 数)。这是 LLM 行为边界，未强制收敛。
- **老客户端不向后兼容**：`task_progress` 是新增 `AgentState` 变体，旧前端 `agentStateToText`/`agentStateToPhase` 的 `assertNever` 会抛异常。bundled 部署下前后端同版本，不可达；若未来前后端分离部署需同版本升级。
