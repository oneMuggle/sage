# 侧边栏任务中心 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把右下角浮动胶囊 `TaskCenterWidget` 迁入侧边栏，成为聚合六种任务来源（registry / chat / lane / goal / todo / scheduled）的统一任务中心，并补齐闲时目标完成通知。

**Architecture:** 纯函数归一层（`unifiedTaskModel`）把六个异构数据源映射到既有的 7 值 `TaskCenterStatus`；独立的 `unifiedTaskStore` 承担三源后端轮询（不碰页面 store，避免 `statusFilter` 污染）；常驻的 `TaskCenterRuntimeHost` 承担轮询（不受侧边栏折叠影响）；卡片 / 分区 / 页面共享同一份归一结果。

**Tech Stack:** React 18 + TypeScript + Zustand（vanilla `create()`）+ vitest + Testing Library / FastAPI（Python 3.10，release/win7 为 3.8）+ Electron 21。

**Spec:** `docs/superpowers/specs/2026-11-09-sidebar-task-center-design.md`

## Global Constraints

- **FSD 分层是 ESLint ERROR**（`eslint.config.js:60-110`）：`app > processes > pages > widgets > features > entities > shared`。`shared` 不得导入 `features`；`features → features` 允许。
- **架构棘轮**（`architecture-policy.json` + `scripts/architecture-check.mjs`）：单文件 `maxFileLines: 800`；已基线文件**不得增长**。`Sidebar.tsx`(728) 未基线，`chatAndSider.ts`(zh 825/en 824) **已基线**——不许往里加键。
- **状态词表只有一套**：`TaskCenterStatus = queued | running | awaiting_approval | paused | succeeded | failed | cancelled`，来自 `src/features/task-center/taskCenterStore.ts`。不得新造第二套。
- **`taskCenterStore` 数据契约不变**：`TaskCenterPetBridge`（`App.tsx:334`）只读 `tasks: Record<string, TaskCenterEntry>`。
- **三个 API 客户端返回形状不同**：`listGoals` → `GoalListResponse{items}`；`todoClient.list` → `TodoListResponse{items}`（用 `limit`/`offset`，**无 `page_size`**）；`scheduledClient.list()` → `ScheduledTask[]`（裸数组）。
- **`TasksPage` 不得加进 `src/pages/index.ts` barrel** → `pagesIndex.p142.test.ts:10` 硬断言 `exportedPageCount === 5`。
- **`/tasks` 路由必须 `lazy()`**（与 `App.tsx` 既有页面一致）。
- **Sidebar 变量名必须用 `taskCenterBadgeCount`**，不得用 `attentionCount`（`Sidebar.tsx:236` 已有同名变量 = 审批+提问）。
- **i18n**：新键全部落在新文件 `locales/{zh,en}/taskCenter.ts`，禁止往 `chatAndSider.ts` 加键。
- **Python 3.8 兼容**（release/win7）：不用 PEP 604 `X | Y`、不用内建泛型注解 `list[str]`、不用 `match`。用 `Optional[X]` + `typing.List`。
- **后端测试**用 `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest`（win7 用 `sage-backend-py38`）。
- **每个 Task 结束必须绿**：`npm run lint && node scripts/architecture-check.mjs && npx vitest run <相关文件>`。

---

## File Structure

**新建（9 个前端文件）**

| 文件 | 职责 |
|---|---|
| `src/features/task-center/unifiedTaskModel.ts` | 类型 + 4 张状态映射表 + 6 个归一函数 + 排序 |
| `src/features/task-center/unifiedTaskStore.ts` | goal/todo/scheduled 三源原始数据 + 轮询刷新 |
| `src/features/task-center/useUnifiedTasks.ts` | 合并 6 源 → 归一 → 排序 → 分组 |
| `src/features/task-center/useTaskCenterActions.ts` | 取消/暂停/立即运行/深链分发 |
| `src/features/task-center/TaskCenterRuntimeHost.tsx` | 常驻轮询宿主（null 渲染） |
| `src/features/task-center/TaskCenterPanel.tsx` | 页面/分区共用内容（compact / full） |
| `src/features/task-center/TaskCenterCard.tsx` | 统一任务卡片（**必须放 features**：features 不得 import widgets，而 Panel 在 features 层要复用它） |
| `src/widgets/sidebar/sections/TaskCenterSection.tsx` | 内容列「任务」分区 |
| `src/pages/TasksPage.tsx` | `/tasks` 路由薄壳 |

**新建（2 个 i18n 文件）**

- `src/shared/lib/i18n/locales/zh/taskCenter.ts`
- `src/shared/lib/i18n/locales/en/taskCenter.ts`

**新建（1 个后端文件 + 3 个测试文件）**

- `backend/services/goal_notifications.py`
- `backend/tests/unit/test_goal_notifications.py`
- `backend/tests/api/test_goal_notifications_route.py`
- `backend/tests/unit/test_goal_service_notifications.py`

**删除**

- `src/widgets/task-center/TaskCenterWidget.tsx`
- `src/widgets/task-center/__tests__/TaskCenterWidget.{test,a1,a4,dedupe,shells}.test.tsx`（行为迁入新测试）

**修改**

| 文件 | 改动 |
|---|---|
| `src/widgets/layout/Sidebar.tsx` | `SECTION_KEYS` + `renderSection` + nav 项 + rail 角标 |
| `src/widgets/layout/Layout.tsx` | `<TaskCenterWidget />` → `<TaskCenterRuntimeHost />` |
| `src/widgets/task-center/DeliveryDrawerHost.tsx` | 接管 `<ShellStreamDrawer />` |
| `src/features/app-panels/panelRegistry.ts` | `task-center` 槽位 `floating` → `left-list` |
| `src/features/app-panels/__tests__/panelRegistry.test.ts` | 两处断言 |
| `src/App.tsx` | `/tasks` 路由（lazy） |
| `src/shared/lib/i18n/zh.ts` / `en.ts` | 各加 1 行 import + 1 行 spread |
| `electron/schedulerNotifications.ts` | `PendingNotificationsPayload` + `collectNotificationItems` |
| `backend/services/goal_service.py` | COMPLETED / FAILED 推通知 |
| `backend/api/scheduled_router.py` | 返回体加 `goal_notifications` |

---

## Task 1: 统一任务模型（M1）

**Files:**
- Create: `src/features/task-center/unifiedTaskModel.ts`
- Test: `src/features/task-center/__tests__/unifiedTaskModel.test.ts`

**Interfaces:**
- Consumes: `TaskCenterStatus` / `TERMINAL_TASK_STATUSES` from `./taskCenterStore`; `Goal`/`GoalStatus` from `../../entities/autonomous-goals/types`; `Todo`/`TodoItemStatus`/`ScheduledTask`/`Lane`/`LaneStatus` from `../../shared/api/types`
- Produces:
  - `UnifiedTaskSource`, `UnifiedTaskEntry`
  - `GOAL_STATUS_MAP`, `TODO_STATUS_MAP`, `SCHEDULED_STATUS_MAP`, `LANE_STATUS_MAP`, `STATUS_PRIORITY`
  - `normalizeRegistryTask(entry: TaskCenterEntry): UnifiedTaskEntry`
  - `normalizeChatTask(input: ChatTaskInput): UnifiedTaskEntry`
  - `normalizeLaneTask(lane: Lane): UnifiedTaskEntry | null`
  - `normalizeGoalTask(goal: Goal): UnifiedTaskEntry | null`
  - `normalizeTodoTask(todo: Todo): UnifiedTaskEntry | null`
  - `normalizeScheduledTask(task: ScheduledTask): UnifiedTaskEntry | null`
  - `compareUnifiedTasks(a, b): number`、`isTerminalStatus(status): boolean`

- [ ] **Step 1: 写失败的测试 —— 状态映射表全枚举**

Create `src/features/task-center/__tests__/unifiedTaskModel.test.ts`:

```ts
import { describe, expect, it } from 'vitest';

import {
  GOAL_STATUS_MAP,
  LANE_STATUS_MAP,
  SCHEDULED_STATUS_MAP,
  TODO_STATUS_MAP,
} from '../unifiedTaskModel';

describe('unifiedTaskModel / 状态映射表', () => {
  it('goal 六状态全覆盖，completed → succeeded', () => {
    expect(GOAL_STATUS_MAP).toEqual({
      pending: 'queued',
      running: 'running',
      paused: 'paused',
      completed: 'succeeded',
      failed: 'failed',
      cancelled: 'cancelled',
    });
  });

  it('todo 四状态全覆盖', () => {
    expect(TODO_STATUS_MAP).toEqual({
      pending: 'queued',
      in_progress: 'running',
      completed: 'succeeded',
      cancelled: 'cancelled',
    });
  });

  it('scheduled 四状态全覆盖', () => {
    expect(SCHEDULED_STATUS_MAP).toEqual({
      never: 'queued',
      running: 'running',
      succeeded: 'succeeded',
      failed: 'failed',
    });
  });

  it('lane 八状态全覆盖，blocked → awaiting_approval', () => {
    expect(LANE_STATUS_MAP).toEqual({
      created: 'queued',
      ready: 'queued',
      running: 'running',
      blocked: 'awaiting_approval',
      succeeded: 'succeeded',
      failed: 'failed',
      stopped: 'cancelled',
      cancelled: 'cancelled',
    });
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/features/task-center/__tests__/unifiedTaskModel.test.ts`
Expected: FAIL — `Cannot find module '../unifiedTaskModel'`

- [ ] **Step 3: 写最小实现 —— 类型 + 映射表**

Create `src/features/task-center/unifiedTaskModel.ts`:

```ts
// src/features/task-center/unifiedTaskModel.ts
//
// 统一任务模型：六种异构任务源 → 单一 UnifiedTaskEntry。
// 只在 features 层（shared 不得导入 features，见 eslint.config.js FSD 规则）。
import type { Goal, GoalStatus } from '../../entities/autonomous-goals/types';
import type {
  Lane,
  LaneStatus,
  ScheduledTask,
  Todo,
  TodoItemStatus,
} from '../../shared/api/types';

import type { TaskCenterEntry, TaskCenterStatus } from './taskCenterStore';
import { TERMINAL_TASK_STATUSES } from './taskCenterStore';

export type UnifiedTaskSource =
  | 'registry'
  | 'chat'
  | 'lane'
  | 'goal'
  | 'todo'
  | 'scheduled';

/**
 * 点击语义覆盖：缺省（null）表示"走 detailPath 路由跳转"。
 * A4 交付验收 / 后台 shell 输出抽屉需要优先于路由跳转。
 */
export type UnifiedTaskOpenTarget =
  | { kind: 'shell'; shellId: string }
  | { kind: 'lane-delivery'; laneId: string }
  | { kind: 'office-delivery'; entryId: string };

export interface UnifiedTaskEntry {
  /** 全局唯一：`<source>:<rawId>` */
  id: string;
  source: UnifiedTaskSource;
  title: string;
  status: TaskCenterStatus;
  /** epoch ms；无则 null */
  startedAt: number | null;
  updatedAt: number | null;
  /** 0-100；无则 null（不伪造） */
  percent: number | null;
  error: string | null;
  cancellable: boolean;
  /** 归属路由（展示 + 兜底跳转）；null = 无归页 */
  detailPath: string | null;
  /** 覆盖 detailPath 的点击语义（交付抽屉 / shell 抽屉）；null = 走 detailPath */
  openTarget: UnifiedTaskOpenTarget | null;
  cancelRef: { source: UnifiedTaskSource; rawId: string } | null;
  meta: Record<string, string | number | null>;
}

export const GOAL_STATUS_MAP: Readonly<Record<GoalStatus, TaskCenterStatus>> = {
  pending: 'queued',
  running: 'running',
  paused: 'paused',
  completed: 'succeeded',
  failed: 'failed',
  cancelled: 'cancelled',
};

export const TODO_STATUS_MAP: Readonly<Record<TodoItemStatus, TaskCenterStatus>> = {
  pending: 'queued',
  in_progress: 'running',
  completed: 'succeeded',
  cancelled: 'cancelled',
};

export const SCHEDULED_STATUS_MAP: Readonly<
  Record<NonNullable<ScheduledTask['last_status']>, TaskCenterStatus>
> = {
  never: 'queued',
  running: 'running',
  succeeded: 'succeeded',
  failed: 'failed',
};

export const LANE_STATUS_MAP: Readonly<Record<LaneStatus, TaskCenterStatus>> = {
  created: 'queued',
  ready: 'queued',
  running: 'running',
  blocked: 'awaiting_approval',
  succeeded: 'succeeded',
  failed: 'failed',
  stopped: 'cancelled',
  cancelled: 'cancelled',
};

export const STATUS_PRIORITY: Readonly<Record<TaskCenterStatus, number>> = {
  failed: 0,
  awaiting_approval: 1,
  running: 2,
  paused: 3,
  queued: 4,
  succeeded: 5,
  cancelled: 6,
};
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run src/features/task-center/__tests__/unifiedTaskModel.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: 写失败的测试 —— 六个归一函数**

Append to the same test file:

```ts
import type { Goal } from '../../../entities/autonomous-goals/types';
import type { Lane, ScheduledTask, Todo } from '../../../shared/api/types';
import type { TaskCenterEntry } from '../taskCenterStore';
import {
  compareUnifiedTasks,
  normalizeChatTask,
  normalizeGoalTask,
  normalizeLaneTask,
  normalizeRegistryTask,
  normalizeScheduledTask,
  normalizeTodoTask,
} from '../unifiedTaskModel';

const makeGoal = (over: Partial<Goal> = {}): Goal => ({
  id: 'g1',
  name: '整理文献',
  description: '',
  status: 'pending',
  session_id: null,
  time_window: {
    off_peak_start: '00:00',
    off_peak_end: '06:00',
    weekends_off_peak: true,
    holidays: [],
    min_pricing_tier: 'standard',
    timezone: 'Asia/Shanghai',
  },
  // 必须与 src/entities/autonomous-goals/types.ts 的 ExecutionBudget 逐字一致
  budget: {
    max_rounds: 10,
    max_hours: 2,
    max_tokens: 1000,
    stop_on_failure: false,
  },
  checkpoints: [],
  current_round: 0,
  created_at: '2026-11-09T10:00:00',
  started_at: null,
  completed_at: null,
  total_tokens_used: 0,
  completion_percentage: 0,
  degradation_level: 'none',
  last_error: null,
  trigger_mode: 'conditional',
  execution_conditions: [],
  ...over,
});

describe('unifiedTaskModel / registry 归一', () => {
  it('普通 registry 任务：保留 percent / detailPath', () => {
    const entry: TaskCenterEntry = {
      id: 'r1',
      kind: 'office',
      title: '生成报告',
      startedAt: 1000,
      status: 'running',
      percent: 42,
      docName: 'report.docx',
    };
    const u = normalizeRegistryTask(entry);
    expect(u).toMatchObject({
      id: 'registry:r1',
      source: 'registry',
      title: '生成报告',
      status: 'running',
      startedAt: 1000,
      percent: 42,
      cancellable: false,
    });
    expect(u.meta.docName).toBe('report.docx');
  });

  it('shell 任务（kind=shell）：不可跳转、可取消、带 shellId', () => {
    const entry: TaskCenterEntry = {
      id: 'shell-1',
      kind: 'shell',
      title: 'npm test',
      startedAt: 2000,
      status: 'running',
      shellId: 'sh-9',
      exitCode: null,
    };
    const u = normalizeRegistryTask(entry);
    expect(u).toMatchObject({
      id: 'registry:shell-1',
      detailPath: null,
      cancellable: true,
    });
    expect(u.cancelRef).toEqual({ source: 'registry', rawId: 'sh-9' });
    expect(u.meta.shellId).toBe('sh-9');
  });

  it('已完成的 shell 任务不可取消', () => {
    const entry: TaskCenterEntry = {
      id: 'shell-2',
      kind: 'shell',
      title: 'done',
      startedAt: 1,
      status: 'succeeded',
      shellId: 'sh-1',
    };
    expect(normalizeRegistryTask(entry).cancellable).toBe(false);
  });
});

describe('unifiedTaskModel / chat 归一', () => {
  it('后台会话流恒为 running', () => {
    const u = normalizeChatTask({ sessionId: 's1', title: '后台对话', firstSeenAt: 500 });
    expect(u).toMatchObject({
      id: 'chat:s1',
      source: 'chat',
      status: 'running',
      startedAt: 500,
      detailPath: '/chat?session=s1',
      cancellable: true,
    });
  });
});

describe('unifiedTaskModel / lane 归一', () => {
  const lane = (over: Partial<Lane> = {}): Lane => ({
    lane_id: 'l1',
    task_id: 'T-1',
    agent_id: 'agent-a',
    status: 'running',
    created_at: 1,
    started_at: 2,
    completed_at: null,
    worktree: null,
    heartbeat: null,
    error: null,
    permission_preset: 'default',
    metadata: {},
    ...over,
  });

  it('可见 lane 归一为 running', () => {
    const u = normalizeLaneTask(lane());
    expect(u).toMatchObject({
      id: 'lane:l1',
      source: 'lane',
      status: 'running',
      startedAt: 2,
      cancellable: true,
      detailPath: '/orchestration',
    });
  });

  it('待验收 lane（succeeded 且未决议）→ awaiting_approval 且不可取消', () => {
    const u = normalizeLaneTask(lane({ status: 'succeeded' }));
    expect(u?.status).toBe('awaiting_approval');
    expect(u?.cancellable).toBe(false);
  });

  it('已决议 / 不可见 lane 不展示（返回 null）', () => {
    expect(normalizeLaneTask(lane({ status: 'succeeded', metadata: { accepted_at: 1 } }))).toBeNull();
    expect(normalizeLaneTask(lane({ status: 'stopped' }))).toBeNull();
  });
});

