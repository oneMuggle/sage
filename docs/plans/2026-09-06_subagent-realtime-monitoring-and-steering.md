# Subagent 实时监控与父 agent 注入方案

> 状态：草案（未授权实施）
> 日期：2026-09-06
> 触发需求：
> 1. 主 agent 能监测子 agent 并获取当前执行步骤内容
> 2. 主 agent 能向子 agent 追加信息
> 3. 用户点击运行中的 subagent 时能看到实时进程

---

## 一、背景与目标

### 1.1 当前能力

| 能力 | 现状 | 缺口 |
|---|---|---|
| 子 agent 派发 | `AgentTool` / `DispatchSubagentsTool` 已可用 | 中间 `AgentEvent` 被大量丢弃，主 agent 看不到细粒度进度 |
| 任务状态 | `ChatDispatcher` 派发 `task_status` / `task_progress` | 只描述 queued/running/done/failed，无 step 级内容 |
| 用户查看 | `TaskTreeSection` 展示任务列表 | 无点击展开实时详情、无事件时间线 |
| 追加信息 | `followup_of` 可继承已完成任务历史 | 无法对运行中任务追加上下文 |
| 编排事件 | `orchestration_lane_events` 表已存在 | 只有历史查询，无实时订阅、无单调递增序号 |
| 取消 lane | `POST /orchestration/lanes/{id}/cancel` | 只改 DB 状态，未连接真实执行句柄 |

### 1.2 目标

- **P0**：主 agent 可通过工具读取子 agent 的结构化运行快照（当前 phase、step、tool、iteration）
- **P0**：用户可在 UI 上点击 subagent 查看实时事件时间线，断线可重连
- **P1**：主 agent 可在 checkpoint 向子 agent 追加约束/澄清信息
- **P1**：用户可在 UI 上向等待中的子 agent 补充信息
- **P2**：暂停/恢复、人工审批、checkpoint 恢复等高级能力

### 1.3 非目标

- ❌ 子 agent 递归派发（保持默认禁止，只读白名单不开放 `agent` / `dispatch_subagents`）
- ❌ 暴露 chain-of-thought / 完整 prompt / 凭据给主 agent 或前端
- ❌ 引入 WebSocket（当前桌面单用户架构，NDJSON 足够）
- ❌ 替换 `ChatDispatcher`（复用其并发/依赖/重试/取消逻辑）

---

## 二、涉及的文件与模块

### 2.1 后端（Python）

| 模块 | 职责 | 改动类型 |
|---|---|---|
| `backend/orchestration/run_controller.py` | **新增**：Run 级控制面外观层 | 新建 |
| `backend/orchestration/subagent_runner.py` | 增加 `ProgressReporter` 回调，在 LLM 轮次/工具调用/步骤转换时生成结构化事件 | 修改 |
| `backend/orchestration/event_hub.py` | **新增**：内存 pub/sub，支持多 subscriber 广播 + sequence cursor | 新建 |
| `backend/orchestration/snapshot_store.py` | **新增**：Run/Task/Step 快照缓存与持久化 | 新建 |
| `backend/domain/orch_events.py` | **新增**：统一事件 envelope 定义 | 新建 |
| `backend/data/orch_events_repo.py` | **新增**：统一事件表 CRUD + sequence 分配 | 新建 |
| `backend/data/orch_steps_repo.py` | **新增**：Step 表 CRUD | 新建 |
| `backend/data/database.py` | 增加 `orch_events`、`orch_steps`、`orch_context_messages` 表 | 修改 |
| `backend/api/orch_run_control.py` | **新增**：REST 端点（snapshot / events stream / steer / cancel） | 新建 |
| `backend/api/chat_stream_registry.py` | 修正为广播模型（per-subscriber queue） | 修改 |
| `backend/api/orchestration_router.py` | `cancel_lane` 连接真实执行句柄 | 修改 |
| `backend/tools/observe_tool.py` | **新增**：`observe_subagents` 工具（仅对父 agent/conductor 开放） | 新建 |
| `backend/tools/steer_tool.py` | **新增**：`steer_subagent` 工具 | 新建 |
| `backend/tools/agent_tool.py` | 集成 ProgressReporter、execution handle 注册 | 修改 |
| `backend/tools/permissions.py` | 登记 `observe_subagents`（READ）和 `steer_subagent`（EXECUTE） | 修改 |

