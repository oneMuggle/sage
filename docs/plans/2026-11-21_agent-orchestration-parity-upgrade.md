# 智能体编排协作对标 Claude Code 优化方案

> 状态：M0–M4.2 已实施并合并 main（并已同步 win7）：M4.1 工具耗时 + transcript 全文引用、M4.3a 编排通知 + 任务深链（main #3225 / win7 #3226）、M4.2 统一运行视图（main #3227 / win7 #3234）；M4.3b 成本透明待实施
> 分支：M4.2 `feat/orch-unified-run-view`（已合并 #3227，canonical run 目录 + 右栏回落，实施记录见 §13）
> 分支：M4.3a `feat/orch-run-notifications`（已合并 #3225，编排 run 通知 + 任务深链，实施计划见 §12）
> 分支：M4.1 `feat/orch-tool-duration`
> 分支：M3.3 `feat/orch-plan-estimates`
> 分支：M3.2 `feat/orch-failed-replan`
> 分支：M3.1 `feat/orch-subagent-types`
> 分支：M2.5 `feat/orch-pause-resume`
> 分支：M2.4 `feat/orch-subagent-thread`
> 分支：M2.3 `feat/orch-subagent-followup`
> 关联：技术手册 §27（多 Agent 编排层）、§36（编排端到端）、§42（Chat-Native 编排）、§108（Plan Mode 增强）、§125（思考展示档位）、§140（插话暂存区）、§148（任务中心）
> 调研方式：后端核心 / 前端 UI / 文档技能三路并行代码审计（本文所有 file:line 均来自实际代码）

## 1. 背景与目标

用户反馈 Sage 的智能体编排协作在以下四方面不如 Claude Code 好用：

1. **查看子 agent 内容不方便**：看不到子代理在做什么、想了什么、完整输出。
2. **主 agent 与子 agent 不能各自独立运行**：主代理派生子代理后被阻塞，子代理也不能作为独立实体继续交互。
3. **任务拆分能力偏弱**：拆分是一次性静态 DAG，缺少角色化选择与失败驱动的重规划。
4. **思考/动作透明不足**：子代理的思考、流式正文完全不可见，工具事件只有摘要。

目标：不重写编排层，在现有 `Planner → ChatDispatcher → SubagentRunner/LaneExecutor` 架构上补齐四类体验差距，使子代理成为"一等公民"。

## 2. 现状盘点（可复用资产，勿重造）

| 能力 | 现状 | 关键位置 |
|---|---|---|
| 双通路子代理 | `agent` 工具（只读、串行 await）＋ `dispatch_subagents`（编排、≤4 并发、depends_on 分波、background 派发 + collect） | `backend/tools/agent_tool.py`、`backend/tools/subagent_tool.py`、`backend/orchestration/chat_dispatcher.py` |
| 计划链路 | 模式判定（auto/force_multi/force_single/template）→ preflight（澄清 + 侦察）→ planner DAG（≤8 任务 + reasoning）→ 计划确认（`confirmed_at` 持久化）→ 步骤级确认 | `backend/orchestration/planner.py`、`plan_preflight.py`、`confirm_marker.py`、PR #3008/#3009 |
| 事件体系 | canonical EventHub（`run.* / task.* / task.step.* / task.approval_*`）+ 聊天流 `subagent_event` 镜像；`orch_events` 持久化；NDJSON `after_seq` 断线续传 | `backend/domain/orch_events.py`、`backend/orchestration/event_hub.py`、`backend/api/orch_run_control.py` |
| 运行状态 | `orch_runs / orch_tasks / orch_events / orch_context_messages` 表；取消/跳过/重试/rerun-failed；`plan_override` 重放 | `backend/data/database.py`、`orch_run_repo.py`、`backend/api/orch_routes.py` |
| 前端展示 | SubagentLivePanel（实时行）、右栏进度（StatusBar/任务树/TaskDetailView）、RunSummaryPanel、TaskCenter、`/orchestration` LaneBoard、思考三档展示 | `src/widgets/chat/SubagentLivePanel.tsx`、`src/widgets/chat/progress/*`、`src/widgets/orchestration/*` |
| 角色体系 | DB `agents` 档案（工具白名单/模型/迭代上限/技能/知识）+ `.sage/agents/*.md` 文件化导入 | `backend/agents/profiles.py`、`agents_files.py` |
| 记忆/工作区隔离 | 子代理记忆归属父专家；worktree/scratch 隔离（默认关）；深度上限 1 | `subagent_runner.py`、`depth.py` |

## 3. 差距分析（对照 Claude Code）

### 3.1 查看子 agent 内容

Claude Code：子代理是后台一等任务，有独立 transcript（含思考、工具调用全文）、实时 `/tasks` 视图、完成通知、`TaskOutput`/output_file 读取、可继续对话。

Sage 现状与缺口：

- **子代理思考/正文被显式过滤**：`subagent_events.py:122` 注释"THINKING / REASONING / CONTENT_DELTA / DONE：不转发（降噪）"。前端 `SubagentLiveEvent` 无 reasoning 字段（`chatAndEventTypes.ts:625-652`）。
- **过程只有摘要**：事件仅含 `tool_name / args_summary / preview`；每子任务事件预算 200 条（`subagent_events.py:34-35`），前端环形缓冲仅最近 20 条（`chatStreamStore.ts:184`）。
- **无 transcript 持久化**：`orch_events` 存 canonical 事件，但没有子代理消息级记录（prompt / 输出 / 思考全文）。
- **详情页断点（P0 级 bug）**：`TaskDetailView` 的事件时间线与 steering `ContextInput` 依赖 `runControlStore`，而唯一写入者 `useOrchEventSubscription` **在整个 src 无生产调用点**（已 grep 验证）→ `knownRun` 恒空 → 时间线与插话 UI 实际不渲染。
- 任务详情不能下钻子任务；完成任务无法继续对话。

### 3.2 主/子 agent 各自独立运行

Claude Code：Agent 工具立即返回 background task；同轮多条调用并发；主代理继续工作；完成后通知并由主代理转述；`SendMessage` 继续任意代理；worktree/remote 隔离。

Sage 现状与缺口：

- **`agent` 工具强制串行等待**：`_await_tool_execution_inner` 特判 await（`backend/core/legacy/agent.py:1784-1799`），且 `agent`/`dispatch_subagents` 被排除出并行工具池（`agent.py:1573-1577`）。
- **后台派发仅一个在飞**：`background=true` 可用，但同一时刻只允许一个后台派发（`chat_dispatcher.py:846-854`）。
- **子代理不是会话**：无 `parent_session_id`/`is_subagent`；会话列表只显示"所在会话运行中"，不出现子代理行；TaskCenter 不逐子代理出条目（lane 条目还依赖 `/orchestration` 页面加载才有数据）。
- **编排插话降级为排队**：`steerActiveOrchTask` 依赖空的 runControlStore 返回 false，`useChat.ts:340-353` 静默回退 queue —— 用户以为"插话"了，实际是排队。
- 无子代理级 pause/resume/替换；`resume_run` 路由不存在（docstring 残留）；无子代理独立 token 预算。

