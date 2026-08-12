# Chat-Native Multi-Agent Orchestration — Design Spec

- **Date:** 2026-08-11
- **Branch:** `feat/multi-agent-orchestration` (基于 `origin/main`)
- **Status:** 已实施（2026-08-11，PR 分支 `feat/multi-agent-orchestration` 全 11 任务完成；实现细节见 `docs/technical/42-chat-multi-agent-orchestration.md`）
- **Author:** Claude (brainstorming with user)

## 1. 背景与目标

### 1.1 问题

用户实测（2026-08-11）确认：Sage 的**聊天链路没有真正的多 agent 协作**。

**现状盘点**（本次调研的完整图景）：

Sage **已有一套成熟编排层**，但三条关键链路全部断开：

| 层 | 现状 | 状态 |
|---|---|---|
| `backend/orchestration/`（~5000 行） | Planner（LLM 拆解→Team+Task DAG，`TaskGraph` 依赖就绪执行）、Router（capability 派发）、LaneExecutor（生命周期/权限/恢复/事件）、TaskRegistry/TeamRegistry/LaneRegistry、EventRecorder/LaneEvent、PolicyEngine/ReportSchema、Heartbeat/WakeScheduler | ✅ 存在 |
| `backend/api/orchestration_router.py` | `POST /orchestration/lanes`（拆解+建 lane）、GET lanes/events | ✅ 存在 |
| 前端 `/orchestration` 页面 | LaneBoard 三栏看板 + store + client | ✅ 存在 |

**但：**

| # | 缺口 | 证据 |
|---|---|---|
| 1 | **执行是桩** | `executor.py:469 _default_agent_runner` 抛 `NO_RUNNER`；生产代码无注入真实 runner（仅测试注入 fake）。lane 建了**永远不会跑** |
| 2 | **聊天未接入** | `/chat/stream` 永远单 `SageAgent.run_loop`；`legacy_routes.py:1781` 只借用 `llm_factory` 做标题生成。`_should_use_orchestrator`（L117）是关键词/长度启发式，漏判、且只分流到非流式 `/chat` |
| 3 | **进度不在聊天里** | 编排进度在独立 `/orchestration` 页面；聊天右侧 Progress 标签页只显示扁平 `streamingToolCalls`，Artifacts 标签页在编排期间为空 |

**根因**：编排层（规划/看板）与执行、与聊天流、与聊天进度 UI 三者之间从未打通。用户的核心诉求——"在聊天框输入复杂任务，看到拆解 + 并行子 agent + 进度树 + 产物"——当前完全不可达。

### 1.2 目标

用户在 `/chat/stream` 发送复杂任务（如"我需要学习量化交易，先搜集相关资料后，整理一份学习资料和操作指南"）时：

1. **拆解**为多个子任务（LLM 上下文感知，非关键词）
2. **并行派遣**子 agent 调研（researcher: web_search/web_fetch/memory）
3. **汇总**后派 writer 子 agent 产出学习资料 + 操作指南（markdown 产物）
4. 聊天右侧 Progress 标签页展示**任务树**（计划 + 子任务实时状态），Artifacts 标签页展示产物

**两条硬约束（核心验收标准）**：

- **复杂任务简单化 = 0 概率**：复杂消息必须进编排（`task_plan` 计划必出 + `dispatch_subagents` 工具必注册）
- **简单任务复杂化 = 0 概率**：简单消息必须走单 agent（无编排事件 + 无 dispatch 工具），**结构上**不可被拆解

### 1.3 非目标 (YAGNI)

- **不改现有 lane 编排层**：`backend/orchestration/`、`/orchestration` API、LaneBoard 页面全部保持原样（复用其资产，不重构其模型）
- 不做子 agent 间 A2A 通信——由 conductor 收口
- 不做任意 DAG 调度——执行顺序由 conductor（主 LLM）驱动，planner 只给计划
- 不转发子 agent 的内部工具调用为独立流事件（粒度停在 `task_status`）
- 不引入进程级隔离（子 agent = 同进程 asyncio task）
- 不改 `AgentEvent` 既有 state 语义，只**新增** `task_plan` / `task_status`