### 2.2 前端（TypeScript/React）

| 模块 | 职责 | 改动类型 |
|---|---|---|
| `src/entities/orchestration/runControlStore.ts` | **新增**：独立 Zustand store，管理 run/task/step 状态和订阅 | 新建 |
| `src/shared/api/orchEventStream.ts` | **新增**：NDJSON 实时订阅客户端（断线重连 + after_seq） | 新建 |
| `src/shared/api/orchRunControlClient.ts` | **新增**：REST 客户端（snapshot / steer / cancel） | 新建 |
| `src/shared/api/types.ts` | 增加 Run/Task/Step 事件类型 | 修改 |
| `src/widgets/chat/progress/SubagentDetailDrawer.tsx` | **新增**：点击 subagent 展开的详情面板 | 新建 |
| `src/widgets/chat/progress/TaskTreeSection.tsx` | 任务行增加点击事件，打开详情抽屉 | 修改 |
| `src/widgets/chat/progress/EventTimeline.tsx` | **新增**：事件时间线组件 | 新建 |
| `src/widgets/chat/progress/ContextInput.tsx` | **新增**：向子 agent 追加信息的输入组件 | 新建 |
| `electron/relay.ts` | 增加编排事件流 relay | 修改 |
| `electron/commands.ts` | 注册新的后端路由映射 | 修改 |

### 2.3 文档

| 文件 | 改动 |
|---|---|
| `docs/technical/42-chat-multi-agent-orchestration.md` | 更新架构描述，标注旧 conductor 语义为 superseded |
| `docs/technical/36-orchestration-e2e.md` | 更新 AgentTool 执行路径描述 |

---

## 三、技术方案

### 3.1 核心架构

```text
主 agent / ChatDispatcher
          │
          │ 创建、派发、追加上下文、取消
          ▼
      RunController ←── 统一控制面
          │
          ├── ExecutionCoordinator
          │       ├── SubagentRunner + ProgressReporter
          │       ├── LaneExecutor
          │       └── ExecutionHandle 注册表（cancel_event + asyncio.Task）
          │
          ├── SnapshotStore
          │       ├── orch_runs (status, revision, last_event_seq, owner_session_id)
          │       ├── orch_tasks (status, revision, current_step_id, waiting_reason)
          │       ├── orch_steps (step_id, kind, name, status, tool_name, previews)
          │       └── orch_context_messages (追加信息审计)
          │
          ├── EventHub (内存 pub/sub)
          │       ├── 多 subscriber 广播（修复 StreamRegistry 竞争消费）
          │       ├── run 内单调递增 sequence
          │       └── orch_events 表持久化
          │
          └── Permission/Ownership Guard
              ├── session_id 归属校验
              ├── 资源所有权检查
              └── 事件脱敏过滤
                          │
                          ▼
       REST snapshot + NDJSON 实时订阅
                          │
                          ▼
                Electron relay / React store
                          │
                          ▼
                 SubagentDetailDrawer
```

### 3.2 状态机

#### 3.2.1 Run 状态

```text
draft → queued → running → completed
                  │   ├── paused
                  │   ├── cancelling → cancelled
                  │   └── failed
                  └── (restart 后) recovery_required
```

| 状态 | 含义 |
|---|---|
| `draft` | 已生成计划，尚未执行，用户可修改 |
| `queued` | 等待调度资源 |
| `running` | 至少一个 task 正在执行 |
| `paused` | 暂停调度新任务 |
| `cancelling` | 已发出取消请求，等待 worker 退出 |
| `completed` | 所有任务终态 |
| `failed` | 不可恢复错误 |
| `cancelled` | 取消完成 |
| `recovery_required` | 进程重启后标记 |

#### 3.2.2 Task 状态

