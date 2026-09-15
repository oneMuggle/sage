# 编码代理对标差距分析·第八轮：执行前确认与失败后恢复（2026-09-10）

- **状态**：批次 A 已交付（分支 `feat/parity-r8-batch-a`，基线 origin/main 9dbbf2ca = #576）；批次 B 见 §6/§7
- **上游文档**：round7（运行时韧性，批次 A/B/C 已交付 main #571/#574/#576、win7 #592）——本轮盘点的两个主体正是 round7 §1.2/§1.3 登记 P3 暂缓的两项：单 agent 计划模式、编排失败恢复入口
- **对标对象**：Claude Code（plan mode：只读调研 → 计划 → 用户批准 → 执行；rerun/续跑）、Cursor（失败 agent 重跑）、Devin（planner→executor 分相）
- **编号约定**：本轮用 **PM 系**（Plan Mode）与 **RV 系**（Recovery）
- **方法**：在最新 main（#576 后）全量复核 round7 勘察结论 + 补充勘察权限模式/确认流/结果持久化三处，全部附 file:line

## 0. 结论速览

第七轮把"跑得动、跑不崩"收口之后，剩余差距集中在**执行生命周期两端**：开跑前的"先规划后批准"契约，与失败后的"只重跑该重跑的"恢复入口。

1. **单 agent 无计划模式契约**：`PermissionMode.READ_ONLY`（`tools/permissions.py:33-41`）作为**全局持久化设置**存在（settings key `permission_mode`，默认 workspace_write），READ_ONLY 下写/执行/出网类工具被拦截——但它是全局开关而非"这一次先规划"；**没有任何"计划 → 用户批准 → 执行"的闭环**（hex 域的 `PermissionMode.PLAN` 注释自述"额外引导 agent 走 propose_plan 审批流"（`domain/permission.py:31-33`），但 legacy 生产路径无 propose_plan、无确认 UI、无入口）；前端零命中 plan_mode。Claude Code 的 plan mode 是"每任务可进出的工作模式"，Sage 缺的是**契约与入口**而非门禁原语。
2. **编排失败后无恢复入口**：`plan_override` 后端全链在（`legacy_routes.py:208-210`（ChatRequest 字段）→ `:1967-1990`（非空跳过 LLM 拆解、force_multi）→ dispatcher P2-7 计划权威派发）、前端透传管道在（`chatApi.ts:161-162` → `useChat.ts:166,283`）——但**零调用方**设置 planOverride，`orch_routes.py` 无 /resume、无 rerun 端点（仅 GET runs、GET runs/{id}、plan、approval-mode、cancel、tasks/{id}/cancel、confirm），run 失败后用户只能整条消息重发（全量重来，已完成子任务成果丢弃）。且 `orch_tasks.output_preview`（`orch_task_repo.py:27`）已持久化 done 任务的结果预览——**恢复所需的数据一直在库里，缺的只是重建入口与"已完成结果回放"机制**。
3. **配套断点**：conductor 无"部分失败"的差异化提示；dispatcher 对计划外重复 task_id 无幂等（rerun 场景天然全新 run_id，无此风险——记录即可）。

## 1. 差距矩阵

| # | 现状 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RV1 | **run 失败后无"只重跑失败任务"**：唯一出路是重发消息全量重来；plan_override 通道在但零调用方 | `orch_routes.py`（无 rerun/resume 端点）；`orchRunClient.ts`（无 resume）；`chatApi.ts:161-162`（透传无来源） | Claude Code rerun、Cursor 重跑 | **P1** |
| RV2 | **done 成果不可复用**：output_preview 已落库但无消费者把它注入后续 run | `orch_task_repo.py:27,61-84`（output_preview upsert/read）；全库无回放方 | Devin 续跑保留进度 | **P1** |
| PM1 | **单 agent 无计划模式**：READ_ONLY 是全局设置；无 /plan 入口、无计划指令、无批准闭环 | `tools/permissions.py:33-41,360-364`（全局模式）；前端 plan_mode 零命中 | Claude Code plan mode | **P1** |
| PM2 | **批准后衔接缺失**：即使只读产出了计划，也没有"批准 → 按计划执行"的代码通路 | hex `domain/permission.py:31-33` 注释提及 propose_plan 审批流；legacy 无对应物 | Claude Code plan approval | P1 |
| — | 已具备：编排确认门（confirmRun + PlanCard needConfirm，multi 路径）；只读门禁原语（legacy READ_ONLY / hex PLAN）；计划权威派发（P2-7，plan_json 单源）；orch_runs/plan + detail API | `legacy_routes.py:2454-2495`（multi 确认）、`PlanCard.tsx`、`chat_dispatcher.py:355-420` | — | 不再建设 |