## 2. 用户故事

- **US-1**：作为用户，我对 AI 说"我需要学习量化交易，先搜集相关资料，整理学习资料和操作指南"，AI 先展示任务计划（3 个子任务：2 调研 + 1 编写），然后并行执行调研，右侧任务树实时刷新，最后 writer 产出两个 markdown 文件出现在 Artifacts 标签页。
- **US-2**：作为用户，我问"今天天气怎么样"，系统直接单 agent 回答，右侧不出现任务树、不产生额外延迟。
- **US-3**：作为用户，我用 `/orchestrate` / `/single` 斜杠命令强制开启/跳过编排。
- **US-4**：作为用户，我在 Agents 页新建"quant_analyst"角色，之后复杂任务里 planner 能按它的描述自动派发它。

## 3. 现状资产调研与决策

### 3.1 参考项目哲学（pi / claw-code 收敛结论）

> **编排不内建 DAG。LLM 决定拆什么；运行时提供"派发原语 + 进度事件面 + 结果通道"。**

| 可复用模式 | 本设计采用 |
|---|---|
| 子 agent = 同一 runtime，裁剪工具集（pi 白名单 / claw-code allowed_tools） | `SageAgent(agent_id)` + `profile.tools` 白名单（已具备） |
| 派发原语（pi `subagent` tool / claw-code `Agent` tool） | `dispatch_subagents` 工具（新增） |
| 进度事件面（pi onUpdate / claw-code LaneEvent） | `task_plan` / `task_status` NDJSON 事件（新增） |
| 结果双通道（content 给模型 / details 给 UI） | 截断文本回传 conductor + 完整结果留 registry |
| 分解决策（LLM + 运行时契约） | **方案 C：planner 预规划 + conductor 执行**（用户已确认） |

### 3.2 复用 vs 新建（本次决策）

用户确认：**方案 C 的用户可见行为不变，实现上复用现有编排资产**。

| 资产 | 用途 | 处置 |
|---|---|---|
| `orchestration/planner.py` `Planner.decompose_request()` | LLM 拆解 → 计划（含单任务降级、≤8 钳制、JSON fence 清洗） | **复用**（生成 `task_plan` 的 plan 来源） |
| `orchestration/agent_adapter.py` `SeededAgentRegistry` | AgentRepository → 可用 agent 列表（校验 agent_id 合法性） | **复用** |
| `orchestration/llm_factory.py` `build_llm_client_from_settings()` | 从用户 endpoint 设置构建 LLM client | **复用**（planner 已内置） |
| `agents/profiles.py` + `AgentProfile` | 子 agent 构造（工具白名单、system_prompt） | **复用** |
| `core/legacy/agent.py` `SageAgent.run_loop` | 子 agent 执行 | **复用**（每子任务一个 run_loop） |
| `tools/context.py` `ToolExecutionContext.stream_id` | 子 agent 内工具向聊天流推实时进度 | **复用**（扩展注入） |
| `chat_stream_registry.py` `StreamRegistry` | 聊天流队列/生命周期 | **复用**（producer 内跑编排） |
| 现有 lane 编排层（LaneExecutor/Router/Registries/看板） | — | **不改**（独立系统，互不干扰） |

**为何不复用 LaneExecutor 执行**：lane 模型是"预脚本化 DAG 执行 + 看板"，而方案 C 需要 conductor 依据中间结果再决策（如调研后决定 writer 任务），且聊天回复需要 conductor 的自然语言收尾。两套状态模型并存成本高于一个轻量 dispatcher。

## 4. 架构（方案 C 混合）