```text
planned → queued → running → succeeded / failed / cancelled
                  │   ├── waiting_input
                  │   ├── waiting_approval
                  │   ├── retrying
                  │   ├── cancelling
                  │   └── blocked
                  └── (restart 后) interrupted
```

#### 3.2.3 Step 状态

```text
pending → running → succeeded / failed / cancelled / skipped
                  │   ├── waiting_input
                  │   └── waiting_approval
```

每个 task 可有多个 step：

```text
task t1
  ├── step 1: prepare_context
  ├── step 2: call_tool:web_search
  ├── step 3: synthesize
  └── step 4: emit_result
```

### 3.3 统一事件协议

#### 3.3.1 Event Envelope

```python
@dataclass(frozen=True)
class RunEvent:
    event_id: str           # 全局唯一
    run_id: str
    seq: int                # run 内单调递增（断点续传）
    event_type: str
    occurred_at: int        # 毫秒时间戳（仅展示用）
    producer: str           # "chat-dispatcher" / "subagent-runner" / "user"
    producer_generation: int # 防旧 worker 迟到事件
    entity: dict            # {"task_id", "lane_id", "step_id", "agent_id"}
    payload: dict           # 事件专属数据
    visibility: str         # "user" | "internal" | "redacted"
    schema_version: str     # "run-events@1.0"
```

#### 3.3.2 事件类型清单

**Run 事件**：
```text
run.created / run.plan.updated / run.queued / run.started
run.paused / run.resumed / run.cancel_requested / run.cancelled
run.completed / run.failed / run.recovered
```

**Task 事件**：
```text
task.planned / task.queued / task.started / task.waiting_input
task.waiting_approval / task.retrying / task.succeeded / task.failed
task.cancel_requested / task.cancelled / task.blocked
```

**Step 事件**：
```text
task.step.created / task.step.started / task.step.progress
task.step.output_delta / task.step.waiting / task.step.completed
task.step.failed
```

**控制命令事件**：
```text
task.context.append_requested / task.context.appended
task.context_delivered / task.context_acknowledged
task.run_requested / task.cancel_requested
task.approval_requested / task.approval_resolved
```

**心跳**：高频心跳只通过实时通道发送，断线后从快照恢复。不默认持久化到事件表。

### 3.4 数据库 Schema

#### 3.4.1 `orch_runs`（扩展现有表）

```sql
ALTER TABLE orch_runs ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orch_runs ADD COLUMN owner_session_id TEXT;
ALTER TABLE orch_runs ADD COLUMN created_by TEXT;
ALTER TABLE orch_runs ADD COLUMN started_at INTEGER;
ALTER TABLE orch_runs ADD COLUMN finished_at INTEGER;
ALTER TABLE orch_runs ADD COLUMN cancel_requested_at INTEGER;
ALTER TABLE orch_runs ADD COLUMN last_event_seq INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orch_runs ADD COLUMN heartbeat_at INTEGER;
ALTER TABLE orch_runs ADD COLUMN execution_generation INTEGER NOT NULL DEFAULT 0;
```

#### 3.4.2 `orch_tasks`（扩展现有表）

```sql
ALTER TABLE orch_tasks ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orch_tasks ADD COLUMN parent_task_id TEXT;
ALTER TABLE orch_tasks ADD COLUMN current_step_id TEXT;
ALTER TABLE orch_tasks ADD COLUMN waiting_reason TEXT;
ALTER TABLE orch_tasks ADD COLUMN cancel_requested_at INTEGER;
ALTER TABLE orch_tasks ADD COLUMN last_event_seq INTEGER;
ALTER TABLE orch_tasks ADD COLUMN last_progress_at INTEGER;
```

#### 3.4.3 `orch_steps`（新增）