### 3.3 任务拆分能力

Claude Code：模型自主分解 + Plan mode 审批 + TodoWrite 过程管理 + 带描述的 `subagent_type` 注册表（角色即工具集/模型/prompt）+ 运行中动态追加 + 确定性 Workflow 引擎。

Sage 已有：preflight 澄清/侦察、planner DAG + reasoning、计划卡可编辑、确认持久化、模板拆解、replan 工具（`update_pending_task/cancel_pending_task/add_task_to_plan`）、TDD 门禁。**基础已相当完整**，差距在：

- **`subagent_type` 字段保留但被忽略**（`agent_tool.py:316-319`）；`agent` 工具完全不读角色档案，永远构造固定只读子代理 → 没有 Explore/Plan/general-purpose 式角色选择。
- **拆分是静态的**：失败只走 retry/rerun，不会以失败上下文触发 re-plan；嵌套深度默认 1，子代理不能按需再派生。
- 拆分成本/预估不可见：planner reasoning 可看，但无"预计轮次/成本"提示。

### 3.4 思考/动作透明

Claude Code：流式思考、工具卡全文、spinner 状态文案、todo 面板、计划批准、实时任务视图、完成通知、成本统计、运行中插话/中断。

Sage 已有：主聊天三档思考展示（detail/trace/result，三级作用域）、ActiveAgentIndicator 阶段指示、组织良好的任务树状态与审批弹窗。差距：

- 子代理维度完全没有思考与流式正文；工具卡无单次耗时（`ToolCall` 无 duration 字段）。
- 编排 run 结束/取消无系统通知与明确反馈（取消 run 直接清空任务板，无 toast）。
- 三套视图数据源不统一：聊天 `taskBoard`、TaskCenter、LaneBoard 各自为政。

## 4. 优化方案（按里程碑）

### M0：修复既有断点（P0，约 1 个 PR）

1. **接通 runControlStore**：在 Chat 页挂载 `useOrchEventSubscription`（订阅 canonical 事件 NDJSON），修复"事件时间线 + steering ContextInput 不渲染"。
2. **编排插话真正生效**：接通后 `steerActiveOrchTask` 走 `POST /orch/runs/{run_id}/tasks/{task_id}/steer`；若后端拒绝或 run 未绑定，UI 明确提示"已改为排队"而不是静默降级。
3. **取消/中断反馈**：取消 run、停止流补 toast/内联状态；`planApprovalFor` 从组件 state 提升为可恢复状态（修 §6.2 两个持久化小缺口）。

验收：运行一次编排 run，能看到逐任务事件时间线；在任务详情发送插话，子代理下一轮边界收到（后端日志 + `orch_context_messages` 有记录）；取消后 UI 有明确反馈。

### M1：子代理 Transcript 一等化（P1）

1. **后端 transcript 模型**：为子代理记录消息级 transcript（system prompt 摘要、user/goal、assistant 正文与 reasoning、tool_call/tool_result 全文、耗时），新表 `orch_task_messages`（或 `orch_task_transcripts` 分块存储），随 `SubagentRunner.run_loop` 事件落库；保留现有 200 事件预算对实时流，但 transcript 不丢。
2. **API**：`GET /orch/runs/{run_id}/tasks/{task_id}/transcript?after_seq=&page_size=`（分页），以及可选流式订阅复用 events NDJSON。
3. **事件扩展**：`SubagentEventSink` 按展示契约转发思考（遵守 detail/trace/result 档位：detail 全量、trace 摘要采样、result 不转发正文只存 transcript），正文按边界采样而非逐 token。
4. **前端子代理详情页**：TaskDetailView 升级为完整 tab（过程 / Transcript / 思考 / 统计）；思考区复用 `ThinkingDisplay` 与 DisplayContract；工具卡复用现有 renderer 并从 transcript 拉全文；事件日志分页替代 20 条环形缓冲。

验收：任一子代理任务点开可看到完整对话与（按档位的）思考；运行结束后历史 run 也能回看 transcript；现有主聊天思考档位设置对子代理生效。

### M2：独立运行与交互闭环（P1–P2）

1. **`agent` 工具后台模式**：增加 `background: true` → 返回 task handle，完成后以 tool result 通知主代理（对标 Claude Code Agent 工具语义）；同轮多条 `agent` 调用允许并发（移除并行池排除，改为受全局并发信号量约束）。
2. **放开后台派发限制**：同一时刻多个后台 dispatch（队列 + 每 run 上限）。
3. **子代理继续对话**：对已完成子代理暴露"继续"（复用 `followup_of` 历史 + steering 注入，等价 `SendMessage`），前端详情页提供输入框。
4. **子代理线程视图**（P2）：为子代理增加 `parent_session_id` 维度，UI 上可"在侧栏打开子代理线程"；TaskCenter 增加 task 级条目（不依赖 `/orchestration` 页面加载）。
5. **pause/resume**：task 级暂停/恢复 + run 级 resume 端点（补齐 `orch_routes.py` docstring 残留）。

验收：主代理调用 `agent(background=true)` 后可继续其他工具调用；两个子代理并行时各自详情可实时查看；对已完成子代理追问可得新回复；task 暂停后可从暂停点恢复。

### M3：任务拆分增强（P1–P2）

1. **落地 `subagent_type`**：`agent` 工具按角色注册表（DB profiles + `.sage/agents/*.md`）选择子代理角色；schema 提供可用角色列表与 description（LLM 据此选择）；内置 Explore（只读）/Plan（规划）/general-purpose（全工具受策略约束）三类默认角色。
2. **失败驱动重规划**：task 失败/连续重试失败时，conductor 携带失败上下文调用 planner 重排剩余任务（复用 `replan_tool` 的 `add/update/cancel_pending_task`），而不是仅 retry。
3. **拆分预检强化**：计划卡展示每任务预估轮次/成本与拆分理由；复杂任务识别 subtask 拆深（depth>1）作为可选开关。
   - M3.3 已交付：Planner prompt 要求 LLM 为每个任务给出 `estimated_iterations`（整数 1–15，越界/非整型由 `sanitize_llm_plan_tasks` 丢弃）与 `complexity`（low/medium/high）；计划卡逐任务渲染复杂度徽章与「≈N 轮」徽章，卡片标题汇总「预估 ≈N 轮」（只累加提供了预估的任务）；新增设置 `orch.allowDeepDecomposition`（默认关闭），控制 planner 是否允许输出 `parent_task_id` 深层拆分。
   - **成本估算刻意延后**：单任务成本取决于执行期实际选用的模型定价与 token 消耗，计划期不可知，强行估算会给出误导性数字；留待 M4.3「编排通知 + 成本透明」在执行期核算后回填。
