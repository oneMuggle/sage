# 2026-08-13 · 编排执行控制层（Orchestration Execution Control）设计

> 状态：设计已批准（用户 2026-08-13 确认"全部 P0+P1+P2 分波交付"）。
> 基线：main @ eacecfe9。范围源自《编排 vs Claude Code 差距分析》（同会话）。
> 交付形态：方案 A —— Wave 1/2/3 各独立 feature 分支 + PR，每波可独立合入。

## 1. 背景与目标

### 1.1 现状

Sage 编排体系两级共存：

- **聊天链路（真实在用）**：`_classify → Planner(≤8) → dispatch_subagents 工具 → ChatDispatcher(并发4, 纯内存) → task_plan/task_progress/task_status 事件 → 前端任务树`。用户实际体验即此路径。
- **Lane 编排层（~5300 行，约 80% 休眠）**：`Planner/Router/LaneExecutor/policy_engine/approval_tokens/report_schema/ultragoal_store/lane_board`。其中 `policy_engine`/`approval_tokens`/`report_schema` 只接线到**从不运行**的 Router/Executor；`ultragoal_store`/`lane_board` 仅测试引用；`LaneExecutor` 默认 runner 抛 `NO_RUNNER`，生产从未实例化。

### 1.2 差距（本设计的输入）

| # | 差距 | 对应优化 |
|---|---|---|
| 1 | 单任务失败靠 prompt 约束，无结构化重试 | P0-1 重试机制化 |
| 2 | 无验证闭环，conductor 直接汇总 | P0-2 ReviewReport 验证环 |
| 3 | 子任务同进程同文件系统，write_file 落 cwd | P0-3 scratch 隔离 |
| 4 | 计划内存态，无落盘无恢复 | P1-4 计划持久化/恢复 |
| 5 | 计划无交互，用户只能旁观 | P1-5 计划卡（可编辑/取消） |
| 6 | DAG 拆了但不落地到展示 | P1-6 depends_on 透传展示 |
| 7 | plan 与派发 task_id 对齐脆弱 | P2-7 派发携带 task_id |
| 8 | 全靠 LLM 自由发挥，无可复现路径 | P2-8 确定性模板 |
| 9 | 并发/预算硬编码 | P2-9 配置化 |
| 10 | 休眠 typed 层投资未变现 | P2-10 接入（复用投资） |

### 1.3 目标

把编排 run 从"内存态 + prompt 约束"升级为**一等公民的持久化执行单元**，加一层**执行控制**（重试/验证/隔离/恢复），并让已投资的 lane typed 层接入真实运行。

## 2. 已确认的设计决策

1. **范围**：全部 P0+P1+P2，分波交付（Wave 1/2/3 独立 PR）。
2. **休眠层处置**：**接入复用**（非删除）——LaneBoard 首次有真实数据，LaneExecutor 从 NO_RUNNER 变可用。
3. **计划审批交互**：**计划卡 + 可编辑取消**（不暂停流）。task_plan 事件后前端渲染可交互计划区；编辑生效窗口 = 首次派发前；整体取消任何时候可用。
4. **隔离目录形态**：**托管 scratch + 归并**——`data_dir/orch_scratch/<run_id>/<task_id>/`，子 agent `workspace_root` 指向，产物经 `_record_artifact_safely` 落 artifacts。

## 3. 整体架构

```text
/chat/stream (multi)
   │  Planner 拆解（DAG, ≤8, agent_hint）
   ▼
Plan 对象（持久化 orch_runs / orch_tasks, P1-4）──→ 前端计划卡（可编辑/取消, P1-5）
   │  task_plan 事件携带 depends_on（P1-6）
   ▼
ChatDispatcher.dispatch  ← dispatch_subagents(含 task_id, P2-7)
   │  每子任务 → ChatTaskState + Lane 镜像（P2-10）
   │  LaneExecutor.execute_lane（真实 agent_runner, P0-1 重试免费获得）
   │  scratch 隔离目录（workspace_root 作用域, P0-3）
   ▼
聚合 markdown → 验证环（reviewer 子 agent → ReviewReport, P0-2）→ conductor 最终汇总
```