```sql
CREATE TABLE orch_steps (
    step_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    kind TEXT NOT NULL,          -- "llm_call" | "tool_call" | "synthesize" | "emit_result"
    name TEXT NOT NULL,
    status TEXT NOT NULL,        -- pending/running/waiting_input/succeeded/failed/cancelled/skipped
    input_summary TEXT,          -- 脱敏截断
    output_preview TEXT,         -- 脱敏截断
    tool_name TEXT,
    error_code TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    started_at INTEGER,
    finished_at INTEGER,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (run_id) REFERENCES orch_runs(run_id),
    FOREIGN KEY (task_id) REFERENCES orch_tasks(task_id)
);

CREATE INDEX idx_orch_steps_run_seq ON orch_steps(run_id, sequence);
CREATE INDEX idx_orch_steps_task_seq ON orch_steps(task_id, sequence);
CREATE INDEX idx_orch_steps_task_status ON orch_steps(task_id, status);
```

#### 3.4.4 `orch_events`（新增统一事件表）

```sql
CREATE TABLE orch_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    task_id TEXT,
    lane_id TEXT,
    step_id TEXT,
    agent_id TEXT,
    occurred_at INTEGER NOT NULL,
    producer TEXT NOT NULL,
    producer_generation INTEGER NOT NULL,
    payload TEXT NOT NULL,       -- JSON
    visibility TEXT NOT NULL,    -- "user" | "internal" | "redacted"
    command_id TEXT,             -- 幂等 key
    schema_version TEXT NOT NULL DEFAULT 'run-events@1.0',
    FOREIGN KEY (run_id) REFERENCES orch_runs(run_id),
    UNIQUE(run_id, seq),
    UNIQUE(command_id) WHERE command_id IS NOT NULL
);

CREATE INDEX idx_orch_events_run_seq ON orch_events(run_id, seq);
```

#### 3.4.5 `orch_context_messages`（新增）

```sql
CREATE TABLE orch_context_messages (
    context_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    source TEXT NOT NULL,        -- "user" | "parent_agent" | "system"
    content_redacted TEXT NOT NULL,  -- 脱敏后内容
    created_at INTEGER NOT NULL,
    created_by TEXT,
    applied_at INTEGER,
    applied_step_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending/delivered/acknowledged/rejected
    FOREIGN KEY (run_id) REFERENCES orch_runs(run_id),
    FOREIGN KEY (task_id) REFERENCES orch_tasks(task_id)
);
```

### 3.5 实时订阅协议

```text
GET /api/v1/orch/runs/{run_id}/events?after_seq=42
Accept: application/x-ndjson
```

行为：
1. 先发送当前 `run.snapshot` 事件
2. 再发送 `after_seq` 之后的历史事件
3. 新事件到达后持续发送
4. 定期发送 heartbeat（30s 间隔）
5. 断线后客户端带上最后 `seq` 重连
6. 若事件已被清理，返回 `410` 或 `resync_required`，客户端重新拉快照

### 3.6 主 agent 观测工具

新增 `observe_subagents` 工具，仅对父 agent/conductor 开放：

```json
{
  "run_id": "run-1",
  "task_ids": ["task-1", "task-2"],
  "after_sequence": 38,
  "include": ["snapshot", "recent_events"],
  "limit": 20
}
```

返回：

```json
{
  "run_id": "run-1",
  "status": "running",
  "summary": {"total": 4, "queued": 1, "running": 2, "succeeded": 1, "failed": 0},
  "tasks": [
    {
      "task_id": "task-1",
      "agent_id": "researcher",
      "status": "running",
      "current_step": {"step_id": "s1", "name": "调用 web_search", "status": "running"},
      "last_progress_at": 1760000000100
    }
  ],
  "recent_events": [...]
}
```

安全约束：
- 只能访问当前 session、当前 run 的子任务
- 服务端验证调用者确实是父 conductor
- 不返回 chain-of-thought、完整 prompt、凭据

### 3.7 父 agent 注入信息

新增 `steer_subagent` 工具：

```json
{
  "run_id": "run-1",
  "task_id": "task-1",
  "message_type": "constraint",
  "content": "优先使用官方文档，忽略 2024 年以前的资料。",
  "apply_mode": "next_boundary"
}
```

`message_type` 可选值：`constraint` / `clarification` / `additional_context` / `correction` / `priority_update` / `reference`

`apply_mode` 可选值：
- `next_boundary`（默认）：下一个 LLM 调用前、工具完成后、进入下一步骤前
- `new_followup`：当前 task 完成后创建 follow-up task

