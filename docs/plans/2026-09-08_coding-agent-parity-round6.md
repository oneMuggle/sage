# 编码代理对标差距分析·第六轮：多智能体编排与通信收口（2026-09-08）

- **状态**：批次 A 已交付（PR #521 → main 07762ec9；win7 PR #523 → 67af641e）；批次 B 已交付（分支 `feat/parity-r6-batch-b`，基线 origin/main 07762ec9）
- **上游文档**：round4（批次 A-E 已交付）、round5（批次 A 信任闭环还账，`.worktrees/feat-parity-r5-batch-a` 在途）——本文不重复其内容，聚焦此前四轮从未系统盘点的**多智能体链路**：任务拆解、编排分发、记录持久化、主 agent ↔ subagent 通信
- **对标对象**：Claude Code（Task/Agent 工具 + 后台代理 + TaskOutput/TaskStop）、Cursor（后台 agent + 逐 hunk 审查）、Devin（planner→executor 会话）、OpenHands（全量事件流持久化可回放）
- **编号约定**：本轮起用 **O 系**（Orchestration），避免与 L/U/F/S 混编
- **方法**：四路代码勘察（拆解链 / 编排链 / 记录链 / 通信链），全部结论附 `file:line` 证据；设计文档（subagent-realtime-monitoring-and-steering / subagent-live-events-and-orchestration-autopilot）逐条对照代码勘误

## 0. 结论速览

前三轮解决"工具面 + 会话语义 + 信任感 UI"之后，本轮盘点发现：Sage 的多智能体链路**看得见（事件双通道投影 + Drawer + 实时步骤）跑得动（拓扑分波 + 重试 + 审批）**，但有四类结构性缺口：

1. **两处"说得出做不到"的断链**：steering（向运行中子代理追加指示）端点/表/UI 齐备，但**无任何代码消费**——消息落库后成死信，前端"已投递，等待执行器接收"的提示与后端现实不符（O1）；`observe_subagents` 工具类已实现且有单测，但**从未注册进生产 registry**，conductor 实际用不了（O4）。
2. **兜底缺失**：编排子任务无 wall-clock 超时（LLM 单请求 60s × profile 迭代上限只能兜上限不兜墙钟）；子代理可嵌套派发只靠白名单结构性拦截，自定义 profile 可穿透且无深度限制（O2/O5）。
3. **记录断点**：子代理对话 transcript 只存内存 `_histories`（重启即失）；`usage_events.session_id` 对子代理恒为 NULL——会话级花费统计不含子代理消耗，也无法归属到 orch run/task（O3）；崩溃后 `orch_runs.status` 永远滞留 `running`（会话级有 `recover_stale_run_states`，run 级没有对应物）（O6）。
4. **拆解层薄**：单 agent 路径 system prompt 无任何任务拆解/todo 引导文本（唯一引导来自工具 description）；`plan_write` 工具无读取方、无 SSE、无 UI（与 `todo_write` + 编排计划重复建设，半成品）；失败后无代码级 re-plan（仅重试 + 级联失败 + LLM 软调整）；编排 resume 的后端通道（`plan_override`）仍在但前端入口已删，计划数据"在库无人引用"。

与主流的定位差异：Claude Code 的 subagent 结果经完整 transcript 持久化可随时回放、支持后台代理与中途 TaskOutput；OpenHands 一切皆事件、全量落库。Sage 的编排事件只有**截断摘要**（预览 500 字、事件预算 200 条/任务），这是产品定位（桌面工作台、成本敏感）下的有意取舍，本轮不追平"全量 transcript 落库"，只收口断链与兜底。

## 1. 四链路差距矩阵

### 1.1 任务拆解