## 2. 批次规划

| 批次 | 主题 | 内容 | 状态 |
| --- | --- | --- | --- |
| **A（本批）** | 编排失败恢复 | RV1 dispatcher `preset_output` 原生短路（done 任务结果回放，不派子代理）+ RV2 `POST /orch/runs/{run_id}/rerun-failed` 端点 + RV3 前端"重跑失败任务"入口（TaskTree → 端点 → planOverride 重发）+ round7 文档 §9 交付号回填 | ✅ 已交付（见 §5） |
| **B** | 单 agent 计划模式 | PM1 `plan_mode` 请求字段 + per-run 只读门（复用 legacy 权限执行器，override READ_ONLY）+ 计划指令 system 块 + PM2 前端 `/plan` 入口与批准条（批准 → 自动衔接执行） | 见 §6 |

## 3. 批次 A 详细设计

### 3.1 RV1 dispatcher 原生 preset 短路（工作量 S）

计划条目（orch_runs.plan_json）增可选 `preset_output` 字段。`ChatDispatcher._run_one_inner` 在 acquire 信号量、过取消守卫、发 running 事件之后短路：计划项带 `preset_output` → 直接 `state.status="done"`、`state.output=preset_output`、`_histories[task_id]=[user(goal), assistant(preset_output)]`（供 followup 回放与下游聚合）、发终态事件——**不建 lane、不派子代理、零 LLM 调用**。既有 `_emit_task_status` → `_persist_task_state` 把 output_preview 落库，任务板/聚合文本自然呈现"已完成（回放）"。下游依赖照常以 done 放行（级联闭包不感知差异）。

### 3.2 RV2 rerun-failed 端点（工作量 S）

`POST /orch/runs/{run_id}/rerun-failed`（orch_routes）：读 run detail（plan_json + tasks）；逐任务构造 plan_override 条目——`done` → 原条目 + `preset_output: output_preview`（缺失时 `"[已完成，结果未留存预览]"`）；`failed/cancelled/blocked` → 原条目重建（goal/agent_id/depends_on 保持，strip 旧 preset）；响应 `{session_id, goal, plan_override}`。goal = `重跑失败任务（已完成子任务结果保留）：{原 goal}`。复用 `GET /runs/{id}` 的 `_run_detail` 组装；run 非终态 → 409。

### 3.3 RV3 前端入口（工作量 S）

`electron/commands.ts` 路由 `orchestration_rerun_failed`；`orchRunClient.rerunFailed(runId)`；`TaskTreeSection` 在 run 终态且存在 failed 任务时显示行内"重跑失败任务"按钮 → 回调 `onRerunFailed` → `Chat.tsx` 调端点拿 plan_override → `sendMessage(goal, sessionId, undefined, "multi", { planOverride })`（既有透传管道，Wave 3 A10）。

## 4. 批次 B 详细设计（预排期）

- **PM1**：`ChatRequest.plan_mode: bool = False`；producer plan_mode 时 ① system 追加计划指令块（只读调研 → 输出分步计划与验收标准，明确"未获批准前不执行"）；② 该 agent 实例权限执行器 override 为 READ_ONLY（`_build_permission_enforcer` 读 settings 处加实例级 override 属性，全局设置不动）。
- **PM2**：前端 `/plan <目标>` slash 命令（mode='plan'，立即发送）→ useChat/chatApi 透传 plan_mode → 流结束后会话内出现"计划批准条"（按计划执行 / 忽略）；批准 → 自动 `sendMessage("请严格按上述计划执行，不要重新规划。")`。

## 5. 批次 A 实施与验证记录（2026-09-10）

