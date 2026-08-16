# Wave 3 · 编排深化设计（P2-7/8/9 + 休眠层 + 计划卡接线）

> 承接 Wave 2（PR #315, `be1bd2d3`）的 §12.6 延后项与 spec §7 的 P2 系列。
> 本次设计覆盖全部 5 个承接项，分 3 个 PR 递进交付。
> 分支基线：main @ `be1bd2d3`。日期：2026-08-14。

## 1. 背景与目标

Wave 1/2 已交付编排的**执行控制**（重试/reviewer/scratch）与**计划生命周期**
（持久化/resume/计划卡 409 锁定/depends_on）。Wave 3 补齐三块结构性缺口：

| 承接项 | 现状缺口 | 本波目标 |
|---|---|---|
| **P2-7** 派发 task_id 对齐 | `dispatch_subagents` schema 无 task_id；dispatcher 用 `_next_task_index` 自增编号，与计划编号错位（§9.3 已知遗留） | 计划权威 + 未知回退 + 缺省自分配 |
| **P2-8** 确定性模板 | `orchestration_mode` 只支持 auto/force_multi/force_single，拆解永远走 LLM | `template:<id>` 模式 + 内置模板 + 前端选择器 |
| **P2-9** 配置化 | `chat_dispatcher.py` 模块常量硬编码（并发/截断/重试/scratch） | `app_settings.orch.*` 段，前后端完整接入 |
| **P2-10** 休眠层 | chat 镜像 lane 已落地；`POST /orchestration/lanes` 只建不跑；无 board 端点 | API lane 真实执行 + LaneBoard 监控端点 |
| **计划卡接线** | `PlanCard`/`PlanCardList` 已交付 + 8 单测，未接入任何视图（评审 Important#1） | 视图接线 + 取消执行 + resume 恢复流 |

## 2. 三个 PR 总览

```
PR A  后端结构   P2-7 计划权威 task_id + P2-8 模板 + P2-9 配置化 + run 级取消端点
PR B  休眠层     P2-10 API lane 可执行（异步+wait 参数）+ GET /orchestration/board
PR C  前端       PlanCard/PlanCardList 视图接线 + 取消执行按钮 + 模板选择器 + resume 恢复流
```

依赖关系：PR A 独立可合；PR B 依赖 PR A 的 P2-9 配置（`orch_settings`，重试/并发参数复用）；
PR C 依赖 PR A 的取消端点 + P2-8 模板 + P2-9 前端设置 + §5.3 的 `original_request`
（独立于 PR B，可单独合）。按 A → B → C 顺序合入。

---

## 3. PR A — 后端结构

### 3.1 P2-7 派发 task_id 对齐（计划权威 + 未知回退）

**问题**：conductor 经 `dispatch_subagents` 派发时 schema 无 task_id（
`backend/tools/subagent_tool.py:25-43`），dispatcher 用 `_next_task_index` 自增
（`chat_dispatcher.py:141,179`）。conductor 合并/乱序/重试时 task_id 与计划编号错位，
前端任务树按 task_id 合并会错乱。

**设计**（用户决策：计划权威 + 未知回退）：

1. **工具 schema 加必填 `task_id`**（`subagent_tool.py` `INPUT_SCHEMA`）：
   ```python
   "properties": {
       "task_id": {"type": "string"},   # 新增
       "agent_id": {"type": "string"},
       "goal": {"type": "string", "maxLength": 2000},
   },
   "required": ["agent_id", "goal", "task_id"],   # task_id 必填
   ```
   conductor 从 `task_plan` 事件的 `plan[].task_id`（t1..tN）取编号回传。

2. **ChatDispatcher 计划权威**：新增构造参数 `plan_json: Optional[str] = None` 与
   内存索引 `self._plan_by_id: Dict[str, dict]`。**首次 dispatch 时**（在
   `_first_dispatch_at` 检查处，`chat_dispatcher.py:170-172`）从
   `self._orch_run_repo.get(self.run_id)` 读 `plan_json` 构建索引——
   **计划卡编辑（`update_plan` → 409 锁定前）经 plan_json 落库后，首次派发即读到
   编辑后的计划**。plan_json 已含 `depends_on`（Wave 2 P1-6），直接透传。