```
用户消息 → POST /chat/stream (orchestration_mode: auto|force_multi|force_single)
  │
  ├─ [gate] 复用 Planner.decompose_request() 语义判定（LLM 二分类）
  │        ├─ single → 现有单 agent 路径（不注册 dispatch 工具，零开销）
  │        └─ multi  → 复用 Planner 生成计划 plan[] ──注入 conductor context──┐
  │                                                                             ▼
  │            conductor = SageAgent("primary") + allowed_tools += dispatch_subagents
  │            ├─ ① 先发 task_plan 事件（计划先展示，可取消）
  │            ├─ ② conductor 按计划调 dispatch_subagents(tasks=[{agent_id, goal}])
  │            │      ├─ 轻量 dispatcher 建任务状态（queued→running→done/failed）
  │            │      ├─ 并行 spawn 子 SageAgent.run_loop（并发上限 4）
  │            │      └─ 聚合子结果（每子结果截断 50KB）返回 conductor
  │            ├─ ③ conductor 视结果再派 writer / 直接 file_tool 落产物
  │            │      └─ file_tool 写产物 → artifacts 表（现有机制，Artifacts 零改动）
  │            └─ ④ 最终回复 = conductor 的 DONE content
  └─ NDJSON：state + task_plan/task_status + content_delta + done
```

### 4.1 tool-toggle 门（核心机制，双失败模式的结构性钳制）

mode 判定用**独立的轻量 LLM 二分类**（`classify(message) -> "single" | "multi"`），而不是看 `decompose_request` 拆出几个任务——否则 mode 由 LLM 拆解行为决定，简单问题被拆成 3 任务时门即失效。

```
① classify(message) → mode: single | multi（独立廉价 LLM 调用；无 LLM → single）
② mode=single → 不注册 dispatch_subagents 工具、不跑 decompose_request
     └─ 主 agent 连"拆解"工具都没有 → 简单任务物理上无法被过度拆解（硬约束 2）
     └─ 语义判定（非关键词），漏判概率低于启发式；且单分支只 1 次廉价分类
③ mode=multi → 才跑 decompose_request 生成 plan，注册 dispatch_subagents
     └─ 复杂任务必出 task_plan（计划先展示）→ 硬约束 1
     └─ 即使 conductor 不立即执行，计划已可见可取消
④ 用户 override（/orchestrate | /single → force_multi | force_single）
     └─ 对两个失败模式的最终逃生门
```

### 4.2 计划先行

`task_plan` 在子 agent 跑之前入队 → 用户立即看到"AI 打算怎么拆"。执行顺序不由 plan 的先后硬编码——conductor 依据 plan 语义自行决策（先并行 research 后 writer），符合方案 C。

## 5. 组件设计

### 5.1 复用点（零改动或最小扩展）

| 组件 | 用法 |
|---|---|
| `Planner(task_registry=None, team_registry=None, llm_client=..., auto_configure=True).decompose_request(message)` | 直接调用。返回 `Plan{plan_id, team_id, tasks:[Task], original_request, reasoning}`。LLM 缺失/失败 → 单任务降级（设计已保证，调用方据此判 single） |
| `SeededAgentRegistry().get_agent(agent_id)` | 校验 dispatch 的 agent_id 在 enabled agents 内；不在 → 工具返回错误文本给 conductor |
| `SageAgent(agent_id=..., llm_config=..., allowed_tools=...)` | 子 agent 执行主体；`run_loop` 是异步生成器，产 DONE content |
| `ToolExecutionContext` | 子 agent 内文件工具写产物落到同一 session 的 artifacts 表（需把 stream_id 注入子 agent context） |

> 注意：`Planner.decompose_request` 会创建 team/task 记录。聊天编排中我们**只取其 plan 结构**，不创建 lane。若其内部 registry 必须持有，用独立 instance 并接受其记录（不改 lane 系统）。

### 5.2 新增 `backend/tools/subagent_tool.py` — `dispatch_subagents` 工具

```python
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "minItems": 1, "maxItems": 4,
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
```

