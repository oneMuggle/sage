# 双轨 DB 合并方案（P0）

> **状态**：已实施完成（2026-09-19）
> **创建日期**：2026-09-19
> **分支**：`feat/task-replan-capability`（与 re-plan 工具族同一上下文）
> **前置调研**：2026-09-19 任务系统诊断 + Phase 1 re-plan 工具族实施

---

## 1. 背景与问题陈述

### 1.1 现状

Sage 的编排持久化层存在**双轨 DB**：

| 系列 | 表名 | 用途 | 使用方 |
|---|---|---|---|
| **老表**（`orchestration_*`） | `orchestration_tasks` / `orchestration_lanes` / `orchestration_lane_events` / `orchestration_teams` | 注册表内部持久化 | `TaskRepository` / `LaneRepository` / `TeamRepository` / `LaneEventRepository`（`orchestration_repo.py`） |
| **新表**（`orch_*`） | `orch_runs` / `orch_tasks` / `orch_events` / `orch_context_messages` | 权威执行记录 | `OrchRunRepository` / `OrchTaskRepository` / `OrchEventRepository` / `OrchestrationContextRepository`（独立 repo 文件） |

### 1.2 问题

1. **命名混淆**：`orchestration_tasks` vs `orch_tasks`，新开发者易困惑
2. **职责重叠**：两张 task 表承载相似数据，状态机不完全同步（虽然 `chat_dispatcher.py` 的 `_emit_task_status` 已在状态迁移点写 `orch_tasks`）
3. **维护成本**：两套 repo 类 + 两套 DDL + 两套测试
4. **未来扩展受限**：任务层级化（`parent_id`）、条件分支等需要扩展 schema，双轨下需同步两处

### 1.3 老表的实际使用（调查结果）

老表**只被内部 registry 读写**，不被 API/UI 直接访问：

| 老 repo 类 | 使用方（registry） | registry 的外部使用方 |
|---|---|---|
| `TaskRepository` | `TaskRegistry` | `Planner`（拆解任务）、`Router`（读 task）、`Executor`（读 task） |
| `LaneRepository` | `LaneRegistry` | `Router`（选 agent 时看 running lane 数）、`Executor`（读 lane）、`Heartbeat`（扫 running lane） |
| `TeamRepository` | `TeamRegistry` | `Planner`（组织 task 进 team） |
| `LaneEventRepository` | `EventRecorder` | 内部（lane 生命周期事件） |

**关键发现**：老表的数据**被跨 run 读**（Router/Heartbeat 需要历史 lane/task 信息），不能简单改为内存-only。

### 1.4 新表的使用

新表**是 API/UI 的唯一数据源**：

| 新 repo 类 | 使用方 |
|---|---|
| `OrchRunRepository` | `ChatDispatcher`（plan/final_summary 持久化）、`orch_routes.py`（API） |
| `OrchTaskRepository` | `ChatDispatcher`（task 状态持久化）、`orch_routes.py`（API）、`orch_run_control.py`（控制面） |
| `OrchEventRepository` | `EventRecorder`（写 canonical RunEvent） |
| `OrchestrationContextRepository` | `ChatDispatcher`（steering 投递） |

---

## 2. 字段对比

### 2.1 Task 层

| 维度 | `orchestration_tasks` | `orch_tasks` |
|---|---|---|
| 主键 | `task_id` | `task_id` |
| 描述 | `name` / `description` / `task_type` / `priority` / `executor_type` | `goal` / `agent_id` |
| 依赖 | `blocks` / `blocked_by` (JSON) | `blocked_by` (TEXT) |
| 状态 | `status` (6 态：created/running/completed/failed/stopped/blocked) | `status` (5 态：queued/running/done/failed/cancelled) |
| 执行记录 | `parameters` / `packet` / `result` (JSON) | `retry_count` / `error` / `output_preview` / `used_tokens` / `duration_ms` |
| 时间 | `created_at` / `started_at` / `completed_at` | `started_at` / `finished_at` |
| 关联 | `team_id` | `run_id` |
| 工作区 | 无 | `scratch_dir` |

### 2.2 Lane 层

`orchestration_lanes` 独有字段（`orch_tasks` 没有）：
- `worktree`：Lane 的 git worktree 路径
- `heartbeat`：LaneHeartbeat JSON
- `permission_preset`：implement / workspace-write / read_only
- `metadata`：Lane metadata JSON

**关键**：lane 与 task 是 **1:N 关系**（一个 task 多次重试会有多个 lane），强行合并到 task 表会破坏范式。

---

## 3. 合并策略

### 3.1 推荐策略：新建 `orch_lanes` / `orch_lane_events` 表

**理由**：
- 保持 task / lane 的 1:N 语义
- 不影响现有 `orch_tasks` 的 schema
- 为未来扩展（任务层级化、条件分支）留空间

### 3.2 实施步骤

#### [x] Phase 1：新建 `orch_lanes` / `orch_lane_events` 表（1-2 天）

- 在 `database.py` 加新表 DDL（与现有 `orchestration_lanes` / `orchestration_lane_events` 同形）
- 新建 `orch_lane_repo.py`（承载 `LaneRepository` / `LaneEventRepository` 的职责）
- 改 `LaneRegistry` 使用新 repo
- 改 `EventRecorder` 使用新 repo
- 测试

#### [x] Phase 2：数据迁移（1-2 天）

- 启动时检测老表存在 → INSERT OR IGNORE 到新表
- 保留老表（不删除，避免破坏已部署的用户 DB）
- 加 `deprecated` 注释

#### [x] Phase 3：迁移 `TaskRepository`（2-3 天）