3. **`dispatch()` 逐任务三态路由**：
   - **匹配计划**（`raw["task_id"] in self._plan_by_id`）→ goal/agent **以计划为准**
     （plan-authoritative，覆盖 tool-passed 值；计划卡编辑在派发前生效的杠杆点）。
   - **未知 task_id**（不在计划）→ 回退 tool-passed 值建新 state（允许 conductor
     动态加任务，不强制闭环）。
   - **缺 task_id**（malformed/旧客户端）→ 自动分配 `t{self._next_task_index + 1}`
     （保留 `_next_task_index` 仅作缺省计数器，向后兼容）。

4. **`_plan_by_id` 只建一次**：首次 dispatch 读库后缓存；同 run 后续 dispatch 复用。

### 3.2 P2-8 确定性模板（OrchestrationTemplate）

**问题**：`orchestration_mode` 无确定性拆解路径，LLM 分解不可复现。

**设计**（用户决策：`orchestration_mode` 支持 `template:<id>`）：

1. **新文件 `backend/orchestration/templates.py`**：
   ```python
   @dataclass
   class TemplateStage:
       id: str            # t1..tN（模板内序号，depends_on 引用它）
       agent_id: str      # 建议角色（需可派发，否则回退 primary）
       goal: str          # 可含 {request} 占位符，运行时 str.replace 替换
       depends_on: List[str]

   @dataclass
   class OrchestrationTemplate:
       id: str
       name: str
       description: str
       stages: List[TemplateStage]

   BUILTIN_TEMPLATES: Dict[str, OrchestrationTemplate]
   def get_template(tid) / def list_templates() -> List[dict]
   ```
   内置模板（对 spec §7.2 `research-write-review` 的调整：**review 不进模板**——
   现有 P0-2 验证环自动兜底，模板含 review stage 会与验证环双重评审）：
   - `research-write`（2 stage）：t1 researcher → t2 writer（depends_on [t1]）
   - `gather-analyze-report`（3 stage）：t1 gather → t2 analyze（dep [t1]）→
     t3 report（dep [t1,t2]）

2. **`Planner.decompose_from_template(template_id, request)`**（`planner.py` 新增）：
   - 校验模板存在；不存在 → `ValueError`。
   - 建 team（复用 `decompose_request` 结构），逐 stage 建 Task：
     `task_id=task-<uuid>`、`description=goal.replace("{request}", request)`
     （无占位符则追加 `\n目标: {request}`）、`parameters.agent_hint` 仅当
     `_is_dispatchable_agent(stage.agent_id)` 为真时写入（复用 F4 校验，
     否则回退 conductor 默认角色）。
   - `depends_on`（stage.id → 真实 task_id）在 task 创建后解析，语义同
     `_sanitize_tasks`（只引更早任务，保 DAG）。
   - `Plan.reasoning = f"template: {template_id}"`。

3. **`legacy_routes` 集成**：
   - `_classify_orchestration_mode` 增分支：`orchestration_mode.startswith("template:")`
     → 直接返回 `"multi"`（模板即强制编排，跳过二分类）。
   - multi 分支（`legacy_routes.py:1745-1749`）：mode 为 template 前缀时用
     `decompose_from_template` 替代 `decompose_request`；模板不存在 → 降级 single
     （logger.warning）。`plan_json`/`task_plan` 事件沿用既有 emit（t{i} 编号）。

### 3.3 P2-9 配置化（app_settings.orch.* 段）

**问题**：`chat_dispatcher.py` 常量硬编码（`35-62` 行：并发 4 / 聚合 120KB /
单结果 50KB / preview 500 / lane 迭代 8 / scratch_root）。

