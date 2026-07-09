---
name: win7-m4-orchestration
description: win7 M4 Orchestration 模块设计 — byte-for-byte port main 的 multi-agent 协调层 (16 backend 文件 + 1 API router + 1 persistence repo + 4 frontend 文件 + 4 张 DB 表)
metadata:
  type: spec
  status: design
  author: brainstorm-session-2026-06-28
  related_specs:
    - 2026-06-28-win7-modules-rollout-design.md
    - 2026-06-28-win7-m3-scheduler-design.md
  related_plans:
    - 2026-06-25-phase8-scheduled-tasks.md
---

# win7 M4 Orchestration Design Spec

## 1. Goal

将 `main` 分支的**multi-agent orchestration 模块**（多智能体协调层） byte-for-byte port 到 `release/win7` 分支，让 win7 用户获得与 main 一致的 multi-agent 任务协调能力 — 用户可在 UI 上提交 ultragoal，由 Planner 分解为多 Task + 多 Lane，由 Executor 调度执行，由 LaneBoard 实时呈现。

**范围边界**：

| 包含 | 不包含 |
|---|---|
| 16 文件 `backend/orchestration/` 包（4501 行） | main 的 `backend/core/legacy/orchestrator.py`（460 行，已有） — 不重复 |
| 1 文件 `backend/api/orchestration_router.py` | main 的 `backend/core/legacy/agent.py`（707 行，已有） — 不重复 |
| 1 文件 `backend/data/orchestration_repo.py`（601 行，win7 缺失） | main 的 `backend/agents/profiles.py`（168 行，已有） — 不重复 |
| `backend/data/database.py` 增加 4 张 orchestration 表 + 7 索引 | `scheduler/evolution.py` AI 进化任务（属 M3 范围但未做，留作后续） |
| 4 文件 frontend（Orchestration page + LaneBoard + store + client） | main 的 `docs/05-agent.md`（文档，不 port） |
| M4 专属 unit + integration tests | main 的 legacy agent 相关 tests（已在 win7） |

**不在本 spec 范围**：

- `scheduler/evolution.py` 的 AI 进化任务（DailySummaryTask、MemoryConsolidationTask）— 独立模块
- `backend/core/legacy/orchestrator.py` — **已存在于 win7**（460 行，byte-for-byte 一致）
- `backend/agents/{__init__.py, profiles.py}` — **已存在于 win7**（byte-for-byte 一致）
- `backend/data/{agent_repo.py, blackboard_repo.py}` — **已存在于 win7**（byte-for-byte 一致）
- `backend/domain/agent.py` — **已存在于 win7**（byte-for-byte 一致）
- `backend/core/legacy/{agent.py, agent_state.py}` — **已存在于 win7**（byte-for-byte 一致）

## 2. Win7 上下文

### 2.1 关键事实（已验证 2026-06-28）

| 项 | 实际状态 | 与 modules-rollout spec §3 的差异 |
|---|---|---|
| 后端 Python 版本 | **3.10.20**（sage-backend env） | rollout spec 说 "py3.8 + pydantic 1.x 适配" — **实际不符** |
| pydantic 版本 | **2.13.4** | 同上，实际是 pydantic 2.x |
| win7 `backend/orchestration/` 目录 | 存在但**仅有 `__pycache__`**（15 个 .pyc 文件，无 .py source） | rollout spec 说"空" — 实际有 pyc 残留 |
| win7 `backend/data/orchestration_repo.py` | **完全缺失** | rollout spec 未提及 |
| win7 `backend/data/database.py` | **缺 4 张 orchestration 表 + 7 索引** | rollout spec 说 "加 4 张表" — 一致 |
| win7 `backend/agents/{profiles.py,__init__.py}` | ✅ **已存在且与 main byte-for-byte 一致** | rollout spec 未提及 |
| win7 `backend/data/{agent_repo.py, blackboard_repo.py}` | ✅ **已存在且与 main byte-for-byte 一致** | rollout spec 未提及 |
| win7 `backend/domain/agent.py` | ✅ **已存在且与 main byte-for-byte 一致** | rollout spec 未提及 |
| win7 `backend/core/legacy/{orchestrator.py, agent.py, agent_state.py}` | ✅ **已存在且与 main byte-for-byte 一致** | rollout spec 未提及 |
| 前端 i18n（M1） | ✅ 已实现 | — |
| 前端主题编辑器（M2 P4） | ✅ 已实现 | — |
| 前端 Scheduler（M3） | ✅ 已实现 | — |

