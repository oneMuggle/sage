# 任务动态调整能力（Re-plan Capability）

> **状态**：完成（2026-09-19）
> **创建日期**：2026-09-19
> **分支**：`feat/task-replan-capability`
> **前置调研**：2026-09-19 任务系统诊断会话（Sage 任务系统 vs Cursor/Devin/OpenAI Agents SDK/LangGraph 对比）

---

## 1. 背景与目标

### 1.1 问题陈述

Sage 当前的任务系统在 LLM 执行过程中**无法动态调整计划**。conductor（主 LLM）在 run 中只能：
- 分批派发任务（`dispatch_subagents` 多次调用）
- 重试失败任务（`retry_of`）
- 追问已完成任务（`followup_of`）

**无法做到**：
- ❌ 修改未派发的任务（goal / agent）
- ❌ 取消未启动的任务
- ❌ 添加新任务到现有计划（带依赖声明）
- ❌ 条件分支（if A fails then do B）

这导致 LLM 只能"死板执行完整计划"，即使发现某任务已无意义或需要调整方向，也无法主动干预，只能靠 prompt 驱动的"失败处理指令"做任务级微调。

### 1.2 主流应用对比

| 应用 | Re-plan 能力 | 触发方式 |
|---|---|---|
| **Devin** | ✅ 核心能力 | Planner-Executor 分离，确定性信号（test exit code）驱动 re-plan |
| **Cursor** | ✅ 可增删改 subtask | 用户可在 Agents Window 增删改；Planner 递归分解 |
| **LangGraph** | ✅ 条件边 + interrupt | `add_conditional_edges()` 运行时动态路由 |
| **Sage 当前** | ⚠️ 仅任务级微调 | 靠 prompt 驱动，无 re-plan 工具 |

### 1.3 目标

**本次实施范围**（Phase 1）：
- ✅ 加 3 个 LLM 工具，让 conductor 能"手术刀式"调整计划
- ✅ 修状态同步问题（`ChatTaskState` → `orch_tasks` 反向写入）
- ✅ 前端 TaskTreeSection 展示"已调整"标记

**不在本次范围**（后续工作）：
- ⏳ P0 完整：合并双轨 DB（`orchestration_tasks` → `orch_tasks`）
- ⏳ P1：任务层级化（`parent_id` / `children`）
- ⏳ Phase 2 re-plan：结构化 `replan_from_here` / `conditional_edge` 原语

---

## 2. 技术方案

### 2.1 新增 3 个 LLM 工具

#### 工具 1: `update_pending_task`

**用途**：修改未启动任务的 goal / agent_id。

**参数**：
```json
{
  "task_id": "string (required)",
  "goal": "string (optional, max 2000 chars)",
  "agent_id": "string (optional)"
}
```

**约束**：
- 只能修改 `status == "queued"` 的任务（未启动）
- 运行中（`running`）或已终态（`done/failed/cancelled`）拒绝
- 修改后立即生效（`_plan_by_id[task_id]` 更新）

**实现**：
- `ChatDispatcher.update_pending_task(task_id, goal, agent_id)` 方法
- 注册到 conductor 的 `tool_registry`（同 `dispatch_subagents`）

**返回**：
```json
{
  "success": true,
  "task_id": "t3",
  "updated_fields": ["goal", "agent_id"],
  "new_goal": "...",
  "new_agent_id": "..."
}
```

#### 工具 2: `cancel_pending_task`

**用途**：取消未启动的任务（不再需要执行）。

**参数**：
```json
{
  "task_id": "string (required)",
  "reason": "string (optional, max 500 chars)"
}
```

**约束**：
- 只能取消 `status == "queued"` 的任务
- 运行中任务用现有 `cancel_task`（HTTP API）
- 取消后状态转 `cancelled`，记录 `reason`

**实现**：
- 扩展现有 `ChatDispatcher.cancel_task()` 支持"未进 dispatch 的任务"
- 当前 `cancel_task` 只能取消"已进 dispatch 的任务"（`chat_dispatcher.py:432`）
- 新方法 `cancel_pending_task(task_id, reason)` 处理未启动任务

**返回**：
```json
{
  "success": true,
  "task_id": "t4",
  "status": "cancelled",
  "reason": "..."
}
```

#### 工具 3: `add_task_to_plan`

**用途**：添加新任务到现有计划（可声明依赖）。

**参数**：
```json
{
  "task_id": "string (required, 必须唯一)",
  "goal": "string (required, max 2000 chars)",
  "agent_id": "string (required)",
  "depends_on": ["string"]  // optional, 只能引用已有 task_id
}
```

**约束**：
- `task_id` 必须唯一（不能与现有任务重复）
- `depends_on` 只能引用已有 task_id（防止悬空依赖）
- 新任务立即加入 `_plan_by_id`，下次 `dispatch_subagents` 可派发