### 3.1 架构决策（含替代）

| 决策 | 选择 | 备选 | 理由 |
|---|---|---|---|
| 重试实现 | 子任务执行路由到 `LaneExecutor.execute_lane`，复用 RecoveryPolicy | 在 ChatDispatcher 重写 retry | 复用已测试的重试/backoff；ChatDispatcher 保留并发/事件/聚合/错误隔离 |
| reviewer | 新增 `reviewer` 角色 + profile | 复用 ReviewService | ReviewService 仅服务技能草稿，非通用复核 |
| DAG 执行 | 只展示不强制拓扑（depends_on 透传） | 拓扑序分批派发 | 与 §42"conductor 依据中间结果再决策"设计一致；正确性由"必须完成全部 N"约束兜底 |
| 休眠层接入 | chat 镜像 lane + API lane 可执行 双通道 | 单通道 | chat 保低风险；API `/lanes` 变真实可执行路径 |

## 4. 数据模型（P1-4）

复用 `backend/data/orchestration_repo.py` 的 SQLite 模式，新增两张表：

```sql
CREATE TABLE orch_runs (
  run_id        TEXT PRIMARY KEY,
  session_id    TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'running',  -- running/completed/failed/cancelled
  created_at    INTEGER NOT NULL,
  plan_json     TEXT NOT NULL,                    -- {tasks:[{task_id,agent_id,goal,depends_on}], reasoning}
  final_summary TEXT
);

CREATE TABLE orch_tasks (
  task_id        TEXT PRIMARY KEY,
  run_id         TEXT NOT NULL REFERENCES orch_runs(run_id),
  agent_id       TEXT NOT NULL,
  goal           TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'queued',  -- queued/running/done/failed
  retry_count    INTEGER NOT NULL DEFAULT 0,
  error          TEXT,
  output_preview TEXT,
  blocked_by     TEXT,                            -- JSON array of task_id
  scratch_dir    TEXT,
  started_at     INTEGER,
  finished_at    INTEGER
);
```

`ChatDispatcher` 在原有内存态 + 事件推送之外，把每次状态迁移**同步写库**。写失败降级为仅内存（与 `task_status` 静默降级同策略，绝不阻塞聊天）。

## 5. Wave 1 — P0 后端接线（1 个 PR，纯后端）

### 5.1 P0-1 重试机制化

- 新建 `backend/orchestration/subagent_runner.py`：真实 `agent_runner`，签名 `async (task: Task, agent_id: str) -> dict`，内部构造 `SageAgent(agent_id=...)` + 目标 prompt 跑 `run_loop`，返回 DONE content（从 `task.parameters["goal"]` 取目标）。
- `ChatDispatcher._run_one` 改调 `LaneExecutor.execute_lane(lane, agent_id)`：
  - 每个子任务创建 `Task`（`parameters["goal"]`）+ `Lane`（`task_id`/`agent_id`）；
  - `LaneExecutor` 的 `_handle_failure`（retry/backoff/max_retries，已实现）自动处理重试；
  - `task_status` 事件增 `retry_count` 字段（Lane metadata 读取）。
- `RecoveryPolicy` 默认 `{on_failure: "retry", max_retries: 2}`（Wave 3 P2-9 进配置）。

### 5.2 P0-2 验证闭环

- 新增 `reviewer` 角色：
  - `backend/api/legacy_routes.py` `_VALID_AGENT_ROLES` 加 `"reviewer"`；
  - `backend/agents/profiles.py` 加 reviewer profile（system prompt：对照子任务 goal 与产出，逐条给出 assertions，标注 FACT/HYPOTHESIS/NEGATIVE_EVIDENCE + 置信度）。
- 全部子任务 done 后、conductor 最终汇总前：
  1. 跑一个 reviewer 子 agent（经 `subagent_runner`，输入 = 聚合 markdown）产出断言；
  2. `LaneExecutor.submit_with_report(lane_id, task_id, assertions)` 落 `ReviewReport`（复用 report_schema）；
  3. 推 `task_review` 事件（`run_id`, `verdict: pass/fail`, `assertion_count`, `summary`）；
  4. 复核结论追加进 conductor 上下文，失败则要求 conductor 先修复关键项再汇总。