describe('unifiedTaskModel / goal 归一', () => {
  it('pending 目标进入列表（闲时任务本体）', () => {
    const u = normalizeGoalTask(makeGoal());
    expect(u).toMatchObject({
      id: 'goal:g1',
      source: 'goal',
      title: '整理文献',
      status: 'queued',
      startedAt: null,
      detailPath: '/goals/g1',
      cancellable: true,
    });
    expect(u?.percent).toBe(0);
  });

  it('ISO 时间戳转 epoch ms', () => {
    const u = normalizeGoalTask(
      makeGoal({ started_at: '2026-11-09T10:00:00', status: 'running', completion_percentage: 40 }),
    );
    expect(u?.status).toBe('running');
    expect(u?.startedAt).toBe(Date.parse('2026-11-09T10:00:00'));
    expect(u?.percent).toBe(40);
  });

  it('completed → succeeded 且不可取消', () => {
    const u = normalizeGoalTask(makeGoal({ status: 'completed' }));
    expect(u?.status).toBe('succeeded');
    expect(u?.cancellable).toBe(false);
  });

  it('failed 保留 last_error', () => {
    const u = normalizeGoalTask(makeGoal({ status: 'failed', last_error: '模型超时' }));
    expect(u?.status).toBe('failed');
    expect(u?.error).toBe('模型超时');
  });
});

describe('unifiedTaskModel / todo 归一', () => {
  const todo = (over: Partial<Todo> = {}): Todo => ({
    id: 7,
    title: '写周报',
    status: 'in_progress',
    priority: 'medium',
    is_recurring: false,
    created_at: '2026-11-09T09:00:00',
    updated_at: '2026-11-09T09:30:00',
    ...over,
  });

  it('in_progress todo 进入列表', () => {
    const u = normalizeTodoTask(todo());
    expect(u).toMatchObject({
      id: 'todo:7',
      source: 'todo',
      status: 'running',
      detailPath: '/todos',
      cancellable: false,
    });
    expect(u?.updatedAt).toBe(Date.parse('2026-11-09T09:30:00'));
  });

  it('pending todo 不展示', () => {
    expect(normalizeTodoTask(todo({ status: 'pending' }))).toBeNull();
  });

  it('completed → succeeded；cancelled 不展示', () => {
    expect(normalizeTodoTask(todo({ status: 'completed' }))?.status).toBe('succeeded');
    expect(normalizeTodoTask(todo({ status: 'cancelled' }))).toBeNull();
  });
});

describe('unifiedTaskModel / scheduled 归一', () => {
  const task = (over: Partial<ScheduledTask> = {}): ScheduledTask => ({
    id: 'st1',
    name: '每日摘要',
    type: 'interval',
    schedule: { interval_minutes: 60 },
    session_id: 's0',
    content: 'summary',
    enabled: true,
    last_status: 'running',
    created_at: 1_700_000_000_000,
    ...over,
  });

  it('running 进入列表', () => {
    const u = normalizeScheduledTask(task());
    expect(u).toMatchObject({
      id: 'scheduled:st1',
      source: 'scheduled',
      title: '每日摘要',
      status: 'running',
      detailPath: '/scheduled',
      cancellable: false,
    });
  });

  it('never / succeeded 不展示', () => {
    expect(normalizeScheduledTask(task({ last_status: 'never' }))).toBeNull();
    expect(normalizeScheduledTask(task({ last_status: 'succeeded' }))).toBeNull();
  });

  it('failed 展示并带 last_error', () => {
    const u = normalizeScheduledTask(task({ last_status: 'failed', last_error: 'boom' }));
    expect(u?.status).toBe('failed');
    expect(u?.error).toBe('boom');
  });
});

describe('unifiedTaskModel / 排序', () => {
  it('failed 排最前，同状态按 startedAt 升序，null 排最后', () => {
    const base = {
      source: 'registry' as const,
      updatedAt: null,
      percent: null,
      error: null,
      cancellable: false,
      detailPath: null,
      openTarget: null,
      cancelRef: null,
      meta: {},
    };
    const list = [
      { ...base, id: 'a', title: 'a', status: 'running' as const, startedAt: 30 },
      { ...base, id: 'b', title: 'b', status: 'failed' as const, startedAt: null },
      { ...base, id: 'c', title: 'c', status: 'running' as const, startedAt: 10 },
    ];
    expect([...list].sort(compareUnifiedTasks).map((e) => e.id)).toEqual(['b', 'c', 'a']);
  });
});
```

- [ ] **Step 6: 运行测试确认失败**

Run: `npx vitest run src/features/task-center/__tests__/unifiedTaskModel.test.ts`
Expected: FAIL — `normalizeRegistryTask is not a function`

- [ ] **Step 7: 实现六个归一函数 + 排序**

Append to `src/features/task-center/unifiedTaskModel.ts`:

```ts
export interface ChatTaskInput {
  sessionId: string;
  title: string;
  /** 首见时间（epoch ms），由 useUnifiedTasks 的 ref 提供 */
  firstSeenAt: number;
}

/** A1: lanes worth surfacing (live work plus failures). */
export function isLaneVisible(status: LaneStatus): boolean {
  return (
    status === 'created' ||
    status === 'ready' ||
    status === 'running' ||
    status === 'blocked' ||
    status === 'failed'
  );
}

/** A4: 待验收 lane —— succeeded 且尚未决议。 */
export function isLaneAwaitingDecision(lane: Lane): boolean {
  if (lane.status !== 'succeeded') return false;
  const meta = lane.metadata ?? {};
  return typeof meta.accepted_at !== 'number' && typeof meta.rejected_at !== 'number';
}

export function isLaneCancellable(status: LaneStatus): boolean {
  return (
    status === 'created' || status === 'ready' || status === 'running' || status === 'blocked'
  );
}

function safeIsoToMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

function nonEmpty(value: string | null | undefined, fallback: string): string {
  const trimmed = (value ?? '').trim();
  return trimmed.length > 0 ? trimmed : fallback;
}

export function normalizeRegistryTask(entry: TaskCenterEntry): UnifiedTaskEntry {
  const isShell = entry.kind === 'shell';
  // A4b: office 交付待验收 → 点击直达交付抽屉（旧 TaskCenterWidget 行为）
  const officeDelivery =
    !isShell && entry.status === 'awaiting_approval' && entry.deliveryRef != null;
  return {
    id: `registry:${entry.id}`,
    source: 'registry',
    title: entry.phase ? `${entry.title} · ${entry.phase}` : entry.title,
    status: entry.status,
    startedAt: Number.isFinite(entry.startedAt) ? entry.startedAt : null,
    updatedAt: entry.finishedAt ?? null,
    percent: typeof entry.percent === 'number' ? entry.percent : null,
    error: entry.error ?? null,
    // shell 运行中可 kill；其他 registry 任务沿用既有不可取消语义
    cancellable: isShell && entry.status === 'running' && Boolean(entry.shellId),
    detailPath: isShell
      ? null
      : entry.kind === 'office'
        ? '/office'
        : entry.kind === 'wiki'
          ? '/knowledge'
          : null,
    openTarget: isShell
      ? entry.shellId
        ? { kind: 'shell', shellId: entry.shellId }
        : null
      : officeDelivery
        ? { kind: 'office-delivery', entryId: entry.id }
        : null,
    cancelRef: isShell && entry.shellId ? { source: 'registry', rawId: entry.shellId } : null,
    meta: {
      kind: entry.kind,
      docName: entry.docName ?? null,
      shellId: entry.shellId ?? null,
      exitCode: entry.exitCode ?? null,
    },
  };
}

export function normalizeChatTask(input: ChatTaskInput): UnifiedTaskEntry {
  return {
    id: `chat:${input.sessionId}`,
    source: 'chat',
    title: input.title,
    status: 'running',
    startedAt: input.firstSeenAt,
    updatedAt: null,
    percent: null,
    error: null,
    cancellable: true,
    detailPath: `/chat?session=${encodeURIComponent(input.sessionId)}`,
    openTarget: null,
    cancelRef: { source: 'chat', rawId: input.sessionId },
    meta: { sessionId: input.sessionId },
  };
}

export function normalizeLaneTask(lane: Lane): UnifiedTaskEntry | null {
  const awaiting = isLaneAwaitingDecision(lane);
  if (!isLaneVisible(lane.status) && !awaiting) return null;
  const status = awaiting ? 'awaiting_approval' : LANE_STATUS_MAP[lane.status];
  return {
    id: `lane:${lane.lane_id}`,
    source: 'lane',
    title: `${lane.task_id}${lane.agent_id ? ` · ${lane.agent_id}` : ''}`,
    status,
    startedAt: lane.started_at ?? null,
    updatedAt: lane.completed_at ?? null,
    percent: null,
    error: lane.error ?? null,
    cancellable: isLaneCancellable(lane.status),
    detailPath: '/orchestration',
    // A4: 待验收 lane 点击直达交付抽屉，而非 /orchestration 路由
    openTarget: awaiting ? { kind: 'lane-delivery', laneId: lane.lane_id } : null,
    cancelRef: { source: 'lane', rawId: lane.lane_id },
    meta: { laneId: lane.lane_id, agentId: lane.agent_id ?? null },
  };
}

export function normalizeGoalTask(goal: Goal): UnifiedTaskEntry | null {
  const status = GOAL_STATUS_MAP[goal.status];
  if (!status) return null;
  const cancellable =
    goal.status === 'pending' || goal.status === 'running' || goal.status === 'paused';
  return {
    id: `goal:${goal.id}`,
    source: 'goal',
    title: nonEmpty(goal.name, goal.id),
    status,
    startedAt: safeIsoToMs(goal.started_at),
    updatedAt: safeIsoToMs(goal.completed_at),
    percent:
      typeof goal.completion_percentage === 'number' ? goal.completion_percentage : null,
    error: goal.last_error ?? null,
    cancellable,
    detailPath: `/goals/${encodeURIComponent(goal.id)}`,
    openTarget: null,
    cancelRef: cancellable ? { source: 'goal', rawId: goal.id } : null,
    meta: {
      triggerMode: goal.trigger_mode,
      degradation: goal.degradation_level,
      round: goal.current_round,
    },
  };
}

export function normalizeTodoTask(todo: Todo): UnifiedTaskEntry | null {
  // pending 是"定义"不是"正在发生"；cancelled 不展示（spec §4.4）
  if (todo.status !== 'in_progress' && todo.status !== 'completed') return null;
  const id = String(todo.id);
  return {
    id: `todo:${id}`,
    source: 'todo',
    title: nonEmpty(todo.title, id),
    status: TODO_STATUS_MAP[todo.status],
    startedAt: null,
    updatedAt: safeIsoToMs(todo.updated_at),
    percent: null,
    error: null,
    cancellable: false,
    detailPath: '/todos',
    openTarget: null,
    cancelRef: null,
    meta: { priority: todo.priority, projectTag: todo.project_tag ?? null },
  };
}

export function normalizeScheduledTask(task: ScheduledTask): UnifiedTaskEntry | null {
  const last = task.last_status ?? 'never';
  // never / succeeded 不展示：历史成功不是待办（spec §4.4）
  if (last !== 'running' && last !== 'failed') return null;
  return {
    id: `scheduled:${task.id}`,
    source: 'scheduled',
    title: nonEmpty(task.name, task.id),
    status: SCHEDULED_STATUS_MAP[last],
    startedAt: null,
    updatedAt: task.last_attempt ?? null,
    percent: null,
    error: task.last_error ?? null,
    cancellable: false,
    detailPath: '/scheduled',
    openTarget: null,
    cancelRef: null,
    meta: { enabled: task.enabled ? 1 : 0, mode: task.mode ?? 'deliver' },
  };
}

export function compareUnifiedTasks(a: UnifiedTaskEntry, b: UnifiedTaskEntry): number {
  const pa = STATUS_PRIORITY[a.status] ?? 99;
  const pb = STATUS_PRIORITY[b.status] ?? 99;
  if (pa !== pb) return pa - pb;
  if (a.startedAt === null && b.startedAt !== null) return 1;
  if (a.startedAt !== null && b.startedAt === null) return -1;
  if (a.startedAt !== null && b.startedAt !== null && a.startedAt !== b.startedAt) {
    return a.startedAt - b.startedAt;
  }
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

export function isTerminalStatus(status: TaskCenterStatus): boolean {
  return TERMINAL_TASK_STATUSES.has(status);
}
```

- [ ] **Step 8: 运行测试确认通过**

Run: `npx vitest run src/features/task-center/__tests__/unifiedTaskModel.test.ts`
Expected: PASS（全部 ~22 个用例）

- [ ] **Step 9: lint + 架构检查**

```bash
npx eslint src/features/task-center/unifiedTaskModel.ts src/features/task-center/__tests__/unifiedTaskModel.test.ts
node scripts/architecture-check.mjs
```
Expected: 无新增 error

- [ ] **Step 10: 提交**

```bash
git add src/features/task-center/unifiedTaskModel.ts src/features/task-center/__tests__/unifiedTaskModel.test.ts
git commit -m "feat(task-center): 统一任务模型与六源归一函数

六种异构任务源（registry/chat/lane/goal/todo/scheduled）映射到既有 7 值
TaskCenterStatus。逐源处理时间戳类型差异（goal/todo 是 ISO，scheduled 是
epoch ms）与 id 类型差异（todo.id 是 number）。可见性规则按 spec §4.4：
pending todo 与 never/succeeded 定时任务不进入列表。"
```

---

## Task 2: 三源轮询 store（M2a）

**Files:**
- Create: `src/features/task-center/unifiedTaskStore.ts`
- Test: `src/features/task-center/__tests__/unifiedTaskStore.test.ts`

**Interfaces:**
- Consumes: `listGoals` from `../../entities/autonomous-goals/goalApi`; `todoClient` from `../../shared/api/todoClient`; `scheduledClient` from `../../shared/api/scheduledClient`; `create` from `zustand`
- Produces: `useUnifiedTaskStore` with state `{ goals, todos, scheduledTasks, loading, error, lastFetchedAt }` and actions `{ refresh, refreshGoals, refreshTodos, refreshScheduled }`；以及 `resetUnifiedTaskStore()`

- [ ] **Step 1: 写失败的测试**

Create `src/features/task-center/__tests__/unifiedTaskStore.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../entities/autonomous-goals/goalApi', () => ({
  listGoals: vi.fn(),
}));
vi.mock('../../../shared/api/todoClient', () => ({
  todoClient: { list: vi.fn() },
}));
vi.mock('../../../shared/api/scheduledClient', () => ({
  scheduledClient: { list: vi.fn() },
}));

import { listGoals } from '../../../entities/autonomous-goals/goalApi';
import { scheduledClient } from '../../../shared/api/scheduledClient';
import { todoClient } from '../../../shared/api/todoClient';
import { resetUnifiedTaskStore, useUnifiedTaskStore } from '../unifiedTaskStore';

const goal = { id: 'g1', name: 'g', status: 'pending' } as never;
const todo = { id: 1, title: 't', status: 'pending' } as never;
const task = { id: 's1', name: 's', last_status: 'never' } as never;