**设计**（用户决策：后端 + 前端设置页完整接入）：

1. **新文件 `backend/orchestration/orch_settings.py`**：
   ```python
   @dataclass
   class OrchSettings:
       max_concurrent_subagents: int = 4
       max_aggregate_chars: int = 120 * 1024
       max_subagent_result_chars: int = 50 * 1024
       max_retries: int = 2
       max_lane_iterations: int = 8
       scratch_root: str = "orch_scratch"

   def load_orch_settings() -> OrchSettings:
       # SettingsRepository().get_json("app_settings") → raw.get("orch", {})
       # 逐键读取，缺省回落 dataclass 默认值（旧设置无 orch 段 → 全默认）
   ```
2. **ChatDispatcher 构造注入**：`__init__` 增 `settings: Optional[OrchSettings] = None`，
   `self.settings = settings or load_orch_settings()`。模块常量改为实例引用：
   - `_semaphore = asyncio.Semaphore(self.settings.max_concurrent_subagents)`
   - `_aggregate` 截断 → `self.settings.max_aggregate_chars` /
     `self.settings.max_subagent_result_chars`
   - `_run_subagent`：`RecoveryPolicy(on_failure="retry", max_retries=self.settings.max_retries)`；
     `MAX_LANE_ITERATIONS` → `self.settings.max_lane_iterations`；
     `_scratch_dir_for` 的 `SCRATCH_ROOT` → `self.settings.scratch_root`。
   - `legacy_routes` 装配：`ChatDispatcher(..., settings=load_orch_settings())`。
3. **前端 `src/entities/setting/types.ts`**：
   ```ts
   export interface OrchSettings {
     maxConcurrentSubagents: number;   // 4
     maxAggregateChars: number;        // 120 * 1024
     maxSubagentResultChars: number;   // 50 * 1024
     maxRetries: number;               // 2
     maxLaneIterations: number;        // 8
   }
   // AppSettings 增 orch: OrchSettings; DEFAULT_SETTINGS.orch = {...}
   // SETTINGS_VERSION '3.0.0' → '4.0.0'（schema 变更）
   ```
   `settingsClient.ts` 的 `PreferenceKey` 白名单不变（`app_settings` 已含子结构）。
   **`scratch_root` 只后端配置**（app_settings.orch.scratch_root 仍存储），前端 UI 不渲染
   路径字段（data_dir 路径对用户无意义）。
4. **设置页**：`GeneralTab.tsx` 增「编排（Orchestration）」section，渲染 5 个数字输入
   （`NumberField` 或复用既有控件模式），`updateSettings({ orch: { ...settings.orch, [k]: v } })`。
   配套 i18n keys（`src/locales/*.json` 的 `settings.*` 段）。

### 3.4 run 级取消执行

**问题**：计划卡"取消执行"按钮需要真正的 run 级取消（用户决策：加取消执行按钮），
现状无后端取消能力（`orch_routes.py` 只有 list/get/resume/update_plan 四端点）。

**设计**：

1. **进程内注册表**（`chat_dispatcher.py` 模块级）：
   ```python
   _ACTIVE_DISPATCHERS: Dict[str, "ChatDispatcher"] = {}
   ```
   `legacy_routes` 在构造 dispatcher 后 `_ACTIVE_DISPATCHERS[run_id] = dispatcher`，
   在 producer 的 `finally` 中 `pop`（长连接结束即注销）。
2. **ChatDispatcher 可中断**：
   - `self._cancelled = asyncio.Event()`（构造时初始化）。
   - `def cancel(self) -> bool`：若已 set 返回 False（幂等），否则 set 并返回 True。
   - `_run_one`（`chat_dispatcher.py:204`）开头检查
     `if self._cancelled.is_set(): state.status = "cancelled"; state.error = "cancelled by user"; self._emit_task_status(state); return`。
   - **语义边界**：取消后 queued 任务不再启动（转 cancelled）；**running 子任务不硬杀**
     （SubagentRunner 无中断通道，run_loop 内部不可达）——尽力放行，已完成结果仍参与聚合，
     conductor 可见 cancelled 状态。已知局限（§7）。