| # | 现状 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| D1 | 单 agent 路径 system prompt 无拆解/todo 引导；拆解全靠 LLM 自主调 `todo_write`/`plan_write` | `profiles.py:333-341`（primary prompt 只讲出网/委派）、`:621-624`（build_system_base 无引导） | Claude Code system prompt 显式要求用 TodoWrite 规划 | P2 |
| D2 | `plan_write` 半成品：已注册但存储无读取方、无 SSE、无 UI，与 `todo_write` + 编排计划三套并存 | `plan_tool.py:111-141`（内存单例全量替换，无消费者） | — | P2（建议退役/并入 todo） |
| D3 | 失败后无代码级 re-plan：仅 `max_retries=2` 重试 + 级联失败 + conductor 软性调整 | `chat_dispatcher.py:593-599`（RecoveryPolicy）、`:485-518`（级联）；`Planner.refine_plan` 是 TODO 桩（`planner.py:468-485`） | Devin 失败后重规划 | P2 |
| D4 | 编排 resume 后端通道在（`plan_override` + `init_orch_run` 落库）但前端入口已删（Wave 4 删 listRuns/resumeRun），`orch_runs.plan_json` 在库无人引用 | `orchRunClient.ts:7-8`（仅剩 cancel/updatePlan/confirm）；`chatApi.ts:138` 恒传 null | Claude Code 会话 resume | P2 |

### 1.2 编排与分发

| # | 现状 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| O2 | **编排子任务无 wall-clock 超时**：`_run_subagent` 全链无 `wait_for`，只受 profile 迭代上限 × LLM 单请求 60s 兜底 | `chat_dispatcher.py:424-452`（_run_one 无超时包装）；对比 `agent_tool.py`（单委派通路有 300s） | Claude Code agent 超时可配 | **P0** |
| O5 | **无显式嵌套深度限制**：编排子代理是完整 SageAgent，若自定义 profile 白名单含 `agent` 工具即可再生一层只读孙代理，无深度拦截 | `subagent_runner.py:137`（完整构造）；全库无 depth 计数器 | — | P1 |
| — | 已具备：批次 ≤8 + 信号量 4（可配）、depends_on 分波 + 级联失败、lane 重试、run 级取消（软中断）、审批 ask/auto、followup_of 续聊、结构化输出 | `subagent_tool.py:29-31`、`chat_dispatcher.py:210/454-518`、`subagent_runner.py:241-256` | — | 不再建设 |
| — | 已知取舍：机制 B（agent 工具）同步通路超时遗弃线程不可杀（docstring 已声明）；无优先级/抢占调度 | `agent_tool.py:22-39`、`:574-600` | — | P3 |

### 1.3 记录与持久化

| # | 现状 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| O3 | **子代理用量无法归属**：`SubagentRunner` 调 `child.run_loop` 不传 `session_id` → `usage_events.session_id=NULL`，会话级花费统计不含子代理消耗 | `subagent_runner.py:174`；`agent.py:783-785`（session_id 注入点存在但调用方未传） | Claude Code /cost 含 subagent | **P1** |
| O6 | **崩溃后 orch_runs 滞留 running**：会话级有 `recover_stale_run_states`（`session_repo.py:211-231`），run 级无对应物 | `backend/main.py:262`（只恢复会话） | — | P1 |
| — | 已具备：task 状态迁移落库（orch_tasks）、事件摘要落库（orch_events，task.*/task.step.*）、after_seq 断点续传 + 启动重放、会话 run 状态收口 | `chat_dispatcher.py:900-916`、`event_hub.py:85-105`、`session_repo.py:211-231` | — | — |
| R1 | 子代理 transcript/流式输出不落库，只有 500 字预览 + 200 条事件预算；`orch_steps` 表与 repo 零写入（死表）；工具调用往返（tool_usage 死表）与审批决策历史不落库 | `subagent_events.py:35-41`、`database.py:958-985`、`permission_gate.py:309-313` | OpenHands 全量事件流 | P3（有意取舍，预算上限防灌爆） |
| R2 | 历史会话重开无法恢复子代理时间线：messages 无 run_id 关联、无 run 列表 API（Wave 4 删）、前端不调 `GET /orch/runs/{id}` | `legacy_routes.py:2876-2886`、`orch_routes.py:68-100`（无前端调用者） | Cursor checkpoints | P3 |

### 1.4 主 agent ↔ subagent 通信