4. （P3）**确定性 Workflow 模板**：把文献流水线、设计管线等高频链路固化为 `template:<id>` DAG（复用现有模板机制），失败重入点明确。

验收：同一请求下 `agent` 工具能按角色选择到不同工具集的子代理；构造一个必然失败的任务验证自动 re-plan 生成的替代任务；模板 DAG 在 App 内可端到端跑通并有进度视图。

### M4：统一透明度与通知（P2–P3）

1. **工具事件补 `duration_ms`** 与完整 args/result 引用（全文存 transcript，卡片按需拉取）。
2. **统一运行视图**：SubagentLivePanel、右栏进度、TaskCenter、LaneBoard 收敛到同一 canonical 事件模型的分层视图，消除三套数据源不同步。
3. **通知**：编排 run 结束/失败/等待审批发系统通知（沿用后台任务通知通道），任务中心跳转深链。
4. **成本透明**：每任务 `used_tokens / duration_ms` 前端展示 + run 汇总；子代理级 token 预算（usage_events 增加 task_id 维度）。

验收：工具卡可见单次耗时；仅在 TaskCenter 一处即可看到所有运行中 run 与子任务；run 结束 5 秒内系统通知可点击跳转；run 汇总成本与后端账一致。

## 5. 实施步骤

- [x] M0.1 挂载 `useOrchEventSubscription`，验证事件时间线渲染
- [x] M0.2 steer 真正路由 + 降级提示
- [x] M0.3 取消/中断 toast + 计划待批准状态恢复
- [x] M1.1 `orch_task_messages` 表 + 落库
- [x] M1.2 transcript 分页 API
- [x] M1.3 思考/正文按 DisplayContract 采样转发（实现改为 transcript 落盘 + 前端按档位渲染，见 M1 实施记录）
- [x] M1.4 前端子代理详情页（过程/Transcript/思考/统计）
- [x] M2.1 `agent(background=true)` + 同轮并发
- [x] M2.2 多个后台 dispatch 并存
- [x] M2.3 子代理继续对话
- [x] M2.4 子代理线程 + TaskCenter task 级条目
- [x] M2.5 task pause/resume + run resume 端点
- [x] M3.1 `subagent_type` 角色注册表落地
- [x] M3.2 失败驱动 re-plan
- [x] M3.3 计划卡成本预估 + 拆深开关（预估轮次/复杂度已落地；成本估算延至 M4.3）
- [x] M4.1 工具耗时 + transcript 全文引用（含 M1 transcript 接线缺陷修复，见 M4.1 实施记录）
- [x] M4.2 统一运行视图（canonical run 目录 + 右栏回落，见 §13 M4.2 实施记录）
- [x] M4.3a 编排通知 + 任务深链（run 结束/失败/待审批系统通知，点击跳转任务中心，见 §12）
- [ ] M4.3b 成本透明（run_id 维度 + 每任务/每 run 金额展示）

## 6. 风险与依赖

| 风险 | 缓解 |
|---|---|
| transcript 全量落盘膨胀 SQLite | 分块存储 + 保留策略（N 天/每 run 上限）；思考按档位采样 |
| 放开 `agent` 并发导致工具爆炸/预算超支 | 全局信号量 + run 级 token/墙钟守门（已有）；每 run 后台 agent 数上限 |
| 子代理线程化改动会话模型 | 先做 UI 层"侧栏线程"只读+继续，不改会话语义；`parent_session_id` 可后移 |
| 思考转发增加 LLM 输出 token 成本 | 采样（每 N 秒一次快照）+ 档位控制；result 档完全不转发 |
| 与 §140 插话 v1 不覆盖编排的旧设计冲突 | 以 canonical steer API 为准，更新技术手册 §140 |
| 前端四套视图归一改造成本 | M4 再做，先保证事件模型单一真相源 |

## M2a 实施记录（2026-11-21）

| 改动 | 文件 |
|---|---|
| `agent(background=true)`：立即返回 `{status:"running", handle_id}`；后台任务完成/失败/取消时把结果经主 agent 的新系统通知队列注入下一次迭代边界（不落库、不发 STEER_CONSUMED）；每 stream 上限 4（`MAX_BACKGROUND_AGENTS_PER_STREAM`） | `backend/tools/agent_background.py`（新）、`backend/tools/agent_tool.py` |
| `SageAgent.inject_system_note` + `_pending_system_notes` 队列与迭代边界注入 | `backend/core/legacy/agent.py` |
| 同轮多个 `agent` 调用并发：执行分组新增 `agents` 组（无钩子/免审批/预算足够才成组，单个回落串行；上限 `_AGENT_CONCURRENT_LIMIT`=4），ACTING/OBSERVING 与 tool 消息仍按模型顺序 | `backend/core/legacy/agent.py` |
| 测试 | `test_agent_system_notes.py`（4）、`test_agent_tool_background.py`（5）、`test_agent_parallel_agents.py`（1） |
| M2.2 多个后台 dispatch 并存：`ChatDispatcher` 由单在飞互斥改为最多 `MAX_CONCURRENT_BACKGROUND_DISPATCHES`=4 并存；`wait_background` 一次 collect 全部在飞派发后聚合；`background_snapshot` 汇总所有派发状态；超限错误码 `background_dispatch_limit` | `backend/orchestration/chat_dispatcher.py`、`backend/tools/subagent_tool.py`、`test_chat_dispatcher_background.py` |

验证：新增 10 用例 + agent 工具/steering/执行分组回归 163 用例全绿；ruff 干净；架构棘轮按协议更新（agent.py 4274、agent_tool.py 813 入基线）；silent-exceptions OK。

## M2.3 实施记录（2026-11-22）