REST 接口：

```text
POST /api/v1/orch/runs/{run_id}/tasks/{task_id}/steer
```

并发控制：
- 追加信息必须携带 `expected_task_revision`
- 服务端 CAS 更新，版本不一致返回 `409 task_state_changed`

安全约束：
- 不能提升权限
- 不能开放工具
- 不能绕过审批
- 不能改变 workspace 根目录
- 单条长度上限 8 KB
- task/run 总上下文大小上限

### 3.8 前端详情面板

#### 3.8.1 SubagentDetailDrawer 结构

```text
┌─────────────────────────────────────────────┐
│ 🔬 researcher (task-1)          [running] ◐ │
│ 迭代: 3/6 │ 耗时: 00:02:15 │ 重试: 0      │
├─────────────────────────────────────────────┤
│ 当前步骤                                     │
│ ├─ 调用 web_search                          │
│ │  status: running                          │
│ │  started: 2 秒前                          │
├─────────────────────────────────────────────┤
│ 事件时间线                                   │
│ ├─ 10:23:01  step.completed: prepare_context│
│ ├─ 10:23:02  step.started: web_search       │
│ ├─ 10:23:03  step.progress: 已找到 5 条结果 │
│ └─ ...                                      │
├─────────────────────────────────────────────┤
│ 追加信息                                     │
│ ┌─────────────────────────────────────────┐ │
│ │ 输入补充信息...                          │ │
│ └─────────────────────────────────────────┘ │
│ [发送]                                       │
├─────────────────────────────────────────────┤
│ 父 agent 注入消息                            │
│ ├─ constraint: 优先使用官方文档 [✓ delivered]│
│ └─ clarification: 关注中文资料 [✓ delivered] │
└─────────────────────────────────────────────┘
```

#### 3.8.2 runControlStore

独立 Zustand store，不塞进 `chatStreamStore`：

```typescript
interface RunControlState {
  runs: Map<string, RunSnapshot>;
  selectedRunId: string | null;
  snapshotsByRunId: Map<string, RunSnapshot>;
  tasksByRunId: Map<string, TaskSnapshot[]>;
  stepsByTaskId: Map<string, StepSnapshot[]>;
  lastSeqByRunId: Map<string, number>;
  connectionStatus: 'connecting' | 'connected' | 'disconnected' | 'resyncing';
  pendingCommands: Map<string, CommandStatus>;
}
```

事件 reducer：
- 根据 `run_id` 路由
- 根据 `seq` 去重
- 丢弃旧事件
- 检测 seq gap → 自动重新拉 snapshot + `after_seq`
- 未知事件保留通用日志，不抛异常

#### 3.8.3 实时输出节流

- 后端事件可按 50-100ms 批量
- 前端 `requestAnimationFrame` 或 100ms throttle 合并
- 永久保存只保存 preview 和最终结果
- 原始增量只在当前订阅存在时保留内存
- 前端设置最大缓冲区（1000 事件）

---

## 四、实施步骤

### Phase 0：安全前置 + 契约统一（预计 2-3 天）

- [ ] 为 run/lane API 增加 `owner_session_id` 归属校验
- [ ] 修正 `StreamRegistry` 为广播模型（per-subscriber queue）
- [ ] 修正 `cancel_lane` 连接真实执行句柄
- [ ] 修正 `interrupt_run` 跨线程竞态（使用 `loop.call_soon_threadsafe`）
- [ ] 修正 `LaneBoardBuilder.last_event_at` 读取真实最后事件
- [ ] 统一 `cancelled` / `stopped` / `done` 终态语义
- [ ] 定义事件 envelope schema 和状态机
- [ ] 编写状态机合法/非法转移测试

**验收**：
- 同一 run 内事件严格可排序
- 重复 cancel/start 不会重复执行
- 旧 worker 不能覆盖新状态
- session A 无法读取 session B 的 run/lane

### Phase 1：后端只读可观测性（预计 3-4 天）