| # | 现状 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| O1 | **steering 死信**：`POST /orch/runs/{id}/tasks/{tid}/steer` 端点（CAS + 限流 + 8KB 校验）落库 `orch_context_messages` 并广播事件，但 `list_pending`/`mark_delivered` 生产零调用方——无任何代码把消息注入运行中子代理上下文；前端 ContextInput 提示"已投递，等待执行器接收"与现实不符 | 端点 `orch_run_control.py:141-330`；repo docstring 自述"executor polls list_pending"（`orch_context_repo.py:5`）但全库无消费；`ContextInput.tsx:96-107` | Claude Code 向后台代理发消息（SendMessage） | **P0** |
| O4 | **observe_subagents 有实现无注册**：`ObserveSubagentsTool` 类 + 单测在，但从未注册进任何生产 registry，conductor 用不了；且其同步 `execute` 在事件循环运行时自拒（返回"应在 async 上下文调用"）——恰好命中 run_loop 对非特判工具的直接调用路径 | `observe_tool.py:83-97`；`legacy_routes.py:2251` 只注册 dispatch_subagents | Claude Code TaskOutput（读后台代理进度） | **P1** |
| — | 已具备：事件双通道（聊天镜像 subagent_event + canonical task.*/task.step.*）、parent_tool_call_id 关联、审批转发/回填/autopilot、run 级取消传播（watcher → child.interrupt）、实时 tail（liveStep + SubagentLivePanel + Drawer 时间线） | `subagent_events.py:288-318`、`chat_dispatcher.py:720-799`、`subagent_runner.py:163-171` | — | — |
| — | 已知缺口（不在本轮）：无单任务 cancel/skip 端点（只能 run 级）；主 agent 无法中途取部分结果（阻塞式聚合是工具协议使然）；机制 B 同步通路无事件桥（跨线程限制） | `TaskTreeSection.tsx:125-129`、`chat_dispatcher.py:926-985` | — | P2/P3 |

### 1.5 设计文档勘误（文档 ✅ vs 代码现实）

- `2026-09-06_subagent-realtime-monitoring-and-steering.md`：Phase 3"父/用户向运行中子代理追加信息 ✅"——**端点半落地，投递未落地**（O1）；`run_controller.py`/`steer_tool.py`/`ProgressReporter` 文档提及，代码不存在；`observe_subagents`"已实现 ✅"——类在、接线无（O4）。
- `2026-09-06_subagent-live-events-and-orchestration-autopilot.md`：P0/P1 属实；P2-1"Message.tsx 按 parent_tool_call_id 分组"未实现（用 SubagentLivePanel 替代）；P2-3"conductor 经 observe_subagents 自感知"前提不成立（未注册）。

## 2. 批次规划

| 批次 | 主题 | 内容 | 状态 |
| --- | --- | --- | --- |
| **A（本批）** | 断链收口 + 兜底补齐 | O1 steering 投递闭环、O2 子任务 wall-clock 超时、O3 子代理用量归属、O4 observe_subagents 注册、O5 嵌套深度防护、O6 orch_runs 崩溃恢复 | ✅ 已交付 |
| **B** | 拆解层增强 | D1 system prompt 拆解引导、D2 plan_write 退役、B3 单任务 skip/cancel（端点 + 任务树按钮）、B4 todo 持久化 | ✅ 已交付（见 §7） |
| **C（待排期）** | 记录深化 | R2 messages↔run 关联 + run 列表 API 恢复（历史时间线回放）、审批决策落库、orch_steps 死表处置（接线或删除） | 待排期 |

## 3. 批次 A 详细设计与实施记录

### 3.1 O1 steering 投递闭环（P0，工作量 M）

**设计**：把"消费 pending steering"作为子代理的**迭代边界行为**放进 `SubagentRunner`——子 run_loop 每轮迭代以 THINKING 事件为界，边界处拉取该任务 `apply_mode="next_boundary"` 的 pending 消息注入上下文（`role=user`，带来源/类型前缀），并 `mark_delivered`。选择边界投递而非并发注入的原因：子代理消息列表是 run_loop 就地修改的单列表，边界追加与下一轮 LLM 调用天然串行，无并发写风险。