| 改动 | 文件 |
|---|---|
| `ChatDispatcher.start_followup(parent_task_id, content)`：仅当 parent 在本进程 dispatcher 内存态且 done；生成唯一 `fuN` 任务 id，经 `followup_of` 后台派发（复用 `_histories[parent]` 子代理历史） | `backend/orchestration/chat_dispatcher.py` |
| `POST /orch/runs/{run_id}/tasks/{task_id}/followup`（404 无活动 run / 409 不可追问或超限 / 400 空或超长内容） | `backend/api/orch_routes.py` |
| IPC `orchestration_followup_task` + manifest；前端 `orchRunControlClient.followupTask` | `electron/commandRoutes/orchestration.ts`、`src/shared/api/orchRunControlClient.ts` |
| TaskDetailView：`activeTaskId`（续聊后切到新任务并继续 transcript 轮询）+ `followupBusy` + 头部 fallback 追问文案；TaskTranscriptPanel 终态任务显示「继续追问」输入框 | `src/widgets/chat/progress/TaskDetailView.tsx`、`TaskTranscriptPanel.tsx` |
| 测试 | `test_orch_followup.py`（9）+ 面板/TaskDetailView 用例 4 |

**已知边界**：续聊依赖 dispatcher 仍在进程内（`_ACTIVE_DISPATCHERS`）；进程重启后返回 404 —— 跨重启续聊需要从 transcript 重建历史，留待后续。

验证：后端 9 新用例全绿 + ruff；前端 typecheck、27 用例、ESLint、构建与 bundle 门禁通过；棘轮 chat_dispatcher 2497。

## M2.4 实施记录（2026-11-22）

| 改动 | 文件 |
|---|---|
| 统一任务模型新增 `subagent` 源：`normalizeSubagentTask`（活跃/失败可见，等待审批映射 awaiting_approval；id `subagent:<sid>:<runId>:<taskId>`）+ `subagent-thread` 打开目标 | `src/features/task-center/unifiedTaskModel.ts` |
| `useUnifiedTasks` 从各会话 `taskBoard`（plan/statuses/live）展开子代理任务条目，跨会话可见 | `src/features/task-center/useUnifiedTasks.ts` |
| TaskCenter 点击子代理条目：写 focus 请求 + 打开右栏进度面板 + 路由到 `/chat?session=`；ProgressSection 消费请求后直接打开该任务详情（过程/对话/steering），实现"打开子代理线程" | `src/entities/orchestration/orchestrationFocusStore.ts`（新）、`useTaskCenterActions.ts`、`ProgressSection.tsx` |
| 卡片图标/文案（zh/en） | `TaskCenterCard.tsx`、`i18n/locales/{zh,en}/taskCenter.ts` |
| 测试 | 模型 3 + 汇总 1 + 动作 1 + 详情定位 1 |

验证：TaskCenter/ProgressSection 相关 14 个套件 / 118 用例全绿；typecheck、ESLint、构建与 bundle 门禁（main 2243/2304KB）、架构棘轮均通过。

## 7. 明确不做（YAGNI）

- 不重写 Planner/ChatDispatcher/EventHub，不做新 DAG 引擎。
- 不把 specialist 复制成新的子代理类型（复用 `SeededAgentRegistry`）。
- 不做跨设备远程子代理（worktree 隔离保持可选）。
- 不引入第二套事件协议；一切以 `orch_events` canonical 事件为准。

## 8. M0 实施记录（2026-11-21）

| 改动 | 文件 |
|---|---|
| Chat 页挂载 canonical 事件订阅（仅 `orch-` 前缀的真实 run；`agent-task-*` 合成板跳过） | `src/pages/Chat.tsx` |
| 编排插话回退语义显式化：区分"无可插话任务"与"插话未送达" | `src/features/send-message/useChat.ts` |
| `steerActiveOrchTask` 支持 store 无快照时按需拉取并回填 | `src/features/send-message/orchSteer.ts` |
| 取消编排运行成功/失败均有 toast（不再静默清空任务板） | `src/pages/chat/useChatMessageActions.ts` |
| 计划待批准状态 localStorage 持久化（重载后批准条恢复） | `src/shared/lib/planApprovalStorage.ts`、`useChat.ts` |
| 历史 run 切换到任务板时补写 `confirmedAt`（计划锁定态恢复） | `src/pages/Chat.tsx` |
| 新增/更新测试 | `orchSteer.test.ts`、`planApprovalStorage.test.ts`、`TaskDetailView.test.tsx`、`Chat.cancel-run.test.tsx` |

验证：`tsc --noEmit` 通过；相关 5 个套件 38 用例通过；编排链路相关 101 个测试文件 / 537 用例全绿；ESLint 无新增错误（2 条为既有 warning）。

## 9. M1 实施记录（2026-11-21）

| 改动 | 文件 |
|---|---|
| 新表 `orch_task_messages`（消息级：goal/reasoning/assistant/tool_call/tool_result/error） | `backend/data/database.py`、`backend/data/orch_transcript_repo.py` |
| `TaskTranscriptRecorder`：与状态事件 sink 并行消费 run_loop 事件，按迭代边界聚合落盘；seq 从 repo `max_seq` 续接；每任务 2000 行封顶；recorder 吞错不影响执行 | `backend/orchestration/transcript.py`、`backend/orchestration/chat_dispatcher.py` |
| `GET /orch/runs/{run_id}/tasks/{task_id}/transcript?after_seq=&limit=`（分页 + has_more） | `backend/api/orch_run_control.py` |
| IPC 路由 `orchestration_get_task_transcript` + manifest 重新生成 | `electron/commandRoutes/orchestration.ts`、`electron/ipc-manifest.json` |
| 前端 `useTaskTranscript`（2s 增量轮询、切任务重置、最多 5 页/轮） | `src/widgets/chat/progress/useTaskTranscript.ts` |
| `TaskTranscriptPanel`：goal/思考/正文/工具调用与结果全文；思考遵守 detail/trace/result 档位 | `src/widgets/chat/progress/TaskTranscriptPanel.tsx` |
| `TaskDetailView` 增加「过程 / 对话」tab，ProgressSection 透传 sessionId | `src/widgets/chat/progress/TaskDetailView.tsx`、`ProgressSection.tsx` |
| 测试 | `test_task_transcript.py`（10）、`test_orch_transcript_api.py`（5）、`TaskTranscriptPanel.test.tsx`（3）、TaskDetailView +1 |

**设计偏差说明（M1.3）**：计划原写"按展示契约转发生成事件"，实现改为**落盘全量 + 前端按档位渲染**——后端无需知道用户档位（档位是前端设置），实时性由 2s 轮询保障，避免在事件白名单/EventHub 中新增高噪声事件类型。后续如需逐字实时，可在此模型上加轻量 `task.transcript.appended` 事件。

验证：后端新测试 15 + 调度器/编排回归 152 全绿；前端 transcript/任务详情/进度 102 用例全绿；`tsc --noEmit`、ESLint、架构棘轮（database 2767 / chat_dispatcher 2432）、silent-exceptions 均通过。

