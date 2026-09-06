# 2026-09-06 子代理实时可视 & 编排自动执行方案

> 状态:待评审。前置:`2026-09-06_subagent-realtime-monitoring-and-steering.md`(Phase 0-3 已交付:编排 RunEvent 流、快照、Drawer、steer)。
> 用户反馈两个痛点:①派遣 subagent 后只能被动等待,看不到实时执行情况;②编排各环节都要确认,摩擦大。

## 1. 根因诊断(证据)

| # | 根因 | 证据 |
|---|------|------|
| R1 | **子代理内部事件被丢弃**。`SubagentRunner` 消费子 `run_loop` 时只收集 `done/failed`,其余(acting/observing/reasoning)全部丢弃;`task.step.*` 事件协议已定义但全库无生产者;`snapshot_store` 已会消费 `task.step.*` 却收不到 | `backend/orchestration/subagent_runner.py:154-162`;`backend/domain/orch_events.py:259-268`;`backend/orchestration/snapshot_store.py:88,162` |
| R2 | **子代理权限审批黑洞**。子 run_loop 触发 `PERMISSION_REQUEST` 后挂起等全局 ApprovalGate,300s 超时 fail-closed;该事件同样被 R1 丢弃,用户看不见。子代理每遇到一个风险工具调用 = 静默挂 5 分钟然后被拒 | `backend/core/legacy/agent.py:828-863`;`backend/services/permission_gate.py:73(DEFAULT_APPROVAL_TIMEOUT_S)`;`subagent_runner.py:154-162` |
| R3 | **审批无分级信任**。主 agent 每个需审批工具都弹 ApprovalDialog,无 run 级/全局自动批准;`task.waiting_approval`/`task.approval_*` 仅有类型定义,无生产者无 UI;全库无 auto_approve/auto_continue 实现 | `backend/domain/orch_events.py:63-64,279-280`;`src/entities/orchestration/runControlStore.ts:181`(仅 reducer);计划卡为软门,派发后无确认点(`orch_routes.py:167-168` 计划锁定) |
| R4 | `agent` 工具通路更差:独立线程阻塞执行、零事件、超时后线程遗弃不可杀 | `backend/tools/agent_tool.py:271,388-414`(parity-round2 L12) |

聊天流侧现状:任务板只有状态迁移事件 `task_status`(queued/running/done/failed/cancelled + 500 字 output_preview),见 `backend/orchestration/chat_dispatcher.py:671-690`。

## 2. 方案总览

三步走:**P0 打通事件流(看得见)→ P1 审批转发 + 分级信任(不卡死、少确认)→ P2 呈现对齐 ZCode + 通路治理**。

核心思路:子代理事件"投影转发"到既有双通道(聊天 NDJSON 流做内联镜像、canonical RunEvent 流做事实源),审批复用全局 gate 只补前端可见性,自动批准复用 permission_rules/policy_engine 风险分级——不新增第三条通道,不做大重构。

## 3. P0 子代理内部事件转发(核心,~1-2 人日)

### 后端

1. `SubagentRunner.__call__` 增加可选 `event_sink`(sync callable,内部 `loop.call_soon_threadsafe` 不需要——子 run_loop 就在本循环协程上);消费循环(`subagent_runner.py:155`)内投影转发:
   - `acting`(tool_call 发起)→ 转发,附 iteration;
   - `observing`(tool_result)→ 转发,结果截 200-500 字预览;
   - `failed` → 已有处理,补发一条;
   - `reasoning`/`content` → **不转发**(token 与 UI 双降噪)。
2. `ChatDispatcher` 组装 SubagentRunner 处(`chat_dispatcher.py:543-621`)注入 sink,双写:
   - 聊天流 entry_queue:新 state `subagent_event`,载荷 `{run_id, task_id, agent_id, goal, iteration, tool_call?, tool_result_preview?, ts}`;
   - canonical EventHub:`task.step.started/completed`(entity.task_id,args 经 `summarize_tool_args` 脱敏,`visibility="redacted"`,附 duration_ms/预览)。snapshot_store 已消费 `task.step.*`,**Drawer/EventTimeline 零前端改动即点亮**。
3. 限流:每子任务事件上限(建议 200 条,超出降级为仅计数);单行 < 64KB(前端 orchEventStream 已有 256KB 行上限保护)。
4. `task_status` 载荷增加 `parent_tool_call_id`(dispatch 处已持有 conductor 的 tc.id)——前端内联渲染的关联键。

### 前端

1. `src/shared/api/types.ts` AgentState 联合增加 `subagent_event`;`chatStreamStore.taskBoard` 每任务新增 `liveStep` + 最近 N=20 事件环形缓冲。
2. `TaskTreeSection` 行内实时化:状态图标旁显示当前步骤("🔧 read_file src/x.py")+ spinner + 最近一步预览;点击行内联展开最近事件,不必开 Drawer。