**实现**（`backend/orchestration/subagent_runner.py`）：
- `SubagentRunner.__init__` 新增 `context_repo`（`OrchestrationContextRepository`，None = 不消费，老调用方/测试零感知）。
- run 启动前投递一次（捕获任务启动前已写入的 steering）；事件循环内 `evt.state == "thinking"` 时再投递。
- 投递格式：`【父代理/用户补充 · {message_type}】{content_redacted}`（user role）。
- 投递失败全吞降级（steering 是增强，绝不杀死子任务）。

**接线**（`backend/orchestration/chat_dispatcher.py`）：`_run_subagent_impl` 构造 `SubagentRunner` 时惰性创建 repo 传入。前端零改动——ContextInput 的"已投递"提示自此为真。

### 3.2 O2 编排子任务 wall-clock 超时（P0，工作量 S）

- `OrchSettings` 新增 `subagent_task_timeout_s`（默认 900s，0 = 关闭），持久化 key `taskTimeoutSeconds`（`orch_settings.py` `_RAW_KEYS` 映射，类型守卫复用 int 分支）。
- `ChatDispatcher._run_one`：`asyncio.wait_for(self._run_subagent(state), timeout=...)`；`asyncio.TimeoutError` → 任务 `failed`，error `task_timeout: 子任务执行超过 Ns，已强制终止`（与用户取消区分：cancel 置位时仍归 cancelled）。下游级联失败复用既有闭包逻辑，无需改动。
- 超时即 `wait_for` 取消内层协程——子 run_loop 的 `async for` 在取消点收口（与 `agent_tool` 异步通路的 L12 根修同一语义）。

### 3.3 O3 子代理用量归属（P1，工作量 S）

- `ChatDispatcher` 构造参数新增 `session_id`（`_build_orchestration_dispatcher` 透传 `data.session_id`）；`init_orch_run` 兜底赋值。
- `SubagentRunner` 新增 `session_id`，`child.run_loop(messages, llm_config=..., session_id=...)`（仅非空时传，兼容既有测试桩签名）。子代理每次 LLM 调用经 `llm_client.session_id`（`agent.py:783-785` 既有注入点）落 `usage_events.session_id`——会话级花费统计自此包含子代理消耗。
- 单委派通路（`agent_tool._run_subagent_async`）同样补传（从 `current_tool_context()` 取，异步路径已有读取点）。

### 3.4 O4 observe_subagents 注册（P1，工作量 S）

- `observe_tool.py`：读快照逻辑提取为同步 `_read_snapshot()`；`execute()` 直接同步读（快照读是纯内存操作，删除"事件循环运行时自拒"的 asyncio.run 依赖——该自拒恰好命中 run_loop 对非特判工具的同步调用路径）；`execute_async()` 委托同一实现。
- `orch_run_control.py`：补 `get_snapshot_store()` 访问器（与 `get_event_hub` 同型）。
- `legacy_routes.py` multi 分支：注册 `ObserveSubagentsTool(snapshot_store, default_run_id=run_id)` + profile 白名单追加，失败降级不阻塞编排。conductor 自此可主动轮询子任务进度（对标 Claude Code TaskOutput）。

### 3.5 O5 嵌套深度防护（P1，工作量 S）

- 新模块 `backend/orchestration/depth.py`：`ContextVar` 深度计数 + `run_at_subagent_depth()` 上下文管理器；上限常量 1（env `SAGE_MAX_SUBAGENT_DEPTH` 可调）。
- `chat_dispatcher._run_subagent_impl`：执行 lane 时置位 depth+1。
- `agent_tool.execute_async` 入口守卫：当前深度 ≥ 上限 → `subagent_depth_exceeded` 拒绝。已知限制：同步 `execute` 遗弃线程通路无 ContextVar 传播（`loop.run_in_executor` 不复制上下文），不设防——该通路生产 run_loop 已不使用（`agent` 特判优先 execute_async），文档明示。

### 3.6 O6 orch_runs 崩溃滞留恢复（P1，工作量 S）

