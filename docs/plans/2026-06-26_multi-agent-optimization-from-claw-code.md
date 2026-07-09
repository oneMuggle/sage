# 多智能体协作编排优化方案（参考 claw-code）

> **日期**: 2026-06-26
> **范围**: 基于 `/home/fz/project/claw-code` 的实际实现经验，对 `docs/plans/2026-06-19_multi-agent-coordination.md` 的增量优化建议
> **目标读者**: 多 Agent 协调层实现阶段的开发者

## 1. 背景

`docs/plans/2026-06-19_multi-agent-coordination.md` 已经给出了 **规划层(OmX) + 路由层(clawhip) + 执行层(claws)** 的三方架构，但停留在抽象接口层面。通过对 claw-code 的 Rust 实现做结构化分析，发现 sage 现有计划有几个**关键能力未覆盖**，同时 claw-code 自身也有几个**局限应当规避**。

本文档定位：**不替换 2026-06-19 计划，而是作为增量补充章节**，聚焦"claw-code 做对了什么 sage 应当借鉴"与"claw-code 做错了什么 sage 应当规避"。

## 2. claw-code 的亮点能力（sage 应当借鉴）

### 2.1 Lane 抽象（执行单元隔离）

claw-code 为每个执行单元引入 `Lane` 概念，独立生命周期、独立状态、独立事件流。sage 现有计划只有"Executor"，缺少执行层的细粒度隔离。

**借鉴方案**:
```python
# backend/orchestration/lane.py
class Lane:
    lane_id: str
    task_id: str
    agent_id: Optional[str]        # 绑定后填充
    status: LaneStatus             # Created/Ready/Running/Blocked/Succeeded/Failed/Stopped
    created_at: int
    heartbeat: Optional[LaneHeartbeat]
    worktree: Optional[str]        # 隔离的文件系统工作目录
    
class LaneStatus(Enum):
    CREATED = "created"
    READY = "ready"                # 依赖已满足，等待 agent
    RUNNING = "running"
    BLOCKED = "blocked"            # 等待外部条件（如人工审批）
    SUCCEEDED = "succeeded"        # 终态
    FAILED = "failed"              # 终态
    STOPPED = "stopped"            # 终态
```

**价值**: 
- 任务(task)与执行(lane)解耦 → 一个 task 失败可重建 lane 重试
- lane 是资源分配的边界（工作目录、agent 绑定、超时计时）
- 比"executor 直接改 task.status"更清晰

### 2.2 Heartbeat 监控（停滞检测）

claw-code 通过 `LaneHeartbeat` 追踪执行单元活跃度，检测"看起来在跑但实际已卡住"的任务。sage 现有计划**完全没提到停滞检测**。

**借鉴方案**:
```python
# backend/orchestration/heartbeat.py
class LaneHeartbeat:
    last_ping_at: int              # 上次活跃时间戳(ms)
    transport_alive: bool          # 与 agent 的通信通道是否健康
    status: HeartbeatStatus        # Healthy / Stalled / TransportDead
    
class HeartbeatMonitor:
    """每 30s 扫描一次所有 Running 的 lane"""
    stalled_after_secs: int = 300  # 5 分钟无 ping 视为 Stalled
    
    async def scan(self):
        for lane in self.registry.list_running():
            age = now_ms() - lane.heartbeat.last_ping_at
            if not lane.heartbeat.transport_alive:
                await self.mark(lane, HeartbeatStatus.TRANSPORT_DEAD)
            elif age > self.stalled_after_secs * 2:
                await self.mark(lane, HeartbeatStatus.TRANSPORT_DEAD)
                await self._recover(lane)  # 触发 recovery_policy
            elif age > self.stalled_after_secs:
                await self.mark(lane, HeartbeatStatus.STALLED)
```

**价值**:
- 避免"僵尸任务"无限期占用并发槽
- 为 recovery_policy 提供触发时机
- 与 chat-stream sweeper (`main.py:_periodic_stream_sweeper`) 机制对齐

### 2.3 LaneBoard 可视化（三分视图）

claw-code 的 `LaneBoard` 把所有 lane 分为 active/blocked/finished 三个桶，每个 entry 带 freshness 状态。sage 现有计划**没有前端可视化方案**。

**借鉴方案**:
```
┌──────────────────────────────────────────────────────────────┐
│  Active (3)          │  Blocked (1)         │  Finished (7)   │
├──────────────────────┼──────────────────────┼─────────────────┤
│ 🟢 scan-code        │ 🔒 gen-report        │ ✅ lint-fix     │
│   Running 2m ago    │   waiting: scan-code │ ✅ test-suite   │
│ 🟡 run-tests        │                      │ ❌ deploy-prod  │
│   Running 30s ago   │                      │ ⏹  cancel-build │
│ 🟢 build-docs       │                      │                 │
└──────────────────────────────────────────────────────────────┘
```