3. **新端点** `POST /api/v1/orch/runs/{run_id}/cancel`（`orch_routes.py`，走 `@with_db_lock`）：
   - body 可选 `{reason: str = "user_cancelled"}`。
   - run 不存在 → 404；status 已是终态（cancelled/completed/failed）→ 409（幂等）。
   - `OrchRunRepository.update_status(run_id, "cancelled")`（repo 新增方法或复用 upsert）。
   - `_ACTIVE_DISPATCHERS.get(run_id)` → `dispatcher.cancel()`（同步 set event，无需 await）。
   - 返回 `{"ok": True, "run_id", "status": "cancelled"}`。
4. **前端**：`orchRunClient.cancelRun(runId)`（`src/shared/api/orchRunClient.ts` 新增）；
   PlanCard 取消按钮语义随 `locked` 切换（§5.1）。

---

## 4. PR B — 休眠层接入（P2-10）

### 4.1 API lane 可执行

**问题**：`POST /orchestration/lanes`（`orchestration_router.py:220-299`）只建 lane 不执行——
Planner 拆解 → Router 绑定 agent → `lane.started` 事件，无真实 agent 运行。

**设计**（用户决策：异步 + wait 参数）：

1. **执行通道复用**：每个 lane 用 `LaneExecutor` + `SubagentRunner` 执行（与
   `ChatDispatcher._run_subagent` 相同语义），`RecoveryPolicy(on_failure="retry",
   max_retries=load_orch_settings().max_retries)`。llm_config 从 `app_settings`
   构建（`build_llm_client_from_settings()` 同源配置；无配置 → lane 直接 failed
   with 明确错误）。
2. **`POST /orchestration/lanes?wait=true`**：
   - 默认（异步）：创建 lanes 后 `asyncio.create_task(_execute_plan_lanes(...))`
     后台执行，立即返回 `CreateLanesOut`（lanes 状态 queued/running）。
   - `wait=true`：创建后 `await _execute_plan_lanes(...)`，返回的 lanes 带终态
     （done/failed）与 output/error。
3. **`_execute_plan_lanes`**：
   - 并行执行（`asyncio.Semaphore(max_concurrent_subagents)`），不强制 DAG 拓扑
     （与 §3.1 "DAG 只展示不强制"、ChatDispatcher 并行语义一致；spec §7.4 同）。
   - 每 lane：scratch 隔离目录（`<data_dir>/<scratch_root>/api-<team_id>/<lane_id>`）、
     task `mark_running`、`run_lane_with_retry`（max_lane_iterations 防御）、
     终态 `mark_completed`/`mark_failed`、`lane.started/completed` 事件照常记录。
   - **ReviewReport**：全部 lanes 终态后，对聚合结果跑 reviewer 验证环
     （`submit_with_report` 落 ReviewReport）。为复用，把 `ChatDispatcher._run_review`
     提取为独立模块函数 `backend/orchestration/review.py: async run_review(...) ->
     ReviewOutcome`（ChatDispatcher 与 API lane 共用；重构不改变 ChatDispatcher 行为）。
   - `wait=true` 响应 `CreateLanesOut` 增可选字段
     `review: Optional[ReviewOutcome]`（verdict/assertion_count/summary）。
4. **前端暂无消费方**（API lane 面向脚本/未来 UI）——PR B 纯后端 + 测试。

### 4.2 LaneBoard 监控端点

- 新端点 `GET /api/v1/orchestration/board`：调用既有的 `LaneBoard` snapshot（
  `backend/orchestration/lane_board.py` 已有 `LaneBoardSnapshot`，M4 交付但未暴露 HTTP）
  序列化为 JSON 返回（lanes 分状态 + freshness + 汇总计数）。