- `OrchRunRepository.fail_stale_running_runs()`：`UPDATE orch_runs SET status='failed', final_summary=COALESCE(final_summary,'应用重启，编排运行中断') WHERE status='running' AND run_id LIKE 'orch-%'`（LIKE 限定编排 run 前缀，避开 `agent-*` 合成 run 的潜在行）；返回行数，失败降级 0。
- `backend/main.py` lifespan：紧跟 `recover_stale_run_states()` 之后调用并打日志——与 S1 会话恢复同语义（default-failed 收口）。

## 4. 双分支纪律（main ↔ release/win7）

- 全部后端改动，py3.8 兼容纪律：禁 PEP 604/585 内建泛型标注、`except asyncio.TimeoutError`（3.8 下 `asyncio.TimeoutError` ≠ 内建 `TimeoutError`）、无 match/zip(strict=)。
- SQLite 写一律行内同步 + `_SQLITE_LOCK`（repo 既有模式，新增代码沿用）。
- 前端零改动（O1 的投递闭环让既有 ContextInput 提示成真，无需改 UI）——win7 对齐面只有 backend/ 与 main.py。
- 方向唯一：main 落地且 CI 绿 → cherry-pick `release/win7` → win7 侧测试绿 → merge。

## 5. 验收标准

| 项 | 验收 |
| --- | --- |
| O1 | run 进行中调 `POST /orch/runs/{id}/tasks/{tid}/steer` → 运行中子代理在下一迭代边界收到消息（单测：THINKING 边界注入 + mark_delivered 状态迁移）；无 repo/无 pending 时零影响 |
| O2 | `subagentTaskTimeoutSeconds=1` 时挂起子任务 ~1s 转 failed 且 error 含 `task_timeout`；下游依赖任务级联 failed；`0` 关闭时不包装 wait_for |
| O3 | `SubagentRunner(session_id=...)` → 子 run_loop 收到 `session_id` kwarg（单测捕获）；`ChatDispatcher(session_id=...)` 全链透传 |
| O4 | `observe_tool.execute()` 在事件循环运行中被调时返回快照而非自拒错误；multi 模式 producer 注册后 conductor profile 白名单含 `observe_subagents` |
| O5 | 深度 1 下 `agent_tool.execute_async` 返回 `subagent_depth_exceeded`；深度 0（conductor）正常放行 |
| O6 | 启动时 status='running' 且 run_id 前缀 `orch-` 的行被置 failed；非 running 行与其他前缀行不动 |
| 回归 | `pytest backend/tests/unit` 全绿；`vitest run`、`tsc --noEmit`、`eslint` 全绿（前端未动，防回归） |

## 6. 实施与验证记录（2026-09-08）

- 全部 6 项按 §3 设计落地；新增/修改文件：`orchestration/subagent_runner.py`（O1 投递 + O3 透传 + `run_loop_accepts_session_id` 签名探测）、`orchestration/chat_dispatcher.py`（O1 接线 + O2 wait_for + O3 session_id + O5 深度置位）、`orchestration/depth.py`（新）、`orchestration/orch_settings.py`（O2 配置）、`tools/agent_tool.py`（O5 守卫 + O3 惰性透传）、`tools/observe_tool.py`（O4 同步读重构）、`api/orch_run_control.py`（O4 getter）、`api/legacy_routes.py`（O4 注册 + O3 透传）、`data/orch_run_repo.py`（O6）、`main.py`（O6 接线）。
- 实现期修正两处设计：① session_id 透传前做 `inspect.signature` 探测（兼容三参测试桩，避免 TypeError 杀死子任务）；② agent_tool 对 `run_loop_accepts_session_id` 采用函数内惰性导入（subagent_runner 顶层 import SageAgent，与其成环）。
- 测试：新增 5 个测试文件 26 用例（`test_subagent_runner_session.py` / `test_chat_dispatcher_timeout.py` / `test_agent_tool_depth_guard.py` / `test_orch_run_recovery.py` / `test_observe_tool.py` 扩展）——26 全绿；改动相关目标集（dispatcher/runner/tool/orch 23 文件）240 passed；API 层 49 passed；全仓收集 5740 用例零收集错误；`ruff check` 全过（`asyncio.TimeoutError` 保留 + noqa：py3.8 下 ≠ 内建 TimeoutError，win7 cherry-pick 依赖此语义）。
- 本地环境既有失败（与 origin/main 基线逐一对照相同：agent_tool 白名单 3 + e2e router 1 + executor 14 errors）确认为本地环境问题，非本批引入，以 CI 为准。