- **RV1**：`ChatDispatcher._run_one_inner` 在 acquire 信号量 + 取消守卫 + running 事件之后插入 preset 短路——`_plan_by_id[task_id].preset_output` 非空 → `state.status="done"` + `output=preset` + `_histories[task_id]=[user(goal), assistant(preset)]` + 终态事件，不建 lane、零 LLM 调用。持久化走既有 `_emit_task_status → _persist_task_state`（output_preview 自然落库）；下游依赖照常以 done 放行。
- **RV2**：`POST /orch/runs/{run_id}/rerun-failed`（orch_routes，`@with_db_lock`）——`_run_detail` 组装 plan+tasks；done → 原条目 + `preset_output`（output_preview，缺失时"[已完成，结果未留存预览]"）；failed/cancelled/blocked → 原条目重建（goal/agent_id/depends_on 保持）；响应 `{session_id, goal, plan_override}`。404 未知 run / 409 running 或无失败任务或无计划。
- **RV3**：`electron/commands.ts` 路由 `orchestration_rerun_failed`；`orchRunClient.rerunFailed`；TaskTreeSection 终态且有失败时行内"重跑失败任务"按钮（`onRerunFailed` prop）→ ProgressSection/RightPanel 透传 → Chat.tsx `handleRerunFailed`：调端点拿 planOverride → `sendMessage(goal, sessionId, undefined, 'force_multi', { planOverride })`（复用 Wave 3 A10 透传管道）。
- **RV4**：round7 文档 §9 交付号回填（main #571/#574/#576；win7 #592）。
- 测试：新增 `test_orch_rerun_failed.py` 6 例（preset 短路不派子代理 + histories 回放对 + 上游 preset 放行下游 + 无 marker 行为不变 + 端点 override 构建/无失败 409/未知 404）；前端 `TaskTreeSection.rerun.test.tsx` 3 例（终态失败显示并回调 / 进行中隐藏 / 无失败隐藏）；dispatcher 回归（skip/timeout）与编排相关面全绿；ruff / tsc / eslint 全过。

## 6. 批次 B 实施与验证记录（2026-09-10）

- **PM1 后端**：`ChatRequest.plan_mode: bool = False`；producer 三处接线——① `system_content` 追加 `_PLAN_MODE_DIRECTIVE`（只读调研 + 结构化计划模板"目标/分步计划/验收标准/风险"）；② agent 实例注入只读门：`_build_permission_enforcer()` 产物经新增 `PermissionEnforcer.force_mode(READ_ONLY)` 后赋 `agent.permission_enforcer`（run_loop 对注入实例直接复用；全局 settings 不动；注入失败降级为仅指令约束）；③ 计划模式与编排互斥（`data.plan_mode → mode="single"`，主对话内调研不派子代理）。
- **PM2 前端**：`ChatConfig.planMode` → chatApi body `plan_mode`；`/plan` slash 命令（新 mode='plan'，立即发送剩余文本，isLoading/disabled 守卫）；Chat.tsx `planApprovalFor` 会话键控批准条——planMode run 自然完成后出现（"按计划执行"= 清批准态 + `force_single` 发送执行指令；"忽略"= 仅清除）。
- 实现期事故：/plan 剥前缀的正则经 JSON→Python 双层转义把 `\b` 写成了真实退格控制字符（`\x08`），前缀剥不掉——改为无反斜杠的 `new RegExp('^/plan','i')` + trim（测试实证）。
- 测试：`test_permissions_enforcer.py` +1（force_mode 实例覆盖：写拒读放行、settings 不动）；`test_chat_plan_mode.py` 2 例（plan_mode 默认 False / 指令内容）；前端 `ChatInput.plan.test.tsx` 3 例（带目标发送 planMode=true / 空目标不发送 / isLoading 拦截）——后端 99 passed、前端 slash 三文件 13 passed；ruff / tsc / eslint 全过；全仓收集零错误。

## 7. 交付记录

| 批次 | main | win7 |
| --- | --- | --- |
| A（编排失败恢复） | PR #598（squash 049258af） | PR #604（cherry-win7-r8，squash c57342cb） |
| B（单 agent 计划模式） | PR #600（squash b20af9b1） | 同上（A/B 合并对齐） |

win7 对齐说明：两批经 cherry-win7-r8 按序 cherry-pick；Chat.tsx 的 handleCancelRun 保留 win7 既有版本、只新增 handleRerunFailed；useChat destructure 与 slashCommands 冲突按"双方保留"（learn + plan 并存）；本地 ruff 全过后由 CI py3.8 job 终验，squash merge（#604）。
