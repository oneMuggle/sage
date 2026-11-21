# 智能体编排协作对标 Claude Code 优化方案

> 状态：M0 已合并 main（`96cfe619c`），M1 已合并 main（`2f5055f0d`）；M2a/M2.2 已实施（同轮并发 + 后台模式 + 多后台派发），M2.3–M2.5 待实施
> 分支：M2 `feat/orch-agent-background`
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
- [ ] M2.2 多个后台 dispatch 并存
- [ ] M2.3 子代理继续对话
- [ ] M2.4 子代理线程 + TaskCenter task 级条目
- [ ] M2.5 task pause/resume + run resume 端点
- [ ] M3.1 `subagent_type` 角色注册表落地
- [ ] M3.2 失败驱动 re-plan
- [ ] M3.3 计划卡成本预估 + 拆深开关
- [ ] M4.1 工具耗时 + transcript 全文引用
- [ ] M4.2 统一运行视图
- [ ] M4.3 编排通知 + 成本透明

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

验证：新增 10 用例 + agent 工具/steering/执行分组回归 163 用例全绿；ruff 干净；架构棘轮按协议更新（agent.py 4274、agent_tool.py 813 入基线）；silent-exceptions OK。

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