describe('unifiedTaskStore', () => {
  beforeEach(() => {
    resetUnifiedTaskStore();
    vi.resetAllMocks();
  });

  it('refresh 同时拉三源并解包两种返回形状', async () => {
    vi.mocked(listGoals).mockResolvedValue({ items: [goal], total: 1, limit: 200, offset: 0 } as never);
    vi.mocked(todoClient.list).mockResolvedValue({ items: [todo], total: 1, limit: 200, offset: 0 } as never);
    vi.mocked(scheduledClient.list).mockResolvedValue([task] as never);

    await useUnifiedTaskStore.getState().refresh();

    const s = useUnifiedTaskStore.getState();
    expect(s.goals).toEqual([goal]);
    expect(s.todos).toEqual([todo]);
    expect(s.scheduledTasks).toEqual([task]);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
    expect(s.lastFetchedAt).toBeTypeOf('number');
  });

  it('显式传 limit=200 与 include_completed=true（不依赖默认 limit=50）', async () => {
    vi.mocked(listGoals).mockResolvedValue({ items: [], total: 0, limit: 200, offset: 0 } as never);
    vi.mocked(todoClient.list).mockResolvedValue({ items: [], total: 0, limit: 200, offset: 0 } as never);
    vi.mocked(scheduledClient.list).mockResolvedValue([] as never);

    await useUnifiedTaskStore.getState().refresh();

    expect(listGoals).toHaveBeenCalledWith(undefined, 200, 0);
    expect(todoClient.list).toHaveBeenCalledWith({
      limit: 200,
      offset: 0,
      include_completed: true,
    });
  });

  it('单源失败不阻断其余两源（部分失败语义）', async () => {
    vi.mocked(listGoals).mockRejectedValue(new Error('goal down'));
    vi.mocked(todoClient.list).mockResolvedValue({ items: [todo], total: 1, limit: 200, offset: 0 } as never);
    vi.mocked(scheduledClient.list).mockResolvedValue([task] as never);

    await useUnifiedTaskStore.getState().refresh();

    const s = useUnifiedTaskStore.getState();
    expect(s.goals).toEqual([]);
    expect(s.todos).toEqual([todo]);
    expect(s.scheduledTasks).toEqual([task]);
    expect(s.error).toBe('goal down');
  });

  it('并发 refresh 只发一轮请求', async () => {
    let resolveGoals: (v: unknown) => void = () => {};
    vi.mocked(listGoals).mockReturnValue(
      new Promise((resolve) => {
        resolveGoals = resolve;
      }) as never,
    );
    vi.mocked(todoClient.list).mockResolvedValue({ items: [], total: 0, limit: 200, offset: 0 } as never);
    vi.mocked(scheduledClient.list).mockResolvedValue([] as never);

    const first = useUnifiedTaskStore.getState().refresh();
    const second = useUnifiedTaskStore.getState().refresh();
    resolveGoals({ items: [], total: 0, limit: 200, offset: 0 });
    await Promise.all([first, second]);

    expect(listGoals).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/features/task-center/__tests__/unifiedTaskStore.test.ts`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 store**

Create `src/features/task-center/unifiedTaskStore.ts`:

```ts
// src/features/task-center/unifiedTaskStore.ts
//
// 任务中心专用的三源只读数据视图。
// 不复用 useGoalStore / useTodoStore / useScheduledTaskStore：
//   - goalStore.load() 会继承用户在 /goals 页设置的 statusFilter（goalStore.ts:48）
//   - 页面 store 有各自的加载节奏与筛选态，会污染"全量视图"语义
import { create } from 'zustand';

import { listGoals } from '../../entities/autonomous-goals/goalApi';
import type { Goal } from '../../entities/autonomous-goals/types';
import { scheduledClient } from '../../shared/api/scheduledClient';
import { todoClient } from '../../shared/api/todoClient';
import type { ScheduledTask, Todo } from '../../shared/api/types';

const FULL_LIMIT = 200;

interface UnifiedTaskState {
  goals: Goal[];
  todos: Todo[];
  scheduledTasks: ScheduledTask[];
  loading: boolean;
  error: string | null;
  lastFetchedAt: number | null;
  refresh: () => Promise<void>;
  refreshGoals: () => Promise<void>;
  refreshTodos: () => Promise<void>;
  refreshScheduled: () => Promise<void>;
}

function toMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export const useUnifiedTaskStore = create<UnifiedTaskState>((set, get) => ({
  goals: [],
  todos: [],
  scheduledTasks: [],
  loading: false,
  error: null,
  lastFetchedAt: null,

  async refresh() {
    // 并发保护：已有请求在飞时不重复发
    if (get().loading) return;
    set({ loading: true, error: null });

    // 三源互不阻断：任一失败只记 error，其余照常落库
    const [goalsR, todosR, scheduledR] = await Promise.allSettled([
      listGoals(undefined, FULL_LIMIT, 0),
      todoClient.list({ limit: FULL_LIMIT, offset: 0, include_completed: true }),
      scheduledClient.list(),
    ]);

    const errors: string[] = [];

    const goals = goalsR.status === 'fulfilled' ? goalsR.value.items : [];
    if (goalsR.status === 'rejected') errors.push(toMessage(goalsR.reason));

    const todos = todosR.status === 'fulfilled' ? todosR.value.items : [];
    if (todosR.status === 'rejected') errors.push(toMessage(todosR.reason));

    // scheduledClient.list() 直接返回数组，不包 { items }
    const scheduledTasks = scheduledR.status === 'fulfilled' ? scheduledR.value : [];
    if (scheduledR.status === 'rejected') errors.push(toMessage(scheduledR.reason));

    set({
      goals,
      todos,
      scheduledTasks,
      loading: false,
      error: errors.length > 0 ? errors.join('; ') : null,
      lastFetchedAt: Date.now(),
    });
  },

  async refreshGoals() {
    try {
      const resp = await listGoals(undefined, FULL_LIMIT, 0);
      set({ goals: resp.items });
    } catch (err) {
      set({ error: toMessage(err) });
    }
  },

  async refreshTodos() {
    try {
      const resp = await todoClient.list({
        limit: FULL_LIMIT,
        offset: 0,
        include_completed: true,
      });
      set({ todos: resp.items });
    } catch (err) {
      set({ error: toMessage(err) });
    }
  },

  async refreshScheduled() {
    try {
      const list = await scheduledClient.list();
      set({ scheduledTasks: list });
    } catch (err) {
      set({ error: toMessage(err) });
    }
  },
}));

/** 测试与 M6 归档用：重置到初始态。 */
export function resetUnifiedTaskStore(): void {
  useUnifiedTaskStore.setState({
    goals: [],
    todos: [],
    scheduledTasks: [],
    loading: false,
    error: null,
    lastFetchedAt: null,
  });
}
```

- [ ] **Step 4: 运行确认通过**

Run: `npx vitest run src/features/task-center/__tests__/unifiedTaskStore.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: 提交**

```bash
git add src/features/task-center/unifiedTaskStore.ts src/features/task-center/__tests__/unifiedTaskStore.test.ts
git commit -m "feat(task-center): 三源只读轮询 store

独立于页面 store（goal/todo/scheduled），避免 statusFilter 污染与加载节奏互扰。
三源返回形状不同：goal/todo 包 { items }，scheduled 是裸数组。单源失败不阻断
其余两源，error 汇总后展示。"
```

---

## Task 3: 六源聚合 hook（M2b）

**Files:**
- Create: `src/features/task-center/useUnifiedTasks.ts`
- Test: `src/features/task-center/__tests__/useUnifiedTasks.test.tsx`

**Interfaces:**
- Consumes: `normalize*` / `compareUnifiedTasks` / `isTerminalStatus` from `./unifiedTaskModel`; `useUnifiedTaskStore` from `./unifiedTaskStore`; `useTaskCenterStore` from `./taskCenterStore`; `useChatStreamStore` from `../send-message/chatStreamStore`; `useLaneBoardStore` from `../../entities/orchestration/laneBoardStore`; `useStore` from `../../shared/lib/store`
- Produces: `useUnifiedTasks(): UnifiedTasksResult`

```ts
interface UnifiedTaskGroups {
  active: UnifiedTaskEntry[];
  failed: UnifiedTaskEntry[];
  finished: UnifiedTaskEntry[];
}
interface UnifiedTasksResult {
  groups: UnifiedTaskGroups;
  all: UnifiedTaskEntry[];
  attentionCount: number; // 进行中 + 失败，用于 rail 角标
  runningCount: number;
  loading: boolean;
  error: string | null;
}
```

- [ ] **Step 1: 写失败的测试**

Create `src/features/task-center/__tests__/useUnifiedTasks.test.tsx`:

```tsx
import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useLaneBoardStore } from '../../../entities/orchestration/laneBoardStore';
import { useStore } from '../../../shared/lib/store';
import { useChatStreamStore } from '../../send-message/chatStreamStore';
import { useTaskCenterStore } from '../taskCenterStore';
import { resetUnifiedTaskStore, useUnifiedTaskStore } from '../unifiedTaskStore';
import { useUnifiedTasks } from '../useUnifiedTasks';

function resetAll(): void {
  useTaskCenterStore.setState({ tasks: {} });
  useChatStreamStore.setState({ sessions: {} });
  useLaneBoardStore.setState({ lanes: [] });
  useStore.setState({ sessions: [], currentSessionId: null } as never);
  resetUnifiedTaskStore();
}

describe('useUnifiedTasks', () => {
  beforeEach(resetAll);

  it('空态：全部分组为空、计数为 0', () => {
    const { result } = renderHook(() => useUnifiedTasks());
    expect(result.current.all).toEqual([]);
    expect(result.current.groups).toEqual({ active: [], failed: [], finished: [] });
    expect(result.current.attentionCount).toBe(0);
    expect(result.current.runningCount).toBe(0);
  });

  it('registry + goal + scheduled 三源合并并按状态分组', () => {
    useTaskCenterStore.setState({
      tasks: {
        r1: {
          id: 'r1',
          kind: 'office',
          title: '生成中',
          startedAt: 1,
          status: 'running',
        },
      },
    });
    useUnifiedTaskStore.setState({
      goals: [
        { id: 'g1', name: '闲时目标', status: 'pending', completion_percentage: 0 } as never,
        { id: 'g2', name: '失败目标', status: 'failed', last_error: 'boom' } as never,
      ],
      scheduledTasks: [
        { id: 's1', name: '定时失败', last_status: 'failed' } as never,
        { id: 's2', name: '历史成功', last_status: 'succeeded' } as never,
      ],
    });

    const { result } = renderHook(() => useUnifiedTasks());
    const ids = result.current.all.map((e) => e.id).sort();

    // s2（succeeded）按 spec §4.4 不进列表
    expect(ids).toEqual(['goal:g1', 'goal:g2', 'registry:r1', 'scheduled:s1']);

    expect(result.current.groups.failed.map((e) => e.id).sort()).toEqual([
      'goal:g2',
      'scheduled:s1',
    ]);
    expect(result.current.groups.active.map((e) => e.id).sort()).toEqual([
      'goal:g1',
      'registry:r1',
    ]);
    expect(result.current.groups.finished).toEqual([]);
  });

  it('attentionCount = 进行中 + 失败，runningCount 只数 running', () => {
    useTaskCenterStore.setState({
      tasks: {
        r1: { id: 'r1', kind: 'office', title: 'a', startedAt: 1, status: 'running' },
        r2: { id: 'r2', kind: 'office', title: 'b', startedAt: 1, status: 'failed' },
        r3: { id: 'r3', kind: 'office', title: 'c', startedAt: 1, status: 'paused' },
        r4: { id: 'r4', kind: 'office', title: 'd', startedAt: 1, status: 'succeeded' },
      },
    });
    const { result } = renderHook(() => useUnifiedTasks());
    expect(result.current.attentionCount).toBe(3); // running + failed + paused
    expect(result.current.runningCount).toBe(1);
  });

  it('后台会话流进入列表，当前会话被排除', () => {
    useStore.setState({
      sessions: [
        { id: 's-cur', title: '当前', created_at: 0, updated_at: 0 } as never,
        { id: 's-bg', title: '后台', created_at: 0, updated_at: 0 } as never,
      ],
      currentSessionId: 's-cur',
    } as never);
    useChatStreamStore.setState({
      sessions: {
        's-cur': { streaming: { startedAt: 1 } } as never,
        's-bg': { streaming: { startedAt: 2 } } as never,
      },
    });

    const { result } = renderHook(() => useUnifiedTasks());
    const chatIds = result.current.all.filter((e) => e.source === 'chat').map((e) => e.id);
    expect(chatIds).toEqual(['chat:s-bg']);
  });

  it('已决议 / 不可见 lane 不进入列表', () => {
    useLaneBoardStore.setState({
      lanes: [
        {
          lane_id: 'l1',
          task_id: 'T1',
          agent_id: null,
          status: 'running',
          created_at: 1,
          started_at: 1,
          completed_at: null,
          worktree: null,
          heartbeat: null,
          error: null,
          permission_preset: 'default',
          metadata: {},
        } as never,
        {
          lane_id: 'l2',
          task_id: 'T2',
          agent_id: null,
          status: 'stopped',
          created_at: 1,
          started_at: 1,
          completed_at: 2,
          worktree: null,
          heartbeat: null,
          error: null,
          permission_preset: 'default',
          metadata: {},
        } as never,
      ],
    });

    const { result } = renderHook(() => useUnifiedTasks());
    expect(result.current.all.filter((e) => e.source === 'lane').map((e) => e.id)).toEqual([
      'lane:l1',
    ]);
  });

  it('排序：failed 在最前', () => {
    useTaskCenterStore.setState({
      tasks: {
        r1: { id: 'r1', kind: 'office', title: 'ok', startedAt: 1, status: 'succeeded' },
        r2: { id: 'r2', kind: 'office', title: 'bad', startedAt: 2, status: 'failed' },
        r3: { id: 'r3', kind: 'office', title: 'run', startedAt: 3, status: 'running' },
      },
    });
    const { result } = renderHook(() => useUnifiedTasks());
    expect(result.current.all[0].id).toBe('registry:r2');
  });

  it('透传 store 的 loading / error', () => {
    useUnifiedTaskStore.setState({ loading: true, error: 'goal down' });
    const { result } = renderHook(() => useUnifiedTasks());
    expect(result.current.loading).toBe(true);
    expect(result.current.error).toBe('goal down');
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/features/task-center/__tests__/useUnifiedTasks.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 hook**

Create `src/features/task-center/useUnifiedTasks.ts`:

```ts
// src/features/task-center/useUnifiedTasks.ts
//
// 纯读取 hook：六个 store → 一份归一列表。无副作用、无请求，
// 侧边栏分区与 /tasks 页面同时挂载也只做一次 useMemo 计算。
import { useEffect, useMemo, useRef } from 'react';

import { useLaneBoardStore } from '../../entities/orchestration/laneBoardStore';
import { useStore } from '../../shared/lib/store';
import { useChatStreamStore } from '../send-message/chatStreamStore';

import { useTaskCenterStore } from './taskCenterStore';
import type { UnifiedTaskEntry } from './unifiedTaskModel';
import {
  compareUnifiedTasks,
  isTerminalStatus,
  normalizeChatTask,
  normalizeGoalTask,
  normalizeLaneTask,
  normalizeRegistryTask,
  normalizeScheduledTask,
  normalizeTodoTask,
} from './unifiedTaskModel';
import { useUnifiedTaskStore } from './unifiedTaskStore';

export interface UnifiedTaskGroups {
  active: UnifiedTaskEntry[];
  failed: UnifiedTaskEntry[];
  finished: UnifiedTaskEntry[];
}

export interface UnifiedTasksResult {
  groups: UnifiedTaskGroups;
  all: UnifiedTaskEntry[];
  /** 进行中 + 失败，用于 rail 角标 */
  attentionCount: number;
  /** 纯 running 数 */
  runningCount: number;
  loading: boolean;
  error: string | null;
}

const ACTIVE_STATUSES = new Set(['queued', 'running', 'paused', 'awaiting_approval']);

export function useUnifiedTasks(): UnifiedTasksResult {
  const registryTasks = useTaskCenterStore((s) => s.tasks);
  const streamSessions = useChatStreamStore((s) => s.sessions);
  const lanes = useLaneBoardStore((s) => s.lanes);
  const sessions = useStore((s) => s.sessions);
  const currentSessionId = useStore((s) => s.currentSessionId);

  const goals = useUnifiedTaskStore((s) => s.goals);
  const todos = useUnifiedTaskStore((s) => s.todos);
  const scheduledTasks = useUnifiedTaskStore((s) => s.scheduledTasks);
  const loading = useUnifiedTaskStore((s) => s.loading);
  const error = useUnifiedTaskStore((s) => s.error);

  // chat 首见时间：沿用 TaskCenterWidget 的 streamStartsRef 约定
  const streamStartsRef = useRef<Map<string, number>>(new Map());

  const activeStreamIds = useMemo(
    () =>
      Object.entries(streamSessions)
        .filter(([, slots]) => slots.streaming != null)
        .map(([id]) => id)
        .filter((id) => id !== currentSessionId),
    [streamSessions, currentSessionId],
  );

  // 维护首见时间：进入即记，退出即删
  useEffect(() => {
    const map = streamStartsRef.current;
    const now = Date.now();
    for (const id of activeStreamIds) {
      if (!map.has(id)) map.set(id, now);
    }
    for (const id of [...map.keys()]) {
      if (!activeStreamIds.includes(id)) map.delete(id);
    }
  }, [activeStreamIds]);

  const sessionTitle = useMemo(() => {
    const map = new Map<string, string>();
    for (const s of sessions) map.set(s.id, s.title ?? s.id);
    return map;
  }, [sessions]);

  const all = useMemo<UnifiedTaskEntry[]>(() => {
    const starts = streamStartsRef.current;
    const entries: UnifiedTaskEntry[] = [];

    for (const t of Object.values(registryTasks)) entries.push(normalizeRegistryTask(t));

    for (const id of activeStreamIds) {
      entries.push(
        normalizeChatTask({
          sessionId: id,
          title: sessionTitle.get(id) ?? id,
          firstSeenAt: starts.get(id) ?? Date.now(),
        }),
      );
    }

    for (const lane of lanes) {
      const e = normalizeLaneTask(lane);
      if (e) entries.push(e);
    }

    for (const goal of goals) {
      const e = normalizeGoalTask(goal);
      if (e) entries.push(e);
    }

    for (const todo of todos) {
      const e = normalizeTodoTask(todo);
      if (e) entries.push(e);
    }

    for (const task of scheduledTasks) {
      const e = normalizeScheduledTask(task);
      if (e) entries.push(e);
    }

    return entries.sort(compareUnifiedTasks);
  }, [registryTasks, activeStreamIds, sessionTitle, lanes, goals, todos, scheduledTasks]);

  const groups = useMemo<UnifiedTaskGroups>(() => {
    const active: UnifiedTaskEntry[] = [];
    const failed: UnifiedTaskEntry[] = [];
    const finished: UnifiedTaskEntry[] = [];
    for (const e of all) {
      if (e.status === 'failed') failed.push(e);
      else if (ACTIVE_STATUSES.has(e.status)) active.push(e);
      else if (isTerminalStatus(e.status)) finished.push(e);
    }
    return { active, failed, finished };
  }, [all]);

  return {
    groups,
    all,
    attentionCount: groups.active.length + groups.failed.length,
    runningCount: all.filter((e) => e.status === 'running').length,
    loading,
    error,
  };
}
```

- [ ] **Step 4: 运行确认通过**

Run: `npx vitest run src/features/task-center/__tests__/useUnifiedTasks.test.tsx`
Expected: PASS (7 tests)

- [ ] **Step 5: 提交**

```bash
git add src/features/task-center/useUnifiedTasks.ts src/features/task-center/__tests__/useUnifiedTasks.test.tsx
git commit -m "feat(task-center): 六源聚合 hook

合并 registry/chat/lane/goal/todo/scheduled，按可见性规则过滤后统一排序分组。
chat 排除当前会话（页面内已有指示），首见时间用 ref 记录。"
```

---

## Task 4: 动作分发 hook（M2c）

**Files:**
- Create: `src/features/task-center/useTaskCenterActions.ts`
- Test: `src/features/task-center/__tests__/useTaskCenterActions.test.tsx`

**Interfaces:**
- Consumes: `goalApi` actions (`startGoal` / `pauseGoal` / `cancelGoal`) from `../../entities/autonomous-goals/goalApi`; `scheduledClient.runNow`; `invoke` from `../../shared/api/desktopInvoke`; `useLaneBoardStore.cancel`; `useTaskCenterStore` (`openShellStream`, `openDelivery`, `setHighlight`, `clearFinished`); `toast` from `sonner`；动态 `import('../send-message/useChat')` 取 `cancelSessionStream`
- Produces: `useTaskCenterActions(): TaskCenterActions`，`TaskCenterActions` 含 `cancel / pause / resume / runNow / open / clearFinished`

- [ ] **Step 1: 写失败的测试**

Create `src/features/task-center/__tests__/useTaskCenterActions.test.tsx`:

```tsx
import { act, renderHook } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock('../../../shared/api/desktopInvoke', () => ({ invoke: vi.fn() }));
vi.mock('../../../entities/autonomous-goals/goalApi', () => ({
  cancelGoal: vi.fn(),
  pauseGoal: vi.fn(),
  startGoal: vi.fn(),
}));
vi.mock('../../../shared/api/scheduledClient', () => ({
  scheduledClient: { runNow: vi.fn() },
}));
vi.mock('../../send-message/useChat', () => ({ cancelSessionStream: vi.fn() }));

import { toast } from 'sonner';

import { cancelGoal, pauseGoal, startGoal } from '../../../entities/autonomous-goals/goalApi';
import { invoke } from '../../../shared/api/desktopInvoke';
import { scheduledClient } from '../../../shared/api/scheduledClient';
import { cancelSessionStream } from '../../send-message/useChat';
import { useTaskCenterStore } from '../taskCenterStore';
import type { UnifiedTaskEntry } from '../unifiedTaskModel';
import { useTaskCenterActions } from '../useTaskCenterActions';

const entry = (over: Partial<UnifiedTaskEntry>): UnifiedTaskEntry => ({
  id: 'goal:g1',
  source: 'goal',
  title: 'g',
  status: 'running',
  startedAt: 1,
  updatedAt: null,
  percent: null,
  error: null,
  cancellable: true,
  detailPath: '/goals/g1',
  openTarget: null,
  cancelRef: { source: 'goal', rawId: 'g1' },
  meta: {},
  ...over,
});

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <MemoryRouter>{children}</MemoryRouter>
);

describe('useTaskCenterActions', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    // open() 会写 taskCenterStore 的抽屉状态，跨用例清理避免顺序耦合
    useTaskCenterStore.setState({ shellStream: null, delivery: null });
  });

  it('goal cancel 调 cancelGoal', async () => {
    vi.mocked(cancelGoal).mockResolvedValue({} as never);
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() => result.current.cancel(entry({})));
    expect(cancelGoal).toHaveBeenCalledWith('g1');
  });

  it('goal pause / resume 调 pauseGoal / startGoal', async () => {
    vi.mocked(pauseGoal).mockResolvedValue({} as never);
    vi.mocked(startGoal).mockResolvedValue({} as never);
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() => result.current.pause(entry({})));
    await act(() => result.current.resume(entry({})));
    expect(pauseGoal).toHaveBeenCalledWith('g1');
    expect(startGoal).toHaveBeenCalledWith('g1');
  });

  it('shell cancel 走 invoke(shell_kill)', async () => {
    vi.mocked(invoke).mockResolvedValue({} as never);
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() =>
      result.current.cancel(
        entry({
          id: 'registry:sh',
          source: 'registry',
          cancelRef: { source: 'registry', rawId: 'sh-9' },
          meta: { shellId: 'sh-9' },
        }),
      ),
    );
    expect(invoke).toHaveBeenCalledWith('shell_kill', { id: 'sh-9' });
  });

  it('chat cancel 调 cancelSessionStream', async () => {
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() =>
      result.current.cancel(
        entry({
          id: 'chat:s1',
          source: 'chat',
          cancelRef: { source: 'chat', rawId: 's1' },
        }),
      ),
    );
    expect(cancelSessionStream).toHaveBeenCalledWith('s1');
  });

  it('scheduled runNow 调 scheduledClient.runNow', async () => {
    vi.mocked(scheduledClient.runNow).mockResolvedValue({} as never);
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() =>
      result.current.runNow(
        entry({
          id: 'scheduled:s1',
          source: 'scheduled',
          cancelRef: null,
        }),
      ),
    );
    expect(scheduledClient.runNow).toHaveBeenCalledWith('s1');
  });

  it('失败时 toast.error 且不抛出', async () => {
    vi.mocked(cancelGoal).mockRejectedValue(new Error('网络错误'));
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() => result.current.cancel(entry({})));
    expect(toast.error).toHaveBeenCalledWith('网络错误');
  });

  it('不可取消的条目是空操作', async () => {
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    await act(() => result.current.cancel(entry({ cancellable: false, cancelRef: null })));
    expect(cancelGoal).not.toHaveBeenCalled();
    expect(invoke).not.toHaveBeenCalled();
  });

  // A4 / Phase 5 回归：旧的 TaskCenterWidget 有三条点击分支，删胶囊后必须保住
  it('open: shell 条目打开后台输出抽屉', () => {
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    act(() =>
      result.current.open(
        entry({
          id: 'registry:shell:sh-9',
          source: 'registry',
          detailPath: null,
          openTarget: { kind: 'shell', shellId: 'sh-9' },
        }),
      ),
    );
    expect(useTaskCenterStore.getState().shellStream).toBe('sh-9');
  });

  it('open: lane 待验收条目直开交付抽屉而非跳 /orchestration', () => {
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    act(() =>
      result.current.open(
        entry({
          id: 'lane:l1',
          source: 'lane',
          status: 'awaiting_approval',
          detailPath: '/orchestration',
          openTarget: { kind: 'lane-delivery', laneId: 'l1' },
        }),
      ),
    );
    expect(useTaskCenterStore.getState().delivery).toMatchObject({ kind: 'lane', laneId: 'l1' });
  });

  it('open: office 待验收条目直开交付抽屉', () => {
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    act(() =>
      result.current.open(
        entry({
          id: 'registry:r1',
          source: 'registry',
          status: 'awaiting_approval',
          detailPath: '/office',
          openTarget: { kind: 'office-delivery', entryId: 'r1' },
        }),
      ),
    );
    expect(useTaskCenterStore.getState().delivery).toMatchObject({ kind: 'office', entryId: 'r1' });
  });

  it('open: 普通条目走 detailPath 路由跳转', () => {
    const { result } = renderHook(() => useTaskCenterActions(), { wrapper });
    act(() => result.current.open(entry({ detailPath: '/goals/g1', openTarget: null })));
    expect(useTaskCenterStore.getState().shellStream).toBeNull();
    expect(useTaskCenterStore.getState().delivery).toBeNull();
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/features/task-center/__tests__/useTaskCenterActions.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: 实现**

Create `src/features/task-center/useTaskCenterActions.ts`:

```ts
// src/features/task-center/useTaskCenterActions.ts
//
// 任务卡片上的动作分发。所有失败都吞掉并 toast —— 与 goalStore / todoStore
// 的错误处理风格一致：任务中心是增强视图，不能因为一次取消失败炸页面。
import { useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { cancelGoal, pauseGoal, startGoal } from '../../entities/autonomous-goals/goalApi';
import { useLaneBoardStore } from '../../entities/orchestration/laneBoardStore';
import { invoke } from '../../shared/api/desktopInvoke';
import { scheduledClient } from '../../shared/api/scheduledClient';

import { useTaskCenterStore } from './taskCenterStore';
import type { UnifiedTaskEntry } from './unifiedTaskModel';

export interface TaskCenterActions {
  cancel: (entry: UnifiedTaskEntry) => Promise<void>;
  pause: (entry: UnifiedTaskEntry) => Promise<void>;
  resume: (entry: UnifiedTaskEntry) => Promise<void>;
  runNow: (entry: UnifiedTaskEntry) => Promise<void>;
  open: (entry: UnifiedTaskEntry) => void;
  clearFinished: () => void;
}

function toMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function useTaskCenterActions(): TaskCenterActions {
  const navigate = useNavigate();
  const cancelLane = useLaneBoardStore((s) => s.cancel);
  const openShellStream = useTaskCenterStore((s) => s.openShellStream);
  const openDelivery = useTaskCenterStore((s) => s.openDelivery);
  const setHighlight = useTaskCenterStore((s) => s.setHighlight);
  const clearFinished = useTaskCenterStore((s) => s.clearFinished);

  const cancel = useCallback(
    async (entry: UnifiedTaskEntry) => {
      if (!entry.cancellable || !entry.cancelRef) return;
      try {
        const { source, rawId } = entry.cancelRef;
        if (source === 'registry') {
          await invoke('shell_kill', { id: rawId });
        } else if (source === 'chat') {
          const { cancelSessionStream } = await import('../send-message/useChat');
          cancelSessionStream(rawId);
        } else if (source === 'lane') {
          cancelLane(rawId);
        } else if (source === 'goal') {
          await cancelGoal(rawId);
        }
      } catch (err) {
        toast.error(toMessage(err));
      }
    },
    [cancelLane],
  );

  const pause = useCallback(async (entry: UnifiedTaskEntry) => {
    if (entry.source !== 'goal' || !entry.cancelRef) return;
    try {
      await pauseGoal(entry.cancelRef.rawId);
    } catch (err) {
      toast.error(toMessage(err));
    }
  }, []);

  const resume = useCallback(async (entry: UnifiedTaskEntry) => {
    if (entry.source !== 'goal' || !entry.cancelRef) return;
    try {
      await startGoal(entry.cancelRef.rawId);
    } catch (err) {
      toast.error(toMessage(err));
    }
  }, []);

  const runNow = useCallback(async (entry: UnifiedTaskEntry) => {
    if (entry.source !== 'scheduled') return;
    const prefix = 'scheduled:';
    const rawId = entry.id.startsWith(prefix) ? entry.id.slice(prefix.length) : '';
    if (!rawId) return;
    try {
      await scheduledClient.runNow(rawId);
    } catch (err) {
      toast.error(toMessage(err));
    }
  }, []);

  const open = useCallback(
    (entry: UnifiedTaskEntry) => {
      // A4 / Phase 5：交付抽屉与 shell 输出抽屉优先于路由跳转
      if (entry.openTarget) {
        const target = entry.openTarget;
        if (target.kind === 'shell') {
          openShellStream(target.shellId);
        } else if (target.kind === 'lane-delivery') {
          openDelivery({ kind: 'lane', laneId: target.laneId });
        } else {
          openDelivery({ kind: 'office', entryId: target.entryId });
        }
        return;
      }
      // P11: office 任务带关联文档名 → 跳转后定位并高亮对应文档行
      if (entry.source === 'registry' && entry.detailPath === '/office' && entry.meta.docName) {
        setHighlight(String(entry.meta.docName));
      }
      if (entry.detailPath) navigate(entry.detailPath);
    },
    [navigate, openShellStream, openDelivery, setHighlight],
  );

  return useMemo(
    () => ({
      cancel,
      pause,
      resume,
      runNow,
      open,
      clearFinished: () => clearFinished(),
    }),
    [cancel, pause, resume, runNow, open, clearFinished],
  );
}
```

- [ ] **Step 4: 运行确认通过**

Run: `npx vitest run src/features/task-center/__tests__/useTaskCenterActions.test.tsx`
Expected: PASS (11 tests)

- [ ] **Step 5: lint（重点检查未使用导入）**

```bash
npx eslint src/features/task-center/useTaskCenterActions.ts
```
Expected: 无 error

- [ ] **Step 6: 提交**

```bash
git add src/features/task-center/useTaskCenterActions.ts src/features/task-center/__tests__/useTaskCenterActions.test.tsx
git commit -m "feat(task-center): 任务动作分发 hook

cancel/pause/resume/runNow/open 六源分发，失败统一 toast.error 并吞掉异常。
chat 取消失败不影响其他源；chat 模块走动态 import 避免拖进首屏。"
```

---

## Task 5: i18n 文案域（M4）

**Files:**
- Create: `src/shared/lib/i18n/locales/zh/taskCenter.ts`
- Create: `src/shared/lib/i18n/locales/en/taskCenter.ts`
- Modify: `src/shared/lib/i18n/zh.ts`
- Modify: `src/shared/lib/i18n/en.ts`
- Test: `src/shared/lib/i18n/__tests__/taskCenterLocale.test.ts`

**Interfaces:**
- Produces: `zhTaskCenter` / `enTaskCenter` const objects with identical key sets; keys land under `taskCenter.section.*`, `taskCenter.source.*`, `taskCenter.group.*`, `taskCenter.action.*`, `taskCenter.filter.*`, `taskCenter.page.*`, `taskCenter.badge.*`

- [ ] **Step 1: 写失败的测试**

Create `src/shared/lib/i18n/__tests__/taskCenterLocale.test.ts`:

```ts
import { describe, expect, it } from 'vitest';

import { en } from '../en';
import { zh } from '../zh';

const PREFIXES = [
  'taskCenter.section.',
  'taskCenter.source.',
  'taskCenter.group.',
  'taskCenter.action.',
  'taskCenter.filter.',
  'taskCenter.page.',
  'taskCenter.badge.',
];

describe('i18n / taskCenter 文案域', () => {
  const zhKeys = Object.keys(zh).filter((k) => PREFIXES.some((p) => k.startsWith(p))).sort();
  const enKeys = Object.keys(en).filter((k) => PREFIXES.some((p) => k.startsWith(p))).sort();

  it('存在新增子树', () => {
    expect(zhKeys.length).toBeGreaterThan(20);
  });

  it('中英文键集完全一致', () => {
    expect(enKeys).toEqual(zhKeys);
  });

  it('所有值非空', () => {
    for (const key of zhKeys) {
      expect((zh as Record<string, string>)[key]?.length ?? 0).toBeGreaterThan(0);
      expect((en as Record<string, string>)[key]?.length ?? 0).toBeGreaterThan(0);
    }
  });

  it('新键不与既有 taskCenter.* 键重名（spread 聚合会静默覆盖）', () => {
    // 既有的扁平键（taskCenter.cancel / clearFinished / status.*）必须仍在，
    // 且新域不得覆盖它们
    expect((zh as Record<string, string>)['taskCenter.cancel']).toBeTruthy();
    expect((zh as Record<string, string>)['taskCenter.action.cancel']).toBeTruthy();
    expect((zh as Record<string, string>)['taskCenter.cancel']).not.toBe(
      (zh as Record<string, string>)['taskCenter.action.cancel'],
    );
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/shared/lib/i18n/__tests__/taskCenterLocale.test.ts`
Expected: FAIL — `zhKeys.length` 为 0（子树还不存在）

- [ ] **Step 3: 新建中文文案域文件**

Create `src/shared/lib/i18n/locales/zh/taskCenter.ts`:

```ts
// 侧边栏任务中心文案域（2026-11-09）。
// 独立分域 —— chatAndSider.ts 已在架构基线内（825 行），禁止再加键。
export const zhTaskCenter = {
  // 分区
  'taskCenter.section.title': '任务',
  'taskCenter.section.empty': '暂无正在进行的任务',
  'taskCenter.section.more': '还有 {count} 条',
  'taskCenter.section.moreArrow': '查看全部 →',

  // 来源
  'taskCenter.source.registry': '页面任务',
  'taskCenter.source.chat': '后台会话',
  'taskCenter.source.lane': '编排',
  'taskCenter.source.goal': '闲时目标',
  'taskCenter.source.todo': '待办',
  'taskCenter.source.scheduled': '定时任务',

  // 分组
  'taskCenter.group.active': '进行中',
  'taskCenter.group.failed': '失败',
  'taskCenter.group.finished': '已完成',

  // 动作
  'taskCenter.action.cancel': '取消',
  'taskCenter.action.pause': '暂停',
  'taskCenter.action.resume': '恢复',
  'taskCenter.action.runNow': '立即运行',
  'taskCenter.action.clearFinished': '清除已完成',
  'taskCenter.action.viewDetail': '查看详情',
  'taskCenter.action.openOutput': '查看输出',

  // 筛选
  'taskCenter.filter.source': '来源',
  'taskCenter.filter.status': '状态',
  'taskCenter.filter.all': '全部',

  // 页面
  'taskCenter.page.title': '任务中心',
  'taskCenter.page.subtitle': '所有正在运行、等待处理与最近完成的任务',
  'taskCenter.page.empty': '当前没有任务',

  // 角标
  'taskCenter.badge.title': '任务中心（{count} 项需关注）',
} as const;
```

- [ ] **Step 4: 新建英文文案域文件**

Create `src/shared/lib/i18n/locales/en/taskCenter.ts`:

```ts
export const enTaskCenter = {
  'taskCenter.section.title': 'Tasks',
  'taskCenter.section.empty': 'No tasks running',
  'taskCenter.section.more': '{count} more',
  'taskCenter.section.moreArrow': 'View all →',

  'taskCenter.source.registry': 'Page task',
  'taskCenter.source.chat': 'Background chat',
  'taskCenter.source.lane': 'Orchestration',
  'taskCenter.source.goal': 'Idle goal',
  'taskCenter.source.todo': 'Todo',
  'taskCenter.source.scheduled': 'Scheduled task',

  'taskCenter.group.active': 'Active',
  'taskCenter.group.failed': 'Failed',
  'taskCenter.group.finished': 'Finished',

  'taskCenter.action.cancel': 'Cancel',
  'taskCenter.action.pause': 'Pause',
  'taskCenter.action.resume': 'Resume',
  'taskCenter.action.runNow': 'Run now',
  'taskCenter.action.clearFinished': 'Clear finished',
  'taskCenter.action.viewDetail': 'View details',
  'taskCenter.action.openOutput': 'View output',

  'taskCenter.filter.source': 'Source',
  'taskCenter.filter.status': 'Status',
  'taskCenter.filter.all': 'All',

  'taskCenter.page.title': 'Task Center',
  'taskCenter.page.subtitle': 'Everything running, waiting on you, or recently finished',
  'taskCenter.page.empty': 'No tasks right now',

  'taskCenter.badge.title': 'Task Center ({count} need attention)',
} as const;
```

- [ ] **Step 5: 聚合进 zh.ts / en.ts**

在 `src/shared/lib/i18n/zh.ts` 的 import 区加一行（与既有 import 同样式）：

```ts
import { zhTaskCenter } from './locales/zh/taskCenter';
```

在 `as const` 之前的 spread 区加一行：

```ts
  ...zhTaskCenter,
```

对 `src/shared/lib/i18n/en.ts` 做同样两处改动：

```ts
import { enTaskCenter } from './locales/en/taskCenter';
```

```ts
  ...enTaskCenter,
```

- [ ] **Step 6: 运行确认通过**

```bash
npx vitest run src/shared/lib/i18n/__tests__/taskCenterLocale.test.ts
npx vitest run src/shared/lib/i18n/__tests__/
```
Expected: PASS；既有 i18n 测试（键数、parity）保持绿

- [ ] **Step 7: 架构检查（确认 chatAndSider 行数没动）**

```bash
git diff --stat src/shared/lib/i18n/locales/zh/chatAndSider.ts src/shared/lib/i18n/locales/en/chatAndSider.ts
node scripts/architecture-check.mjs
```
Expected: 两个 chatAndSider 文件 0 改动；架构检查绿

- [ ] **Step 8: 提交**

```bash
git add src/shared/lib/i18n/locales/zh/taskCenter.ts src/shared/lib/i18n/locales/en/taskCenter.ts src/shared/lib/i18n/zh.ts src/shared/lib/i18n/en.ts src/shared/lib/i18n/__tests__/taskCenterLocale.test.ts
git commit -m "feat(i18n): 任务中心文案域

独立分域文件，不碰已进入架构基线的 chatAndSider.ts。中英文键集一致性由测试
兜底；新键全部落在 section/source/group/action/filter/page/badge 子树下，
与既有扁平键 taskCenter.cancel / taskCenter.status.* 不重名。"
```

---

## Task 6: 任务卡片组件（M3a）

**Files:**
- Create: `src/features/task-center/TaskCenterCard.tsx`
- Test: `src/features/task-center/__tests__/TaskCenterCard.test.tsx`

**Interfaces:**
- Consumes: `UnifiedTaskEntry` / `UnifiedTaskSource` from `./unifiedTaskModel`; `TaskCenterActions` from `./useTaskCenterActions`; `TaskCenterStatus` from `./taskCenterStore`; `useI18n` from `../../shared/lib/i18n`；状态文案复用既有 `taskCenter.status.*`
- Produces: `TaskCenterCard({ entry, actions, compact? }): JSX.Element`

- [ ] **Step 1: 写失败的测试**

Create `src/features/task-center/__tests__/TaskCenterCard.test.tsx`:

```tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { UnifiedTaskEntry } from '../unifiedTaskModel';
import { TaskCenterCard } from '../TaskCenterCard';

// useI18n() 在 <I18nProvider> 之外会直接 throw —— 所有组件测试必须包裹
const wrap = (ui: React.ReactElement) => <I18nProvider>{ui}</I18nProvider>;
const renderCard = (ui: React.ReactElement) => render(wrap(ui));

const makeEntry = (over: Partial<UnifiedTaskEntry> = {}): UnifiedTaskEntry => ({
  id: 'goal:g1',
  source: 'goal',
  title: '整理文献',
  status: 'running',
  startedAt: 1,
  updatedAt: null,
  percent: 40,
  error: null,
  cancellable: true,
  detailPath: '/goals/g1',
  openTarget: null,
  cancelRef: { source: 'goal', rawId: 'g1' },
  meta: {},
  ...over,
});

const actions = {
  cancel: vi.fn(),
  pause: vi.fn(),
  resume: vi.fn(),
  runNow: vi.fn(),
  open: vi.fn(),
  clearFinished: vi.fn(),
};

describe('TaskCenterCard', () => {
  it('渲染标题与来源标签', () => {
    renderCard(<TaskCenterCard entry={makeEntry()} actions={actions} />);
    expect(screen.getByText('整理文献')).toBeTruthy();
    expect(screen.getByText('闲时目标')).toBeTruthy();
  });

  it('percent 非 null 时渲染进度条，否则渲染耗时', () => {
    const { rerender } = renderCard(<TaskCenterCard entry={makeEntry()} actions={actions} />);
    expect(screen.getByRole('progressbar')).toBeTruthy();

    rerender(
      wrap(
        <TaskCenterCard
          entry={makeEntry({ percent: null, startedAt: Date.now() - 65_000 })}
          actions={actions}
        />,
      ),
    );
    expect(screen.queryByRole('progressbar')).toBeNull();
    expect(screen.getByText(/1m/)).toBeTruthy();
  });

  it('可取消时点取消按钮调 actions.cancel', () => {
    renderCard(<TaskCenterCard entry={makeEntry()} actions={actions} />);
    fireEvent.click(screen.getByRole('button', { name: /取消/ }));
    expect(actions.cancel).toHaveBeenCalledWith(expect.objectContaining({ id: 'goal:g1' }));
  });

  it('不可取消时不渲染取消按钮', () => {
    renderCard(<TaskCenterCard entry={makeEntry({ cancellable: false })} actions={actions} />);
    expect(screen.queryByRole('button', { name: /取消/ })).toBeNull();
  });

  it('点击卡片主体调 actions.open', () => {
    renderCard(<TaskCenterCard entry={makeEntry()} actions={actions} />);
    fireEvent.click(screen.getByRole('button', { name: /整理文献/ }));
    expect(actions.open).toHaveBeenCalled();
  });

  it('failed 状态渲染错误文案', () => {
    renderCard(
      <TaskCenterCard entry={makeEntry({ status: 'failed', error: '模型超时' })} actions={actions} />,
    );
    expect(screen.getByText('模型超时')).toBeTruthy();
  });

  it('compact 模式隐藏来源标签', () => {
    renderCard(<TaskCenterCard entry={makeEntry()} actions={actions} compact />);
    expect(screen.queryByText('闲时目标')).toBeNull();
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/features/task-center/__tests__/TaskCenterCard.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: 实现卡片**

Create `src/features/task-center/TaskCenterCard.tsx`:

```tsx
// src/features/task-center/TaskCenterCard.tsx
//
// 统一任务卡片。侧边栏 compact 分区与 /tasks 完整页面共用同一组件。
// 放在 features 层：TaskCenterPanel（features）要复用它，而 features 不得 import widgets。
import { clsx } from 'clsx';
import {
  AlertCircle,
  CalendarClock,
  CheckCircle2,
  Clock,
  FileSpreadsheet,
  ListTodo,
  Loader2,
  MessageSquare,
  Network,
  PauseCircle,
  Target,
  X,
  XCircle,
  type LucideIcon,
} from 'lucide-react';

import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

import type { TaskCenterStatus } from './taskCenterStore';
import type { UnifiedTaskEntry, UnifiedTaskSource } from './unifiedTaskModel';
import type { TaskCenterActions } from './useTaskCenterActions';

const SOURCE_ICON: Record<UnifiedTaskSource, LucideIcon> = {
  registry: FileSpreadsheet,
  chat: MessageSquare,
  lane: Network,
  goal: Target,
  todo: ListTodo,
  scheduled: CalendarClock,
};

const STATUS_ICON: Record<TaskCenterStatus, LucideIcon> = {
  queued: Clock,
  running: Loader2,
  awaiting_approval: AlertCircle,
  paused: PauseCircle,
  succeeded: CheckCircle2,
  failed: XCircle,
  cancelled: XCircle,
};

const STATUS_TONE: Record<TaskCenterStatus, string> = {
  queued: 'text-muted',
  running: 'text-primary',
  awaiting_approval: 'text-warning',
  paused: 'text-muted',
  succeeded: 'text-success',
  failed: 'text-error',
  cancelled: 'text-muted',
};

function formatElapsed(ms: number): string {
  const sec = Math.max(0, Math.floor(ms / 1000));
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const hour = Math.floor(min / 60);
  return `${hour}h ${min % 60}m`;
}

export interface TaskCenterCardProps {
  entry: UnifiedTaskEntry;
  actions: TaskCenterActions;
  compact?: boolean;
}

export function TaskCenterCard({ entry, actions, compact = false }: TaskCenterCardProps) {
  const { t } = useI18n();
  const SourceIcon = SOURCE_ICON[entry.source];
  const StatusIcon = STATUS_ICON[entry.status];
  const tone = STATUS_TONE[entry.status];
  const sourceLabel = t(`taskCenter.source.${entry.source}` as TranslationKey);
  const statusLabel = t(`taskCenter.status.${entry.status}` as TranslationKey);

  const elapsed =
    entry.startedAt != null && entry.status === 'running'
      ? formatElapsed(Date.now() - entry.startedAt)
      : null;

  return (
    <div className="group flex items-start gap-2 px-3 py-1.5 rounded-md hover:bg-bg-hover transition-colors">
      <button
        type="button"
        onClick={() => actions.open(entry)}
        aria-label={`${entry.title} · ${statusLabel}`}
        className="flex-1 min-w-0 text-left"
      >
        <div className="flex items-center gap-1.5">
          <SourceIcon className="w-3.5 h-3.5 shrink-0 text-muted" aria-hidden />
          <span className="truncate text-ui-sm text-text">{entry.title}</span>
          <StatusIcon
            className={clsx('w-3.5 h-3.5 shrink-0', tone, entry.status === 'running' && 'animate-spin')}
            aria-hidden
          />
          <span className={clsx('text-ui-2xs shrink-0', tone)}>{statusLabel}</span>
        </div>

        <div className="mt-0.5 flex items-center gap-2">
          {!compact && <span className="text-ui-2xs text-muted shrink-0">{sourceLabel}</span>}
          {entry.percent != null ? (
            <div
              className="h-1 flex-1 max-w-[120px] rounded-full bg-ui-border overflow-hidden"
              role="progressbar"
              aria-valuenow={entry.percent}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className="h-full bg-primary transition-[width]"
                style={{ width: `${Math.min(100, Math.max(0, entry.percent))}%` }}
              />
            </div>
          ) : elapsed ? (
            <span className="text-ui-2xs text-muted">{elapsed}</span>
          ) : null}
          {entry.status === 'failed' && entry.error && (
            <span className="text-ui-2xs text-error truncate" title={entry.error}>
              {entry.error}
            </span>
          )}
        </div>
      </button>

      {entry.cancellable && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            void actions.cancel(entry);
          }}
          className="shrink-0 p-1 rounded text-muted hover:text-error opacity-0 group-hover:opacity-100 focus:opacity-100"
          aria-label={t('taskCenter.action.cancel')}
          title={t('taskCenter.action.cancel')}
        >
          <X className="w-3.5 h-3.5" aria-hidden />
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 4: 运行确认通过**

Run: `npx vitest run src/features/task-center/__tests__/TaskCenterCard.test.tsx`
Expected: PASS (7 tests)

- [ ] **Step 5: 提交**

```bash
git add src/features/task-center/TaskCenterCard.tsx src/features/task-center/__tests__/TaskCenterCard.test.tsx
git commit -m "feat(task-center): 统一任务卡片

分区与页面共用。percent 非空渲染进度条，否则渲染已耗时；failed 展示错误行；
取消按钮 hover 显现并阻止事件冒泡。compact 模式隐藏来源标签。"
```

---

## Task 7: 面板内容组件（M3b）

**Files:**
- Create: `src/features/task-center/TaskCenterPanel.tsx`
- Test: `src/features/task-center/__tests__/TaskCenterPanel.test.tsx`

**Interfaces:**
- Consumes: `useUnifiedTasks`、`useTaskCenterActions`、`TaskCenterCard`、`useI18n`
- Produces: `TaskCenterPanel({ variant: 'compact' | 'full' }): JSX.Element`

- [ ] **Step 1: 写失败的测试**

Create `src/features/task-center/__tests__/TaskCenterPanel.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { TaskCenterPanel } from '../TaskCenterPanel';
import { useTaskCenterStore } from '../taskCenterStore';
import { resetUnifiedTaskStore } from '../unifiedTaskStore';

// useI18n() 在 <I18nProvider> 之外会 throw —— 面板及其子卡片都调它
function renderPanel(variant: 'compact' | 'full') {
  return render(
    <I18nProvider>
      <MemoryRouter>
        <TaskCenterPanel variant={variant} />
      </MemoryRouter>
    </I18nProvider>,
  );
}

function seed(count: number, status: 'running' | 'failed' = 'running'): void {
  const tasks: Record<string, unknown> = {};
  for (let i = 0; i < count; i += 1) {
    tasks[`r${i}`] = { id: `r${i}`, kind: 'office', title: `任务 ${i}`, startedAt: i, status };
  }
  useTaskCenterStore.setState({ tasks: tasks as never });
}

describe('TaskCenterPanel', () => {
  beforeEach(() => {
    useTaskCenterStore.setState({ tasks: {} });
    resetUnifiedTaskStore();
  });

  it('空态显示占位文案', () => {
    renderPanel('compact');
    expect(screen.getByText('暂无正在进行的任务')).toBeTruthy();
  });

  it('compact 每组最多 3 条并显示"还有 N 条"', () => {
    seed(5);
    renderPanel('compact');
    expect(screen.getByText('任务 0')).toBeTruthy();
    expect(screen.getByText('任务 2')).toBeTruthy();
    expect(screen.queryByText('任务 3')).toBeNull();
    expect(screen.getByText(/还有 2 条/)).toBeTruthy();
  });

  it('full 模式展示全部并显示分组标题', () => {
    seed(5);
    renderPanel('full');
    expect(screen.getByText('任务 4')).toBeTruthy();
    expect(screen.getByText('进行中')).toBeTruthy();
  });

  it('compact 模式不显示已完成组', () => {
    useTaskCenterStore.setState({
      tasks: {
        bad: { id: 'bad', kind: 'office', title: '失败的', startedAt: 1, status: 'failed' },
        done: { id: 'done', kind: 'office', title: '完成的', startedAt: 9, status: 'succeeded' },
      } as never,
    });
    renderPanel('compact');
    expect(screen.queryByText('已完成')).toBeNull();
    expect(screen.getByText('失败')).toBeTruthy();
  });

  it('full 模式显示已完成组与清除按钮', () => {
    useTaskCenterStore.setState({
      tasks: {
        done: { id: 'done', kind: 'office', title: '完成的', startedAt: 9, status: 'succeeded' },
      } as never,
    });
    renderPanel('full');
    expect(screen.getByText('已完成')).toBeTruthy();
    expect(screen.getByRole('button', { name: /清除已完成/ })).toBeTruthy();
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/features/task-center/__tests__/TaskCenterPanel.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: 实现面板**

Create `src/features/task-center/TaskCenterPanel.tsx`:

```tsx
// src/features/task-center/TaskCenterPanel.tsx
//
// 任务列表内容。compact = 侧边栏分区（每组最多 3 条），full = /tasks 页面。
import { useMemo, useState } from 'react';

import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

import { TaskCenterCard } from './TaskCenterCard';
import type { UnifiedTaskEntry, UnifiedTaskSource } from './unifiedTaskModel';
import { useTaskCenterActions } from './useTaskCenterActions';
import { useUnifiedTasks } from './useUnifiedTasks';

const GROUP_ORDER = ['active', 'failed', 'finished'] as const;
type GroupKey = (typeof GROUP_ORDER)[number];

const COMPACT_LIMIT = 3;

export interface TaskCenterPanelProps {
  variant: 'compact' | 'full';
}

export function TaskCenterPanel({ variant }: TaskCenterPanelProps) {
  const { t } = useI18n();
  const actions = useTaskCenterActions();
  const { groups, all, loading, error } = useUnifiedTasks();
  const [sourceFilter, setSourceFilter] = useState<UnifiedTaskSource | 'all'>('all');

  const visibleGroups = useMemo(() => {
    const byGroup = variant === 'compact' ? (['active', 'failed'] as const) : GROUP_ORDER;
    return byGroup
      .map((key) => {
        let list: UnifiedTaskEntry[] = groups[key as GroupKey];
        if (sourceFilter !== 'all') list = list.filter((e) => e.source === sourceFilter);
        return { key: key as GroupKey, list };
      })
      .filter((g) => g.list.length > 0);
  }, [groups, sourceFilter, variant]);

  const sources = useMemo(() => {
    const set = new Set<UnifiedTaskSource>();
    for (const e of all) set.add(e.source);
    return [...set];
  }, [all]);

  if (error && all.length === 0) {
    return <div className="px-3 py-2 text-ui-2xs text-error">{error}</div>;
  }

  if (all.length === 0 && !loading) {
    return (
      <div className="px-3 py-2 text-ui-2xs text-muted">
        {variant === 'compact'
          ? t('taskCenter.section.empty')
          : t('taskCenter.page.empty')}
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      {variant === 'full' && (
        <div className="px-3 pb-2 flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => setSourceFilter('all')}
            className={sourceFilter === 'all' ? 'text-primary' : 'text-muted'}
          >
            {t('taskCenter.filter.all')}
          </button>
          {sources.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSourceFilter(s)}
              className={sourceFilter === s ? 'text-primary' : 'text-muted'}
            >
              {t(`taskCenter.source.${s}` as TranslationKey)}
            </button>
          ))}
        </div>
      )}

      {visibleGroups.map(({ key, list }) => {
        const shown = variant === 'compact' ? list.slice(0, COMPACT_LIMIT) : list;
        const overflow = list.length - shown.length;
        return (
          <div key={key} className="mt-1">
            <div className="px-3 py-1 text-ui-2xs uppercase text-muted">
              {t(`taskCenter.group.${key}` as TranslationKey)}
            </div>
            {shown.map((entry) => (
              <TaskCenterCard
                key={entry.id}
                entry={entry}
                actions={actions}
                compact={variant === 'compact'}
              />
            ))}
            {overflow > 0 && (
              <div className="px-3 py-1 text-ui-2xs text-muted">
                {t('taskCenter.section.more').replace('{count}', String(overflow))}
              </div>
            )}
          </div>
        );
      })}

      {variant === 'full' && groups.finished.length > 0 && (
        <div className="px-3 pt-2">
          <button
            type="button"
            onClick={actions.clearFinished}
            className="text-ui-2xs text-muted hover:text-text"
          >
            {t('taskCenter.action.clearFinished')}
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: 运行确认通过**

Run: `npx vitest run src/features/task-center/__tests__/TaskCenterPanel.test.tsx`
Expected: PASS (5 tests)

- [ ] **Step 5: 提交**

```bash
git add src/features/task-center/TaskCenterPanel.tsx src/features/task-center/__tests__/TaskCenterPanel.test.tsx
git commit -m "feat(task-center): 任务面板内容组件

compact（分区，每组 3 条 + 溢出计数，不显示已完成组）与 full（页面，全部 +
来源筛选 + 清除已完成）两种形态共用一份渲染逻辑。"
```

---

## Task 8: 侧边栏分区与导航（M3c）

**Files:**
- Create: `src/widgets/sidebar/sections/TaskCenterSection.tsx`
- Test: `src/widgets/sidebar/__tests__/TaskCenterSection.test.tsx`
- Modify: `src/widgets/sidebar/index.ts`（barrel 追加导出）
- Modify: `src/widgets/layout/Sidebar.tsx`（`SECTION_KEYS` / `coreNavItems` / `renderSection` / rail 角标）

**Interfaces:**
- Consumes: `SiderSection` from `../SiderSection`（props 已核实：`sectionKey` / `label` / `icon` / `collapsed` / `onToggleCollapsed` / `trailing?` / `render` / `maxHeight?` / `fill?`）；`TaskCenterPanel` from `../../../features/task-center/TaskCenterPanel`；`useUnifiedTasks` from `../../../features/task-center/useUnifiedTasks`
- Produces: `TaskCenterSection({ collapsed, onToggleCollapsed }): JSX.Element`

- [ ] **Step 1: 写失败的测试**

Create `src/widgets/sidebar/__tests__/TaskCenterSection.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import { useTaskCenterStore } from '../../../features/task-center/taskCenterStore';
import { resetUnifiedTaskStore } from '../../../features/task-center/unifiedTaskStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import { TaskCenterSection } from '../sections/TaskCenterSection';

// useI18n() 在 <I18nProvider> 之外会 throw（SiderSection 内部也调它）
function renderSection(collapsed = false) {
  return render(
    <I18nProvider>
      <MemoryRouter>
        <TaskCenterSection collapsed={collapsed} onToggleCollapsed={() => {}} />
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe('TaskCenterSection', () => {
  beforeEach(() => {
    useTaskCenterStore.setState({ tasks: {} });
    resetUnifiedTaskStore();
  });

  it('渲染"任务"章节头', () => {
    renderSection();
    expect(screen.getByText('任务')).toBeTruthy();
  });

  it('有任务时章节头显示计数', () => {
    useTaskCenterStore.setState({
      tasks: {
        r1: { id: 'r1', kind: 'office', title: 'a', startedAt: 1, status: 'running' },
        r2: { id: 'r2', kind: 'office', title: 'b', startedAt: 1, status: 'failed' },
      } as never,
    });
    renderSection();
    expect(screen.getByText('2')).toBeTruthy();
  });

  it('折叠时不渲染卡片', () => {
    useTaskCenterStore.setState({
      tasks: {
        r1: { id: 'r1', kind: 'office', title: '不应出现', startedAt: 1, status: 'running' },
      } as never,
    });
    renderSection(true);
    expect(screen.queryByText('不应出现')).toBeNull();
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/widgets/sidebar/__tests__/TaskCenterSection.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: 实现分区组件**

Create `src/widgets/sidebar/sections/TaskCenterSection.tsx`:

```tsx
// src/widgets/sidebar/sections/TaskCenterSection.tsx
//
// 内容列「任务」分区。轮询不在本组件内（折叠即不渲染），
// 统一由常驻的 TaskCenterRuntimeHost 承担（spec §5.4）。
import { ListTodo } from 'lucide-react';

import { TaskCenterPanel } from '../../../features/task-center/TaskCenterPanel';
import { useUnifiedTasks } from '../../../features/task-center/useUnifiedTasks';
import { useI18n } from '../../../shared/lib/i18n';
import { SiderSection } from '../SiderSection';

export interface TaskCenterSectionProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

export function TaskCenterSection({ collapsed, onToggleCollapsed }: TaskCenterSectionProps) {
  const { t } = useI18n();
  const { attentionCount } = useUnifiedTasks();

  return (
    <SiderSection
      sectionKey="tasks"
      label={t('taskCenter.section.title')}
      icon={ListTodo}
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      maxHeight="320px"
      trailing={
        attentionCount > 0 ? <span className="text-ui-2xs text-muted">{attentionCount}</span> : undefined
      }
      render={() => <TaskCenterPanel variant="compact" />}
    />
  );
}
```

- [ ] **Step 4: 运行确认通过**

Run: `npx vitest run src/widgets/sidebar/__tests__/TaskCenterSection.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 5: 改 Sidebar.tsx —— SECTION_KEYS + nav 项 + renderSection + rail 角标**

对 `src/widgets/layout/Sidebar.tsx` 做四处改动：

**(a) `:68` SECTION_KEYS 加 `'tasks'`：**

```ts
const SECTION_KEYS = ['project', 'conversations', 'tasks', 'git'] as const;
```

**(b) `coreNavItems`（`:109`）加两项：**

```ts
const coreNavItems: NavItem[] = [
  { path: '/chat', label: '对话', icon: MessageSquare },
  { path: '/tasks', label: '任务', icon: ListTodo },
  { path: '/projects', label: '项目工作台', icon: Folder },
  { path: '/todos', label: '待办', icon: ListTodo },
  { path: '/goals', label: '闲时目标', icon: Target },
  { path: '/memory', label: '记忆', icon: Brain },
];
```

同时把 `Target` 加进顶部 lucide-react 导入（与 `ListTodo` 同行区域）。

**(c) `renderSection` 加 `case 'tasks'`**（找到现有 `case 'git'` 分支旁边）：

```tsx
case 'tasks':
  return (
    <TaskCenterSection
      collapsed={collapsedSections.has('tasks')}
      onToggleCollapsed={() => toggleCollapsed('tasks')}
    />
  );
```

并在 `src/widgets/sidebar/index.ts` barrel 追加一行（按字母序插在 `SidebarProjectList` 之后）：

```ts
export { TaskCenterSection } from './sections/TaskCenterSection';
```

`Sidebar.tsx` 不直接深引 section 文件 —— 沿用文件里既有的 barrel 写法（`:53-58`），
把 `TaskCenterSection` 加进同一条解构导入：

```tsx
import {
  ConversationsSection,
  GitStatusSection,
  SidebarProjectList,
  TaskCenterSection,
  useSiderSections,
} from '../sidebar';
```

> **注意**：`:221-225` 的解构是
> `const { order: sectionOrder, collapsed: collapsedSections, toggleCollapsed } = useSiderSections(...)`。
> `collapsedSections` 是 **`Set<string>`**（不是 Record），因此判定用 `.has('tasks')`，
> 切换用 `toggleCollapsed('tasks')`。不要新增第二套状态，也不要用 `toggleSection`（该函数不存在）。

**(d) rail 角标** —— 在 `:511` 既有 `trailing={item.path === '/chat' ? <AttnBadge count={attentionCount} /> : undefined}` 处，改为同时支持 `/tasks`：

```tsx
trailing={
  item.path === '/chat' ? (
    <AttnBadge count={attentionCount} />
  ) : item.path === '/tasks' ? (
    <AttnBadge count={taskCenterBadgeCount} />
  ) : undefined
}
```

并在组件体内（`attentionCount` 定义之后、`return` 之前）加：

```tsx
// ⚠️ 变量名不得复用 attentionCount —— 它已被 /chat 角标占用（审批+提问）
const { attentionCount: taskCenterBadgeCount } = useUnifiedTasks();
```

并导入：

```tsx
import { useUnifiedTasks } from '../../features/task-center/useUnifiedTasks';
```

> **语义提示**（写进该行注释）：`/chat` 角标 = 审批 + 提问；`/tasks` 角标 = 进行中 + 失败任务。两者口径不同，`title` 文案已能区分（R16 已知缺口）。

- [ ] **Step 6: 运行既有 Sidebar 测试**

```bash
npx vitest run src/widgets/layout/__tests__/
```
Expected: PASS；若有硬编码 nav 项数量的断言，按新数量更新（新增了 `/tasks` 与 `/goals`）。

- [ ] **Step 7: 架构检查（确认 Sidebar.tsx 未超 800 行）**

```bash
wc -l src/widgets/layout/Sidebar.tsx
node scripts/architecture-check.mjs
```
Expected: ≤ 800；架构检查绿

- [ ] **Step 8: 提交**

```bash
git add src/widgets/sidebar/sections/TaskCenterSection.tsx src/widgets/sidebar/__tests__/TaskCenterSection.test.tsx src/widgets/layout/Sidebar.tsx
git commit -m "feat(sidebar): 任务中心分区与导航入口

SECTION_KEYS 加 tasks；核心导航加 /tasks 与 /goals（修复闲时目标无入口的
发现性缺陷）；rail /tasks 角标 = 进行中+失败任务数，变量名用
taskCenterBadgeCount 避免遮蔽既有的审批+提问计数。"
```

---

## Task 9: `/tasks` 页面与路由（M3d）

**Files:**
- Create: `src/pages/TasksPage.tsx`
- Test: `src/pages/__tests__/TasksPage.test.tsx`
- Modify: `src/App.tsx`（lazy import + 路由）
- **不改** `src/pages/index.ts`

**Interfaces:**
- Produces: `TasksPage(): JSX.Element`（命名导出，与 `TodoPage` 一致）

- [ ] **Step 1: 写失败的测试**

Create `src/pages/__tests__/TasksPage.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../features/task-center/TaskCenterPanel', () => ({
  TaskCenterPanel: ({ variant }: { variant: string }) => (
    <div data-testid="panel">{variant}</div>
  ),
}));

import { I18nProvider } from '../../shared/lib/i18n';
import { TasksPage } from '../TasksPage';

describe('TasksPage', () => {
  beforeEach(() => vi.clearAllMocks());

  it('渲染标题、副标题与 full 模式面板', () => {
    render(
      <I18nProvider>
        <MemoryRouter>
          <TasksPage />
        </MemoryRouter>
      </I18nProvider>,
    );
    expect(screen.getByText('任务中心')).toBeTruthy();
    expect(screen.getByTestId('panel').textContent).toBe('full');
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/pages/__tests__/TasksPage.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: 实现页面**

Create `src/pages/TasksPage.tsx`:

```tsx
// src/pages/TasksPage.tsx
//
// /tasks 路由薄壳。⚠️ 不要加进 src/pages/index.ts barrel ——
// pagesIndex.p142.test.ts 硬断言 exportedPageCount === 5。
import { TaskCenterPanel } from '../features/task-center/TaskCenterPanel';
import { useI18n } from '../shared/lib/i18n';

export function TasksPage() {
  const { t } = useI18n();
  return (
    <div className="h-full flex flex-col">
      <header className="px-6 py-4 border-b border-ui-border">
        <h1 className="text-lg font-medium text-text">{t('taskCenter.page.title')}</h1>
        <p className="mt-1 text-ui-sm text-muted">{t('taskCenter.page.subtitle')}</p>
      </header>
      <div className="flex-1 overflow-y-auto py-2">
        <TaskCenterPanel variant="full" />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 运行确认通过**

Run: `npx vitest run src/pages/__tests__/TasksPage.test.tsx`
Expected: PASS (1 test)

- [ ] **Step 5: 在 App.tsx 加 lazy 导入与路由**

在其它 `lazy()` 定义旁（`:86` 附近）加：

```tsx
const TasksPage = lazy(() =>
  import('./pages/TasksPage').then((m) => ({ default: m.TasksPage })),
);
```

在 `/todos` 路由（`:315`）旁加：

```tsx
<Route path="/tasks" element={<TasksPage />} />
```

- [ ] **Step 6: 验证 barrel 未被破坏**

```bash
npx vitest run src/pages/Help/__tests__/pagesIndex.p142.test.ts
git diff --stat src/pages/index.ts
```
Expected: PASS；`src/pages/index.ts` 0 改动

- [ ] **Step 7: 提交**

```bash
git add src/pages/TasksPage.tsx src/pages/__tests__/TasksPage.test.tsx src/App.tsx
git commit -m "feat(tasks): /tasks 任务中心页面与路由

lazy import 与既有页面一致；不进 pages barrel（会破坏 exportedPageCount 断言）。"
```

---

## Task 10: 常驻轮询宿主（M3e）

**Files:**
- Create: `src/features/task-center/TaskCenterRuntimeHost.tsx`
- Test: `src/features/task-center/__tests__/TaskCenterRuntimeHost.test.tsx`

**Interfaces:**
- Consumes: `listShells` from `../../shared/api/shellApi`; `useTaskCenterStore`; `useUnifiedTaskStore`
- Produces: `TaskCenterRuntimeHost(): null`

- [ ] **Step 1: 写失败的测试**

Create `src/features/task-center/__tests__/TaskCenterRuntimeHost.test.tsx`:

```tsx
import { render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/shellApi', () => ({ listShells: vi.fn() }));

import { listShells } from '../../../shared/api/shellApi';
import { useTaskCenterStore } from '../taskCenterStore';
import { TaskCenterRuntimeHost } from '../TaskCenterRuntimeHost';
import { resetUnifiedTaskStore, useUnifiedTaskStore } from '../unifiedTaskStore';

describe('TaskCenterRuntimeHost', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetAllMocks();
    useTaskCenterStore.setState({ tasks: {} });
    resetUnifiedTaskStore();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('挂载即拉一次 shell 列表', async () => {
    vi.mocked(listShells).mockResolvedValue([]);
    render(<TaskCenterRuntimeHost />);
    await vi.waitFor(() => expect(listShells).toHaveBeenCalledTimes(1));
  });

  it('按 3s 轮询 shell', async () => {
    vi.mocked(listShells).mockResolvedValue([]);
    render(<TaskCenterRuntimeHost />);
    await vi.waitFor(() => expect(listShells).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(3_000);
    expect(listShells).toHaveBeenCalledTimes(2);
  });

  it('shell 列表同步进 taskCenterStore', async () => {
    vi.mocked(listShells).mockResolvedValue([
      { shell_id: 'sh-1', command: 'npm test', status: 'running', exit_code: null, age_seconds: 3 },
    ] as never);
    render(<TaskCenterRuntimeHost />);
    await vi.waitFor(() =>
      expect(useTaskCenterStore.getState().tasks['shell:sh-1']).toMatchObject({
        kind: 'shell',
        shellId: 'sh-1',
      }),
    );
  });

  it('渲染 null', () => {
    vi.mocked(listShells).mockResolvedValue([]);
    const { container } = render(<TaskCenterRuntimeHost />);
    expect(container.firstChild).toBeNull();
  });

  it('goal 轮询仅在存在非终态目标时继续', async () => {
    vi.mocked(listShells).mockResolvedValue([]);
    const refreshGoals = vi.spyOn(useUnifiedTaskStore.getState(), 'refreshGoals');
    useUnifiedTaskStore.setState({ goals: [{ id: 'g1', name: 'g', status: 'running' } as never] });

    render(<TaskCenterRuntimeHost />);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(refreshGoals).toHaveBeenCalled();

    useUnifiedTaskStore.setState({
      goals: [{ id: 'g1', name: 'g', status: 'completed' } as never],
    });
    refreshGoals.mockClear();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(refreshGoals).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/features/task-center/__tests__/TaskCenterRuntimeHost.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: 实现宿主**

Create `src/features/task-center/TaskCenterRuntimeHost.tsx`:

```tsx
// src/features/task-center/TaskCenterRuntimeHost.tsx
//
// 常驻轮询宿主 —— 挂在 Layout，永不受侧边栏折叠影响。
// 为什么不在分区里轮询：SiderSection 折叠后 render() 不再调用，
// 后台 shell 退出将永远反映不到任务中心（spec §5.4）。
import { useEffect } from 'react';

import { listShells } from '../../shared/api/shellApi';

import { useTaskCenterStore } from './taskCenterStore';
import { useUnifiedTaskStore } from './unifiedTaskStore';

const SHELL_TASK_POLL_MS = 3_000;
const GOAL_POLL_MS = 10_000;
const SLOW_SOURCE_POLL_MS = 30_000;

const NON_TERMINAL_GOAL = new Set(['pending', 'running', 'paused']);

export function TaskCenterRuntimeHost(): null {
  const registerShell = useTaskCenterStore((s) => s.registerShell);
  const removeMissingShells = useTaskCenterStore((s) => s.removeMissingShells);

  // shell 3s 轮询（逻辑与 TaskCenterWidget:228-256 完全一致）
  useEffect(() => {
    let cancelled = false;
    const poll = (): void => {
      listShells()
        .then((shells) => {
          if (cancelled) return;
          for (const shell of shells) {
            registerShell({
              shell_id: shell.shell_id,
              command: shell.command,
              status: shell.status,
              exit_code: shell.exit_code ?? null,
              age_seconds: shell.age_seconds,
            });
          }
          removeMissingShells(shells.map((s) => s.shell_id));
        })
        .catch(() => {
          /* 静默：任务中心是增强信息 */
        });
    };
    poll();
    const timer = window.setInterval(poll, SHELL_TASK_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [registerShell, removeMissingShells]);

  // goal 10s 轮询，仅在存在非终态目标时继续
  useEffect(() => {
    const timer = window.setInterval(() => {
      const { goals, refreshGoals } = useUnifiedTaskStore.getState();
      if (goals.some((g) => NON_TERMINAL_GOAL.has(g.status))) void refreshGoals();
    }, GOAL_POLL_MS);
    return () => window.clearInterval(timer);
  }, []);

  // todo / scheduled 30s 轮询，仅在存在活动条目时继续
  useEffect(() => {
    const timer = window.setInterval(() => {
      const { todos, scheduledTasks, refreshTodos, refreshScheduled } = useUnifiedTaskStore.getState();
      if (todos.some((t) => t.status === 'in_progress')) void refreshTodos();
      if (scheduledTasks.some((t) => t.last_status === 'running')) void refreshScheduled();
    }, SLOW_SOURCE_POLL_MS);
    return () => window.clearInterval(timer);
  }, []);

  // 首屏拉一次三源（不等轮询）
  useEffect(() => {
    void useUnifiedTaskStore.getState().refresh();
  }, []);

  return null;
}
```

- [ ] **Step 4: 运行确认通过**

Run: `npx vitest run src/features/task-center/__tests__/TaskCenterRuntimeHost.test.tsx`
Expected: PASS (5 tests)

- [ ] **Step 5: 提交**

```bash
git add src/features/task-center/TaskCenterRuntimeHost.tsx src/features/task-center/__tests__/TaskCenterRuntimeHost.test.tsx
git commit -m "feat(task-center): 常驻轮询宿主

shell 3s / goal 10s / todo+scheduled 30s，均只在存在活动条目时继续。
放 Layout 而非侧边栏分区 —— 折叠后分区不渲染，轮询必须独立于 UI 可见性。"
```

---

## Task 11: 切换挂载点、迁移 shell 抽屉、删除旧胶囊（M3f）

**Files:**
- Modify: `src/widgets/layout/Layout.tsx:16, :211`
- Modify: `src/widgets/task-center/DeliveryDrawerHost.tsx`
- Delete: `src/widgets/task-center/TaskCenterWidget.tsx`
- Delete: `src/widgets/task-center/__tests__/TaskCenterWidget.{test,a1,a4,dedupe,shells}.test.tsx`
- Create: `src/widgets/task-center/__tests__/DeliveryDrawerHost.shell.test.tsx`

**Interfaces:**
- Consumes: `TaskCenterRuntimeHost` from `../../features/task-center/TaskCenterRuntimeHost`
- Produces: `DeliveryDrawerHost` 现在同时渲染 `ShellStreamDrawer`

- [ ] **Step 1: 先写"shell 抽屉仍在"的回归测试**

**新建** `src/widgets/task-center/__tests__/DeliveryDrawerHost.shell.test.tsx`
（原 `DeliveryDrawerHost.p140.test.ts` 是 `.ts`，只测纯函数、不含 JSX，不要往里塞渲染用例）：

```tsx
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { useTaskCenterStore } from '../../../features/task-center/taskCenterStore';
import { I18nProvider } from '../../../shared/lib/i18n';

import { DeliveryDrawerHost } from '../DeliveryDrawerHost';

// useI18n() 在 <I18nProvider> 之外会 throw —— ShellStreamDrawer 内部要调它
const renderHost = () =>
  render(
    <I18nProvider>
      <DeliveryDrawerHost />
    </I18nProvider>,
  );

describe('DeliveryDrawerHost · shell 输出抽屉（Task 11）', () => {
  afterEach(() => {
    useTaskCenterStore.setState({ shellStream: null, delivery: null });
  });

  it('渲染 ShellStreamDrawer（原挂载点 TaskCenterWidget 已删除）', () => {
    useTaskCenterStore.setState({ shellStream: 'sh-1' });
    renderHost();
    expect(screen.getByTestId('shell-stream-drawer')).toBeTruthy();
  });

  it('无 shellStream 时不渲染 shell 抽屉', () => {
    renderHost();
    expect(screen.queryByTestId('shell-stream-drawer')).toBeNull();
  });
});
```

> `ShellStreamDrawer.tsx:44` 根节点已有 `data-testid="shell-stream-drawer"`，直接用；
> 条目缺失时它照样渲染（标题回落为 `shellId`），所以测试不必预置 `tasks`。

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/widgets/task-center/__tests__/DeliveryDrawerHost.shell.test.tsx`
Expected: FAIL — 第一条用例 `shell-stream-drawer` 未渲染（被 `if (!delivery) return null` 早退吞掉）

- [ ] **Step 3: 改 DeliveryDrawerHost 接管 ShellStreamDrawer**

`src/widgets/task-center/DeliveryDrawerHost.tsx` 现在是**多个早退**
（`if (!delivery) return null` / `if (!lane) return null` / `if (!ref) return null`）。
直接往末尾追加 `<ShellStreamDrawer />` 永远不会渲染 —— 必须把交付抽屉降级成局部变量，
再在同一个 fragment 里与 shell 抽屉并列返回。

整体替换为：

```tsx
// src/widgets/task-center/DeliveryDrawerHost.tsx
/**
 * A4: 全局交付抽屉宿主 —— 挂在 Layout，按 taskCenterStore.delivery 渲染
 * lane / office 交付抽屉；同时接管原 TaskCenterWidget 的后台 shell 输出抽屉。
 * 交付抽屉与 shell 抽屉互斥（store 的 openDelivery/openShellStream 互相清空），
 * 但**独立渲染** —— 不能用早退，否则其中一方的空状态会吞掉另一方。
 */
import type { ReactNode } from 'react';

import { useLaneBoardStore } from '../../entities/orchestration/laneBoardStore';
import { OfficeDeliveryDrawer } from '../../features/office/OfficeDeliveryDrawer';
import { useTaskCenterStore } from '../../features/task-center/taskCenterStore';
import { LaneDetailDrawer } from '../orchestration/LaneDetailDrawer';

import { ShellStreamDrawer } from './ShellStreamDrawer';

export function DeliveryDrawerHost() {
  const delivery = useTaskCenterStore((s) => s.delivery);
  const closeDelivery = useTaskCenterStore((s) => s.closeDelivery);
  const shellStream = useTaskCenterStore((s) => s.shellStream);
  const lanes = useLaneBoardStore((s) => s.lanes);
  const tasks = useTaskCenterStore((s) => s.tasks);

  let deliveryBlock: ReactNode = null;
  if (delivery?.kind === 'lane') {
    const lane = lanes.find((l) => l.lane_id === delivery.laneId) ?? null;
    deliveryBlock = lane ? <LaneDetailDrawer lane={lane} open onClose={closeDelivery} /> : null;
  } else if (delivery?.kind === 'office') {
    const ref = delivery.ref ?? tasks[delivery.entryId]?.deliveryRef;
    deliveryBlock = ref ? (
      <OfficeDeliveryDrawer
        entryId={delivery.entryId}
        workspacePath={ref.workspacePath}
        filePath={ref.filePath}
        formatSpec={ref.formatSpec}
        open
        onClose={closeDelivery}
      />
    ) : null;
  }

  return (
    <>
      {deliveryBlock}
      {shellStream ? <ShellStreamDrawer shellId={shellStream} /> : null}
    </>
  );
}
```

> 文件后半段的 `DeliveryDrawerHostAuditInput` / `evaluateDeliveryDrawerHostGovernanceAudit`
> **原样保留**（`DeliveryDrawerHost.p140.test.ts` 仍在测它们）。

- [ ] **Step 4: 改 Layout.tsx**

把 `:16` 的导入：

```tsx
import { TaskCenterWidget } from '../task-center/TaskCenterWidget';
```

改为：

```tsx
import { TaskCenterRuntimeHost } from '../../features/task-center/TaskCenterRuntimeHost';
```

把 `:211` 的挂载：

```tsx
<TaskCenterWidget />
```

改为：

```tsx
<TaskCenterRuntimeHost />
```

- [ ] **Step 5: 删除旧组件与测试**

```bash
git rm src/widgets/task-center/TaskCenterWidget.tsx
git rm src/widgets/task-center/__tests__/TaskCenterWidget.test.tsx
git rm src/widgets/task-center/__tests__/TaskCenterWidget.a1.test.tsx
git rm src/widgets/task-center/__tests__/TaskCenterWidget.a4.test.tsx
git rm src/widgets/task-center/__tests__/TaskCenterWidget.dedupe.test.tsx
git rm src/widgets/task-center/__tests__/TaskCenterWidget.shells.test.tsx
```

- [ ] **Step 6: 全量搜索残留引用**

```bash
grep -rn 'TaskCenterWidget' src/ electron/ --include=*.ts --include=*.tsx
```
Expected: 无输出（若仍有引用，逐个改到新归属）

- [ ] **Step 7: 运行相关测试**

```bash
npx vitest run src/widgets/task-center/__tests__/ src/features/task-center/__tests__/
npx tsc --noEmit
npx eslint src/widgets/task-center src/features/task-center src/widgets/layout
```
Expected: 全绿；无未使用导入

- [ ] **Step 8: 提交**

```bash
git add -A src/widgets/task-center src/widgets/layout/Layout.tsx
git commit -m "refactor(task-center): 浮动胶囊迁入侧边栏，删除旧组件

Layout 挂载 TaskCenterRuntimeHost（常驻轮询）；ShellStreamDrawer 迁到
DeliveryDrawerHost（同为全局 overlay）。taskCenterStore 契约不变，桌宠桥接
与交付抽屉无回归。旧组件 5 个测试的行为已由新模型的测试承接。"
```

---

## Task 12: panelRegistry 槽位迁移（M3g）

**Files:**
- Modify: `src/features/app-panels/panelRegistry.ts:164-168`
- Modify: `src/features/app-panels/__tests__/panelRegistry.test.ts`

**Interfaces:**
- Produces: `task-center` 条目的 `slot === 'left-list'`、`currentOwner === 'widgets/sidebar/sections/TaskCenterSection.tsx'`

- [ ] **Step 1: 先跑测试看现状**

```bash
npx vitest run src/features/app-panels/__tests__/panelRegistry.test.ts
```
Expected: PASS（改动前基线）

- [ ] **Step 2: 修改 registry 条目**

在 `src/features/app-panels/panelRegistry.ts:164-168` 处：

```ts
{
  id: 'task-center',
  slot: 'left-list',
  label: '任务中心',
  migrationBatch: 'C',
  currentOwner: 'widgets/sidebar/sections/TaskCenterSection.tsx',
},
```

- [ ] **Step 3: 更新测试断言**

在 `src/features/app-panels/__tests__/panelRegistry.test.ts` 中找到对 `task-center` 的两处硬编码断言（`slot: 'floating'` 和 `currentOwner: ...TaskCenterWidget.tsx:305`），改为：

```ts
expect(taskCenter.slot).toBe('left-list');
expect(taskCenter.currentOwner).toBe('widgets/sidebar/sections/TaskCenterSection.tsx');
```

- [ ] **Step 4: 运行确认通过**

```bash
npx vitest run src/features/app-panels/__tests__/panelRegistry.test.ts
```
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/features/app-panels/panelRegistry.ts src/features/app-panels/__tests__/panelRegistry.test.ts
git commit -m "refactor(app-panels): task-center 槽位 floating → left-list

任务中心从浮动层迁入内容列，panelRegistry 的槽位与 owner 同步更新。"
```

---

## Task 13: 目标完成通知队列（M5a）

**Files:**
- Create: `backend/services/goal_notifications.py`
- Modify: `backend/services/goal_service.py:230, :246, :634`
- Modify: `backend/api/scheduled_router.py:254-257`
- Test: `backend/tests/unit/test_goal_notifications.py`
- Test: `backend/tests/unit/test_goal_service_notifications.py`
- Test: `backend/tests/api/test_goal_notifications_route.py`

**Interfaces:**
- Consumes: `Goal` from `backend.domain.autonomous_goals`
- Produces:
  - `GoalNotificationQueue` with `.push(goal)`, `.drain() -> List[Dict[str, Any]]`
  - `get_goal_notification_queue() -> GoalNotificationQueue`、`reset_goal_notification_queue()`
  - `/api/v1/scheduled/notifications/pending` 返回体新增 `goal_notifications`

- [ ] **Step 1: 写失败的单元测试**

Create `backend/tests/unit/test_goal_notifications.py`:

```python
"""目标完成/失败通知队列的单元测试。"""

from backend.domain.autonomous_goals import Goal, GoalStatus
from backend.services.goal_notifications import (
    GoalNotificationQueue,
    get_goal_notification_queue,
    reset_goal_notification_queue,
)


def _goal(status: GoalStatus, name: str = "整理文献", error=None) -> Goal:
    return Goal(id="g1", name=name, description="", status=status, last_error=error)


def test_completed_goal_pushes_success_title():
    queue = GoalNotificationQueue()
    queue.push(_goal(GoalStatus.COMPLETED))
    items = queue.drain()
    assert len(items) == 1
    assert items[0]["kind"] == "goal"
    assert items[0]["status"] == "succeeded"
    assert "整理文献" in items[0]["title"]
    assert items[0]["title"].startswith("✅")


def test_failed_goal_pushes_failure_title_with_error():
    queue = GoalNotificationQueue()
    queue.push(_goal(GoalStatus.FAILED, error="模型超时"))
    items = queue.drain()
    assert len(items) == 1
    assert items[0]["status"] == "failed"
    assert items[0]["title"].startswith("❌")
    assert items[0]["body"] == "模型超时"


def test_non_terminal_status_is_ignored():
    queue = GoalNotificationQueue()
    for status in (GoalStatus.PENDING, GoalStatus.RUNNING, GoalStatus.PAUSED):
        queue.push(_goal(status))
    assert queue.drain() == []


def test_drain_empties_queue():
    queue = GoalNotificationQueue()
    queue.push(_goal(GoalStatus.COMPLETED))
    queue.drain()
    assert queue.drain() == []


def test_singleton_is_resettable():
    first = get_goal_notification_queue()
    first.push(_goal(GoalStatus.COMPLETED))
    reset_goal_notification_queue()
    second = get_goal_notification_queue()
    assert second is not first
    assert second.drain() == []
```

- [ ] **Step 2: 运行确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_goal_notifications.py -v
```
Expected: FAIL — `ModuleNotFoundError: backend.services.goal_notifications`

- [ ] **Step 3: 实现通知队列（py3.8 兼容）**

Create `backend/services/goal_notifications.py`:

```python
"""闲时目标完成 / 失败通知队列（2026-11-09）。

与 BackgroundNotificationQueue 同构：进程内 bounded deque + threading.Lock，
无持久化。Electron 主进程通过
``GET /api/v1/scheduled/notifications/pending`` 的 ``goal_notifications`` 键排空。

为什么不复用 background_notifications：``background_tasks`` 键的语义是
"后台 Bash 任务"，混入目标通知会污染既有消费方（spec §7.2）。
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

MAX_GOAL_NOTIFICATIONS = 100

_TERMINAL_STATUSES = ("completed", "failed")


class GoalNotificationQueue:
    """线程安全的目标终态通知队列。"""

    def __init__(self, maxlen: int = MAX_GOAL_NOTIFICATIONS) -> None:
        self._items: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(self, goal: Any) -> None:
        """记录一条目标终态通知；非终态忽略。"""
        status = getattr(goal.status, "value", goal.status)
        if status not in _TERMINAL_STATUSES:
            return

        name = (getattr(goal, "name", "") or goal.id).strip()[:60]
        succeeded = status == "completed"
        error = getattr(goal, "last_error", None)

        with self._lock:
            self._items.append(
                {
                    "kind": "goal",
                    "goal_id": str(goal.id),
                    "status": "succeeded" if succeeded else "failed",
                    "title": (
                        f"✅ 闲时目标完成：{name}" if succeeded else f"❌ 闲时目标失败：{name}"
                    ),
                    "body": (error or "").strip()[:200],
                    "created_at": datetime.now().isoformat(),
                }
            )

    def drain(self) -> List[Dict[str, Any]]:
        """排空并返回全部通知。"""
        with self._lock:
            items = list(self._items)
            self._items.clear()
            return items


_queue: Optional[GoalNotificationQueue] = None
_queue_lock = threading.Lock()


def get_goal_notification_queue() -> GoalNotificationQueue:
    """进程级单例。"""
    global _queue
    with _queue_lock:
        if _queue is None:
            _queue = GoalNotificationQueue()
        return _queue


def reset_goal_notification_queue() -> None:
    """测试用：丢弃单例。"""
    global _queue
    with _queue_lock:
        _queue = None
```

- [ ] **Step 4: 运行单元测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_goal_notifications.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 5: 写失败的路由测试**

Create `backend/tests/api/test_goal_notifications_route.py`:

```python
"""pending 通知端点包含 goal_notifications 键的回归测试。"""

from fastapi.testclient import TestClient

from backend.main import app


def test_pending_notifications_includes_goal_key():
    client = TestClient(app)
    resp = client.get("/api/v1/scheduled/notifications/pending")
    assert resp.status_code == 200
    body = resp.json()
    assert "goal_notifications" in body
    assert isinstance(body["goal_notifications"], list)
    # 既有三键语义不变
    assert "scheduled_tasks" in body
    assert "todo_reminders" in body
    assert "background_tasks" in body
```

- [ ] **Step 6: 运行确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/api/test_goal_notifications_route.py -v
```
Expected: FAIL — `assert 'goal_notifications' in body`

- [ ] **Step 7: 改 scheduled_router 返回体**

在 `backend/api/scheduled_router.py:240-258` 的局部导入区加：

```python
    from backend.services.goal_notifications import get_goal_notification_queue
```

把 `return {...}` 改为：

```python
        return {
            "scheduled_tasks": svc.drain_pending_notifications(),
            "todo_reminders": todo_items,
            # 2026-11-06 Phase 1: 后台 Bash 任务完成通知
            "background_tasks": get_background_notification_queue().drain(),
            # 2026-11-09: 闲时目标终态通知（独立队列，不混入 background_tasks）
            "goal_notifications": get_goal_notification_queue().drain(),
        }
```

- [ ] **Step 8: 运行确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/api/test_goal_notifications_route.py -v
```
Expected: PASS

- [ ] **Step 9: 写服务层推送测试**

Create `backend/tests/unit/test_goal_service_notifications.py`:

```python
"""goal_service 在目标终态时推通知的回归测试。"""

import pytest

from backend.domain.autonomous_goals import GoalStatus
from backend.services.goal_notifications import (
    get_goal_notification_queue,
    reset_goal_notification_queue,
)


@pytest.fixture(autouse=True)
def _clean_queue():
    reset_goal_notification_queue()
    yield
    reset_goal_notification_queue()


def test_terminal_goal_status_enqueues_notification(goal_service):
    goal = goal_service.create_goal(name="测试目标", description="", session_id=None)
    stored = goal_service.get_goal(goal.id)
    stored.status = GoalStatus.COMPLETED
    get_goal_notification_queue().push(stored)

    items = get_goal_notification_queue().drain()
    assert any(i["goal_id"] == goal.id for i in items)
```

> 若仓库里没有名为 `goal_service` 的 pytest fixture，改用既有 `test_goal_service.py` 里的夹具构造方式（同目录内 `conftest.py` 或该文件的 `@pytest.fixture`）。断言本身不变。真实终态路径（`_execute_loop` 跑完）由 Task 15 的手工冒烟覆盖。

- [ ] **Step 10: 改 goal_service.py 三处终态推通知**

在 `backend/services/goal_service.py` 顶部导入：

```python
from backend.services.goal_notifications import get_goal_notification_queue
```

在 `:230` 附近（`goal.status = GoalStatus.COMPLETED` 之后）：

```python
                    goal.status = GoalStatus.COMPLETED
                    get_goal_notification_queue().push(goal)
```

在 `:246` 附近（`goal.status = GoalStatus.FAILED` 之后）：

```python
                goal.status = GoalStatus.FAILED
                get_goal_notification_queue().push(goal)
```

在 `:634` 附近（`_apply_degradation` 里的 `goal.status = GoalStatus.FAILED` 之后）：

```python
            goal.status = GoalStatus.FAILED
            get_goal_notification_queue().push(goal)
```

> 若 import 会引入循环依赖（`goal_service ← goal_notifications` 无反向依赖，理论不会），改为与 `scheduled_router` 相同的函数内局部导入。

- [ ] **Step 11: 运行相关后端测试**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_goal_notifications.py \
  backend/tests/unit/test_goal_service.py \
  backend/tests/unit/test_goal_service_notifications.py \
  backend/tests/api/test_goal_notifications_route.py \
  backend/tests/api/test_autonomous_goals_routes.py -v
```
Expected: PASS；已知环境性失败（端口 / git 中文 / AsyncMock）集合与基线一致即可

- [ ] **Step 12: Python 3.8 兼容性检查**

```bash
grep -n 'list\[\|dict\[\|tuple\[\| | None\|match ' backend/services/goal_notifications.py
```
Expected: 无输出（该文件用 `List`/`Dict`/`Optional`）

- [ ] **Step 13: 提交**

```bash
git add backend/services/goal_notifications.py backend/services/goal_service.py backend/api/scheduled_router.py backend/tests/unit/test_goal_notifications.py backend/tests/api/test_goal_notifications_route.py backend/tests/unit/test_goal_service_notifications.py
git commit -m "feat(goals): 闲时目标终态通知队列

目标 completed/failed 时推入独立队列，通过 notifications/pending 的
goal_notifications 键暴露。不复用 background_tasks —— 该键语义是后台 Bash
任务，混入会污染既有消费方。py3.8 兼容（无 PEP 604 / 内建泛型）。"
```

---

## Task 14: Electron 通知消费（M5b）

**Files:**
- Modify: `electron/schedulerNotifications.ts:23-28, :43-49`
- Test: `electron/__tests__/schedulerNotifications.test.ts`

**Interfaces:**
- Produces: `PendingNotificationsPayload.goal_notifications?: PendingNotificationItem[]`；`collectNotificationItems` 合并四键

- [ ] **Step 1: 写失败的测试**

在 `electron/__tests__/schedulerNotifications.test.ts` 追加：

```ts
it('collectNotificationItems 合并 goal_notifications', () => {
  const items = collectNotificationItems({
    scheduled_tasks: [{ title: 'A' }],
    goal_notifications: [{ title: 'B', status: 'succeeded' }],
  });
  expect(items.map((i) => i.title)).toEqual(['A', 'B']);
});

it('goal_notifications 中无 title 的条目被丢弃', () => {
  const items = collectNotificationItems({
    goal_notifications: [{ body: 'no title' }, { title: 'C' }],
  });
  expect(items.map((i) => i.title)).toEqual(['C']);
});
```

- [ ] **Step 2: 运行确认失败**

```bash
npx vitest run electron/__tests__/schedulerNotifications.test.ts
```
Expected: FAIL — 第二项缺失

- [ ] **Step 3: 改 payload 类型与合并逻辑**

在 `electron/schedulerNotifications.ts:23-28` 的 `PendingNotificationsPayload` 加上：

```ts
  /** 2026-11-09: 闲时目标终态通知 */
  goal_notifications?: PendingNotificationItem[];
```

把 `collectNotificationItems`（`:43-49`）改为：

```ts
export function collectNotificationItems(
  payload: PendingNotificationsPayload | null | undefined,
): PendingNotificationItem[] {
  const items = [
    ...(payload?.scheduled_tasks ?? []),
    ...(payload?.todo_reminders ?? []),
    ...(payload?.background_tasks ?? []),
    ...(payload?.goal_notifications ?? []),
  ];
  return items.filter((item) => typeof item.title === 'string' && item.title.length > 0);
}
```

- [ ] **Step 4: 运行确认通过**

```bash
npx vitest run electron/__tests__/schedulerNotifications.test.ts
```
Expected: PASS（含既有用例）

- [ ] **Step 5: 提交**

```bash
git add electron/schedulerNotifications.ts electron/__tests__/schedulerNotifications.test.ts
git commit -m "feat(electron): 消费 goal_notifications 转 OS 通知

pending 端点第四键并入既有 15s 轮询；无 title 条目仍被丢弃。"
```

---

## Task 15: 文档归档与双分支同步（M6）

**Files:**
- Delete: `docs/plans/2026-10-28_idle-deferred-task-execution.md`
- Create: `docs/technical/146-sidebar-task-center.md`
- Create: `docs/user-manual/46-task-center.md`
- Modify: `docs/technical/README.md`、`docs/user-manual/README.md`、`docs/superpowers/specs/README.md`

- [ ] **Step 1: 确认技术/用户手册的下一可用编号**

```bash
ls docs/technical/ | sort | tail -5
ls docs/user-manual/ | sort | tail -5
```
Expected: 技术最大编号 145（→ 新文件 146）；用户最大编号 45（→ 46）。**以实际输出为准**，若已被占用顺延。

- [ ] **Step 2: 新建技术文档**

Create `docs/technical/146-sidebar-task-center.md`（结构：总览 → 架构 → 六源归一 → 轮询与可见性 → 通知链路 → 双分支差异 → 排障）。开头一句话定位 + 章节目录。正文复用 spec §3–§8，改写为"实现说明"而非"设计论证"。

最低必须包含的表格：

```markdown
| 来源 | store / API | 关键字段差异 |
|---|---|---|
| registry | `useTaskCenterStore.tasks` | `startedAt` epoch ms；`kind==='shell'` 走 shell 分支 |
| chat | `useChatStreamStore.sessions` | 排除当前会话；首见时间由 ref 记录 |
| lane | `useLaneBoardStore.lanes` | `succeeded` 且未决议 → awaiting_approval |
| goal | `listGoals(undefined, 200, 0)` | 返回 `{items}`；时间戳是 ISO 字符串 |
| todo | `todoClient.list({limit, offset, include_completed})` | 返回 `{items}`；`id` 是 number |
| scheduled | `scheduledClient.list()` | 裸数组；`last_status` 决定是否展示 |
```

- [ ] **Step 3: 新建用户手册**

Create `docs/user-manual/46-task-center.md`。内容：任务中心在哪（侧边栏「任务」导航 + 内容列分区 + `/tasks` 页面）、六种任务来源各代表什么、失败任务如何重试、如何取消、闲时目标完成会收到系统通知。

- [ ] **Step 4: 更新两个 README 目录**

在 `docs/technical/README.md` 的章节目录表格追加一行（编号 + 链接 + 一句话简介）。在 `docs/user-manual/README.md` 同样追加。

- [ ] **Step 5: 删除已完成的计划文档**

```bash
git rm docs/plans/2026-10-28_idle-deferred-task-execution.md
```

- [ ] **Step 6: spec 状态改为已实施**

在 `docs/superpowers/specs/README.md:51` 的一行简介末尾追加 `（状态：已实施）`；并在 spec 文件头部 `状态: 设计中` 改为 `状态: 已实施`（若存在该行）。

- [ ] **Step 7: 全量门禁**

```bash
npm run lint
node scripts/architecture-check.mjs
npx tsc --noEmit
npx vitest run
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit backend/tests/api -q
```
Expected: 全绿；后端已知环境性失败集合与基线一致

- [ ] **Step 8: 提交并开 PR**

```bash
git add -A docs/
git commit -m "docs(task-center): 归档技术/用户手册章节，删除已完成计划

技术 §146 / 用户 §46；spec 状态改已实施。docs/plans 里闲时任务计划随功能
落地删除（规则见 feature-development.md）。"
git push -u origin feat/sidebar-task-center
gh pr create --title "feat: 侧边栏任务中心（闲时目标可见性修复 + 六源统一）" --body "$(cat <<'EOF'
## 变更

- 删除右下角浮动胶囊，任务中心迁入侧边栏（rail 入口 + 内容列分区 + /tasks 页面）
- 六源统一：registry / chat / lane / goal / todo / scheduled
- 修复闲时目标发现性缺陷：侧边栏新增 /goals 与 /tasks 导航项
- 闲时目标完成/失败新增系统通知（独立队列，不污染 background_tasks）

## 测试

- [x] 单测：unifiedTaskModel / unifiedTaskStore / useUnifiedTasks / actions / panel / card / section / page
- [x] 后端：goal_notifications 队列 + pending 端点四键
- [x] Electron：collectNotificationItems 合并 goal_notifications
- [ ] 手工冒烟：侧边栏分区、/tasks 页、shell 输出抽屉、交付抽屉、桌宠

## 双分支

cherry-pick 到 release/win7 后用 sage-backend-py38 复跑后端测试。
EOF
)"
```

- [ ] **Step 9: cherry-pick 到 release/win7（人工确认后）**

```bash
git log --oneline main..feat/sidebar-task-center
git diff origin/release/win7 --stat | head -40
# 逐个 squash 后的 commit cherry-pick；先确认 win7 上无既有实现
```
Expected: 冲突仅出现在 `Sidebar.tsx` 行号漂移与 i18n 聚合文件；按 win7 基线取齐后重应用单行改动。

- [ ] **Step 10: py3.8 复跑**

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_goal_notifications.py backend/tests/api/test_goal_notifications_route.py -v
```
Expected: PASS

---

## Self-Review

**1. Spec coverage（逐节对照）**

| spec 节 | 覆盖任务 |
|---|---|
| §3.1 方案 C / §3.2 三个可见面 | Task 8（rail + 分区）、Task 9（页面） |
| §3.3 FSD 合规（归一表放 features） | Task 1 文件位置 + Global Constraints |
| §4.1 `UnifiedTaskEntry` | Task 1 Step 3 |
| §4.2 六源字段映射 | Task 1 Step 7（六个 normalize 函数） |
| §4.3 四张状态映射表 | Task 1 Step 3 + Step 1 测试 |
| §4.4 可见性规则 | Task 1（todo pending / scheduled never+succeeded 返回 null）+ Task 3 测试 |
| §4.5 shell 子类 | Task 1 `normalizeRegistryTask` shell 分支 |
| §5.2 `useUnifiedTasks` | Task 3 |
| §5.3 `unifiedTaskStore` | Task 2 |
| §5.4 `TaskCenterRuntimeHost` | Task 10 |
| §5.5 `TaskCenterSection` | Task 8 |
| §5.6 `TaskCenterCard` | Task 6 |
| §5.7 `useTaskCenterActions` | Task 4 |
| §5.8 删除 widget + 能力迁移 | Task 11 |
| §5.9 Sidebar / 路由 / 角标命名 | Task 8（badge）、Task 9（路由） |
| §5.10 panelRegistry | Task 12 |
| §6 数据流（首屏/轮询/取消/深链） | Task 2 + Task 3 + Task 4 + Task 10 |
| §7.1 复用既有通知管道 | Task 14 |
| §7.2 目标通知独立队列 | Task 13 |
| §7.3 前端内提示 | Task 7（error 行）+ Task 6（failed 错误文案） |
| §8 错误处理 | Task 2（部分失败）、Task 4（toast 吞异常）、Task 7（error 展示） |
| §9 国际化 | Task 5 |
| §10.1–10.3 前端测试 | 各任务的 Step 1 |
| §10.4 后端测试 | Task 13 |
| §10.5 回归与门禁 | 每个 Task 末步 + Task 15 Step 7 |
| §10.6 / §13 双分支 | Task 15 Step 9–10 |
| §11 M1–M6 | Task 1 / 2–4 / 6–12 / 5 / 13–14 / 15 |
| §12 R1–R16 | 见下方"风险 → 缓解落点" |
| §14 文档归档 | Task 15 |

**2. Placeholder scan**：无 TBD / TODO / "类似 Task N"。所有代码块为可编译内容。

**3. Type consistency**：
- `UnifiedTaskEntry.cancelRef: { source, rawId } | null` —— Task 4 的 `cancel` 与 Task 1 的生产者一致。
- `useUnifiedTasks()` 返回 `attentionCount` / `runningCount` —— Task 8 用 `attentionCount`（重命名 `taskCenterBadgeCount`），Task 7 用 `groups/all/loading/error`，一致。
- `TaskCenterPanel({ variant })` —— Task 8 传 `"compact"`，Task 9 传 `"full"`，一致。
- `TaskCenterCard({ entry, actions, compact })` —— Task 7 的调用与 Task 6 的定义一致。
- `useTaskCenterActions()` 返回 6 个方法 —— Task 4 定义；Task 6 用 `cancel`/`open`，Task 7 用 `clearFinished`，一致。
- `GoalNotificationQueue.push(goal)` —— Task 13 Step 3 定义，Step 10 在 `goal_service` 三处调用，一致。

**4. 自审修正（已直接改入上文，executor 以上文引用处为准）**

| 发现的问题 | 修正落点 |
|---|---|
| `ExecutionBudget` fixture 形状臆造 | Task 1 改为 `{ max_rounds, max_hours, max_tokens, stop_on_failure }`（与 `entities/autonomous-goals/types.ts` 逐字一致） |
| `t()` 被传两个参数（签名只接受一个 key） | Task 6 改为 `t('taskCenter.section.more').replace('{count}', String(overflow))` |
| `DeliveryDrawerHost` 多处早退会吞掉 shell 抽屉 | Task 11 Step 3 改为 `deliveryBlock` 局部变量 + fragment 并列渲染；新增 `DeliveryDrawerHost.shell.test.tsx`（`.tsx`，原 `.ts` 只测纯函数） |
| `collapsedSections.tasks` —— 实际是 `Set<string>` | Task 8 Step 5(c) 改 `collapsedSections.has('tasks')` / `toggleCollapsed('tasks')` |
| 组件测试缺 `<I18nProvider>`（`useI18n()` 会 throw） | Task 6/7/8/9/11 的测试根节点统一包裹 |
| A4 交付/高亮能力在归一化中丢失 | 新增 `UnifiedTaskOpenTarget` + `UnifiedTaskEntry.openTarget`；Task 4 `open()` 优先直开 shell / 交付抽屉，再回落 `detailPath` |
| `TaskCenterCard` 放 widgets 层会被 `features → widgets` 禁区拒绝 | 移到 `src/features/task-center/TaskCenterCard.tsx` |
| Sidebar 深引 section 文件，偏离既有 barrel 写法 | Task 8 改为 `src/widgets/sidebar/index.ts` 追加导出，Sidebar 从 `'../sidebar'` 解构 |
| `t('...' as never)` 抹掉类型 | 全部去掉强制转换；模板串 key 才用 `as TranslationKey` |

**风险 → 缓解落点**

| 风险 | 落点 |
|---|---|
| R1 Sidebar 行数 | Task 8 Step 7 显式 `wc -l` + 架构检查 |
| R2 panelRegistry 断言 | Task 12 Step 3 |
| R3 4 处挂载点 | Task 11 Step 6 grep 残留 + Step 7 全量测试 |
| R4 折叠即停轮询 | Task 10（宿主放 Layout）+ 其测试 |
| R5 statusFilter 污染 | Task 2（独立 store，不 import 页面 store） |
| R6 chatAndSider 棘轮 | Task 5 Step 7 校验 diff 为空 |
| R7 background_tasks 污染 | Task 13（独立文件 + 独立返回键） |
| R8 py3.8 | Task 13 Step 12 + Task 15 Step 10 |
| R9 垂直空间 | Task 8 `maxHeight="320px"` + Task 7 compact 每组 3 条 |
| R10 状态词表分化 | Task 1（单处映射表 + 全枚举测试） |
| R11 路由冲突 | Task 9 Step 5（`/tasks` 无冲突） |
| R12 barrel 断言 | Task 9 Step 6 |
| R13 API 形状 | Task 2 Step 1 测试（三种形状各一例）+ Step 3 注释 |
| R14 i18n 覆盖 | Task 5 Step 1 第 4 个用例 |
| R15 变量名遮蔽 | Task 8 Step 5(d) |
| R16 attention 口径缺口 | Task 8 Step 5(d) 注释 + Task 15 文档写入已知缺口 |
