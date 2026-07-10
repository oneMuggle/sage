---
name: win7-m3-scheduler
description: win7 M3 Scheduler 模块设计 — byte-for-byte port main 的简单 scheduler (用户定时消息)
metadata:
  type: spec
  status: design
  author: brainstorm-session-2026-06-28
  related_specs:
    - 2026-06-28-win7-modules-rollout-design.md
    - 2026-06-28-win7-m2-theme-editor-design.md
  related_plans:
    - 2026-06-25-phase8-scheduled-tasks.md (main 的 phase 8 实施计划,本 spec 的参考源)
---

# win7 M3 Scheduler Design Spec

## 1. Goal

将 `main` 分支的**简单 scheduler 模块**（用户定时消息功能）byte-for-byte port 到 `release/win7` 分支，让 win7 用户获得与 main 完全一致的定时任务体验。

**范围边界**：

| 包含 | 不包含 |
|---|---|
| 用户创建的 once/recurring 定时消息 | main 的 `scheduler/evolution.py` AI 进化任务（866 行，涉及 memory_manager，留作后续模块） |
| `services/scheduler.py` + `api/scheduled_router.py` |  |
| 前端 5 核心组件 + Sidebar CronJobSection + ChatInput 定时按钮 |  |

**不在本 spec 范围**：

- AI 进化任务（DailySummaryTask、MemoryConsolidationTask 等） — 属于后续模块（可能并入 M4 Orchestration）
- `scheduler/cron.py` 的 `EvolutionScheduler` — 同上
- 定时任务的 LLM 流式响应 — 当前定时消息走 `message_repo.insert`（系统消息角色），不触发 LLM

## 2. Win7 上下文

### 2.1 关键事实（已验证 2026-06-28）

| 项 | 实际状态 | 与 CLAUDE.md 的差异 |
|---|---|---|
| 后端 Python 版本 | **3.10.20**（sage-backend env） | CLAUDE.md 写"Python 3.8 + pydantic 1.x" — **实际不符** |
| pydantic 版本 | **2.13.4** | 同上，实际是 pydantic 2.x |
| sage-backend-py38 env | **不存在** | 仅 `sage-backend` 一个 env |
| APScheduler | **3.10.4** ✅ 已安装 | — |
| croniter | ✅ 已安装 | — |
| 前端 i18n（M1） | ✅ 已实现：`src/shared/lib/i18n/{index.tsx,zh.ts,en.ts,formatMessage.ts,useLocaleStore.ts}` | — |

**结论**：win7 后端环境与 main 完全一致（py3.10 + pydantic 2.x），可 byte-for-byte port 无需 pydantic 1.x 适配。

### 2.2 M2 P4 已验证路径

M2 P4（主题编辑器 rework）采用 byte-for-byte port 策略：
- 从 main git 直接复制 ~20 个文件
- 仅做 i18n key 适配（12 个 M2 键删除，13 个 main 键加入）
- 单分支 `feat/win7-theme-editor-p4`，6 commits
- 结果：tsc 0 新错误，vitest 352/352，pytest 1150+

M3 沿用同一路径。

## 3. 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│ Frontend (React 18 + Vite + TypeScript)                      │
├──────────────────────────────────────────────────────────────┤
│  ScheduledTasks page ─── taskStore (Zustand)                  │
│       │                       │                              │
│  CronJobSection sidebar       │ scheduledClient (IPC)        │
│       │                       │                              │
│  ChatInput [定时] btn         │                              │
└───────────────────────────────┼──────────────────────────────┘
                                │ Electron IPC / preload
                                ▼