**结论**：

1. win7 后端环境与 main **完全一致**（py3.10 + pydantic 2.x），可 byte-for-byte port 无需 pydantic 1.x 适配
2. ~70% 的 M4 supporting 依赖**已在 win7 存在且与 main byte-for-byte 一致**（之前 phase 9 sync 已 port）
3. M4 实际需 port 的增量 = 16 orchestration/ 文件 + 1 API router + 1 orchestration_repo + DB DDL + 4 frontend 文件

### 2.2 M2 P4 / M3 已验证路径

M2 P4 和 M3 均采用 byte-for-byte port 策略：
- 从 main git 直接复制文件
- 仅做 i18n key 适配（如需要）
- 单分支 `feat/win7-<module>`，多 commits
- 结果：tsc 0 新错误，vitest + pytest 全过

M4 沿用同一路径。

## 3. 架构总览

```
┌──────────────────────────────────────────────────────────────────────┐
│ Frontend (React 18 + Vite + TypeScript)                              │
├──────────────────────────────────────────────────────────────────────┤
│  Orchestration page ─── LaneBoard widget                             │
│       │                      │                                       │
│       │               laneBoardStore (Zustand)                       │
│       │                      │                                       │
│       │               orchestrationClient (IPC/HTTP)                 │
└───────┼──────────────────────┼───────────────────────────────────────┘
        │                      │ Electron IPC / preload → HTTP
        ▼                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Backend (FastAPI + Python 3.10)                                      │
├──────────────────────────────────────────────────────────────────────┤
│  /api/v1/orchestration/*  (api/orchestration_router.py)              │
│       │                                                              │
│       ▼                                                              │
│  orchestration/                                                      │
│  ├── Planner ──────► decompose_request(ultragoal) → Plan+Tasks       │
│  ├── Router ───────► route_task(task) → RoutingDecision              │
│  ├── Executor ─────► Lane 生命周期管理 (READY → RUNNING → terminal)  │
│  ├── Heartbeat ────► Lane 健康监控                                    │
│  ├── LaneBoard ────► Lane 状态聚合 + 实时聚合                         │
│  ├── PolicyEngine ─► Typed policy decisions (M2)                     │
│  ├── UltragoalStore ► Director-only goal persistence                  │
│  ├── ApprovalTokens ► Privileged dispatch tokens (M2)                │
│  ├── Events ───────► Lifecycle event recording + streaming           │
│  └── ReportSchema ─► ReviewReport typed schema                       │
│                                                                      │
│  Registries (in-memory + SQLite-backed):                             │
│  ├── TaskRegistry ←→ TaskRepository (orchestration_repo.py)          │
│  ├── LaneRegistry ←→ LaneRepository                                  │
│  ├── TeamRegistry ←→ TeamRepository                                  │
│  └── EventRecorder ←→ LaneEventRepository                            │
│                                                                      │
│  SQLite:                                                             │
│  ├── orchestration_tasks (task_id, status, priority, dependencies)   │
│  ├── orchestration_lanes (lane_id, agent_id, status, heartbeat)      │
│  ├── orchestration_lane_events (event_id, lane_id, event_type)       │
│  └── orchestration_teams (team_id, status, task_ids)                 │
└──────────────────────────────────────────────────────────────────────┘
```

## 4. Backend 组件详细设计

### 4.1 数据模型层 (`backend/orchestration/models.py` — 398 行)

**已存在 main 的核心 dataclass**：