## 10. M3.3 实施记录（2026-11-23）

| 改动 | 文件 |
|---|---|
| Planner 提示词新增 `estimated_iterations`（整数 1–15）与 `complexity`（low/medium/high）契约；`sanitize_llm_plan_tasks` 对越界/非整型值静默丢弃（提示词与校验共用 `MAX_ESTIMATED_ITERATIONS` 常量，避免两侧漂移） | `backend/orchestration/planner.py` |
| 深层拆分开关：默认关闭（提示词要求平铺、禁用 `parent_task_id`），开启后允许 Planner 输出子任务层级；设置读取失败按关闭处理 | `backend/orchestration/planner.py`、`backend/orchestration/orch_settings.py` |
| 计划条目透传预估字段（`plan_override` 与 decompose 两条路径） | `backend/api/legacy_routes.py` |
| 设置链路打通：`allow_deep_decomposition` ↔ `allowDeepDecomposition` 别名 + 编排段白名单（白名单缺项会让编排段任一保存 400 `invalid_settings_shape`，前端静默吞错） | `backend/data/settings_canonicalizer.py` |
| 计划卡：逐任务复杂度徽章（高/中/低，配色走主题 token）+「≈N 轮」徽章；卡片标题汇总「预估 ≈N 轮」（只累加提供了预估的任务，缺省时不渲染任何徽章） | `src/components/PlanCard.tsx`、`src/shared/api/types/chatAndEventTypes.ts` |
| 设置页：编排 tab 新增「允许深层拆分」开关，同步注册表 / 设置搜索 / 审计导出 | `src/pages/settings/OrchestrationTab.tsx`、`src/entities/setting/settingsRegistry.ts`、`src/entities/setting/types.ts`、`src/pages/settings/settingsSearchEntries.ts`、`src/pages/settings/settingsAuditExports.ts` |
| 中英文案 | `src/shared/lib/i18n/locales/zh/settingsUi.ts`、`src/shared/lib/i18n/locales/en/settingsUi.ts` |
| 测试 | `backend/tests/unit/orchestration/test_planner_estimates.py`（9）、`backend/tests/contract/test_settings_schema_parity.py`、`src/widgets/chat/__tests__/PlanCard.test.tsx`（+3）、`src/pages/settings/__tests__/OrchestrationTab.test.tsx`（+4） |

**成本估算刻意延后到 M4.3**：单任务成本取决于执行期实际选用的模型定价与 token 消耗，计划期不可知，强行给出货币数字会误导用户。M3.3 只给「预估轮次 + 复杂度档位」这两个计划期可知的相对量；真实成本待 M4.3 在执行期核算 `usage_events` 后回填。

**已知边界**：另一条「计划文本 → 任务」通道（`backend/api/orch_routes.py` 的 `_PLAN_ITEMS_PROMPT` / `_PLAN_REVISION_PROMPT`）未接入预估字段，该路径产出的计划不显示预估徽章 —— 该文件 797 行、距 800 行架构棘轮上限仅 3 行，本 PR 不动它。

验证：`tsc --noEmit` 通过；ESLint 0 error（123 warning 为既有）；后端契约 + 预估专项 154 用例全绿；前端 PlanCard + OrchestrationTab 61 用例全绿；`ruff check`（改动文件）、`lint-imports`（六边形契约）、架构棘轮、体积门禁（最大 chunk 2246KB / 预算 2304KB）均通过。

## 11. M4.1 实施记录（2026-11-23）

| 改动 | 文件 |
|---|---|
| **修复 M1 接线缺陷**：`chat_dispatcher` 构造了 `TaskTranscriptRecorder` 包装器 `_event_sink`，却把裸 `sink` 传给 `SubagentRunner` → 生产环境 `orch_task_messages` 恒为空；改为 `event_sink=_event_sink`（approval 专用第二处 sink 无需 recorder，保持裸 sink） | `backend/orchestration/chat_dispatcher.py` |
| 子代理工具事件补关联键与耗时：chat 镜像携带 `tool_call_id`/`duration_ms`；canonical `task.step.started` 载荷补 `tool_call_id`（`task.step.completed` 的 `duration_ms` 原本已有） | `backend/orchestration/subagent_events.py` |
| 前端类型：`SubagentLiveEvent` 与宽松 `AgentEvent` 增可选 `tool_call_id`/`duration_ms`（旧后端缺省时按无耗时渲染） | `src/shared/api/types/chatAndEventTypes.ts` |
| Transcript 面板：tool_call 行本身无耗时（后端 OBSERVING 时才知道），按 `tool_call_id` 关联 tool_result 行 `duration_ms` 展示；本地重复 `formatDuration` 统一到共享 `progressFormat` | `src/widgets/chat/progress/TaskTranscriptPanel.tsx` |
| 事件时间线：canonical 事件行内渲染 `· 1.2s` 耗时徽标（`payload.duration_ms` 为数值时） | `src/widgets/chat/progress/EventTimeline.tsx` |
| 任务详情实时事件：`tool_result` 行追加 `· 耗时` | `src/widgets/chat/progress/TaskDetailView.tsx` |
| 架构棘轮：按协议仅上调本 PR 触及条目（chat_dispatcher 2634→2635、chatAndEventTypes 988→995） | `architecture-baseline.json` |
| 测试 | `test_subagent_events.py`（+2：mirror/canonical 字段断言、`TaskTranscriptRecorder` 接线回归）、`TaskTranscriptPanel.test.tsx`（+2 断言）、`EventTimeline.duration.test.tsx`（新，3）、`TaskDetailView.test.tsx`（+1） |

**「transcript 全文引用」的落地方式**：M4 第 1 条要求"完整 args/result 引用（全文存 transcript，卡片按需拉取）"——M1 已建好 `orch_task_messages` 全文落盘与分页 API，本里程碑补上的是其**从未被喂数据**的接线修复；工具卡全文按需拉取沿用 transcript 面板（"完整参数"展开与结果详情），耗时则同时进入实时镜像与 canonical 事件两条通道。

**已知遗留（不在本 PR）**：transcript 的 `_dump_args` 落盘未脱敏（`summarize_tool_args` 的密钥清洗只作用于实时镜像）；全文引用场景下如需脱敏应在 recorder 侧补同款清洗，另行跟进。

验证：后端 subagent_events + transcript + canonical publish + chat_dispatcher 80 用例全绿；前端 transcript/时间线/任务详情 26 用例全绿；`tsc --noEmit`、ESLint（改动文件 0 error）、`prettier --check`、`ruff check`、架构棘轮均通过。

## 12. M4.3a 实施计划（2026-11-23）