**实现**：
- `ChatDispatcher.add_task_to_plan(task_id, goal, agent_id, depends_on)` 方法
- 更新 `_plan_by_id` 和 `TaskGraph` 依赖关系
- 重新计算 waves（`topology.build_waves()`）

**返回**：
```json
{
  "success": true,
  "task_id": "t9",
  "added_to_wave": 3,
  "depends_on": ["t1", "t2"]
}
```

### 2.2 修状态同步问题

**当前问题**：`ChatTaskState.status` 和 `orch_tasks.status` 不严格同步，dispatcher 崩溃后内存态丢失但 DB 里 task 还活着。

**修复方案**：
- 在 `ChatDispatcher` 的状态迁移点（`_run_one` / `mark_completed` / `cancel_task`）反向写入 `orch_tasks.status`
- 关键位置：
  - `chat_dispatcher.py:732` `_run_one` 开始时 → `orch_tasks.status = "running"`
  - `chat_dispatcher.py:918` 级联失败时 → `orch_tasks.status = "failed"`
  - `chat_dispatcher.py:422` `cancel_task` 时 → `orch_tasks.status = "cancelled"`

**实现**：
- 复用现有 `OrchTaskRepository.update_status(task_id, status)` 方法
- 在 dispatcher 的状态迁移点调用

### 2.3 前端展示"已调整"标记

**当前问题**：LLM 动态调整的任务在前端看不出与"原计划"的区别。

**修复方案**：
- `orch_tasks` 表加 `adjusted_by_llm BOOLEAN DEFAULT FALSE` 列
- 3 个新工具调用时设置 `adjusted_by_llm = TRUE`
- 前端 `TaskTreeSection` 在任务名后显示 `🔧` 图标（已调整）

**实现**：
- 后端：`database.py` 加列 + migration
- 前端：`TaskTreeSection.tsx` 读取 `adjusted_by_llm` 字段并渲染图标

---

## 3. 实施步骤

### 里程碑 1：后端 3 个新工具（1 周）

- [x] **T1.1**：`ChatDispatcher.update_pending_task()` 方法 + 单元测试
- [x] **T1.2**：`ChatDispatcher.cancel_pending_task()` 方法 + 单元测试
- [x] **T1.3**：`ChatDispatcher.add_task_to_plan()` 方法 + 单元测试
- [x] **T1.4**：3 个工具类（`UpdatePendingTaskTool` / `CancelPendingTaskTool` / `AddTaskToPlanTool`）
- [x] **T1.5**：注册到 conductor 的 `tool_registry`（`legacy_routes.py:2549-2560`）
- [x] **T1.6**：conductor system prompt 补充"何时使用这些工具"的指引（`legacy_routes.py:2631-2643`）

### 里程碑 2：状态同步修复（3 天）

> **实施期核实**：`_emit_task_status`（`chat_dispatcher.py:1556`）已在状态迁移点调用
> `_persist_task_state`（line 1606）把 `ChatTaskState` 写库 —— 方案中的"状态不同步"
> 判断与现状不符，`orch_tasks.status` 已为准。T2.1-T2.3 标注为"现状已满足，无额外改动"。
> 实际新增价值在里程碑 3：`adjusted` 字段透出（未派发任务取消时补发 cancelled 事件让
> 前端可见）。

- [x] **T2.1**：`_emit_task_status` 已含 `_persist_task_state` 调用（line 1606，现状满足）
- [x] **T2.2**：回归测试 `test_chat_dispatcher_plan_authority.py` 等 97 项全绿
- [x] **T2.3**：`_persist_plan()` 把 plan 调整回写 `orch_runs.plan_json`，resume 可重建

### 里程碑 3：前端"已调整"标记（3 天）

- [x] **T3.1**：`_emit_task_status` 加 `adjusted: boolean` 字段（`_adjusted_plan_ids` 透传）
- [x] **T3.2**：`TaskStatusEvent` 类型加 `adjusted?: boolean`（`types.ts` + `llmStream.ts` 同步）
- [x] **T3.3**：前端 `TaskTreeSection.tsx` 在任务行渲染"已调整"徽章（`text-warning`）
- [x] **T3.4**：前端测试 `TaskTreeSection.test.tsx` 验证徽章渲染；后端测试 28 项含"取消未派发任务补发 cancelled 事件"

### 里程碑 4：集成测试 + 文档（2 天）

- [x] **T4.1**：后端 `test_replan_tool.py` 28 项覆盖三工具 + dispatch 联动（已取消任务拒绝派发、更新后的 goal 经 dispatch 生效、新增任务可派发）
- [x] **T4.2**：`tool_names.py` 模块注释补 re-plan 工具族说明
- [x] **T4.3**：本计划文档