- 工具执行体委托 §5.3 dispatcher，通过 `ToolExecutionContext.stream_id` 直接从工具向 `entry.queue` 推 `task_status`（不依赖 conductor 的 run_loop 事件泵 → 子 agent 跑多久进度都实时）。
- 返回值 = 聚合 markdown（截断），进 conductor 上下文；单个任务失败 → 错误摘要进聚合，conductor 可重试/改派/放弃。
- **仅 multi 模式注册**到 conductor 的 `allowed_tools`（tool-toggle 门）。

### 5.3 新增 `backend/orchestration/chat_dispatcher.py` — 轻量 dispatcher

纯内存，单次编排 run 生命周期内存在，不持久化：

```python
class ChatTaskState:
    task_id, agent_id, goal, status   # queued|running|done|failed
    output, error, started_at, finished_at

class ChatDispatcher:
    def __init__(self, stream_id, entry_queue, llm_config): ...
    async def dispatch(self, tasks) -> str   # 聚合 markdown
        # 1. 每任务建 ChatTaskState(queued) → 推 task_status
        # 2. worker pool（并发上限 4）并行:
        #      child = SageAgent(agent_id=task.agent_id, llm_config=llm_config)
        #      content = child.run_loop(...) 收 DONE
        #      ToolExecutionContext 注入 stream_id（产物落同一 session）
        # 3. 每任务迁移 running→done/failed → 推 task_status（error 隔离，其余继续）
        # 4. 聚合：每子结果截断 50KB 拼接 markdown 返回
```

- 子 agent 的 `llm_config` 与 conductor 同源（复用 `/chat/stream` producer 已构造的 config）。
- 产物经子 agent 内 file_tool → `artifact_repo.record_artifact` → 前端 Artifacts 标签页自动出现（零改动）。

### 5.4 `/chat/stream` producer 改造

`legacy_routes.py` `chat_stream_create` 的 producer：

```
① 构造 llm_config（现有逻辑不变）
② _classify_orchestration_mode(data.message, data.orchestration_mode) -> mode
   - force_multi / force_single: 直接定，跳过 LLM
   - auto: 轻量 LLM 二分类（复用 build_llm_client_from_settings；无 LLM → single）
③ mode == "multi":
     plan = Planner.decompose_request(data.message)   # 复用
     plan 为空/单任务 → 降级 single（= 没开编排）
     run_id = "orch-" + uuid
     conductor = SageAgent("primary") + allowed_tools += ["dispatch_subagents"]
     system prompt 追加 plan 块（"以下为任务计划，请按需调用 dispatch_subagents 执行"）
     入队 task_plan 事件
     → 跑 conductor.run_loop（复用现有事件泵）
   mode == "single":
     → 现有单 agent 路径完全不变（零回归）
④ 落盘/记忆/标题生成逻辑不变（conductor 的 DONE content 即最终回复）
```

- `ChatRequest` 新增 `orchestration_mode: str = "auto"`（`auto | force_multi | force_single`）。
- `_classify_orchestration_mode` 为 producer 内私有 helper（或 `chat_dispatcher` 模块函数）：单次 LLM 调用返回 `"single" | "multi"`，异常/无 client → `"single"`。

### 5.5 角色扩展：`POST /agents` + `writer` 种子

现有体系"可编辑不可增"（无 `POST /agents`；`legacy_routes.py:846` 有 `role` 白名单）。最小扩展：

1. **`POST /agents`** 创建端点（复用 `EditAgentForm` 字段）——把"可编辑"升级为"可新增"，打开可扩展性（US-4）。
2. **`writer` 默认种子**：`tools=["file_read", "file_write", "memory_search"]`，system_prompt 专长"产出学习资料/操作指南等 markdown 文档"。与其它角色同级，可编辑/禁用。
3. **派发按 `agent_id`**：`Planner.decompose_request` 的 LLM prompt 已注入可用 agents 描述（需确认其 prompt 含 description），任何自定义角色自动可被 planner 引用——`role` 白名单对编排无意义，新建角色时 `role` 可留空或并入白名单。