| 类 | 用途 | 关键字段 |
|---|---|---|
| `TaskStatus` (Enum) | Task 生命周期 | CREATED/RUNNING/BLOCKED/COMPLETED/FAILED/STOPPED + `is_terminal()` |
| `Task` (dataclass) | 工作单元 | task_id, name, task_type, status, priority, executor_type, parameters, packet, blocks, blocked_by, result, timestamps, team_id |
| `TaskPacket` (dataclass) | 高级配置 | recovery_policy, escalation_policy |
| `RecoveryPolicy` (dataclass) | 失败处理 | on_failure, retry_backoff_secs, max_retries |
| `EscalationPolicy` (dataclass) | 升级策略 | threshold, target |
| `LaneStatus` (Enum) | Lane 生命周期 | CREATED/READY/RUNNING/SUCCEEDED/FAILED/STOPPED/CANCELLED |
| `Lane` (dataclass) | 执行单元 | lane_id, task_id, agent_id, status, created_at, started_at, completed_at, worktree, heartbeat, error, permission_preset, metadata |
| `LaneHeartbeat` (dataclass) | 心跳数据 | last_ping_at, transport_alive, status |
| `TeamStatus` (Enum) | Team 生命周期 | PLANNED/ACTIVE/COMPLETED/FAILED |
| `Team` (dataclass) | 任务组 | team_id, name, task_ids, status, metadata |
| `Agent` (dataclass) | 智能体 | agent_id, name, capabilities, status, current_task_id, metadata |

**方法**：Task 包含状态转换方法（mark_running, mark_completed, mark_failed, mark_blocked, mark_stopped），每个方法都验证前置状态并触发时间戳更新。

### 4.2 持久化层 (`backend/data/orchestration_repo.py` — 601 行)

**win7 缺失，需从 main port**。提供 4 个 Repository 类：

| Repository | 主要方法 |
|---|---|
| `TaskRepository` | `create(task)`, `get(task_id)`, `update(task)`, `delete(task_id)`, `list_by_team(team_id)`, `list_by_status(status)`, `find_ready_tasks()` |
| `LaneRepository` | `create(lane)`, `get(lane_id)`, `update(lane)`, `update_heartbeat(lane_id, heartbeat)`, `list_by_task(task_id)`, `list_by_status(status)`, `find_stale(max_age_secs)` |
| `TeamRepository` | `create(team)`, `get(team_id)`, `update(team)`, `add_task(team_id, task_id)`, `list_by_status(status)` |
| `LaneEventRepository` | `record(event)`, `list_by_lane(lane_id)`, `list_by_task(task_id)`, `list_since(timestamp)` |

**辅助函数**：`_to_jsonable(obj)` — 递归转换 dataclass 实例为 dict（用于 JSON 序列化到 SQLite TEXT 列）。

### 4.3 DB Schema 变更 (`backend/data/database.py`)

需在 `init_tables()` 中新增 4 张表 + 7 索引（从 main `database.py` 行 272-371 byte-for-byte 复制）：

```sql
-- 任务表
CREATE TABLE IF NOT EXISTS orchestration_tasks (
    task_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    task_type TEXT NOT NULL DEFAULT 'general',
    status TEXT NOT NULL DEFAULT 'created',
    priority INTEGER NOT NULL DEFAULT 0,
    executor_type TEXT NOT NULL DEFAULT 'agent',
    parameters TEXT NOT NULL DEFAULT '{}',
    packet TEXT,
    blocks TEXT NOT NULL DEFAULT '[]',
    blocked_by TEXT NOT NULL DEFAULT '[]',
    result TEXT,
    created_at INTEGER NOT NULL,
    started_at INTEGER,
    completed_at INTEGER,
    team_id TEXT
);
CREATE INDEX idx_orch_tasks_status ON orchestration_tasks(status);
CREATE INDEX idx_orch_tasks_team ON orchestration_tasks(team_id);

-- Lane 表（执行单元）
CREATE TABLE IF NOT EXISTS orchestration_lanes (
    lane_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    agent_id TEXT,
    status TEXT NOT NULL DEFAULT 'created',
    created_at INTEGER NOT NULL,
    started_at INTEGER,
    completed_at INTEGER,
    worktree TEXT,
    heartbeat TEXT,
    error TEXT,
    permission_preset TEXT NOT NULL DEFAULT 'implement',
    metadata TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (task_id) REFERENCES orchestration_tasks(task_id) ON DELETE CASCADE
);
CREATE INDEX idx_orch_lanes_task ON orchestration_lanes(task_id);
CREATE INDEX idx_orch_lanes_status ON orchestration_lanes(status);

-- Lane 事件表
CREATE TABLE IF NOT EXISTS orchestration_lane_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    lane_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    agent_id TEXT,
    timestamp INTEGER NOT NULL,
    provenance TEXT NOT NULL DEFAULT 'system',
    metadata TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (lane_id) REFERENCES orchestration_lanes(lane_id) ON DELETE CASCADE
);
CREATE INDEX idx_orch_events_lane ON orchestration_lane_events(lane_id);
CREATE INDEX idx_orch_events_task ON orchestration_lane_events(task_id);

-- Team 表
CREATE TABLE IF NOT EXISTS orchestration_teams (
    team_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    task_ids TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    completed_at INTEGER
);
CREATE INDEX idx_orch_teams_status ON orchestration_teams(status);
```