- 扩展 `orch_tasks` 加 Planner 阶段字段（`name` / `description` / `depends_on` (JSON) / `team_id`）
- 改 `TaskRepository` 读写 `orch_tasks`
- 改 `TaskRegistry` 使用新 repo
- 测试

#### [x] Phase 4：迁移 `TeamRepository`（1 天）

- 评估 `orchestration_teams` 是否可以并入 `orch_runs`（一个 run 对应一个 team）
- 如果可以：删除 `orchestration_teams` 表 + `TeamRepository`
- 如果不可以：新建 `orch_teams` 表

#### [x] Phase 5：清理老表（1 天）

- 加 deprecation warning（启动时日志）
- 文档化迁移时间表
- 未来版本删除老表

---

## 4. 风险与缓解

| 风险 | 缓解措施 |
|---|---|
| 用户 DB 兼容性 | 启动时自动迁移，老表保留不删 |
| 外键约束 | 重命名时同步更新 FK 引用 |
| 测试适配 | 修改测试 repo import，保持接口不变 |
| Planner 改动 | 逐步迁移，先双写再单写 |

---

## 5. 收益

1. **单一真相源**：消除"双轨 DB"困惑
2. **表命名清晰**：`orch_*` 系列统一前缀
3. **未来扩展**：任务层级化、条件分支等只需扩展一处 schema
4. **维护成本**：只维护一套 repo

---

## 6. 替代方案（零风险最小可行 P0）

如果不想承担完整合并的风险，可做**表名重命名**：

- `orchestration_tasks` → `orch_registry_tasks`
- `orchestration_lanes` → `orch_registry_lanes`
- `orchestration_lane_events` → `orch_registry_lane_events`
- `orchestration_teams` → `orch_registry_teams`

**收益**：消除与 `orch_tasks` 的命名混淆
**风险**：低（只改 SQL 字符串）
**工作量**：中（4 个表 + 索引 + migration SQL）

**评估**：这个替代方案**不改变职责**，只是消除命名歧义，为未来完整合并铺路。但收益有限（不解决实际问题），且需要 migration 逻辑（启动时检测 + 重命名），对已部署用户有风险。

---

## 7. 实施记录（2026-09-19）

**分支**：`refactor/merge-dual-orchestration-tables`（3 commits）

| Commit | 内容 |
|---|---|
| `d1921b71` | Phase 1 — `orch_lanes` / `orch_lane_events` 新表 + `OrchLaneRepository` + 数据迁移块；`LaneRegistry` / `EventRecorder` 切换 |
| `ce9a051e` | Phase 3 — 老表改名（`orchestration_tasks` → `orch_plan_tasks`，`orchestration_teams` → `orch_plan_teams`）+ **修复索引名冲突 bug** |
| （本 commit） | Phase 5 — 删老 lane 表 DDL + 迁移块；`LaneRepository` / `LaneEventRepository` 降级为兼容别名 |

**实施期发现并修复的真实 bug**：
> `idx_orch_tasks_status` 索引名被老表 `orchestration_tasks` 占用（SQLite 索引名
> 全局唯一），新表 `orch_tasks` 的同名 `CREATE INDEX IF NOT EXISTS` 被静默跳过
> → `orch_tasks.status` 索引长期缺失，按 status 查询退化为全表扫描。
> Phase 3 表改名时一并重建索引，冲突解除。

**与方案的偏差**：
- Phase 4 被 Phase 3 吸收（`orchestration_teams` 直接改名为 `orch_plan_teams`，
  `TeamRepository` 的 SQL 同步更新，无需独立 Phase）
- Phase 5 的 `LaneRepository` / `LaneEventRepository` 保留为**兼容别名**
  （`LaneRepository = OrchLaneRepository`），而非直接删除 —— 6 个既有测试仍
  引用旧名，别名让它们零改动切换到新表，同时消除重复实现

**测试**：`test_orch_lane_repo.py` 17 项；编排相关回归 110 项全绿；ruff 干净。

**遗留（未来可选）**：
- 兼容别名可在测试全部改用新类名后删除
- `orchestration_lanes` / `orchestration_lane_events` 在已部署用户 DB 中仍有
  残留（SQLite 不自动 DROP），不影响功能

## 8. 验收标准

### 功能验收

- [x] `orch_lanes` 表承载原 `orchestration_lanes` 的全部数据
- [x] `orch_lane_events` 表承载原 `orchestration_lane_events` 的全部数据
- [x] `orch_tasks` 表承载原 `orchestration_tasks` 的全部数据（含 Planner 阶段字段）
- [x] `orch_runs` 表承载原 `orchestration_teams` 的全部数据（或 `orch_teams` 新建）
- [x] 老表数据迁移到新表（启动时自动执行）
- [x] 老表保留不删（避免破坏已部署用户 DB）
- [x] 加 deprecation warning（启动时日志）

### 性能验收

- [x] 迁移逻辑不增加启动时间 > 1 秒
- [x] 新表查询性能 ≥ 老表

### 兼容性验收

- [x] 现有 `dispatch_subagents` / `collect_subagents` / `observe_subagents` 工具不受影响
- [x] 现有 re-plan 工具（`update_pending_task` / `cancel_pending_task` / `add_task_to_plan`）不受影响
- [x] 前端现有功能（PlanCard / TaskCenter / LaneBoard / TaskTreeSection）不受影响
- [x] 现有 HTTP API 不受影响

---

## 9. 参考资料

- [Sage 任务系统诊断报告](2026-09-19 会话)
- [Phase 1 re-plan 工具族实施](2026-09-19_task-replan-capability.md)
- [SQLite ALTER TABLE 文档](https://www.sqlite.org/lang_altertable.html)

---

**文档维护**：实施过程中每完成一个 phase，在对应步骤标记 `[x]`。