**前端实现**:
- 新增 Zustand store: `src/entities/orchestration/laneBoardStore.ts`
- 新增组件: `src/widgets/agents/LaneBoard.tsx`
- 通过现有的 NDJSON 事件流（`sage:listen`）实时推送 lane 状态变更
- 与现有 `useScheduledTaskStore` 风格一致

### 2.4 Lane 事件系统（完整生命周期）

claw-code 定义了细粒度的 lane 生命周期事件流。sage 计划的 Notification 抽象太粗。

**借鉴方案**:
```python
# backend/orchestration/events.py
class LaneEvent(str, Enum):
    # 执行生命周期
    STARTED = "lane.started"             # lane 创建
    READY = "lane.ready"                 # 依赖满足，等待调度
    RUNNING = "lane.running"             # agent 开始执行
    BLOCKED = "lane.blocked"             # 阻塞（等待外部条件）
    SUCCEEDED = "lane.succeeded"         # 成功完成
    FAILED = "lane.failed"               # 失败
    STOPPED = "lane.stopped"             # 被取消
    
    # Git 集成（如果支持）
    COMMIT_CREATED = "lane.commit.created"
    PR_OPENED = "lane.pr.opened"
    MERGED = "lane.merged"
    
    # 失败分类（关键！）
    # Provenance: PromptDelivery / TrustGate / BranchDivergence / Compile / Test

class LaneEventPayload(BaseModel):
    event: LaneEvent
    lane_id: str
    task_id: str
    agent_id: Optional[str]
    timestamp: int
    provenance: str              # "LiveLane" / "Recovery" / "Retry"
    metadata: Dict[str, Any]     # 失败原因、错误堆栈、恢复策略等
```

**价值**:
- 与现有 `chat-stream-{streamId}` NDJSON 对齐（lane 事件走同一通道）
- 失败分类为后续 recovery_policy 提供信号
- 前端可按 event 类型做差异化展示

### 2.5 TaskPacket 高级任务包（恢复/升级策略）

sage 计划的 Task 只有 `parameters: Dict[str, Any]`，缺少任务级别的恢复策略。claw-code 的 `TaskPacket` 把"任务该怎么执行"打包在一起。

**借鉴方案**:
```python
# backend/orchestration/task_packet.py
class TaskPacket(BaseModel):
    # 任务描述
    objective: str
    scope: List[str]                      # 允许修改的文件/目录
    acceptance_tests: List[str]           # 完成后必须通过的测试
    
    # 执行约束
    model: Optional[str]                  # 指定使用的 LLM
    permission_profile: str               # "read-only" / "workspace-write" / "full"
    timeout_secs: int = 600
    max_retries: int = 2
    
    # 失败处理
    recovery_policy: RecoveryPolicy       # 失败时怎么办
    escalation_policy: EscalationPolicy   # 解决不了怎么办
    
class RecoveryPolicy(BaseModel):
    on_failure: str                       # "retry" / "skip" / "abort-siblings" / "ask-human"
    retry_backoff_secs: List[int] = [30, 120, 600]
    
class EscalationPolicy(BaseModel):
    after_retries: str                    # "notify-human" / "mark-blocked" / "fail-fast"
    notify_channels: List[str] = []       # ["discord", "email"]
```

**价值**:
- 任务自带"失败该怎么办"的声明，而不是依赖全局默认
- 与 claw-code 的 Team 分组结合 → 复杂工作流的异常处理

### 2.6 Agent 权限预设（最小权限）

claw-code 把 agent 分为 `Audit` / `Explain` / `Implement` 三种预设，对应只读 / 只读 / 写权限。sage 现有 4 个 AgentProfile（primary/researcher/coder/memory_manager），但**权限模型只在数据层**，没有执行层隔离。

**借鉴方案**:
```python
# backend/orchestration/permission.py
class PermissionPreset(str, Enum):
    AUDIT = "audit"             # 只读：代码分析、测试运行
    EXPLAIN = "explain"         # 只读：文档生成、解释说明
    IMPLEMENT = "implement"     # 写：代码修改、文件创建

class LanePermission:
    preset: PermissionPreset
    allowed_paths: List[str]    # 相对于 worktree 的路径白名单
    denied_tools: List[str]     # 禁用的工具（如 "shell", "http_request"）
    
    def check(self, action: AgentAction) -> bool:
        """执行前校验"""
```

