# 36 · 编排端到端：Planner LLM + Lane 创建 + 循环内子代理（M5）

M5 之前，编排层（claw-code 启发的 lanes/teams）是 UI 只读的：Planner 的
`llm_client` 默认 `None`（规划是死路径）、API 无创建端点、agent 循环内无法派生子代理。
本章记录把编排层端到端接通的四件事。

---

## 1. Planner 接入真实 LLM

`backend/orchestration/llm_factory.py`（新增）复用 `evolution.py` 的模式——
构造函数可注入；缺省时 `build_llm_client_from_settings()` 从 `preferences` 表读 endpoints：

1. 优先 `modelSelections.chatModel`
2. 次选首个带 `apiKey` 的 endpoint
3. `to_camel` 兼容历史 snake_case 残留
4. 无可用配置 → 返回 `None` → 规划**降级为单任务**（不崩）

`planner.py` 改为 JSON DAG 提示词（`id` / `title` / `description` / `depends_on` /
`agent_hint`），并对 LLM 输出做清洗：

| 清洗规则 | 目的 |
| --- | --- |
| 任务数 cap 8 | 防洪泛（1000 任务输入被截为 8，链式依赖保持完整） |
| `depends_on` 只允许指向**前序**任务 | 结构上无环——三向环输入也能完成且结果是 DAG |
| `description` cap 4000 字符（`MAX_TASK_DESCRIPTION_CHARS`） | 落库前截断 |
| 坏 JSON → 单任务回退 | 永不因 LLM 输出畸形而失败 |

## 2. Lane 创建端点

`POST /api/v1/orchestration/lanes`：目标 → Planner 产出团队 + 任务 DAG →
每个任务按 **显式 agent > `agent_hint` 命中种子 agent > Router 能力分派** 绑定
agent 并建 lane，记录 `lane.started` 事件，lane 元数据 `source=planner`。

- 400：空目标 / 未知 agent
- `SeededAgentRegistry`（`orchestration/agent_adapter.py`）把 `AgentRepository`
  适配为 Router 接口，与 `main.py` lifespan 共享，消除重复装配
- 注册表改为**按请求构造**（测试隔离 + 避免 import 期单例固化）
- `lane_registry.create_lane` 改为多态（`str | Lane` + metadata），修通 Router
  真实注册表路径；`orchestration_repo.py` 补 `metadata` / `permission_preset`
  往返持久化（列早已存在，仓储此前忽略，无需迁移）

## 3. 循环内 agent 工具（子代理）

`backend/tools/agent_tool.py`（新增）。`AgentTool.execute`（同步）：

```
TaskRegistry/LaneRegistry 建 source=subagent lane
  → CREATED → READY → RUNNING
  → ThreadPoolExecutor 内 asyncio.run 跑受限 SageAgent(bare=True)
     （run_loop，max_iterations=6）
  → 成功 SUCCEEDED / 失败 FAILED，事件经 EventRecorder 落库
```

- **只读白名单** `SUBAGENT_TOOL_WHITELIST`：`read_file` / `list_dir` /
  `web_search` / `web_fetch` / `memory_search` / `calculator`。双层防御 =
  结构化白名单（不注册其余工具）+ 子代理自身的 `ToolPolicy`
- **超时** `SUBAGENT_TIMEOUT_S = 300`（env `SAGE_AGENT_TOOL_TIMEOUT` 覆盖）。
  `future.result(timeout=...)` → 干净的超时 error ToolResult + lane `FAILED(timeout)`；
  `executor.shutdown(wait=False)` 以免超时被 `ThreadPoolExecutor.__exit__` 再次阻塞
- **答案截断** 20 000 字符；失败返回 error ToolResult，主循环继续
- `SageAgent(bare=True)` 路径：子代理跳过记忆栈 + `register_all_tools`
  （省掉一次性注册表的浪费，含冷启动 MCP `list_tools`）；默认路径不变

### 事件循环卸载

`run_loop` 对 `agent` 工具走 `loop.run_in_executor` 派发（其余工具**分发路径不变**），
使事件循环在整个子 run 期间保持响应（health 端点、board 轮询、其它会话）。
ContextVar 说明：`run_in_executor` 会复制当前 context（Python 3.7.1+），此处无害——
`AgentTool.execute` 从不读取 `ToolExecutionContext` ContextVar，其状态全部自建。

### 能力分类（EXECUTE）

`agent` 在 `TOOL_CAPABILITIES` 中**显式登记为 `EXECUTE`**，与 `skill` / `terminal` /
`repl` 同级：派生子代理 = 启动一个自主 LLM 循环（网络 + token + worker 线程），
开放性强于 skill。因此在默认 `workspace_write` 模式下**需要用户逐次审批**；
`read_only` 模式直接拒绝。子代理自身只拿只读白名单是**第二层**防御，不能替代这一层。

回归保护：`test_permissions_enforcer.py::test_classify_tool_m5_agent_tool_is_execute`
与 `test_agent_tool_loop.py::TestAgentToolPermissions`。

### 残余风险

worker 线程**不可杀**，会跑到自己的 6 轮上限；实际由 `LLMClient` 的 per-request
httpx 超时兜底（`LLMConfig.timeout=60`）。注入的、未设超时的 client 是剩余敞口——
已在 `agent_tool` 模块 docstring 声明。

## 4. 前端

- `electron/commands.ts` — `orchestration_create_lane` 路由 + guard 测试
- `src/shared/api/types.ts` — `PlannerTaskOut` / `CreateLanesResponse`
- `src/shared/api/orchestrationClient.ts` — `createLane()`
- `src/entities/orchestration/laneBoardStore.ts` — `createLane` action
  （创建 → refresh → 错误重抛供 toast）
- `src/pages/Orchestration.tsx` — 目标输入 + 创建编排按钮 + sonner toast
- `src/widgets/orchestration/LaneBoard.tsx` — `metadata.source` 徽章
  （subagent 紫 / planner 靛）
- i18n `orchestration.*` 10 键 ×2

## 5. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| `Router._create_lane` 传 `Lane` 与旧 mock 测试的约定冲突 | `create_lane` 多态兼容两路；`test_e2e_5lane_workflow.py` 保持绿 |
| 子代理在工作线程访问 SQLite | 单一连接 `check_same_thread=False` + WAL；仅内存工具路径触达 |
| lane metadata 此前不持久化 | 补仓储往返（schema 列已存在，无需迁移） |
| 子代理无限跑 | `max_iterations=6` + `SUBAGENT_TIMEOUT_S` + httpx per-request 超时 |

## 6. 测试

| 层 | 文件 | 数量 |
| --- | --- | --- |
| 单元 | `test_planner_llm.py` | 9 |
| 单元 | `test_llm_factory.py`（含 snake 残留兼容、损坏配置降级） | 10 |
| 单元 | `test_agent_tool.py` | 8 |
| 单元 | `test_permissions_enforcer.py`（agent=EXECUTE 回归） | 1 |
| API | `test_orchestration_lanes.py` | 7 |
| 集成 | `test_agent_tool_loop.py`（含超时、事件循环 ticker、审批拦截） | 5 |
| 前端 | `orchestrationClient.test.ts` 3 + `Orchestration.test.tsx` 4 + commands guard | 7+ |