## 4. P1 审批转发 + 编排分级信任(~1-2 人日)

### 4.1 审批转发(修黑洞,优先)

- sink 中拦截 `permission_request` 事件 → 转发为聊天流 `permission_request` 事件(载荷附 task_id/agent_id/goal 徽标)+ canonical `task.approval_requested`;resolved 后回填 `task.approval_resolved`。
- **关键洞察:子 agent 的审批请求本就注册在全局 ApprovalGate 单例,`POST /permissions/{id}/answer` 端点零改动即可应答——唯一缺口是前端看不见。**
- `ApprovalDialog` 增加子代理上下文条(哪个任务、什么目标、第几轮)。

### 4.2 分级信任(autopilot)

- **run 级**:PlanCard 增加"自动批准非危险工具"开关,随 run 持久化(orch_runs.plan_json 或 app_settings.orch);TaskTree 头部可随时切换。
- **实现**:按模式给子 agent 注入包装 Enforcer(AutoApprove):命中用户已 remember 规则或低风险白名单 → 直接放行;高风险 → 仍走 4.1 转发审批。复用 `policy_engine.py:319-342` 风险分级与 permission_rules,不发明第二套分级。
- **全局**:设置 GeneralTab 编排区增加默认模式(每次询问 / 自动批准非危险工具)。危险工具(bash rm、git push --force 等由 policy_engine 判定)**永远不自动批**。
- 附:审批等待时触发 OS 通知(parity-round2 U6 通知基础设施已交付,补触发点)。

## 5. P2 呈现对齐 ZCode + 通路治理(~2-3 人日)

1. **聊天内联 live block**:`Message.tsx` 中 subagent 派遣工具卡(现 humanize 为 "Delegate <goal>",`humanize.ts:184-193`)升级为实时分组——头部 goal+状态+spinner,body 以 `parent_tool_call_id` 关联 `subagent_event` 逐行追加(每步一行:工具名+参数摘要+结果预览),done 后折叠为摘要。ZCode Task 工具的视觉对等物。
2. **`agent` 工具通路治理**:推荐收敛到 `dispatch_subagents` 单任务派遣,`agent` 保留为兼容别名;顺带解决 L12(300s 遗弃线程)。备选:跨线程接同一 sink(`loop.call_soon_threadsafe` 投递 entry_queue)。
3. **conductor 自感知**:`task.step.*` 进入 RunSnapshot 后,`observe_subagents`(`observe_tool.py:59-81`)天然看到子代理实时步骤;可选在波间把 task_progress 注入 conductor。
4. 可选:laneBoardStore 从 REST 拉取改事件订阅(`applyEvent` 已具备,`laneBoardStore.ts:140-180`,缺事件源接线)。

## 6. 关键设计决策

| 决策 | 理由 |
|------|------|
| 双通道分工:聊天流=轻量镜像(内联渲染),canonical 流=事实源(Drawer/快照) | 与 monitoring 方案 Phase 0-3 架构一致;不合并通道(PARITY.md WebSocket 是另一独立议题) |
| 投影而非全量转发:只转发 acting/observing/failed,预览截断 | 子代理 reasoning/content 是 token 与 UI 双重噪声;90% 的"看见"价值在工具调用序列 |
| 审批复用全局 gate,零新增解析机制 | 后端唯一缺口是前端可见性;避免造第二套审批状态机 |
| 默认行为不变:autopilot 默认关;事件转发默认开(纯只读观测) | 安全底线;观测无副作用可直接上线 |

## 7. 测试

- backend:SubagentRunner sink 投影单测(fake run_loop);dispatcher 注入与限流;AutoApprove enforcer 矩阵(白名单/remember/危险工具/关闭);审批转发 e2e(answer 唤醒子 agent,验证不再 300s 超时)。
- frontend:chatStreamStore reducer(subagent_event/liveStep/环形缓冲);TaskTreeSection 实时行;Message live block;沿用 `Orchestration.test.tsx`/`GeneralTab.orch.test.tsx` 模式。
- e2e:stub 工程 smoke 增加一条"派遣 → 行内实时步骤 → 审批弹窗 → 放行 → 完成"。

## 8. 风险与对策

- 事件洪流 → 每任务上限 + 预览截断;NDJSON 行限已有。
- 参数泄露 → 复用 `summarize_tool_args` 脱敏 + `visibility="redacted"`。
- 双通道顺序/一致性 → 镜像事件带 task_id+ts,前端按事件类型幂等合并;Drawer 以 canonical seq 为准。
- autopilot 误批 → 危险工具硬拦截;默认关;运行中可随时切回。