### 4.4 核心协调层（`backend/orchestration/` 包 — 16 文件 4501 行）

| 文件 | 行数 | 核心类/函数 | 用途 |
|---|---|---|---|
| `__init__.py` | 2 | — | 包标记 |
| `task_registry.py` | 195 | `TaskRegistry` | Task CRUD + 依赖图查询（ready tasks = all blocked_by completed） |
| `lane_registry.py` | 219 | `LaneRegistry` | Lane CRUD + heartbeat + stale lane 检测 |
| `team_registry.py` | 175 | `TeamRegistry` | Team CRUD + task 关联 |
| `planner.py` | 295 | `Planner`, `Plan` | LLM-based task 分解（decompose_request），创建 Team + 多 Task + 依赖 |
| `router.py` | 325 | `Router`, `RoutingDecision`, `DispatchStrategy` | Task → Agent 路由（round_robin / capability_based / load_based），可选 PolicyEngine |
| `executor.py` | 492 | `LaneExecutor`, `LaneExecutionError` | Lane 生命周期管理（READY→RUNNING→terminal），permission 验证，event 记录，recovery 策略 |
| `heartbeat.py` | 110 | `HeartbeatMonitor` | 后台 worker，定期扫描 stale lanes |
| `lane_board.py` | 486 | `LaneBoard` | Lane 状态聚合 + 实时查询（list_lanes, get_lane_summary, board_stats） |
| `events.py` | 252 | `LaneEvent`(Enum), `LaneEventPayload`, `EventRecorder`, `EventStream` | Event 记录 + 查询 + NDJSON streaming |
| `permission.py` | 106 | `AgentAction`(Enum), `LanePermission`, `PermissionChecker`, `PermissionPreset` | Permission 校验（preset: implement/deploy/read_only） |
| `policy_engine.py` | 346 | `PolicyEngine`, `PolicyContext`, `PolicyDecisionEvent` | Typed policy decisions (M2) — 取代简单的 route_task |
| `approval_tokens.py` | 246 | `ApprovalTokenStore`, `ApprovalToken` | Privileged dispatch tokens (M2) |
| `ultragoal_store.py` | 606 | `UltragoalStore`, `Ultragoal`, `WorkerWriteDenied`, `DuplicateGoalId`, `GoalNotFound` | Director-only goal persistence + append-only ledger + checkpoint |
| `report_schema.py` | 248 | `ReviewReport`, `ProjectionRef`, `ReviewVerdict` | Executor 生成的 typed review report (M2) |

### 4.5 API Router (`backend/api/orchestration_router.py`)

**提供 4 个 REST endpoints**：

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/v1/orchestration/lanes` | 列出 lanes（可过滤 status, team_id, limit） |
| GET | `/api/v1/orchestration/lanes/{lane_id}` | 获取单 lane 详情 |
| GET | `/api/v1/orchestration/lanes/{lane_id}/events` | 获取 lane 事件流 |
| POST | `/api/v1/orchestration/lanes/{lane_id}/cancel` | 取消 lane |

**Response models**（Pydantic 2.x 语法，无需适配）：
- `LaneOut`, `LaneHeartbeatOut`, `LaneEventOut`, `CancelIn`

**Router 工厂**：`build_router() -> APIRouter` — 创建内部 `LaneRegistry` + `EventStream` 实例。

### 4.6 main.py 集成

在 `backend/main.py` lifespan 中挂载 `orchestration_router`（与 scheduler_router 同样模式）：

```python
from backend.api.orchestration_router import build_router as build_orchestration_router
app.include_router(build_orchestration_router())
```

## 5. Frontend 组件详细设计

### 5.1 页面 (`src/pages/Orchestration.tsx` — ~16 行)

```typescript
import { LaneBoard } from '../widgets/orchestration/LaneBoard';