---

## 5. PR C — 前端（计划卡接线 + 模板选择器 + resume 恢复流）

### 5.1 计划卡视图接线（RightPanel Progress tab）

现状：`ProgressSection` 在 `taskBoard` 存在时渲染 `TaskTreeSection`；`PlanCard`/
`PlanCardList` 未接入。

**设计**：

1. **Progress tab 三态**（`ProgressSection.tsx`）：
   - `taskBoard == null` → 渲染 `PlanCardList`（历史编排记录，恢复入口）。
   - `taskBoard && !dispatchedAt` → 渲染 `PlanCard`（未派发，可编辑 + 开始/取消）。
   - `taskBoard && dispatchedAt` → 渲染 `TaskTreeSection`（执行中，现状）。
2. **PlanCard 交互接线**：
   - **开始执行**（`onStart(updatedPlan)`）：`orchRunClient.updatePlan(runId, plan)`
     落库（409 未派发才 free）→ 本地置 `locked=true`。真正执行杠杆在 §3.1 计划权威：
     conductor 后续首 dispatch 读到编辑后的 plan_json。首个 `task_status` →
     `dispatchedAt` → 切 TaskTreeSection。
   - **取消按钮语义**（`onCancel` 随 `locked` 切换）：
     - 未派发：`onCancel` → 清 `taskBoard`（放弃本次编排，不调后端）。
     - 已派发：按钮文案「取消执行」→ `orchRunClient.cancelRun(runId)` →
       后端置 cancelled + dispatcher 停新任务；前端收到 run 终态后清 board。
3. **`orchRunClient.ts` 增**：`cancelRun(runId)`。`getRun`/`updatePlan` 客户端已存在
   （Wave 2），`getRun` 返回的 `OrchRunDetail` 增 `original_request` 字段（§5.3 恢复流用）。

### 5.2 模板选择器

- **入口**：Chat 输入区（`ChatInput` 上方工具条）渲染编排模式条：下拉
  「编排模式：自动 ▾」，选项：自动（LLM 二分类）/ 强制编排（LLM 拆解）/
  `research-write` / `gather-analyze-report`。选择 `research-write` 等 →
  `orchestration_mode = "template:<id>"`，经 `chatStream` payload 透传（现有
  `orchestrationMode` 通道）。
- 与斜杠命令 `/orchestrate` `/single` 并存：斜杠是临时 override，selector 是持久偏好
  （本波持久偏好只存组件 state，不写 settings——YAGNI；写 settings 归后续）。
- 配套 i18n keys（`chat.*` 段）。

### 5.3 resume 恢复流（plan_override 逐字恢复）

**设计**（用户决策：plan_override 逐字恢复）：

1. **`orch_runs` 增 `original_request TEXT` 列**：`ChatDispatcher.init_orch_run`
   （`chat_dispatcher.py:334`）签名增 `original_request: str`，落库；
   `legacy_routes` 传 `data.message`。
2. **`POST /orch/runs/{id}/resume` 响应增 `original_request`**（`orch_routes.py:123`，
   `ResumeResponse` 增字段）。
3. **`/chat/stream` ChatRequest 增**（`legacy_routes.py:161 ChatRequest`）：
   - `plan_override: Optional[List[dict]] = None`——非空时**跳过 LLM 拆解**，
     直接用 override plan 建 dispatcher + 注入 conductor 计划块 + 推 task_plan；
     `total_tasks = len(plan_override)`；`orchestration_mode` 视为 `force_multi`。
     **override items 自带 task_id（t1..tN），task_plan 事件直接沿用，不重新 enumerate**。
   - `run_id: Optional[str] = None`——复用 resume 返回的 `new_run_id`（
     `ChatDispatcher(run_id=...)` 用该 id，`init_orch_run` 覆盖占位行，dispatcher
     首 dispatch 从该 run 的 plan_json 读权威计划 = override plan）。
