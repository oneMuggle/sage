# Orchestration End-to-End (M5)

> 日期：2026-07-29 · 分支：`feat/orchestration-e2e`（基于 main，合并顺序在 M1/M2 之后）

## 背景与目标

Sage 的编排层（claw-code 启发的 lanes/teams）此前是 UI 只读的：Planner 的
`llm_client` 默认 None（规划是死路径）、API 无创建端点、Agent 循环内无法派生
子代理。M5 把编排层端到端接通：

1. Planner 接入真实 LLM（从用户 endpoint 配置构造，保留测试注入）
2. `POST /api/v1/orchestration/lanes` 创建端点（目标 → 任务 DAG → 泳道）
3. 循环内 `agent` 工具（主代理派生只读子代理，泳道可见）
4. 前端目标输入 + 创建编排 + 子代理徽章

## 涉及的文件与模块

**后端（新增）**
- `backend/orchestration/llm_factory.py` — 从 `app_settings` 解析 LLMClient（endpoints + modelSelections.chatModel，防御式降级 None）
- `backend/orchestration/agent_adapter.py` — `SeededAgentRegistry`（AgentRepository → Router 接口；与 main.py lifespan 共享，消除重复）
- `backend/tools/agent_tool.py` — `agent` 工具 + `SUBAGENT_TOOL_WHITELIST`（read_file/list_dir/web_search/web_fetch/memory_search/calculator）
- 测试：`backend/tests/unit/test_planner_llm.py`（9）、`test_llm_factory.py`（10）、`test_agent_tool.py`（8）、`backend/tests/api/test_orchestration_lanes.py`（7）、`backend/tests/integration/test_agent_tool_loop.py`（2）

**后端（修改）**
- `backend/orchestration/planner.py` — LLM 注入 + JSON DAG 提示词（id/title/description/depends_on/agent_hint）+ 清洗（cap 8、依赖只允许指向前序任务 ⇒ 结构无环、坏 JSON → 单任务回退）+ 修复 team_registry/task_registry 调用约定
- `backend/orchestration/lane_registry.py` — `create_lane` 多态（str | Lane + metadata），修通 Router 真实注册表路径
- `backend/data/orchestration_repo.py` — lane 的 `metadata`/`permission_preset` 往返持久化（列早已存在，仓储此前忽略）
- `backend/api/orchestration_router.py` — POST /lanes（400 空目标/未知 agent）、TaskOut、注册表改为按请求构造（测试隔离 + 避免 import 期单例固化）
- `backend/main.py` — lifespan 改用 `SeededAgentRegistry`
- `backend/tools/__init__.py` — 注册 AgentTool

**前端（修改）**
- `electron/commands.ts` + `electron/__tests__/commands.test.ts` — `orchestration_create_lane` 路由 + guard 测试
- `src/shared/api/types.ts` — `PlannerTaskOut` / `CreateLanesResponse`
- `src/shared/api/orchestrationClient.ts` — `createLane()`（+ `__tests__/orchestrationClient.test.ts`，3 例）
- `src/entities/orchestration/laneBoardStore.ts` — `createLane` action（创建 → refresh → 错误重抛供 toast）
- `src/pages/Orchestration.tsx` — 目标输入 + 创建编排按钮 + sonner toast（+ `__tests__/Orchestration.test.tsx`，4 例）
- `src/widgets/orchestration/LaneBoard.tsx` — `metadata.source` 徽章（subagent 紫/planner 靛）
- `src/shared/lib/i18n/zh.ts` + `en.ts` — `orchestration.*` 10 键 ×2

## 技术方案

- **LLM 构造**：复用 evolution.py 模式 — 构造函数可注入；缺省时
  `llm_factory.build_llm_client_from_settings()` 从 preferences 表读
  endpoints（优先 modelSelections.chatModel，次选首个带 apiKey 的 endpoint，
  `to_camel` 兼容 snake 残留），无可用配置 → None → 规划降级为单任务。
- **Lane 创建**：Planner 产出团队+任务 DAG → 每个任务按「显式 agent >
  agent_hint 命中种子 agent > Router 能力分派」绑定 agent 并建 lane，
  记录 `lane.started` 事件；lane 元数据 `source=planner`。
- **子代理**：`AgentTool.execute`（同步）→ TaskRegistry/LaneRegistry 建
  `source=subagent` lane 并 CREATED→READY→RUNNING → ThreadPoolExecutor 内
  `asyncio.run` 跑受限 SageAgent（`run_loop`，max_iterations=6）→ 成功
  SUCCEEDED / 失败 FAILED，事件经 EventRecorder 落库。答案截断 20 000 字符；
  失败返回 error ToolResult，主循环继续。白名单靠结构化（不注册）+ 子代理
  自身 ToolPolicy 双层防御。
- **能力分类**：main 无 `backend/tools/permissions.py`（随 M1 到来）—
  已在 agent_tool 模块 docstring 注明「M1 合并后按 READ 等价分类」。

## 实施步骤

- [x] 1. 阅读既有编排层/工具/前端代码，确认构建于现有注册表之上
- [x] 2. `llm_factory.py` + 单测（含 snake 残留兼容、损坏配置降级）
- [x] 3. Planner LLM 注入 + DAG 提示词 + 清洗/cap/回退 + 单测
- [x] 4. LaneRepository metadata 往返 + LaneRegistry 多态 create_lane
- [x] 5. `SeededAgentRegistry` + main.py 复用 + POST /lanes + API 测试
- [x] 6. `agent_tool.py`（只读白名单、worker 线程、lane 镜像、输出截断）+ 注册 + 单测
- [x] 7. 集成测试：run_loop 发 `agent` 工具调用 → lane SUCCEEDED → DONE
- [x] 8. 前端：IPC 路由+guard、client、store action、页面表单、徽章、i18n、vitest
- [x] 9. 质量门：ruff、py3.8 py_compile、py38_compat_rewrite --check、
      pytest unit+api（1632 通过）、integration（201 通过，5-lane e2e 绿）、
      vitest 全量（861 通过）、tsc + typecheck:electron + eslint 干净

## 风险评估与依赖

| 风险 | 缓解 |
|---|---|
| M1/M2 先合并带来的工具表冲突 | `agent_tool` 白名单是常量元组；M2 的 glob/grep/todo 合并时追加即可；`TOOL_CAPABILITIES` 分类点已在 docstring 标注 |
| Router._create_lane 传 Lane 与旧 mock 测试的约定 | `create_lane` 多态兼容两路；`test_e2e_5lane_workflow.py` 保持绿 |
| 子代理在工作线程访问 SQLite | 单一连接 `check_same_thread=False` + WAL；仅内存工具路径触达 |
| lane metadata 此前不持久化 | 补仓储往返（schema 列已存在，无需迁移） |