- [ ] 实现 `RunController` 外观层
- [ ] 实现 `EventHub` 内存 pub/sub
- [ ] 实现 `SnapshotStore`
- [ ] 扩展 `SubagentRunner` 集成 `ProgressReporter`
- [ ] 新建 `orch_events` / `orch_steps` 表
- [ ] 实现 `GET /orch/runs/{id}/snapshot`
- [ ] 实现 `GET /orch/runs/{id}/events?after_seq=N`（NDJSON 流）
- [ ] 实现 `observe_subagents` 工具
- [ ] 实现 Electron relay 订阅
- [ ] 编写事件序号单调性、subscriber 广播、断线重连测试

**验收**：
- 主 agent 可读取子 agent 结构化快照
- 多 subscriber 收到完全相同、顺序一致的事件
- 断线后按 `after_seq` 补齐事件
- 慢 subscriber 不阻塞其他 subscriber 或 worker

### Phase 2：前端实时详情面板（预计 3-4 天）

- [ ] 实现 `runControlStore`
- [ ] 实现 `orchEventStream` NDJSON 客户端
- [ ] 实现 `SubagentDetailDrawer`
- [ ] 实现 `EventTimeline` 组件
- [ ] `TaskTreeSection` 任务行增加点击事件
- [ ] 实现断线重连和 seq gap 处理
- [ ] 实现实时输出节流
- [ ] 编写前端 reducer、断线恢复、乱序事件测试

**验收**：
- 用户点击 subagent 可看实时进程
- 断线重连后仍能看到当前 task/step
- 离开聊天页后 Run Console 仍可见
- cancelled 任务不再显示为 running

### Phase 3：父 agent 注入信息（预计 2-3 天）

- [x] 新建 `orch_context_messages` 表（database.py DDL + PRAGMA 幂等迁移）
- [x] 实现 `POST /orch/runs/{id}/tasks/{tid}/steer`（orch_run_control.py）
- [x] 实现 CAS revision（SnapshotStore 内存 revision 作权威基准；DB `orch_tasks.revision` 作为 steer 次数审计痕迹，由 `bump_revision_for_steer` 在 steer 成功时累加）
- [x] 实现 `ContextInput` 前端组件 + 集成到 `SubagentDetailDrawer`
- [x] 编写注入投递、ACK、并发冲突测试（test_orch_context_repo.py 22 用例 + test_orch_run_control_steer.py 16 用例，全部通过）
- [x] 端点安全加固（code-review + security-review 反馈）：
  - 强制 CAS：`expected_task_revision` 必传，缺失返回 400 `missing_expected_task_revision`
  - 锁内原子检查：terminal-check + CAS-check + INSERT 同一 `SnapshotStore._lock` 内完成（TOCTOU 闭合）
  - 滑动窗口限流：10 req/60s per (run_id, task_id)，超限 429
  - JSON 解析失败不再泄露原始异常，返回固定 `invalid_json`
  - SQLite CHECK 约束（defense-in-depth）
  - steer 控制事件 producer_generation 与 task 当前值对齐，防止被 SnapshotStore "旧 worker 不覆盖新状态" 规则丢弃

**验收**：
- 主 agent 可向运行中 task 追加信息
- 追加信息在下一边界生效
- 并发追加触发 `409` 而非静默覆盖
- 追加内容不提升权限、不绕过审批

### Phase 4：高级能力（预计 3-5 天，可选）

- [ ] 实现 `paused` / `waiting_input` / `waiting_approval` 状态
- [ ] 实现用户手动运行/暂停/恢复
- [ ] 实现 execution lease 防双重执行
- [ ] 实现进程重启后 `recovery_required` 标记
- [ ] 实现 stale worker 检测
- [ ] 编写故障恢复、双重执行防护测试

**验收**：
- 用户点击一次只创建一个 execution
- 页面刷新后仍能继续查看
- backend 重启后 running task 被标记为 interrupted

---

## 五、风险评估与依赖