**价值**:
- lane 启动时注入权限 → agent 在执行中无法越权
- 与 TaskPacket.permission_profile 协同
- 为后续沙箱化（subprocess / docker）打基础

### 2.7 Team 分组（工作流编排）

claw-code 的 Team 把多个 task 组合为一个工作流单元。sage 计划没有这层抽象。

**借鉴方案**:
```python
# backend/orchestration/team.py
class Team:
    team_id: str
    name: str
    task_ids: List[str]              # 关联的 task
    status: TeamStatus               # Created / Running / Completed / Failed / Cancelled
    created_at: int
    metadata: Dict[str, Any]         # 触发源、关联 session、用户意图等

class TeamRegistry:
    """与 TaskRegistry 平级，管理 team-task 关系"""
    def create(self, name: str, task_ids: List[str]) -> Team: ...
    def list_teams(self, status: Optional[TeamStatus] = None) -> List[Team]: ...
    def get_team_tasks(self, team_id: str) -> List[Task]: ...
```

**价值**:
- 用户发起的"复杂请求"对应一个 team，team 包含多个 task
- team 是 Planner 的产出物（一个 plan 创建一个 team）
- 与前端 `useSessionStore` 的会话概念对齐（一个 session 可触发一个 team）

## 3. claw-code 的局限（sage 应当规避）

| claw-code 局限 | sage 的正确做法 |
|---|---|
| **顺序执行**：当前 `run_agents_inner` 是顺序链式 | ✅ 一开始就用 DAG 调度 + 并行（2026-06-19 计划已覆盖） |
| **无自动任务分解**：依赖外部调用方 | ✅ 集成 LLM 做智能分解（2026-06-19 计划已覆盖） |
| **无显式 blocks/blockedBy**：依赖关系只在 graph 层面，task 本身不感知 | ✅ 在 Task 字段中显式声明 `blocks: List[str]` 和 `blocked_by: List[str]`，查询更直接 |
| **内存存储**：TaskRegistry 无持久化，重启丢失 | ✅ 用 SQLite 持久化（已有 `backend/data/` 模式） |
| **无动态任务分配**：CLI 参数指定 agent | ✅ Router 基于 agent 能力 + 当前负载动态分配 |
| **单一工作区**：所有 agent 共享文件系统 | ✅ 每个 lane 一个 git worktree（或临时目录），避免并发冲突 |
| **事件不落盘**：Lane 事件仅内存广播 | ✅ 事件写 SQLite `lane_events` 表，支持重放与审计 |

## 4. 与现有计划的对照

| 维度 | 2026-06-19 计划 | claw-code 实现 | 本文档建议（增量） |
|---|---|---|---|
| 任务抽象 | Task(7 字段) | Task(12 字段 + TaskPacket) | **强化**：引入 TaskPacket + blocks/blocked_by 字段 |
| 执行单元 | Executor（无状态） | Lane（独立生命周期） | **新增**：Lane 抽象 + LaneStatus 状态机 |
| 依赖管理 | TaskGraph.dependencies | 无显式 | **新增**：Task 字段级 blocks/blocked_by |
| 状态追踪 | 4 状态 | 6 状态 | **强化**：增加 Blocked / Stopped |
| 停滞检测 | ❌ | Heartbeat（3 状态） | **新增**：HeartbeatMonitor + recovery_policy |
| 失败处理 | 全局 retry | recovery_policy / escalation_policy | **新增**：任务级声明式策略 |
| 权限隔离 | ❌ | 3 种 preset | **新增**：LanePermission + 执行时校验 |
| 可视化 | ❌ | LaneBoard（三分视图） | **新增**：前端 LaneBoard 组件 |
| 事件系统 | Notification（粗） | LaneEvent（细 + 失败分类） | **强化**：lane.* 事件 + provenance 标签 |
| 工作流分组 | ❌ | Team | **新增**：Team + TeamRegistry |
| 持久化 | 设计 DB schema | 内存 | **对齐**：SQLite + 重启恢复 |
| 并发控制 | asyncio.Semaphore(5) | 顺序执行 | **保持**：DAG + 并行（2026-06-19 计划已覆盖） |

## 5. 优先级排序（按价值/成本排序）