---

## 4. 风险评估

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| 3 个新工具与现有 `dispatch_subagents` 语义冲突 | 高 | 工具注册时加互斥检查（同 run 不能同时用 `update` 和 `dispatch` 同一 task） |
| `add_task_to_plan` 破坏 DAG 依赖（悬空依赖） | 中 | 严格校验 `depends_on` 只能引用已有 task_id |
| 状态同步反向写入增加 DB 负载 | 低 | 只在状态迁移点写，不在 heartbeat 写 |
| 前端 `🔧` 图标在某些字体下显示异常 | 低 | 用 SVG 图标替代 emoji |

---

## 5. 后续工作（不在本次范围）

### 5.1 P0 完整：合并双轨 DB

**目标**：把 `orchestration_tasks` 数据迁移到 `orch_tasks`，删除老表。

**涉及**：
- `database.py:1186` 老表迁移脚本
- `TaskRepository` 改为读写 `orch_tasks`
- 前端 API 切换数据源

**预计工期**：1 周

### 5.2 P1：任务层级化

**目标**：支持"主任务 → 子任务 → 步骤"三层结构。

**涉及**：
- `orch_tasks` 加 `parent_task_id` / `depth` 列
- Planner 改造：递归分解到叶子节点
- 前端 `TaskTreeSection` 改为真正的树形视图

**预计工期**：2 周

### 5.3 Phase 2 re-plan：结构化原语

**目标**：让 LLM 能基于中间结果重新规划整个后半段。

**涉及**：
- `replan_from_here(from_task_id, new_tasks)` 工具
- `conditional_edge(trigger_task_id, on_success, on_failure)` 原语
- 改 `topology.py` 的 Kahn 分波逻辑支持"条件依赖"

**预计工期**：2 周

---

## 6. 验收标准

### 6.1 功能验收

- [ ] LLM 在 run 中能调用 `update_pending_task` 修改未启动任务的 goal
- [ ] LLM 在 run 中能调用 `cancel_pending_task` 取消不需要的任务
- [ ] LLM 在 run 中能调用 `add_task_to_plan` 添加新任务并声明依赖
- [ ] dispatcher 崩溃后 `orch_tasks.status` 与内存态一致
- [ ] 前端 `TaskTreeSection` 正确显示"已调整"标记

### 6.2 性能验收

- [ ] 3 个新工具的响应时间 < 100ms（不含 DB 写入）
- [ ] 状态同步反向写入不增加 heartbeat 负载
- [ ] 前端渲染"已调整"标记不增加首屏时间

### 6.3 兼容性验收

- [ ] 现有 `dispatch_subagents` / `collect_subagents` / `observe_subagents` 工具不受影响
- [ ] 现有 HTTP API（`update_plan` / `cancel_task`）不受影响
- [ ] 前端现有功能（PlanCard / TaskCenter / LaneBoard）不受影响

---

## 7. 参考资料

- [Cursor Subagents Docs](https://cursor.com/docs/subagents)
- [Devin Interactive Planning](https://cognitionai.mintlify.app/work-with-devin/interactive-planning)
- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [Sage 任务系统诊断报告](2026-09-19 会话)

---

## 附录 A：工具 Schema 定义

### `update_pending_task`

```python
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string"},
        "goal": {"type": "string", "maxLength": 2000},
        "agent_id": {"type": "string"},
    },
    "required": ["task_id"],
}
```

### `cancel_pending_task`

```python
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string"},
        "reason": {"type": "string", "maxLength": 500},
    },
    "required": ["task_id"],
}
```

### `add_task_to_plan`

```python
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string"},
        "goal": {"type": "string", "maxLength": 2000},
        "agent_id": {"type": "string"},
        "depends_on": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["task_id", "goal", "agent_id"],
}
```

---

## 附录 B：Conductor System Prompt 补充

在 `legacy_routes.py:2579-2612` 的计划块后追加：

```python
+ "\n\n当需要动态调整计划时，可使用以下工具："
+ "- update_pending_task(task_id, goal?, agent_id?): 修改未启动任务的 goal 或 agent（只能改 status=queued 的任务）"
+ "- cancel_pending_task(task_id, reason?): 取消不需要的未启动任务（只能取消 status=queued 的任务）"
+ "- add_task_to_plan(task_id, goal, agent_id, depends_on?): 添加新任务到计划，可声明依赖（depends_on 只能引用已有 task_id）"
+ "这些工具让你在发现原计划不再适用时能主动调整，而不是死板执行完整计划。"
```

---

**文档维护**：实施过程中每完成一个里程碑，在对应步骤标记 `[x]`。