┌──────────────────────────────────────────────────────────────┐
│ Backend (FastAPI + Python 3.10)                              │
├──────────────────────────────────────────────────────────────┤
│  /api/v1/scheduled/*  (scheduled_router.py)                  │
│       │                                                      │
│       ▼                                                      │
│  SchedulerService (services/scheduler.py)                    │
│       │                                                      │
│       ├─ APScheduler BackgroundScheduler (in-process)        │
│       └─ JSON persistence (scheduled_tasks.json, atomic)     │
│              │                                               │
│              ▼                                               │
│       _fire() → message_repo.insert() → 目标 session         │
└──────────────────────────────────────────────────────────────┘
```

**核心职责**：

- **SchedulerService** — APScheduler 包装 + JSON 持久化 + 线程安全
- **scheduled_router** — REST API（CRUD + run-now）
- **taskStore** — Zustand 状态，IPC 调用
- **UI components** — CronExpressionPicker（cron 编辑）+ CreateTaskModal（创建/编辑）+ ScheduledTasks page（列表）
- **Sidebar/ChatInput** — 快捷入口

**技术栈**：

- Backend: APScheduler 3.10.4 + croniter + pydantic 2.x
- Frontend: Zustand 4.4.7 + sonner（toast）+ lucide-react（icons）
- 存储：`backend/data/scheduled_tasks.json`（UTC epoch ms，atomic write）
- 时间：存 UTC epoch ms，前端 `Intl.DateTimeFormat()` 显示本地时间

## 4. Backend 组件

### 4.1 `backend/services/scheduler.py`（377 行，byte-for-byte from main）

**核心接口**：

```python
class SchedulerService:
    def __init__(store_path: Path, message_repo: Any, session_repo: Any)
    def list_tasks() -> list[ScheduledTask]
    def get_task(task_id: str) -> ScheduledTask
    def add_task(name, task_type, schedule, session_id, content) -> ScheduledTask
    def update_task(task_id: str, **changes) -> ScheduledTask
    def delete_task(task_id: str)
    def run_now(task_id: str)                  # 立即触发
    def start() / shutdown() / is_running()

@dataclass
class ScheduledTask:
    id: str
    name: str
    type: Literal["once", "recurring"]
    schedule: dict[str, Any]       # {kind: "once", at: ms} | {kind: "recurring", cron: str}
    session_id: str
    content: str
    enabled: bool
    created_at: int
    last_run: int | None = None
    next_run: int | None = None

class TaskNotFoundError(KeyError): ...
class ValidationError(ValueError): ...

def get_scheduler_service() -> SchedulerService | None
def init_scheduler_service(store_path, message_repo, session_repo) -> SchedulerService
```

**关键行为**：

- **持久化**：`{version: 1, tasks: [...]}` JSON，atomic write（tmp + os.replace）
- **线程安全**：`threading.Lock` 保护所有 JSON 读写
- **触发机制**：`_fire()` → `message_repo.insert(session_id, role='system', content=task.content, created_at=now)`
- **一次性任务**：触发后自动 `enabled=False` + `remove_job`
- **周期性任务**：触发后更新 `last_run` + 计算新 `next_run`
- **异常处理**：`_fire()` 内异常只 log，不抛到 APScheduler loop
- **启动恢复**：`__init__` 调用 `_load_from_disk()` + `_reschedule_all()`

### 4.2 `backend/api/scheduled_router.py`（166 行）

**Endpoints**：

| Endpoint | Method | 描述 | 错误 |
|---|---|---|---|
| `/api/v1/scheduled/health` | GET | 健康检查 | — |
| `/api/v1/scheduled/tasks` | GET | 列出所有任务 | — |
| `/api/v1/scheduled/tasks` | POST | 创建任务 | 422 (bad cron/past at/missing session) |
| `/api/v1/scheduled/tasks/{id}` | PATCH | 更新 name/enabled | 404 (missing) / 422 (validation) |
| `/api/v1/scheduled/tasks/{id}` | DELETE | 删除任务 | 404 |
| `/api/v1/scheduled/tasks/{id}/run` | POST | 立即执行 | 404 |

**关键设计**：

- **Factory 模式**：`build_router(get_service: Callable[[], SchedulerService | None])` — 注入 service getter，便于测试 mock
- **Pydantic models**：ScheduleIn/Out, CreateTaskIn, UpdateTaskIn, TaskOut
- **错误映射**：`TaskNotFoundError` → 404, `ValidationError` → 422

### 4.3 `backend/main.py` lifespan 集成

```python
# startup（在 app.state.db = db 之后）
store_path = Path("backend/data/scheduled_tasks.json")
scheduler_service = init_scheduler_service(
    store_path=store_path,
    message_repo=MessageRepository(),
    session_repo=SessionRepository(),
)
scheduler_service.start()
app.state.scheduler = scheduler_service
app.include_router(
    build_scheduled_router(get_scheduler_service),
    prefix="/api/v1",
)

# cleanup（yield 之后）
if hasattr(app.state, "scheduler") and app.state.scheduler is not None:
    app.state.scheduler.shutdown()
```

### 4.4 依赖

| 文件 | 改动 |
|---|---|
| `backend/requirements.txt` | 加 `apscheduler==3.10.4`（main 已加） |
| `backend/requirements-py38.txt` | 同步加 `apscheduler==3.10.4`（保持双 deps 一致，per CLAUDE.md 双分支策略） |

**注**：虽然 py38 env 实际不存在，但保持 `requirements-py38.txt` 与 `requirements.txt` 同步是双分支策略的约束。

## 5. Frontend 组件

### 5.1 类型与基础设施

**`src/shared/api/types.ts`** — 追加 ScheduledTask 类型：

```typescript
export type ScheduleKind = 'once' | 'recurring';

export type Schedule =
  | { kind: 'once'; at: number }
  | { kind: 'recurring'; cron: string };

export interface ScheduledTask {
  id: string;
  name: string;
  type: ScheduleKind;
  schedule: Schedule;
  session_id: string;
  content: string;
  enabled: boolean;
  last_run?: number | null;
  next_run?: number | null;
  created_at: number;
}

export interface CreateTaskInput {
  name: string;
  type: ScheduleKind;
  schedule: Schedule;
  session_id: string;
  content: string;
}

export interface UpdateTaskInput {
  name?: string;
  enabled?: boolean;
}
```

**`src/features/scheduled/cronValidator.ts`** — 纯函数（无 deps）：

- `validateCronExpression(input: string): ValidationResult` — 5-field cron 验证，支持 `*`、列表、范围、步长
- `validateOneShotTimestamp(atMs: number): ValidationResult` — 未来时间验证
- `describeSchedule(schedule, locale): string` — 人类可读描述（用 `Intl.DateTimeFormat`）
- `CRON_PRESETS: readonly CronPreset[]` — 6 个预设：hourly, daily-08, daily-18, weekday-09, weekly-mon, monthly-1st

### 5.2 IPC Client + Store

**`src/shared/api/scheduledClient.ts`**：

```typescript
export const scheduledClient = {
  list(): Promise<ScheduledTask[]>
    → invoke('scheduled_list_tasks', {})
  create(input: CreateTaskInput): Promise<ScheduledTask>
    → invoke('scheduled_create_task', { input })
  update(id: string, changes: UpdateTaskInput): Promise<ScheduledTask>
    → invoke('scheduled_update_task', { id, changes })
  delete(id: string): Promise<void>
    → invoke('scheduled_delete_task', { id })
  runNow(id: string): Promise<ScheduledTask>
    → invoke('scheduled_run_task', { id })
}
```

**`src/entities/scheduled/taskStore.ts`**（Zustand）：

```typescript
interface ScheduledTaskState {
  tasks: ScheduledTask[];
  loading: boolean;
  error: string | null;
  load(): Promise<void>;
  create(input: CreateTaskInput): Promise<ScheduledTask>;
  update(id: string, changes: UpdateTaskInput): Promise<ScheduledTask>;
  delete(id: string): Promise<void>;
  runNow(id: string): Promise<ScheduledTask>;
}
```

### 5.3 UI 组件

**`src/features/scheduled/CronExpressionPicker.tsx`**：

- 6 个 preset chips（点击选中，高亮当前）
- 自定义 cron input
- 实时 validation 显示错误（`data-testid="cron-error"`）
- `data-testid="cron-preset-{preset.id}"` 便于测试

**`src/features/scheduled/CreateTaskModal.tsx`**：

- **双模式**：`task?` prop 存在则编辑，否则创建
- **字段**：Name, Type（once/recurring toggle）, Cron picker / At datetime input, Session selector, Content textarea, Enabled toggle
- **Validation**：submit 按钮 disable 直到 name + content + (cron/at) 都有效
- **错误显示**：inline（modal 内）+ sonner toast（失败）
- **时间输入**：`<input type="datetime-local">`，本地时区，转 UTC epoch ms

**`src/pages/ScheduledTasks.tsx`**：

- 列表：每行显示 name, schedule 描述（via `describeSchedule`）, status badge（enabled/disabled）, last_run, next_run
- 操作：Edit / Delete（带确认）/ Run now
- 顶部：Create 按钮
- Empty state：`scheduled.empty` i18n 文案
- 挂载时 `useScheduledTaskStore.load()`

### 5.4 Sidebar + ChatInput 集成

**`src/widgets/sidebar/sections/CronJobSection.tsx`**：

- 位置：ConversationsSection 下方（**spike 验证**：win7 Sidebar 是否有 ConversationsSection；如结构不同则调整位置）
- 只读列表：name + status badge
- 点击：`navigate('/scheduled')` 跳转编辑页
- 数据源：`useScheduledTaskStore`（共享 store，避免重复 load）

**`src/widgets/chat/ChatInput.tsx`** 修改：

- 加"定时"按钮（lucide `Clock` icon）— **spike 验证**：win7 ChatInput 的具体结构（main 是 "attach row 旁"，win7 可能不同），按实际结构决定位置
- 点击打开 CreateTaskModal，预填：
  - `sessionId`：当前 chat session
  - `content`：当前输入框内容
  - 其他字段留空（用户填）

### 5.5 路由 + i18n

**`src/App.tsx`**：

```tsx
<Route path="/scheduled" element={<ScheduledTasks />} />
```

**i18n**：在 `src/shared/lib/i18n/{zh,en}.ts` 加 28 个键：

- 22 个 `scheduled.*` 键（title, subtitle, empty, create, edit, field.*, status.*, action.*, toast.*, confirm.*）
- 6 个 `cron.preset.*` 键（hourly, daily08, daily18, weekday09, weeklyMon, monthly1st）

## 6. 数据流

### 6.1 用户创建定时任务

```
CreateTaskModal.submit
  → useScheduledTaskStore.create(input)
  → scheduledClient.create(input)
  → window.electronAPI.invoke('scheduled_create_task', { input })
  → Electron main → HTTP POST /api/v1/scheduled/tasks
  → scheduled_router.create_task
    → SchedulerService.add_task
    → validate（cron/at, session exists）
    → APScheduler.add_job（CronTrigger/DateTrigger）
    → atomic JSON write
  → 返回 ScheduledTask → store 追加 → UI 更新
```

### 6.2 任务触发

```
APScheduler 触发 _fire(task)
  → session_repo.exists(session_id)?
    → no: log warning, skip
    → yes: message_repo.insert(session_id, role='system', content=task.content, created_at=now)
  → once 任务: enabled=False + remove_job
  → recurring 任务: 更新 next_run + last_run
  → atomic JSON write
```

### 6.3 Sidebar 显示

```
CronJobSection mount
  → useScheduledTaskStore.load()（首次）
  → scheduledClient.list()
  → 渲染 list（name + status badge）
  → 点击 → navigate('/scheduled')
```

## 7. 错误处理

| 层 | 错误类型 | 处理 |
|---|---|---|
| Backend validation | `ValidationError`（bad cron, past at, missing session） | 422 + detail message |
| Backend not found | `TaskNotFoundError` | 404 |
| Backend fire | `_fire()` 内异常 | log, 不抛, 不影响 scheduler loop |
| Backend JSON read | 文件损坏/缺失 | log warning, start empty |
| Backend init | MessageRepo/SessionRepo 不存在 | 优雅降级（`getattr` fallback） |
| IPC | invoke 失败 | 抛到 client, catch 后 toast |
| Frontend store | load/create/update/delete 失败 | 设 `error` 字段, UI inline 显示 |
| Frontend modal | create/update 失败 | inline error + sonner toast |

## 8. 测试策略

### 8.1 Byte-for-byte port 8 个测试文件

| 测试文件 | 行数 | 描述 |
|---|---|---|
| `backend/services/__tests__/test_scheduler.py` | ~382 | SchedulerService 单元（17 tests） |
| `backend/tests/integration/test_scheduled_api.py` | ~168 | Router 集成（10 tests） |
| `src/features/scheduled/__tests__/cronValidator.test.ts` | ~88 | Cron 验证纯函数（17 tests） |
| `src/shared/api/__tests__/scheduledClient.test.ts` | ~70 | IPC client（6 tests） |
| `src/entities/scheduled/__tests__/taskStore.test.ts` | ~110 | Zustand store（7 tests） |
| `src/features/scheduled/__tests__/CronExpressionPicker.test.tsx` | ~40 | Picker 组件（5 tests） |
| `src/features/scheduled/__tests__/CreateTaskModal.test.tsx` | ~140 | Modal 组件（5 tests） |
| `src/widgets/chat/__tests__/ChatInput.scheduled.test.tsx` | ~40 | ChatInput 集成（2 tests） |

### 8.2 覆盖率目标（与 main 一致）

- `scheduler.py` ≥ 95%
- `cronValidator.ts` ≥ 95%
- `scheduledClient.ts` ≥ 90%
- 总 frontend ≥ 85%
- 总 backend ≥ 85%

### 8.3 适配点

- i18n：win7 用 `useI18n()` 而非 i18next — 签名兼容（`{ t } = useI18n()`）
- 路径：win7 用 `src/shared/api` 而非 main 的 `src/shared/api-client`
- 类型：win7 的 `t()` 用 `TranslationKey`（严格类型），加 28 个键后自动扩展

## 9. 实施策略

### 9.1 分支

- **单分支**：`feat/win7-m3-scheduler`
- 分多个 commit（预计 8-10 个），每 commit 可独立验证
- 完成后 PR → local merge → push release/win7 → 删 feat 分支

### 9.2 Commit 顺序（预估）

1. `build(backend): add apscheduler 3.10.4`
2. `feat(backend): SchedulerService + tests`
3. `feat(backend): scheduled_router + integration tests`
4. `feat(backend): mount scheduler in main.py lifespan`
5. `feat(types): add ScheduledTask types`
6. `feat(scheduled): cronValidator + scheduledClient + taskStore + tests`
7. `feat(scheduled): CronExpressionPicker + CreateTaskModal + tests`
8. `feat(scheduled): ScheduledTasks page + i18n keys`
9. `feat(sidebar): CronJobSection + ChatInput 定时按钮`
10. `chore: route + integration verification`

### 9.3 实施顺序

1. **Backend first**（commit 1-4）：deps → service → router → main.py 集成
2. **Frontend infrastructure**（commit 5-6）：types → validator/client/store
3. **Frontend UI**（commit 7-8）：picker → modal → page → i18n
4. **Integration**（commit 9-10）：sidebar + ChatInput + route + 全量验证

## 10. DoD 清单（单模块）

- [ ] 10 个 commit 已 push 到 `feat/win7-m3-scheduler`
- [ ] pytest 全过（backend 新增 ~27 tests）
- [ ] vitest 全过（frontend 新增 ~42 tests）
- [ ] 覆盖率达标（scheduler.py ≥ 95%, cronValidator.ts ≥ 95%）
- [ ] tsc 0 新错误
- [ ] PR 创建 + code-review agent 通过（无 critical/high）
- [ ] 用户 review 通过
- [ ] Local merge → push release/win7
- [ ] 删 feat 分支
- [ ] CHANGELOG.md 加条目
- [ ] Memory 更新（`sage-m3-scheduler-merged.md`）
- [ ] Ledger 更新（`.superpowers/sdd/progress.md`）

## 11. 风险与缓解

| 风险 | 概率 | 缓解 |
|---|---|---|
| Electron IPC command 名与 main 不一致 | 低 | 检查 `electron/main.ts` 已有 command 注册模式，按 main 风格加 5 个新 command |
| Sidebar 集成与现有 Sider 冲突 | 中 | 实施 commit 9 前先 spike：确认 win7 Sidebar 结构（ConversationsSection 是否存在），如有冲突先做适配层 |
| ChatInput 结构与 main 不同 | 中 | 实施 commit 9 前先 spike：确认 win7 ChatInput 具体结构（"attach row" 是否存在），按实际结构放按钮 |
| `MessageRepository.insert` 签名不匹配 | 低 | main 已有此方法，检查 win7 是否已有；如无则 port |
| 总工期超 2 天 | 低 | M2 P4 已验证 byte-for-byte 路径，风险可控 |

## 12. 参考

- **Main 源码**（byte-for-byte port 源）：
  - `backend/services/scheduler.py`（377 行）
  - `backend/api/scheduled_router.py`（166 行）
  - `src/entities/scheduled/taskStore.ts`
  - `src/features/scheduled/cronValidator.ts`
  - `src/features/scheduled/CronExpressionPicker.tsx`
  - `src/features/scheduled/CreateTaskModal.tsx`
  - `src/shared/api/scheduledClient.ts`
- **Main 测试文件**（byte-for-byte port 源）：7 个测试文件，见 §8.1
- **Main 实施计划**：`docs/superpowers/plans/2026-06-25-phase8-scheduled-tasks.md`（3500 行，详细 step-by-step）
- **技术文档**：`docs/technical/24-scheduled-tasks.md`
- **Rollout 总览 spec**：`docs/superpowers/specs/2026-06-28-win7-modules-rollout-design.md` §5.3

---

**Spec 状态**：✅ 设计完成，待用户最终审阅后转入 writing-plans 阶段。

**下一步**：用户 review 本 spec 文件 → 确认后启动 writing-plans skill 创建 M3 实施计划。