| 优先级 | 优化点 | 价值 | 实现成本 | 建议阶段 |
|---|---|---|---|---|
| **P0** | Lane 抽象 + LaneStatus 状态机 | 极高（解耦任务与执行） | 中 | Phase 1 |
| **P0** | SQLite 持久化 Task + Lane | 极高（重启恢复） | 中 | Phase 1 |
| **P0** | blocks/blocked_by 显式依赖 | 高（查询直接） | 低 | Phase 1 |
| **P1** | Heartbeat 停滞检测 | 高（避免僵尸任务） | 中 | Phase 2 |
| **P1** | LaneEvent 事件系统 | 高（可观测性） | 中 | Phase 2 |
| **P1** | TaskPacket + recovery_policy | 高（声明式失败处理） | 中 | Phase 2 |
| **P2** | Permission 预设 + 执行时校验 | 中（安全） | 中 | Phase 3 |
| **P2** | Team + TeamRegistry | 中（工作流分组） | 低 | Phase 3 |
| **P3** | LaneBoard 前端可视化 | 中（UX） | 中 | Phase 4 |
| **P3** | Lane worktree 隔离 | 低（当前 sage 非代码仓库编辑场景） | 高 | Phase 4+ |

## 6. 实施建议

### 6.1 分阶段合并到现有计划

**建议把本文档的优化点合并到 2026-06-19 计划的对应阶段**：

#### Phase 1（核心数据模型）增量
- ✅ 引入 Lane + LaneStatus 模型
- ✅ Task 增加 `blocks: List[str]` 和 `blocked_by: List[str]`
- ✅ TaskPacket 作为 Task 的高级载荷
- ✅ SQLite schema：`tasks`、`lanes`、`lane_events`、`teams`

#### Phase 2（规划层 + 路由层）增量
- ✅ Planner 输出 Team + TaskGraph（带 blocks/blocked_by）
- ✅ Router 在分发时创建 Lane，注入 Permission preset
- ✅ TaskRegistry 增加 HeartbeatMonitor

#### Phase 3（执行层）增量
- ✅ Executor 改造为 Lane 生命周期管理
- ✅ Lane 执行前校验 Permission
- ✅ Lane 失败时按 recovery_policy 处理
- ✅ 每个 Lane 事件写入 SQLite

#### Phase 4（可视化 + 集成）增量
- ✅ 新增 `LaneBoard.tsx` 前端组件
- ✅ 通过 NDJSON 事件流推送 lane 状态
- ✅ `laneBoardStore.ts` Zustand store

### 6.2 关键文件路径建议

```
backend/orchestration/
├── __init__.py
├── models.py                    # Task, TaskPacket, Lane, Team
├── task_registry.py             # SQLite 持久化（参考 backend/data/ 模式）
├── lane_registry.py             # Lane 生命周期管理
├── team_registry.py             # Team 分组管理
├── heartbeat.py                 # HeartbeatMonitor
├── events.py                    # LaneEvent + 事件持久化
├── permission.py                # PermissionPreset + LanePermission
├── planner.py                   # 2026-06-19 已规划
├── router.py                    # 2026-06-19 已规划
├── executor.py                  # 2026-06-19 已规划（改造为 Lane-aware）
└── scheduler.py                 # 2026-06-19 已规划（DAG 调度）

src/entities/orchestration/
├── types.ts                     # Lane, Task, Team TS 类型
├── laneBoardStore.ts            # Zustand store
└── __tests__/

src/widgets/agents/
├── LaneBoard.tsx                # 三分视图组件
├── LaneCard.tsx                 # 单个 lane 卡片
└── __tests__/
```

### 6.3 与现有模块的集成点

| 现有模块 | 集成方式 |
|---|---|
| `backend/services/scheduler.py` (Phase 8) | Lane 调度复用 APScheduler？或独立 asyncio task？建议独立，Phase 8 专注 cron 任务 |
| `backend/core/legacy/orchestrator.py` | 逐步迁移到新 executor，legacy 保留兼容 |
| `backend/data/*_repo.py` | task_registry / lane_registry 走同样的 SQLite repo 模式 |
| `electron/relay.ts` (NDJSON) | Lane 事件复用 NDJSON 通道推送前端 |
| `src/shared/lib/store.ts` | 新增 laneBoardStore，不污染全局 store |
| `backend/application/services/chat_service.py` | 用户聊天触发 Planner → 创建 Team + Lanes |

### 6.4 验证标准（补充 2026-06-19）

1. **重启恢复**：后端重启后，所有 Running 的 lane 能自动检测停滞并恢复
2. **失败隔离**：一个 lane 失败不会级联到兄弟 lane（除非 recovery_policy 声明 abort-siblings）
3. **可观测性**：LaneBoard 实时显示所有活跃/阻塞/完成的 lane
4. **权限校验**：audit preset 的 agent 无法写文件（测试用例覆盖）
5. **事件重放**：从 SQLite 读取 lane_events 重放任意 team 的完整历史

## 7. 总结