4. **前端恢复流**（`PlanCardList` 恢复按钮）：
   `resumeRun(runId)` → `{new_run_id, plan, original_request}` →
   `sendMessage(original_request, { plan_override: plan, run_id: new_run_id,
   orchestrationMode: "force_multi" })` → 聊天流直接执行存储计划。
5. `useChat.sendMessage` 增 `planOverride`/`runId` 透传（第 4 参以上扩展或 option 对象）。

---

## 6. 测试计划

**PR A（后端结构）**：
- unit `test_subagent_tool.py`：`INPUT_SCHEMA` 校验 task_id 必填（缺省 → 工具校验失败）。
- unit `test_chat_dispatcher_plan_authority.py`：计划匹配用计划 goal/agent（覆盖 tool 值）；
  unknown task_id 回退 tool 值；缺 task_id 自动分配；`_plan_by_id` 首 dispatch 后缓存。
- unit `test_chat_dispatcher_cancel.py`：cancel 后 queued 转 cancelled；幂等；
  running 不硬杀（已完成结果入聚合）。
- unit `test_templates.py`：get/list 内置模板；`decompose_from_template` 的 reasoning/
  agent_hint（非法角色回退）/depends_on 解析；未知模板 raise。
- unit `test_orch_settings.py`：默认值 + app_settings 覆盖 + 缺 orch 段回落。
- integration `test_chat_orchestration_stream.py`：`orchestration_mode="template:research-write"`
  的 task_plan 匹配模板 stages；`/orch/runs/{id}/cancel` 全链路（落库 cancelled + 事件）。

**PR B（休眠层）**：
- unit `test_orchestration_router_exec.py`：`wait=true` mock agent runner 返回终态 +
  ReviewReport；`wait=false` 立即返回 + 后台执行完成（poll status）。
- unit `test_board_endpoint.py`：`GET /orchestration/board` 返回 snapshot 结构。
- integration：API lane 执行后 lane/task 落库终态。

**PR C（前端）**：
- vitest `ProgressSection`：无 taskBoard → PlanCardList；未派发 → PlanCard；派发后 →
  TaskTreeSection。
- vitest `PlanCard` 接线：开始 → updatePlan 落库 + 锁定；取消（未派发清 board / 派发后
  cancelRun）。
- vitest `PlanCardList` 恢复流：resumeRun → sendMessage(plan_override)。
- vitest `orchRunClient`：updatePlan/cancelRun/getRun IPC mock。
- vitest 设置页：orch section 渲染 + 数值更新。

**回归**：pytest 全量（≥3706）+ vitest 全量（≥1239）+ `typecheck:electron`（electron
改动必须跑，wave2 教训）+ CI。

---

## 7. 风险与延后项

| 项 | 处置 |
|---|---|
| plan 权威依赖首 dispatch 读库；用户点「开始」与 conductor 首 dispatch 竞态 → 编辑可能落在 409 后 | 前端 updatePlan 409 兜底显示锁定；竞态窗口毫秒级，可接受 |
| cancel 不硬杀 running subagent（无中断通道） | 已知局限，本波接受；硬杀需 SubagentRunner 中断通道，延后 |
| API lane 后台 `asyncio.create_task` 随服务重启丢失 | 持久化恢复不在本波（延后）；wait=true 路径无此问题 |
| 模板 `{request}` 用 `str.replace`（同 classify 模式，防 `.format()` 抛错） | 模板 goal 为受控文案，无注入面；保留 replace 语义 |
| `SETTINGS_VERSION` bump 对已有用户设置的影响 | `load_orch_settings` 对缺 orch 段回落默认；前端 DEFAULT_SETTINGS merge 已覆盖旧结构 |
| P2-7 计划权威下 conductor 若仍按旧 plan 编号派发（增删行后漂移） | unknown task_id 回退 tool 值 + 缺省自分配双保险 |
| 模板选择器写 settings 持久化 | YAGNI 本波只存组件 state；持久化归后续 |
