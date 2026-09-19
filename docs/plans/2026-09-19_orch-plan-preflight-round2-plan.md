# 编排计划前置 Round 2——计划模式 × 编排打通（/plan 批准后走 multi 派发）

> 日期: 2026-09-19
> 前序: 2026-09-19_orch-plan-preflight-plan.md（Round 1：澄清门 + 侦察先行）
> 目标分支: feat/orch-plan-preflight（与 Round 1 同分支延续，合并评估后 cherry-pick win7）

## 背景

Round 8 交付的单 agent 计划模式（/plan）批准后只能以 `force_single` 单 agent
执行——"只读调研 → 出方案 → 批准 → **多智能体并行实施**"走不通（计划模式与
编排互斥，`legacy_routes.py:2416`）。本批打通最后一步：批准的计划可一键转
编排任务卡，经既有确认门派发。

## 方案：已批准计划文本 → 结构化任务项 → plan_override 派发

复用恢复流（A10）的 `plan_override` 全套管道（producer 透传自带 task_id、
PlanCard 确认门、dispatch），只缺"计划 markdown → `{task_id, agent_id, goal,
depends_on}` 列表"的结构化一步。新增一个后端端点完成它，前端批准条加一个
入口按钮。

### 链路

```
/plan 完成 → 计划批准条
  └─ [按计划执行（编排）] → POST /api/v1/orch/plan-items {text}
       → LLM 结构化（planner 同款清洗纪律）→ {items: [{task_id, agent_id, goal, depends_on}]}
  → sendMessage(opts.planOverride=items) → ChatRequest.plan_override
  → producer 跳过 decompose/preflight，直接 task_plan + 确认门
  → PlanCard（可再编辑/删行）→ confirm → conductor dispatch_subagents
```

### 变更面

| 层 | 文件 | 内容 |
| --- | --- | --- |
| 后端 | `backend/orchestration/planner.py` | `_sanitize_tasks` 主体提为模块级 `sanitize_llm_plan_tasks()`（方法委托，行为不变，供端点复用） |
| 后端 | `backend/api/orch_routes.py` | `POST /orch/plan-items`：LLM 结构化计划文本；无 LLM → 503；畸形输出 → 502；≤8 任务、agent_hint 经 `_is_dispatchable_agent` 过滤、depends 只引更早任务（保 DAG），占位 `idx:k` → `t{k+1}` |
| Electron | `electron/commands.ts` | IPC 映射 `orchestration_plan_items` → POST /api/v1/orch/plan-items |
| 前端 | `src/shared/api/orchRunClient.ts` | `planItemsFromText(text)` |
| 前端 | `src/pages/Chat.tsx` | 批准条新增 `data-testid="plan-approve-orch"` 按钮：取当前会话最后一条 assistant 消息（即计划文本）→ 调端点 → `sendMessage(..., { planOverride: items })`；失败 toast 提示并可回落既有单 agent 按钮 |

### 关键决策

- **结构化失败响亮失败（502）而非静默降级**：这是显式用户动作，静默降成
  单任务会让用户以为"编排了"其实没有；toast 引导回落单 agent 按钮。
- **不走 Planner.decompose_request**：恢复流 override 路径已验证"透传自带
  task_id"可靠，且天然跳过 Round 1 的 preflight（计划文本已是结构化输入，
  再澄清/侦察是浪费往返）。
- **双重确认保留**：plan_override 仍走 task_plan 确认门 + PlanCard 可编辑
  ——结构化是 LLM 转译，用户应在任务卡上对转译结果做最终裁决（与编排主
  流程的确认契约一致）。
- **计划文本来源**：批准条出现时流已结束、内容已落 store，取当前会话最后
  一条 assistant 消息即可（与"按上述计划执行"的既定语义一致）。

## 验收

- 后端单测（新增 `backend/tests/unit/test_orch_plan_items.py`）：
  `sanitize_llm_plan_tasks` 模块函数（非法输入/上限/依赖向前约束/hint 过滤）、
  `idx:k → t{k+1}` 映射、响应解析（围栏剥离/畸形 → None）。
- 后端集成：`POST /orch/plan-items` 正常结构化（patch LLM 工厂）/ 无 LLM
  503 / 畸形输出 502 / 超长文本 422。
- 回归：`test_planner_llm.py`（重构等价性）、`test_chat_orchestration_stream.py`
  的 override 用例（透传路径未动）全绿。
- 前端：`npm run typecheck` 通过；worktree 经 junction 复用主工作区
  node_modules。

## 非目标（继续登记）

- 计划 artifact 持久化 + 执行期逐步对照 + 验收失败定点返工（TaskPacket 激活）。
- `orch_preflight` 前端可视化、OrchSettings 设置 UI 透出。
- 结构化任务项的预览编辑（批准后直接进 PlanCard 确认门，已有编辑能力）。

## 实施与验证记录（2026-09-19）

交付物：
- `planner.py`：`sanitize_llm_plan_tasks()` 提升为模块级（`_sanitize_tasks`
  委托，行为不变）；
- `orch_routes.py`：`POST /orch/plan-items`（`PlanItemsRequest/PlanItem/
  PlanItemsResponse` + `placeholder_deps_to_ids` + `_parse_plan_items_response`），
  503 no_llm_configured / 502 llm_call_failed·plan_items_parse_failed /
  422 病态输入（≤20000 字符）；
- `electron/commands.ts`：IPC 映射 `orchestration_plan_items`；
- `orchRunClient.ts`：`planItemsFromText(text)`；
- `Chat.tsx`：批准条 `data-testid="plan-approve-orch"` 按钮（planOrchBusyRef
  防双击；空 items / 请求失败 toast 引导回落单 agent 按钮）。

验证结果：
- 后端 97/97：新增 `test_orch_plan_items.py` 9 用例 + planner 重构等价性
  （test_planner_llm 15）+ orchestration stream（含 override 透传用例）+
  preflight 18 + orch_settings / chat_plan_mode / agent_profile_wiring /
  router_registration / question_routes；
- 前端：`tsc --noEmit` 0 错误；vitest send-message + shared/api 34 文件
  259 用例全过；eslint（Chat.tsx / orchRunClient.ts / commands.ts）0 告警；
- worktree 经 junction 复用主工作区 node_modules（仅本地开发加速，不入库）。