## 7. 批次 B 实施与验证记录（2026-09-09）

### 7.1 D1 system prompt 拆解引导

`build_system_base()` 追加 `_TODO_GUIDANCE_PROMPT`（多步骤任务 ≥3 步先用 `todo_write` 建清单、随执行实时更新、同一时刻一条 in_progress；单步任务不建）。与 office 能力声明同模式——子代理 profile 无 todo_write 时文本无工具可调，无副作用。

### 7.2 D2 plan_write 退役

全链移除：`tools/plan_tool.py`（含内存 store）、`tools/__init__.py` 注册与导出、`domain/tool_names.py` `PLAN_TOOLS` 常量及全集、`agents/profiles.py` primary 种子与 import、`tests/unit/test_plan_tool.py`。存量 DB 清理：`ensure_default_agents()` 改名迁移段顺带剪除 `plan_write`（避免 T3 启动告警"引用未注册工具名"）。新增 2 测试（存量剪除 + 默认种子不再含）。依据：工具无任何读取方/SSE/UI，与 todo_write + 编排计划三套重复，继续暴露只会误导 LLM 把计划写进无处可去的地方。

### 7.3 B3 单任务跳过

- **dispatcher**：`_run_one` 每任务建档 `skip`（用户跳过信号）与 `merged`（skip ∨ run 级取消）事件，relay 协程汇入；源已置位时同步汇入（防 relay 未调度导致 cancel-before-dispatch 守卫漏判——首跑即回归，测试已复现）。`SubagentRunner` 经 `_task_cancel_events` 档案拿 merged，run 级取消与单任务跳过共用软中断通道。`cancel_task(task_id)`：queued → acquire 后短路（"skipped by user"），running → interrupt 通道，终态/未知 → False。跳过任务走既有级联闭包：下游 `blocked_by_failed:` failed。
- **端点**：`POST /orch/runs/{run_id}/tasks/{task_id}/cancel`（orch_routes；活动注册表 404 / 不可跳过 409）。
- **前端**：`electron/commands.ts` 路由 `orchestration_cancel_run_task`、`orchRunClient.cancelTask`、`TaskTreeSection` queued/running 行内"跳过"按钮（stopPropagation 防误开 Drawer；in-flight 集合防重复点击）。

### 7.4 B4 todo 持久化

- 新表 `session_todos(session_id PK, todos_json, updated_at)` + `SessionTodoRepository`（upsert/get/delete/delete_all，`_SQLITE_LOCK` 纪律）。
- `_NotifyingTodoStore` write-through：`replace` 落库、`get` miss 回填（经 `_cache_put` 不重复落库不触发监听）、`clear` 连持久行一起删（"处处遗忘"——否则 get 复活已清清单，首跑即发现）；匿名桶不落库；structured output 用的纯 `SessionStateStore` 保持内存语义。
- producer 流启动时推送持久化快照（`todo_snapshot`）：重启/重开会话后任务板恢复。

### 7.5 验证

- 新增/扩展 6 个测试文件：`test_session_todo_repo.py`（11 例）、`test_chat_dispatcher_task_skip.py`（4 例）、`test_orch_routes_task_cancel.py`（4 例）、`test_agent_profile_wiring.py` D1 断言、`test_profiles_intranet_web_access_migration.py` D2 两例；改动相关后端集 158 passed，聊天流/编排集成 31 passed；ruff 全过。
- 前端 tsc：仅 mermaid 模块缺失一处报错（#520 并行合入后本地未 npm install 的环境问题，main 工作区同样复现，CI npm ci 后为绿）；本批前端文件无类型错误。