- reviewer 子 agent 失败 → 降级跳过验证（不阻塞）。

### 5.3 P0-3 scratch 隔离

- run 开始建 `data_dir/orch_scratch/<run_id>/<task_id>/`（`data_dir` 沿用现有约定；`orch_scratch` 根 + `.gitignore` 条目）。
- 子 agent 运行时 `ToolExecutionContext.workspace_root` 指向其 scratch 目录（复用 F2 的无条件 set_tool_context 模式），`write_file` 被 `file_tool._path_within_workspace` 边界检查锁进 scratch。
- 成功产物经既有 `_record_artifact_safely` 落 artifacts（路径指向 scratch 持久位置）。
- 越界写 → `write_file` 权限拒绝，子 agent 自愈。

### 5.4 Wave 1 测试

- ChatDispatcher 重试单测：失败→重试→成功；retry 耗尽→failed 进聚合（错误隔离不破坏）。
- LaneExecutor + subagent_runner 集成：真实 runner 产出 DONE content。
- reviewer 复核单测：断言解析、verdict 判定、submit_with_report 事件。
- scratch 单测：workspace_root 作用域下 write_file 越界被拒；产物落 artifacts。
- 集成测试：多任务 run 含 1 失败子任务自动重试成功，task_status 带 retry_count。

## 6. Wave 2 — P1 计划生命周期（1-2 个 PR）

### 6.1 P1-4 计划落盘/恢复

- §4 两张表 + `backend/data/orchestration_repo.py` 增 `OrchRunRepository`/`OrchTaskRepository`（CRUD + list）。
- `ChatDispatcher` 状态迁移同步写库（降级策略见 §4）。
- 新端点（`legacy_routes.py` 或独立 router）：
  - `GET /orch/runs`（历史列表）+ `GET /orch/runs/{run_id}`；
  - `POST /orch/runs/{run_id}/resume` —— 从持久化 plan 重建新 run（新 run_id + session_id 透传），子任务状态重置 queued。
- 前端"历史编排记录"列表 + 每行"恢复"按钮（复用 sendMessage 链路触发 resume）。

### 6.2 P1-5 计划卡

- 前端 `TaskTreeSection`/`useChat` 拦截 `task_plan`，渲染可交互计划卡：
  - 每行：状态图标 + agent_id 徽标 + goal（**可编辑**）+ 删除按钮（需 ≥1 行）；
  - 头部按钮：开始 / 取消。
- 编辑走 `plan_update` IPC（invoke 通道）→ 后端更新 `run.plan` → 重发 `task_plan`（前端与后端收敛）。
- **编辑生效窗口 = 首次派发前**（conductor 已把计划 baked 进 system prompt，派发后锁定为只读）；取消任何时候可用（复用整条 stream cancel + `task_cancel` 事件标记 run cancelled）。

### 6.3 P1-6 DAG 展示

- `task_plan` item 增 `depends_on: string[]`（planner `_sanitize_tasks` 已有 blocked_by 结果，仅透传占位符→真实 task_id）。
- 前端任务树显示依赖（"↳ t1" 缩进或箭头），不强制拓扑执行。

### 6.4 Wave 2 测试

- 持久化：run/task 写读回、resume 重建、写失败降级。
- 前端 vitest：计划卡渲染/编辑/删除/取消；plan_update 事件处理。
- task_plan depends_on 字段断言（后端 + 前端）。

## 7. Wave 3 — P2 结构增强 + 休眠层接入（1-2 个 PR）

### 7.1 P2-7 派发 task_id 对齐根治

- `dispatch_subagents` 工具 schema 每任务加必填 `task_id`；
- `ChatDispatcher.dispatch` 用传入 task_id 定位 `ChatTaskState`（弃用 `_next_task_index` 自增）；
- 与 plan 中 task_id（t1..tN）严格对齐，消灭 §10.5 脆弱不变量。
- conductor 需知 task_id：计划已展示于 prompt/计划资源，工具描述注明。

### 7.2 P2-8 确定性模板