M4.3 拆成两个里程碑：**M4.3a 编排通知 + 任务深链**（本节）与 **M4.3b 成本透明**（run_id 维度 + 金额展示）。
拆分理由：M4.3b 依赖 `usage_events` 增加 run_id 维度并回填历史账目，与 M4.2「统一运行视图」共用同一批数据字段；
先让 M4.3a 把 canonical run 终态事件与通知通道落地，M4.3b 才有稳定的 run 级锚点。

### 12.1 背景与目标

M4 第 3 条要求"编排 run 结束/失败/等待审批发系统通知（沿用后台任务通知通道），任务中心跳转深链"，
验收线是"run 结束 5 秒内系统通知可点击跳转"。当前缺口（均为实际代码位置）：

| 缺口 | 证据 |
| --- | --- |
| run 终态无系统通知 | `backend/api/chat_stream_support.py:25` 的 `_finalize_orch_run` 只落 `orch_runs` 表，无任何通知副作用 |
| run 终态无 canonical 事件 | 全仓无 `run.completed` / `run.failed` / `run.cancelled` 的生产发布点（`backend/domain/orch_events.py:239-241` 只定义枚举，`backend/orchestration/snapshot_store.py:108` 只消费） |
| 审批等待无系统通知 | `backend/orchestration/subagent_events.py:218` 只发 `task.waiting_approval` canonical 事件 |
| 轮询节奏 15s > 5s 验收线 | `electron/schedulerNotifications.ts:44` `SCHEDULER_NOTIFICATION_POLL_MS = 15_000` |
| 通知无点击跳转 | `electron/main.ts:2784` 的 `notify` 只 `new Notification(...).show()`，丢弃 payload，无 click handler |
| 通知载荷无编排维度 | `electron/schedulerNotifications.ts:12` 的 `PendingNotificationItem` 只有 `session_id`，无 `run_id` / `task_id` |

### 12.2 技术方案

沿用既有"后端内存队列 → `GET /api/v1/scheduled/notifications/pending` 原子排空 → Electron 主进程轮询 → OS 通知"通道
（`backend/services/background_notifications.py` + `electron/schedulerNotifications.ts`），新增第六路队列 `orch_runs`，
**不引入第二套通知协议**（对齐 §7 "一切以 canonical 事件为准"）。

1. **后端队列（新文件 `backend/services/orch_run_notifications.py`）**
   - `OrchRunNotificationQueue`：线程安全有界 deque（maxlen=100），`push(...)` / `drain()`，与 `BackgroundNotificationQueue` 同构。
   - `get_orch_run_notification_queue()` 模块级单例。
   - `push_run_notification(run_id, status, *, session_id=None, task_id=None, title=None, body=None)`：统一入口，自身吞错（通知失败不影响主流）。
   - `resolve_session_id(run_id)`：按 run_id 查 `orch_runs.session_id`（查不到返回空串）—— 使事件发布方无需自带 session_id。
2. **run 终态通知 + canonical 事件（`backend/api/chat_stream_support.py`）**
   - `_finalize_orch_run` 在 `OrchRunRepository().finalize(...)` 之后：
     - finalize **前**先读一次旧 status，判定 `cancelled`（用户取消端点 `backend/api/orch_routes.py:398` 先写 `cancelled`，随后被 finalize 覆盖）→ 避免取消被误报为失败。
     - 发布 canonical `run.completed` / `run.failed` / `run.cancelled`（`make_event` + EventHub；未装配则降级跳过）。
     - 推 `orch_runs` 队列通知（标题含 run 终态，正文含摘要前 N 字）。
   - 新增段独立 try/except，不影响既有 finalize 闭环。
3. **审批等待通知（`backend/orchestration/subagent_events.py`）**
   - `task.waiting_approval` 发布后调用 `push_run_notification(..., status="awaiting_approval", task_id=...)`。
   - session_id 由 `resolve_session_id(run_id)` 解析 → **无需改 `chat_dispatcher.py`**（该文件已达架构棘轮上限 2635，零余量）。
4. **pending 端点（`backend/api/scheduled_router.py`）**
   - `drain_pending_notifications` 返回体新增 `"orch_runs": get_orch_run_notification_queue().drain()`。
5. **Electron 侧（`electron/schedulerNotifications.ts` + 新文件 `electron/orchNotifications.ts`）**
   - `PendingNotificationsPayload` 新增 `orch_runs`；`PendingNotificationItem` 新增 `run_id` / `task_id`。
   - `collectNotificationItems` 合并第六路队列。
   - `notify` 签名由 `(title, body)` 改为 `(item)` —— 点击跳转需要 run/task 维度；`electron/main.ts` 的回调改为一行委托（净减行数，不动棘轮）。
   - 新文件 `electron/orchNotifications.ts` 承载"创建通知 + click → 聚焦窗口 + 回发 `sage:event:orch-notify-click`"，main.ts 只调一行。
   - 轮询间隔 `SCHEDULER_NOTIFICATION_POLL_MS` 15s → 4s（满足 5s 验收线；轮询为单个 localhost GET，开销可忽略）。
6. **Renderer 深链（`src/App.tsx` + 新文件 `src/features/orch-notify/orchNotify.ts`）**
   - 复用 preload 的通用 `listen` shim（`ipcRenderer.on('sage:event:<event>')`），**无需改 `electron/preload.ts`**（且 preload 尚有 13 行余量）。
   - `OrchNotifyBridge`：收到 `{sessionId, runId, taskId}` → 复用任务中心的深链三元组
     （`useOrchestrationFocusStore.focusThread` + `useRightPanelStore.setTab('progress')` / `setOpen(true)` + `navigate('/chat?session=...')`，
     见 `src/features/task-center/useTaskCenterActions.ts:104-112`）。

### 12.3 实施步骤

- [x] M4.3a-1 后端队列 + `push_run_notification` + `resolve_session_id`
- [x] M4.3a-2 `_finalize_orch_run` 发 canonical run 终态事件 + 推通知
- [x] M4.3a-3 `task.waiting_approval` 推审批通知
- [x] M4.3a-4 pending 端点新增 `orch_runs` 队列
- [x] M4.3a-5 Electron：载荷扩展 + `notify(item)` + click 回发 + 4s 轮询
- [x] M4.3a-6 Renderer：`OrchNotifyBridge` 深链跳转
- [x] M4.3a-7 测试（后端队列/终态/审批 + 前端 collect/notify/bridge）
- [x] M4.3a-8 门禁（ruff / lint-imports / 架构棘轮 / 体积 / tsc / vitest / eslint）

### 12.4 风险与依赖