| 维度 | 结论 |
|---|---|
| **借鉴 claw-code 什么** | Lane 抽象、Heartbeat、LaneBoard、LaneEvent、TaskPacket、Permission preset、Team |
| **规避 claw-code 什么** | 顺序执行、无自动分解、内存存储、无显式依赖、无动态分配 |
| **与现有计划关系** | 增量补充 2026-06-19，不替换；分 4 个 phase 合并 |
| **优先级** | P0：Lane + SQLite + blocks/blocked_by；P1：Heartbeat + Events + TaskPacket；P2/P3：Permission / Team / 可视化 / worktree |

**下一步行动**:
1. 用户审阅本优化方案
2. 把 P0 项合并到 2026-06-19 计划的 Phase 1
3. 启动 Phase 1 实施（建议新分支 `feat/multi-agent-core`）

## 8. Phase 1 实施完成报告

**实施日期**: 2026-06-26  
**分支**: `feat/multi-agent-core`  
**测试覆盖**: 29/29 单元测试通过

### 已完成的文件

#### 核心数据模型
- `backend/orchestration/__init__.py` - 模块初始化
- `backend/orchestration/models.py` - Task, Lane, Team, TaskPacket, Heartbeat 等数据模型
  - TaskStatus: CREATED/RUNNING/BLOCKED/COMPLETED/FAILED/STOPPED
  - LaneStatus: CREATED/READY/RUNNING/BLOCKED/SUCCEEDED/FAILED/STOPPED
  - TeamStatus: CREATED/RUNNING/COMPLETED/FAILED/CANCELLED
  - TaskPacket: 包含 RecoveryPolicy 和 EscalationPolicy
  - LaneHeartbeat: 包含 HeartbeatStatus (HEALTHY/STALLED/TRANSPORT_DEAD)

#### SQLite 持久化层
- `backend/data/orchestration_repo.py` - 4 个 Repository 实现
  - TaskRepository: Task CRUD + 依赖查询（get_ready_tasks）
  - LaneRepository: Lane CRUD + heartbeat 更新
  - TeamRepository: Team CRUD + task 关联
  - LaneEventRepository: 事件追加 + 按 lane/task 查询
- `backend/data/database.py` - 新增 4 个表 schema
  - `orchestration_tasks`
  - `orchestration_lanes`
  - `orchestration_lane_events`
  - `orchestration_teams`

#### Registry 层
- `backend/orchestration/task_registry.py` - Task 生命周期管理
  - 依赖解析（get_ready_tasks）
  - 状态转换（mark_running/completed/failed/blocked/stopped）
  - 双向依赖关系维护（blocks/blocked_by）
- `backend/orchestration/lane_registry.py` - Lane 生命周期管理
  - Agent 绑定
  - Heartbeat 监控（get_stalled_lanes）
  - 状态转换
- `backend/orchestration/team_registry.py` - Team 管理
  - Task 关联（add_task/remove_task）
  - 进度聚合（get_team_progress）
  - 完成状态检测（is_team_completed/has_team_failed）

#### 事件系统
- `backend/orchestration/events.py` - Lane 事件记录与查询
  - LaneEvent: 生命周期事件枚举
  - EventProvenance: 事件来源分类（LiveLane/Recovery/Retry/Heartbeat/Manual）
  - EventRecorder: 事件持久化
  - EventStream: 事件查询 + 重放（replay_lane）

#### 单元测试
- `backend/tests/unit/test_orchestration_models.py` - 29 个测试用例
  - Task 状态转换（10 个）
  - Lane 状态转换（5 个）
  - Team 状态转换（7 个）
  - TaskPacket 配置（3 个）
  - Heartbeat 模型（2 个）
  - 状态机完整性（2 个）

### 与计划对照

| 计划项 | 状态 | 说明 |
|--------|------|------|
| Lane 抽象 + LaneStatus 状态机 | ✅ 完成 | 7 种状态，完整生命周期 |
| SQLite 持久化 Task + Lane | ✅ 完成 | 4 个表 + 4 个 Repository |
| blocks/blocked_by 显式依赖 | ✅ 完成 | TaskRegistry 自动维护双向关系 |
| Heartbeat 停滞检测 | ✅ 完成 | LaneRegistry.get_stalled_lanes() |
| Lane 事件系统 | ✅ 完成 | EventRecorder + EventStream |
| TaskPacket + recovery_policy | ✅ 完成 | 声明式失败处理策略 |

### 下一步

Phase 2 实施（规划层 + 路由层）：
- Planner: 任务分解 + Team 创建
- Router: Agent 分发 + Permission 注入
- 集成 HeartbeatMonitor 到 main.py lifespan