- 模板定义模块 `backend/orchestration/templates.py`：`OrchestrationTemplate {id, name, stages:[{agent_id, description, depends_on}]}`。
- 内置模板示例：`research-write-review`（researcher 调研 → writer 写作 → reviewer 校验）。
- `orchestration_mode` 支持模板 id：Planner 用模板 stage 列表替代自由 LLM 拆解（复用现有 DAG 落库/事件机制，`plan.reasoning = "template: <id>"`）。
- 前端模板选择器（多模式时显示）。

### 7.3 P2-9 配置化

- app_settings 增编排段：`orch.max_concurrent_subagents`（默认 4）、`orch.max_aggregate_chars`（默认 120KB）、`orch.max_subagent_result_chars`（默认 50KB）、`orch.max_retries`（默认 2）、`orch.scratch_root`（默认 `data_dir/orch_scratch`）。
- 运行时读取（`ChatDispatcher` 构造参数注入，`legacy_routes` 从 settings 装配）。

### 7.4 P2-10 休眠层接入

1. **chat 镜像 lane**：chat 编排 run 每子任务 `lane_registry.create_lane` + 生命周期 `LaneEvent`（STARTED/RUNNING/SUCCEEDED/FAILED），**LaneBoard 首次有真实数据**。
2. **API lane 可执行**：`POST /api/v1/orchestration/lanes` 从"只建不跑"变为真实执行——`LaneExecutor` + Wave1 的 `subagent_runner` + RecoveryPolicy；lanes 带真实结果与 ReviewReport。
3. **LaneBoard 监控端点**：`GET /api/v1/orchestration/board`（freshness summary + 分状态 lane 数），供前端编排面板后续接入。

### 7.5 Wave 3 测试

- task_id 对齐：乱序/缺省 task_id 的 dispatch 处理。
- 模板拆解：模板 → DAG → 派发全链路。
- 配置读取：settings 覆盖默认值。
- lane 镜像：chat run 在 lane_registry 产生对应 lane + 事件。
- API lane 执行：`POST /lanes` 分解→路由→执行→结果/报告。

## 8. 错误处理与降级链

| 场景 | 行为 |
|---|---|
| 持久化写失败 | 降级仅内存，日志记录，不阻塞聊天 |
| reviewer 失败 | 跳过验证继续汇总，log warning |
| retry 耗尽 | 任务 failed 进聚合（现有错误隔离），conductor 可见 |
| scratch 越界写 | `write_file` 权限拒绝，子 agent 自愈（prompt 可见） |
| resume 目标 run 不存在/已删 | 404 + 前端提示 |
| plan_update 在派发后 | 后端拒绝（"已开始执行，计划锁定"），前端锁只读 |

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| ChatDispatcher 改走 LaneExecutor 引入回归 | Wave 1 独立 PR + 既有编排集成测试全量回归；LaneExecutor 状态机严格但 ChatDispatcher 保留事件/聚合/隔离职责 |
| reviewer 角色新增影响 agent 列表 | 角色只读新增，不影响既有 5 角色；profile 独立 |
| 计划卡编辑语义（派发后锁定）可能困惑用户 | 前端明确"已开始执行，计划锁定"提示；取消永远可用 |
| 并发写库性能 | 编排 run 低频（每 run ≤8 任务 × ≤3 次状态迁移），SQLite 足够；写失败降级兜底 |
| 三波范围大 | 每波独立分支/PR/测试 gate，Wave 1 全绿再启 Wave 2 |

## 10. 相关章节

- [`42-chat-multi-agent-orchestration.md`](../technical/42-chat-multi-agent-orchestration.md) — 聊天编排现状 + §9/§10 已知遗留（本设计逐项闭合）
- [`27-multi-agent-orchestration.md`](../technical/27-multi-agent-orchestration.md) — lane 层 M1-M5（P2-10 接入对象）
- [`23-chat-streaming.md`](../technical/23-chat-streaming.md) — NDJSON 协议 / Electron IPC 事件桥接
- [`22-agents-crud.md`](../technical/22-agents-crud.md) — agent 角色/CRUD（reviewer 新增遵循）