## 6. 事件协议（NDJSON 新增 2 种 state）

### `task_plan`（编排开始时发一次，子 agent 跑之前）

```json
{
  "state": "task_plan",
  "run_id": "orch-<uuid>",
  "plan": [
    {"task_id": "t1", "agent_id": "researcher", "goal": "搜集量化交易入门/基础资料"},
    {"task_id": "t2", "agent_id": "researcher", "goal": "搜集量化交易实操与工具资料"},
    {"task_id": "t3", "agent_id": "writer",     "goal": "整理成学习资料 + 操作指南"}
  ]
}
```

### `task_status`（每个子任务每次状态迁移发一次）

```json
{
  "state": "task_status",
  "run_id": "orch-<uuid>",
  "task_id": "t1",
  "status": "running",
  "agent_id": "researcher",
  "goal": "搜集量化交易入门资料",
  "error": null,
  "output_preview": null
}
```

- `status`: `queued | running | done | failed`
- `output_preview`: done 时截断结果（≤500 字），供 UI 展开
- **不转发子 agent 内部工具调用为独立事件**（MVP 裁剪，避免流碎片化）

## 7. 前端

### 7.1 `useChat.ts` 事件循环扩展

与现有 `permission_request`/`ask_user_question` 同样"先消费、不进内容累加器"模式：

```ts
if (evt.state === 'task_plan')  setTaskBoard({ runId: evt.run_id, plan: evt.plan, statuses: {} });
if (evt.state === 'task_status')
  setTaskBoard(prev => prev && prev.runId === evt.run_id
    ? { ...prev, statuses: { ...prev.statuses, [evt.task_id]: evt } }
    : prev);
```

- 新消息开始时清空 taskBoard（`streamingToolCallsRef.current = []` 同处）。
- `llmStream.ts` 的 `AgentState` 联合新增 `task_plan | task_status`。

### 7.2 `widgets/chat/progress/TaskTreeSection.tsx`（Progress 标签页内）

- 有 `taskBoard.plan` 时渲染任务树：每子任务一行 = 状态图标（queued ○ / running ◐ / done ✓ / failed ✗）+ `agent_id` 徽标 + goal；done/failed 可展开看 `output_preview`/`error`。
- 顶部汇总行："子任务 2/3 完成"。
- `taskBoard.plan` 为空 → 回落现有 tool-call 列表（简单任务不变，零视觉噪音）。
- `key={task_id}` 稳定定位；状态原子更新。

### 7.3 手动覆盖传输

`ChatRequest.orchestration_mode`；斜杠命令 `/orchestrate` → `force_multi`、`/single` → `force_single`（前端解析后随请求发出）。

## 8. 错误处理（每层降级，不级联崩溃）

| 层级 | 失败场景 | 行为 |
|---|---|---|
| 语义判定 | LLM 不可用 / 失败 | 降级 `single`，走现有单 agent；日志记录。**绝不因编排器故障阻塞聊天** |
| 计划生成 | `decompose_request` 降级为单任务 / 非法 JSON / 校验不过 | 视为 single（= 没开编排） |
| Dispatch 工具 | conductor 调用时 LLM 出错 | 工具返回错误文本给 conductor，可重试/改派/放弃 |
| 子 agent | 单个 run_loop 失败 | `task_status=failed` + error；其余继续（错误隔离）；失败以错误摘要参与聚合 |
| 子 agent | 全部失败 | conductor 拿到聚合错误摘要，自行降级输出 |
| 聚合 | 子结果超长 | 每子结果截断 50KB 进 conductor；完整结果留 ChatDispatcher |
| 事件推送 | 队列满/关闭 | `contextlib.suppress` 静默降级，不中断 dispatcher（进度尽力而为，正确性靠 dispatcher 内存态） |
| 并发 | 子任务超限 | 工具 schema 钳制 ≤4；并发上限 4，多余排队 |