| 风险 | 缓解 |
| --- | --- |
| 轮询 15s → 4s 增加后端请求量 | 单次 localhost GET，队列为空即返回空数组；沿用既有"上一轮未完成跳过本轮"防堆积 |
| 通知与终态事件双通道各发一次导致重复通知 | 通知只由 `push_run_notification` 单点产生；canonical 事件本身不直接产通知 |
| 取消 run 被误报为"失败" | finalize 前先读旧 status，`cancelled` 优先判定 |
| 用户关闭窗口时点击通知无处可跳 | 点击前先 restore/show/focus 窗口（复用 `sage:session:notify` 既有做法） |
| `orch_routes.py` 已 797 行（上限 800） | 本里程碑不改该文件；取消通知依赖旧状态读取而非新增端点钩子 |
| `chat_dispatcher.py` 已达棘轮上限 2635 | 审批通知改在 `subagent_events.py`（415 行）落地，不动 dispatcher |
| 摘要过长撑爆通知 | 摘要截断至 120 字；标题 120 / 正文 200 字上限沿用 Electron 侧既有裁剪 |

### 12.5 与后续里程碑的关系

- **M4.3b（成本透明）**：run 终态通知已带 run_id，可作为成本汇总展示的入口；金额字段仍待 `usage_events` 增加 run_id 维度并回填。
- **M4.2（统一运行视图）**：本里程碑补上的 canonical `run.completed/failed/cancelled` 是 M4.2"三套视图收敛到同一事件模型"的缺失拼图；
  M4.2 需同时修 `task.paused/resumed` 未映射（`runControlStore.ts:182`、`laneBoardStore.ts:58`）与 `task.skipped` 被白名单丢弃（`orchEventStream.ts:17`）两处映射缺陷。

## 12.6 M4.3a 实施记录（2026-11-23）

| 改动 | 文件 |
| --- | --- |
| 第六路通知队列：`OrchRunNotificationQueue`（有界 deque，maxlen=100）+ `push_run_notification` 统一入口（自身吞错）+ `resolve_session_id` 按 run_id 反查 `orch_runs.session_id` + `summarize_for_notification`（压行 + 120 字截断） | `backend/services/orch_run_notifications.py`（新） |
| `_finalize_orch_run` 闭环后补两件事：发布 canonical `run.completed/failed/cancelled`（EventHub 未装配降级跳过）+ 推 `orch_runs` 队列通知；finalize **前**快照旧 status，**DB 终态为准**（`finalize` 只改 `status='running'` 行，已被取消端点写成 `cancelled` 的行不被迟到的 producer finally 覆盖，通知也报 `cancelled` 而非失败） | `backend/api/chat_stream_support.py` |
| `task.waiting_approval` canonical 事件后推 `awaiting_approval` 通知（session_id 经 `resolve_session_id` 解析，不改 `chat_dispatcher.py`） | `backend/orchestration/subagent_events.py` |
| pending 端点返回体新增 `orch_runs`（第六键，排空语义不变） | `backend/api/scheduled_router.py` |
| 载荷扩展 `run_id` / `task_id` + `notify(item)` 签名 + 六路队列合并 + 轮询 15s → 4s（满足 5s 验收线） | `electron/schedulerNotifications.ts` |
| 通知创建 + 点击聚焦窗口 + 回发 `sage:event:orch-notify-click`（标题 120 / 正文 200 截断；无 `run_id` 的通知仅展示、不挂点击）；main.ts 只留一行委托（棘轮零增长） | `electron/orchNotifications.ts`（新）、`electron/main.ts` |
| `OrchNotifyBridge`：点击 → `focusThread` + 右栏 progress 面板 + `navigate('/chat?session=')`（复用 preload 通用 `sage:event:*` shim，未改 preload） | `src/features/orch-notify/orchNotify.ts`（新）、`src/App.tsx` |
| 测试 | 后端 `test_orch_run_notifications.py`（16）+ `test_orch_run_notifications_route.py`（2）；前端 `orchNotifications.test.ts`（6）、`schedulerNotifications.test.ts` 扩至 9、`orchNotify.test.ts`（4） |

**设计要点**：通知与 canonical 事件是同一收尾点的两条观测通道 —— 通知只由 `push_run_notification` 单点产生（不会与 canonical 事件重复通知）；`effective_status` 以 `orch_runs` 行的最终状态为准，取消端点对已终态 run 返回 409，所以"finalize 前已是 cancelled"即用户主动取消。

**已知边界**：通知队列为进程内内存队列，App 未运行时产生的编排终态不会补发（与既有五路通知通道语义一致）。

验证：后端 6 文件 53 用例全绿（含新增 18 例）；`ruff check`、py38 兼容、silent-exceptions、`lint-imports`、架构棘轮、`tsc --noEmit`、ESLint、vitest（受影响 3 文件 19 用例）全部通过。
## 13. M4.2 统一运行视图（2026-11-23）

### 13.1 根因定位（第一手证据）

「三套数据源不同步」不是视图没接上，而是 **canonical 数据没有跨会话查询入口**：

| 层 | 事实 |
|---|---|
| 真相层 | `orch_runs` / `orch_tasks` 已由 `ChatDispatcher.init_orch_run` / `_persist_task_state` 逐次落库，字段齐全（状态 / 起止 / 用量 / 层级 / 错误 / 父子关系） |
| 投影层 | `OrchRunRepository.list()`（跨会话全量列表）**存在但零调用者**；`GET /orch/runs` 强制要求 `session_id`；`GET /orch/runs/{id}/snapshot` 只读进程内 `SnapshotStore`（重启后为空）且一次只能看一个 run；`OrchTaskRepository` 无批量查询 |
| 视图层 | TaskCenter 的子代理条目来自**内存** `useChatStreamStore.taskBoard`（只覆盖前端加载过的会话）；右栏进度同源；LaneBoard 属 lane 域，独立数据源 |

结果：**会话未被前端加载过 ⇒ 该 run 及其子任务在 TaskCenter 里根本不存在**；应用重启后右栏进度同样空白。这正是验收条目「仅在 TaskCenter 一处即可看到所有运行中 run 与子任务」当前无法满足的原因。

### 13.2 分层视图设计

```
Layer 0 真相   orch_runs + orch_tasks + orch_events（SQLite，已落库）
Layer 1 投影   GET /api/v1/orch/runs/directory?scope=all → 一次拿到「run + 其子任务」
               （scope: active/failed/finished/all；limit 1..200，默认 50）
               前端 runDirectoryStore（3s 轮询）→ 唯一投影层
Layer 2 视图   TaskCenter（canonical 条目 + 内存 live 叠加）
               右栏进度（内存优先，缺失时回落 canonical）
               SubagentLivePanel / LaneBoard（内存/领域数据，作为实时叠加层）
```