export function Orchestration() {
  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-7xl mx-auto px-6 py-6">
        <h1 className="text-2xl font-semibold mb-6">Orchestration Board</h1>
        <LaneBoard />
      </div>
    </div>
  );
}
```

### 5.2 IPC Client (`src/shared/api/orchestrationClient.ts`)

4 个方法，通过 Electron preload 映射到 HTTP：

| IPC Channel | HTTP | 用途 |
|---|---|---|
| `orchestration_list_lanes` | GET `/api/v1/orchestration/lanes` | 列出 lanes |
| `orchestration_get_lane` | GET `/api/v1/orchestration/lanes/{id}` | 获取单 lane |
| `orchestration_list_lane_events` | GET `/api/v1/orchestration/lanes/{id}/events` | 获取事件 |
| `orchestration_cancel_lane` | POST `/api/v1/orchestration/lanes/{id}/cancel` | 取消 lane |

### 5.3 Zustand Store (`src/entities/orchestration/laneBoardStore.ts`)

**状态**：`lanes`, `loading`, `error`, `teamIdFilter`
**Actions**：`load(teamId?)`, `refresh()`, `cancel(laneId, reason?)`, `applyEvent(event)`, `computeBoard()`

**Board 分组逻辑**：
- `active`: `created | ready | running`
- `blocked`: `blocked`
- `finished`: `succeeded | failed | stopped | cancelled`

**Immutable updates**：所有 state 更新返回新对象，不 mutate 原 state。

### 5.4 LaneBoard Widget (`src/widgets/orchestration/LaneBoard.tsx`)

三列布局：Active | Blocked | Finished

每列渲染 `LaneCard`：
- 显示 lane_id, task_id, agent_id, status badge, heartbeat freshness
- 非终态 lane 显示"取消"按钮
- Status labels 已 i18n（中/英混合，main 实现如此）

### 5.5 路由注册

- `react-router-dom` 添加 `/orchestration` 路由
- Sidebar 添加 Orchestration 导航入口（可选，与 M3 一致的模式）

### 5.6 Electron IPC 注册

在 `electron/preload.ts` 和 `electron/main.ts` 中添加 4 个 IPC channels（与 M3 `scheduled_*` 同样模式）。

## 6. 数据流（关键场景）

### 6.1 用户提交 ultragoal

```
User submits ultragoal on Orchestration page
  → Orchestration.tsx.onSubmit(ultragoal)
  → orchestrationClient.submitUlagoal(...) [future API, not in current main]
  → Planner.decompose_request(ultragoal, context)
    → TeamRegistry.create_team(team)
    → TaskRegistry.create(task1), ..., TaskRegistry.create(taskN)
    → Task dependencies wired via blocked_by/blocks
  → Router.route_task(task) for each ready task
    → LaneRegistry.create(lane) for each task
    → DispatchStrategy selects agent
  → Executor.start(lane)
    → PermissionChecker.validate(lane.permission_preset)
    → EventRecorder.record(LaneEvent.STARTED)
    → lane.status = RUNNING
  → LaneBoard 实时刷新（via polling or SSE）
```

### 6.2 Lane 心跳 + 健康监控

```
Lane running in background
  → Agent sends heartbeat ping every 30s
  → LaneRegistry.update_heartbeat(lane_id, heartbeat)
  → HeartbeatMonitor scans every 60s
    → find_stale(max_age_secs=180)
    → For each stale lane:
      → EventRecorder.record(LaneEvent.FAILED, reason="heartbeat_timeout")
      → lane.status = FAILED
      → Apply RecoveryPolicy (retry/skip/abort-siblings/ask-human)
```

### 6.3 LaneBoard 实时聚合

```
Frontend laneBoardStore.load()
  → orchestrationClient.listLanes({ team_id })
  → HTTP GET /api/v1/orchestration/lanes?team_id=xxx
  → /api/v1/orchestration/lanes handler
    → LaneRegistry.list_by_status(...) + LaneBoard.aggregate()
  → return lanes[]
  → laneBoardStore.set({ lanes })
  → groupLanes(lanes) → { active, blocked, finished }
  → LaneBoard re-renders with 3 columns