### 5.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| SQLite 高并发写入性能 | 事件吞吐可能成为瓶颈 | WAL 模式 + 事务内分配 seq + 内存 buffer 批量写入 |
| 进程重启丢失内存状态 | subscriber 断线、execution handle 丢失 | 持久化 run/task 状态 + `recovery_required` 标记 |
| `ChatDispatcher` 职责膨胀 | 维护复杂度增加 | 用 `RunController` 外观层隔离，不直接修改 dispatcher 核心逻辑 |
| 旧文档误导 | 开发者混淆 | Phase 0 标记旧文档为 superseded |
| 事件脱敏遗漏 | 泄露凭据/prompt | 定义 `visibility` 过滤层 + 安全审计 |

### 5.2 依赖

- 现有 `ChatDispatcher` 并发/依赖/重试/取消逻辑
- 现有 `orch_runs` / `orch_tasks` / `orchestration_lane_events` 表
- 现有 `Electron relay` NDJSON 机制
- 现有 `LaneBoardStore` Zustand 模式
- 现有 `SubagentRunner` 执行路径

### 5.3 不在范围内

- ❌ 子 agent 递归派发
- ❌ WebSocket 双向通信
- ❌ 多进程/多机器部署（当前桌面单用户）
- ❌ 跨 session 任务共享
- ❌ 完整 prompt / chain-of-thought 暴露

---

## 六、测试计划

### 6.1 后端测试

| 类别 | 测试项 |
|---|---|
| 状态机 | 所有合法转移；非法转移被拒绝；双击 start 只启动一次；restart 后 running → recovery_required |
| 事件协议 | seq 单调递增；event_id 幂等；seq gap 触发 resync；慢 subscriber 不阻塞 worker |
| 并发 | 同一 task 不能双重执行；retry/cancel 竞争；多 session 不能互相读写 |
| 安全 | 无 owner 访问返回 403/404；追加 context 不能修改权限；事件中不出现 token |
| 取消 | queued/running/completed 三种时机取消；取消与成功同时发生终态唯一；跨线程取消安全 |

### 6.2 前端测试

| 类别 | 测试项 |
|---|---|
| reducer | 按 run_id 路由；按 seq 去重；seq gap 触发 resync；未知事件不抛异常 |
| 断线恢复 | 断线后按 after_seq 恢复；乱序事件不回退状态 |
| 交互 | 运行按钮双击只发一个命令；context 提交成功 resume 失败输入不丢失 |
| 可见性 | 离开聊天页后 Run Console 仍可见；cancelled 任务不显示为 running |

### 6.3 E2E 测试

- 主 agent 派发子 agent → 用户在详情面板看到实时 step
- 用户向等待中的子 agent 追加信息 → 子 agent 接收并继续
- 用户取消运行中的子 agent → 状态正确收敛
- 断线重连 → 事件补齐，状态一致

---

## 七、关键取舍说明

| 决策 | 理由 |
|---|---|
| 复用 `ChatDispatcher`，不新建执行器 | 已有并发/依赖/重试/取消/worktree，避免两套语义 |
| SQLite WAL，不引 Redis/NATS | 桌面单用户，无新增基础设施需求 |
| NDJSON + `after_seq`，不引 WebSocket | 现有 relay 成熟，单向事件+REST 命令足够 |
| 只持久化 step preview，不保存完整输出 | 降低 SQLite 膨胀，减少敏感信息泄露 |
| 追加信息默认下一边界生效，不打断 | 打断引入 LLM 中断一致性、工具半执行状态等复杂问题 |
| 独立 `runControlStore`，不塞进 `chatStreamStore` | 用户离开聊天页后仍需查看 run 状态 |

---

## 八、与现有规则的关系

- **不修改 `release/win7` 分支**：本方案只针对 main 分支，Win7 LTS 维护分支独立演进
- **Python 环境**：后端测试使用 `/home/fz/anaconda3/envs/sage-backend/bin/python`
- **分支策略**：非小改动先建 `feat/subagent-realtime-monitoring` feature 分支
- **测试要求**：TDD，先测试再实现，覆盖率 ≥80%
- **代码审查**：实现后调用 code-reviewer；涉及权限/文件/网络时调用 security-reviewer
- **敏感信息**：不在事件 payload、日志、UI 中暴露 token、API key、Authorization、完整 prompt