收敛原则：**canonical 定状态，内存定实时细节**。子任务 id 统一为 `subagent:<session_id>:<run_id>:<task_id>`，canonical 与内存条目同 id ⇒ 天然去重，内存只补 `liveStep` / `waitingApproval`（canonical 不存这两项）。

### 13.3 实施步骤

- [x] 步骤 1：`OrchRunRepository.list_active()`（跨会话活动 run，新→旧，limit）
- [x] 步骤 2：`OrchTaskRepository.list_by_runs()`（批量取子任务）
- [x] 步骤 3：`GET /orch/runs/directory` 端点（`orch_run_control` 路由，`scope` 四档 + limit 1..200；挂在 legacy `/orch/runs/{run_id}` 之前避免路径吞并）
- [x] 步骤 4：Electron IPC 通道 `orchestration_list_run_directory` + ipc-manifest 映射
- [x] 步骤 5：前端类型 + 客户端（扩展 `src/shared/api/orchRunClient.ts`，未另建目录客户端文件）
- [x] 步骤 6：`runDirectoryStore`（entities 层，zustand，3s 轮询刷新）
- [x] 步骤 7：统一模型新增 `'run'` 来源 + `normalizeCanonicalRun` / `normalizeCanonicalTask`
- [x] 步骤 8：`useUnifiedTasks` 合并 canonical 与内存条目（同 id 去重，canonical 定状态）
- [x] 步骤 9：`TaskCenterRuntimeHost` 挂 3s 轮询（与 shell 同 cadence）
- [x] 步骤 10：任务中心交互（run 级取消 / 跳转会话）
- [x] 步骤 11：中英文案 `taskCenter.source.run`
- [x] 步骤 12：右栏进度 canonical 回落（内存 taskBoard 缺失时用 canonical 合成）
- [x] 步骤 13：测试（后端 pytest + 前端 vitest）与架构棘轮核对

### 13.4 实施记录（2026-11-23）

| 改动 | 文件 |
|---|---|
| 跨会话目录查询 `list_by_statuses()`（状态过滤 + 新→旧 + limit） | `backend/data/orch_run_repo.py` |
| 批量取子任务 `list_by_runs()`（IN 查询，空列表短路） | `backend/data/orch_task_repo.py` |
| 目录端点 `GET /orch/runs/directory`（scope 四档 + limit 1..200；plan_json 解析、子任务 15 字段投影） | `backend/api/orch_run_control.py` |
| Electron IPC `orchestration_list_run_directory` + manifest 再生成（428 命令） | `electron/commandRoutes/orchestration.ts`、`electron/ipc-manifest.json` |
| 前端类型与客户端：`DirectoryRun`/`DirectoryTask`、`listRunDirectory(scope, limit)`（防御性归一） | `src/shared/api/orchRunClient.ts` |
| `runDirectoryStore`（zustand：3s 轮询、loading 并发去重、失败保留上一轮数据）+ `findActiveRunForSession` | `src/entities/orchestration/runDirectoryStore.ts` |
| 统一模型：`'run'` 来源、`CANONICAL_RUN_STATUS_MAP`、`normalizeCanonicalTask`（与内存行同 id）、`canonicalRunProgress`、`normalizeCanonicalRun`（run 级兜底行仅在无可见子任务时出）、`mergeSubagentEntries`（canonical 定状态；内存补审批 / liveStep / 真实标题） | `src/features/task-center/unifiedTaskModel.ts` |
| `useUnifiedTasks`：canonical 条目先入 Map，内存行同 id 合并，未被合并的 canonical 条目（含 run 级行）追加 | `src/features/task-center/useUnifiedTasks.ts` |
| `TaskCenterRuntimeHost`：3s 目录轮询（与 shell cadence 一致，跨窗口会话也能出条目） | `src/features/task-center/TaskCenterRuntimeHost.tsx` |
| 任务中心交互：run 级取消走 `orchestration_cancel_run_control` 并立即刷新；`run-progress` 打开右栏进度并跳会话 | `src/features/task-center/useTaskCenterActions.ts` |
| 卡片来源图标 + 中英文案 `taskCenter.source.run` | `TaskCenterCard.tsx`、locales zh/en `taskCenter.ts` |
| 右栏 canonical 回落：`buildCanonicalTaskBoard` 把目录投影为 `TaskBoardState`（plan 空时用任务行兜底；计划中未落库任务按 queued 合成；paused 计入 queued 保持旧事件口径）；`Chat.tsx` 以 `effectiveTaskBoard = taskBoard ?? canonicalTaskBoard` 供事件订阅 / 粘性滚动 / 计划卡 / 右栏 | `src/features/task-center/canonicalTaskBoard.ts`、`src/pages/Chat.tsx` |
| 架构棘轮：按协议仅上调本 PR 触及条目（`src/pages/Chat.tsx` 889→908） | `architecture-baseline.json` |
| 测试 | 后端 `test_run_directory.py`（新，14）；前端 `unifiedTaskModel.test.ts`（+9）、`canonicalTaskBoard.test.ts`（新，4）、`runDirectoryStore.test.ts`（新，4） |

**收敛形态落地**：run 级兜底行只覆盖「已确认未派发 / 全部子任务终态后仍在收尾 / 子任务全部终态后 run 失败」三种没有可见子任务行的窗口，避免同一 run 在任务中心出现父子两层重复行；子任务行 canonical 与内存天然同 id 去重，`awaiting_approval` 是唯一由内存侧压过 canonical 的状态（DB 不存待审批）。合成右栏任务板不写回 `chatStreamStore` —— 内存板一旦出现即优先，canonical 事件订阅用合成板 runId 继续补齐实时细节。

**已知遗留**：LaneBoard 仍是 lane 域独立数据源（lane 与 orch run 是两套调度单元，本里程碑只保证其在 TaskCenter 中与 run 条目并列可见）；目录轮询为全量 `limit=50`，run 数量大时无增量游标；右栏合成板不含 `liveStep`（canonical 不存），进程重启后事件时间线为空但任务状态正确；§12.5 提到的 `task.paused/resumed` 映射与 `task.skipped` 白名单两处事件映射缺陷未在本里程碑修复（不影响目录聚合的状态正确性）；M4.3b 成本透明未做。

验证：后端目录端点专项 14 用例 + 邻居 140 用例全绿，`ruff check` 通过；前端 task-center 套件（含 i18n 字节对与 IPC 契约）130 用例全绿；`tsc --noEmit`、ESLint（改动文件 0 error）、`prettier --check`、架构棘轮、`ipc:manifest:check`（428 命令）均通过。