```

## 7. 测试策略

### 7.1 单元测试（目标覆盖率 ≥80%）

| 文件 | 对应测试文件 | 主要测试场景 |
|---|---|---|
| `models.py` | `test_orchestration_models.py` | Task 状态转换 + Lane 状态转换 + Team 状态转换 |
| `task_registry.py` | `test_orchestration_e2e.py` (partial) | Task CRUD + 依赖图查询 + ready task 检测 |
| `lane_registry.py` | 同上 | Lane CRUD + heartbeat + stale 检测 |
| `planner.py` | `test_orchestrator_dispatch.py` | Task 分解 + Team 创建 |
| `router.py` | `test_orchestrator_dispatch.py` | round_robin + capability_based + load_based 路由 |
| `executor.py` | `test_orchestration_executor.py` | Lane 生命周期 + permission 验证 + recovery |
| `lane_board.py` | `test_lane_board.py` | 聚合查询 + 实时统计 |
| `events.py` | 同上 | Event 记录 + 查询 + NDJSON streaming |
| `permission.py` | 同上 | Permission preset 校验 |
| `policy_engine.py` | 同上 | Policy decision 生成 |
| `approval_tokens.py` | 同上 | Token 创建/验证/撤销 |
| `ultragoal_store.py` | 同上 | Director-only write + Worker write denied + ledger |
| `report_schema.py` | 同上 | ReviewReport schema 校验 |

### 7.2 集成测试

| 测试文件 | 场景 |
|---|---|
| `test_e2e_5lane_workflow.py` | 完整 5-lane workflow（ultragoal → planner → router → executor → terminal） |
| `test_routes_agents.py` | `/api/v1/orchestration/*` endpoints |
| `test_routes_agents_toggle.py` | Agent toggle + lane status 变化 |
| `test_routes_agents_update.py` | Agent metadata update |

### 7.3 Frontend 测试

| 文件 | 测试场景 |
|---|---|
| `laneBoardStore.test.ts` | load/refresh/cancel/applyEvent/computeBoard |
| `LaneBoard.test.tsx` | 渲染 3 列 + lane card + cancel 按钮 |
| `Orchestration.test.tsx` | Page mount + LaneBoard 集成 |

## 8. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| `backend/data/orchestration_repo.py` 601 行 import 链复杂 | 中 | M4 P1 延期 | 先跑 `pytest backend/tests/unit/test_orchestration_e2e.py` 验证 import 通 |
| `ultragoal_store.py` 606 行 + threading | 中 | 测试复杂 | byte-for-byte port + main 的 test 直接复用 |
| `policy_engine.py` + `approval_tokens.py` (M2 新增) 与基础 router 的耦合 | 低 | 集成问题 | Router 支持可选 `policy_engine` 和 `token_store`，None 时降级 |
| Electron IPC 4 新 channels 与 preload 现有 channels 冲突 | 低 | IPC 失败 | 每个 channel 名加 `orchestration_` 前缀 |
| 总工期 11 天（8 天 backend + 3 天 frontend）| 中 | 后续模块延期 | 可拆 M4a (P1-P3: core + registries) / M4b (P4-P5: policy + frontend) |

## 9. DoD 清单（M4）

- ✅ M4 design spec + impl plan 已 commit 到 `docs/superpowers/{specs,plans}/`
- ✅ `feat/win7-m4-orchestration` 分支 CI 绿
- ✅ backend: pytest 新增 tests 全过 + 不破坏已有 1192 tests
- ✅ frontend: vitest 新增 tests 全过 + 不破坏已有 399 tests + tsc 0 新错误
- ✅ DB migration: `orchestration_*` 4 张表 + 7 索引 已加入 `database.py`
- ✅ `backend/api/orchestration_router.py` 4 endpoints 可用
- ✅ `backend/main.py` 挂载 orchestration router
- ✅ Electron preload + main.ts 注册 4 个 IPC channels
- ✅ Sidebar 添加 Orchestration 导航入口
- ✅ Frontend `/orchestration` 路由 + Orchestration page 渲染
- ✅ code-review agent 通过（无 critical/high）
- ✅ 用户 review 通过
- ✅ CHANGELOG.md 已更新
- ✅ Memory: sage-m4-orchestration-merged.md 已创建

## 10. 实施步骤预览

### Phase 1: DB Schema + Persistence (P1, 1.5 天)
- `backend/data/database.py` 加 4 张 orchestration 表 + 7 索引
- Port `backend/data/orchestration_repo.py` (601 行) byte-for-byte
- Port 或复用 main 的 `test_data_blackboard_repo.py` 风格写 `test_orchestration_repo.py`
- 验证: `pytest backend/tests/unit/test_orchestration_repo.py`

### Phase 2: Core Models + Registries (P2, 2 天)
- Port `backend/orchestration/{models.py, __init__.py}` byte-for-byte
- Port `backend/orchestration/{task_registry.py, lane_registry.py, team_registry.py}` byte-for-byte
- Port main 的 `test_orchestration_models.py` byte-for-byte
- 验证: `pytest backend/tests/unit/test_orchestration_models.py`

### Phase 3: Planner + Router + Events (P3, 2 天)
- Port `backend/orchestration/{planner.py, router.py, events.py}` byte-for-byte
- Port main 的 `test_orchestrator_dispatch.py` byte-for-byte
- 验证: `pytest backend/tests/unit/test_orchestrator_dispatch.py`

### Phase 4: Executor + Heartbeat + LaneBoard (P4, 2 天)
- Port `backend/orchestration/{executor.py, heartbeat.py, lane_board.py}` byte-for-byte
- Port main 的 `test_orchestration_executor.py`, `test_lane_board.py` byte-for-byte
- 验证: `pytest backend/tests/unit/test_orchestration_executor.py test_lane_board.py`

### Phase 5: Policy + Ultragoal + Approval + Report + Permission (P5, 2 天)
- Port `backend/orchestration/{policy_engine.py, ultragoal_store.py, approval_tokens.py, report_schema.py, permission.py}` byte-for-byte
- Port main 的剩余 unit tests byte-for-byte
- 验证: 所有 backend/tests/unit/test_orchestration_* 全过

### Phase 6: API Router + main.py 集成 (P6, 1 天)
- Port `backend/api/orchestration_router.py` byte-for-byte
- 修改 `backend/main.py` 挂载 orchestration router
- Port main 的 `test_routes_agents.py`, `test_routes_agents_toggle.py`, `test_routes_agents_update.py` byte-for-byte
- 验证: `pytest backend/tests/integration/test_routes_agents*.py`

### Phase 7: Frontend + Electron IPC (P7, 2.5 天)
- Port 4 个 frontend 文件 byte-for-byte: `Orchestration.tsx`, `laneBoardStore.ts`, `orchestrationClient.ts`, `LaneBoard.tsx`
- 添加 `/orchestration` 路由到 react-router
- 添加 Sidebar 导航入口
- 添加 4 个 Electron IPC channels 到 preload.ts + main.ts
- 添加 frontend tests byte-for-byte
- 验证: `npm run test` 全过 + `npm run build` 成功

### Phase 8: CHANGELOG + Memory + Merge (P8, 0.5 天)
- CHANGELOG.md 更新 [Unreleased]
- Memory: sage-m4-orchestration-merged.md
- PR + code-review agent + 用户 review + merge

## 11. 参考

- 项目级 CLAUDE.md：`/home/fz/project/sage/.claude/CLAUDE.md`（双分支策略、Python 环境、测试要求）
- modules-rollout spec：`docs/superpowers/specs/2026-06-28-win7-modules-rollout-design.md`
- M3 spec（格式参考）：`docs/superpowers/specs/2026-06-28-win7-m3-scheduler-design.md`
- main orchestration 实现：`git ls-tree -r main --name-only -- backend/orchestration/`
- main 前端 orchestration：`src/pages/Orchestration.tsx`, `src/entities/orchestration/laneBoardStore.ts`, `src/shared/api/orchestrationClient.ts`, `src/widgets/orchestration/LaneBoard.tsx`
- 历史同步记录：`/home/fz/.claude/projects/-home-fz-project-sage/memory/sage-win7-sync-progress.md`
- main agent 设计文档：`docs/plans/2026-06-19_multi-agent-coordination.md`, `docs/plans/2026-06-22_agent-orchestrator-wiring.md`

---

**Spec 状态**：✅ 设计完成，待用户最终审阅后转入 writing-plans 阶段。

**下一步**：用户 review 本 spec 文件 → 确认后启动 M4 implementation plan。