**不变式**：编排层（判定/计划/dispatcher）任何失败都必须可降级到"等于没开编排"的单 agent 输出，不被用户感知为崩溃。这是 tool-toggle 门之外的第二条安全网。

## 9. 测试策略（TDD，两个失败模式的硬约束）

**后端单元测试**
1. 复用 `Planner.decompose_request` 的既有测试（不动）；新增：聊天气泡的 plan 提取（取 tasks → plan[] 结构）
2. `_classify_orchestration_mode`：LLM 返回 multi/single 透传；异常/无 client → `single`；`force_multi`/`force_single` 直接定
3. `ChatDispatcher`：mock 子 agent → 并发 + 事件顺序 `task_plan → (queued→running→done)*N`；单任务失败不影响其余；并发上限生效
4. `subagent_tool` 注册 toggle：**single 模式工具不注册（简单任务结构上无法被拆解）；multi 模式才注册**

**集成测试（关键）**
5. `/chat/stream` multi 路径：mock LLM 返回 multi + 计划 → 事件顺序 `task_plan → task_status... → done`；conductor 工具集含 dispatch_subagents
6. `/chat/stream` single 路径：**断言不出现 task_plan/task_status，且无 dispatch_subagents 工具**——把"简单任务复杂化 = 0"编码进测试
7. 用户 override：`force_single` 时复杂消息也不进编排；`force_multi` 反之

**前端单元测试（vitest）**
8. `useTaskBoard`：解析 task_plan/task_status → 状态树正确累积；新消息清空
9. `TaskTreeSection`：计划渲染、状态图标、output_preview 展开、空计划回落现有列表
10. 回归：`/chat/stream` single 路径既有测试全绿（编排不得破坏简单对话）

**验收口径**："复杂任务简单化"由测试 5 兜底（plan 必出 + 工具必注册）；"简单任务复杂化"由测试 6 + 测试 4 兜底（single 无工具、无编排事件）。

## 10. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| conductor 拿到 plan 后不执行（LLM 走神） | 计划展示但任务不跑 | plan 注入 system prompt + 工具描述约束（pi workflow 提示词模式）+ 用户 override 兜底（pi/claw-code 均接受此残余风险） |
| `Planner.decompose_request` 创建 team/task 记录污染 registry | 编排层脏数据 | 用独立 registry 实例接受其记录；或聊天气泡自建 plan 提取（实现时定，倾向后者，最小侵入） |
| 子结果 token 灌爆 conductor 上下文 | 编排质量下降 | 每子结果截断 50KB + 只回传摘要/引用 |
| 语义判定每次多耗 1 次 LLM 调用 | 简单任务延迟增加 | 仅 multi 分支多耗（single 分支只一次廉价分类）；无 LLM 时跳过判定直接 single |
| 子 agent 工具副作用（写文件等） | 非预期产物 | 子 agent 工具集由 profile.tools 白名单控制；writer 才给 file_write |
| 并发 4 子 agent × LLM 调用 | API 配额/成本 | 并发上限 4 + 子任务数 ≤4；失败可降级 single |

## 11. 实施里程碑（草案，最终以 writing-plans 拆解为准）

| 里程碑 | 内容 | 验收 |
|---|---|---|
| M1 后端地基 | 确认 Planner 复用点（plan 提取、registry 隔离）+ `ChatDispatcher` + 单元测试 | 单测绿 |
| M2 工具 + producer | `subagent_tool` + `/chat/stream` multi 分支 + `orchestration_mode` 字段 + 事件协议 | 集成测试 4/5/6 绿 |
| M3 角色扩展 | `POST /agents` + `writer` 种子 | agents CRUD 测试绿 |
| M4 前端 | `useTaskBoard` + `TaskTreeSection` + 斜杠覆盖 | vitest 绿 + 回归绿 |
| M5 端到端 | 真实 LLM 走通（调研→写资料→产物进 Artifacts） | 用户手动验收 |
