# 侧边栏任务中心（Sidebar Task Center）—— 设计规格

| 项 | 值 |
|---|---|
| 日期 | 2026-11-09 |
| 状态 | 已实施 |
| 起始分支 | `main` |
| 同步分支 | `release/win7`（cherry-pick，非 merge） |
| 关联计划 | 取代 `docs/plans/2026-10-28_idle-deferred-task-execution.md`（该文档实施后删除） |

---

## 1. 背景与问题

### 1.1 用户观察到的现象

> "之前 sage 项目应该是设计了闲时任务，为什么现在的最新版本中没有看到"

闲时自主目标（Autonomous Goal）在 v0.4.9-alpha.78 / v0.4.9-alpha.78-win7 已经实现并发布，但用户在桌面端找不到入口。

### 1.2 根因（已逐行核实）

| 核实项 | 结论 | 证据 |
|---|---|---|
| 后端调度器存在？ | ✅ 存在 | `backend/services/autonomous_goal_scheduler.py`（`check_and_start_pending_goals` / `register_to_scheduler`） |
| 后端 REST 路由存在？ | ✅ 存在 | `backend/api/autonomous_goals_router.py`（list/create/start/pause/cancel/report） |
| 前端路由存在？ | ✅ 存在 | `src/App.tsx:317` → `/goals`；`:318` → `/goals/:goalId` |
| 前端页面存在？ | ✅ 存在 | `src/features/autonomous-goals/GoalListPage.tsx` / `GoalDetailPage.tsx` |
| 前端 store 存在？ | ✅ 存在 | `src/entities/autonomous-goals/goalStore.ts`（`useGoalStore`） |
| **侧边栏导航入口存在？** | ❌ **不存在** | `src/widgets/layout/Sidebar.tsx:109-127` —— `coreNavItems` / `toolsNavItems` / `advancedNavItems` 三组共 14 项，**没有任何 `/goals` 条目** |

**结论**：功能完整可用，只是没有入口。用户必须手动敲 URL `#/goals` 才能看到。这是**可发现性缺陷**，不是功能缺失。

附带发现：`/scheduled`（定时任务）和 `/todos`（待办）虽然有导航入口，但三者是三个互不相通的页面，用户无法在一个地方看到"我此刻有哪些任务在跑"。

### 1.3 目标

1. **可发现**：闲时任务、后台长任务、待办、定时任务在侧边栏一处可见。
2. **可控制**：每个任务卡片可取消 / 暂停 / 立即运行 / 查看详情。
3. **可感知**：任务完成或失败时主动通知（不依赖用户盯着界面）。
4. **不回归**：`TaskCenterWidget` 现有的 4 类任务来源（registry / chat / lane / shell）、交付抽屉、桌宠桥接、shell 输出抽屉全部保持可用。

### 1.4 非目标（本期明确不做）

- 不在任务中心里新建任务（创建仍走 `/todos` / `/scheduled` / `/goals` 各自的页面）。
- 不做任务依赖图 / DAG 视图（编排已有 `/orchestration` 泳道视图）。
- 不做任务历史归档与检索（终态任务只在内存中保留到本会话结束）。
- 不改后端任务模型（`Goal` / `Todo` / `ScheduledTask` 的字段与接口一律不动）。

---

## 2. 竞品参考

### 2.1 海外主流

| 产品 | 做法 | 可借鉴点 |
|---|---|---|
| ChatGPT | 对话页内联"正在运行"状态；任务在侧栏可见 | 双轨入口：触发在对话，管理在侧栏 |
| Claude Code | 后台任务在终端/会话列表可见，可 `Ctrl+B` 跳转 | 打断 + 接管（interrupt & takeover） |
| Devin / Cursor Background Agent | 云端任务卡片带状态徽章 + 进度条 + 深链 | 任务单元化 + 显式进度 + 深链恢复 |
| Google Workspace / Notion AI | 完成后邮件/服务号通知 | 多通道通知 |

### 2.2 国内主流

| 产品 | 做法 | 可借鉴点 |
|---|---|---|
| 通义千问 | 任务执行前二次确认（"是否开始"） | 两步确认降低误触发 |
| 腾讯元宝 / 微信服务号 | 结果推送到服务号消息 | 通知走独立通道，不打扰当前界面 |
| 文心一言 | 长任务拆成"子任务单元"逐个可见 | 任务单元化 |
| Trae Multi-Tasks | 多任务云端并行 + 并行度控制 | 并行度与预算显式化 |
| 扣子 Coze | 工作流节点级状态回传 | 节点状态映射到统一状态机 |

### 2.3 借鉴到 Sage 的结论

1. **双轨入口**：任务既能在对话里发起，也能在侧边栏统一管理 —— 本设计采用"侧边栏分区 + rail 入口 + 完整页面"三面。
2. **任务单元化**：每个任务 = 一张独立卡片，带状态徽章 / 进度条 / 单任务操作。
3. **状态机归一**：六个来源的状态词表各不相同，必须归一到一套统一状态（见 §4.3）。
4. **显式进度**：能拿到百分比就显示百分比；拿不到就显示状态徽章 + 已耗时，不伪造进度。
5. **打断与接管**：卡片上直接给"取消"动作，不要求用户去对应页面找。
6. **深链恢复**：卡片点击直达来源详情（`/goals/:id`、`/office`、`/orchestration` 等）。
7. **独立通知通道**：任务完成走 OS 通知（复用现有 Electron 15s 轮询管道），不占用当前界面的 toast 通道。
8. **两步确认**：闲时目标由后端空闲检测自动触发，不经用户确认即有破坏性 —— 因此**启动目标**必须在卡片上显式可见，且**取消**永远可用。

---

## 3. 总体架构

### 3.1 方案：C —— 把浮动胶囊迁入侧边栏

现状是右下角浮动胶囊 `TaskCenterWidget`（496 行），只能在内容区右上角浮着，承载 registry / chat / lane / shell 四类任务。用户反馈的"看不到闲时任务"则完全不在它的射程内。

**采用方案 C**：删除浮动胶囊，把任务聚合能力下沉到侧边栏与 `/tasks` 页面。

### 3.2 三个可见面

```
┌─ rail（56px，常驻） ─┐┌─ 内容列（240px） ────────┐┌─ 主区域 ───────────┐
│  🗂 项目              ││ ▸ 项目                   ││                     │
│  💬 对话              ││ ▸ 会话                   ││   /tasks            │
│  ✅ 待办              ││ ▸ Git                    ││   完整任务中心      │
│  🧠 记忆              ││ ▸ 任务  ← 新增分区        ││                     │
│  ⏰ 定时任务          ││   ┌──────────────────┐  ││                     │
│  ⚡ 任务  ← 新增(角标) ││   │ ▸ 运行中  2      │  ││                     │
│  🎯 闲时目标 ← 新增   ││   │ ▸ 失败    1      │  ││                     │
└──────────────────────┘│   └──────────────────┘  │└─────────────────────┘
```

| 面 | 位置 | 内容 | 密度 |
|---|---|---|---|
| rail 入口 | `Sidebar.tsx` rail 分组 | "任务"图标 + 进行中数量角标 → `/tasks` | 极低（56px） |
| 内容列分区 | `Sidebar.tsx` 内容列 | "任务"分区：进行中 / 待处理 / 失败 分组卡片 | 低（240px，最多 8 张，超出内部滚动） |
| 完整页面 | 新增 `/tasks` 路由 | 全部来源 × 全部状态，可筛选、可分组、可清空终态 | 高（整页） |

**为什么保留内容列分区而不只做页面**：idle 目标在后台跑，用户往往正在别处工作，rail 角标只能给一个数字，内容列分区能给出标题 + 状态 + 取消按钮——这是"随时可接管"的前提。

**为什么还要完整页面**：内容列宽 240px，与会话分区（`flex-1`）争抢垂直空间；且"定时任务"与"待办"是"任务定义"而非"运行实例"，需要在更宽的视图里对照查看。

### 3.3 分层与 FSD 合规

本项目 FSD 分层由 ESLint 强制（`eslint.config.js:60-110`，全部 `error`）：

```
app > processes > pages > widgets > features > entities > shared
```

`features → features` **允许**（既有先例：`src/features/attention/useAttentionSnapshot.ts` → `../changes/changesListStore`）；`shared` 不得导入 `entities/features/widgets/pages/app/processes`。

| 关注点 | 落点 | 层级 | 依赖合法性 |
|---|---|---|---|
| 统一任务模型（类型 + 状态归一表 + 纯函数） | `src/features/task-center/unifiedTaskModel.ts` | features | 依赖 `entities`（Goal/Lane 类型）+ `shared`（Todo/ScheduledTask 类型）✅ |
| 统一聚合 hook | `src/features/task-center/useUnifiedTasks.ts` | features | 依赖 `features/task-center` + `entities/*` + `features/send-message` ✅ |
| 统一动作分发 | `src/features/task-center/useTaskCenterActions.ts` | features | 同上 ✅ |
| 轮询宿主（shell + goal） | `src/features/task-center/TaskCenterRuntimeHost.tsx` | features | ✅ |
| 卡片 UI | `src/widgets/task-center/TaskCenterCard.tsx` | widgets | 可依赖 features/entities/shared ✅ |
| 侧边栏分区 | `src/widgets/sidebar/sections/TaskCenterSection.tsx` | widgets | ✅ |
| 完整页面内容 | `src/features/task-center/TaskCenterPanel.tsx` | features | ✅ |
| 路由页薄壳 | `src/pages/TasksPage.tsx` | pages | 可依赖 features ✅ |

> ⚠️ **明确禁止**：状态归一表**不得**放在 `src/shared/lib/statusMaps.ts`。`TaskCenterStatus` 定义在 `src/features/task-center/taskCenterStore.ts`，`shared` 导入 `features` 会被 ESLint FSD 规则判为 **error**。归一表必须落在 `features` 层。

### 3.4 数据流总览

```
   ┌── 实时 store（已有，响应式读取）──────────────┐
   │ taskCenterStore.tasks      registry + shell │
   │ chatStreamStore.sessions   chat             │
   │ laneBoardStore.lanes       lane             │
   └───────────────────┬────────────────────────┘
                       │
   ┌── 轮询 store（新增）────────────────────────┐
   │ unifiedTaskStore                            │
   │   goals        ← goalApi.listGoals()   10s │
   │   todos        ← todoClient.list()     30s │
   │   scheduled    ← scheduledClient.list() 30s │
   └───────────────────┬────────────────────────┘
                       │
              ┌────────▼─────────┐
              │ useUnifiedTasks  │  归一 + 排序 + 分组 + 过滤
              └────────┬─────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   rail 角标      内容列分区      /tasks 页面
   (Sidebar)   (TaskCenterSection) (TaskCenterPanel)
                       │
                       ▼
              useTaskCenterActions
              取消/暂停/立即运行/深链
```

---

## 4. 统一任务模型

### 4.1 归一后的条目

```ts
// src/features/task-center/unifiedTaskModel.ts

export type UnifiedTaskSource =
  | 'registry'   // taskCenterStore：office / wiki / custom / shell 长任务
  | 'chat'       // chatStreamStore：后台会话流
  | 'lane'       // laneBoardStore：编排泳道
  | 'goal'       // 闲时自主目标
  | 'todo'       // 待办
  | 'scheduled'; // 定时任务

export interface UnifiedTaskEntry {
  /** 全局唯一：`<source>:<rawId>` */
  id: string;
  source: UnifiedTaskSource;
  /** 归一化标题（已做空值兜底，永不为空串） */
  title: string;
  /** 归一化状态（见 §4.3） */
  status: TaskCenterStatus;
  /** 开始时间（epoch ms）；无则 null */
  startedAt: number | null;
  /** 更新时间（epoch ms）；无则 null */
  updatedAt: number | null;
  /** 进度 0-100；无则 null（**不伪造**） */
  percent: number | null;
  /** 错误信息；无则 null */
  error: string | null;
  /** 是否可取消 */
  cancellable: boolean;
  /** "查看详情"目标路由；null = 不可跳转 */
  detailPath: string | null;
  /** 取消动作所需的原始标识 */
  cancelRef: { source: UnifiedTaskSource; rawId: string } | null;
  /** 附加展示信息（文档名 / 会话标题 / 泳道 agent 等） */
  meta: Record<string, string | number | null>;
}
```

> `status` 复用 `TaskCenterStatus`（`src/features/task-center/taskCenterStore.ts`），7 个取值：`queued | running | awaiting_approval | paused | succeeded | failed | cancelled`。不新造第二套状态词表。

### 4.2 六种来源的原始字段映射

**注意各来源字段名与时间戳类型并不一致**，这是本设计最容易出错的地方，逐条列明：

| source | 原始 id | 标题字段 | 状态字段 | 开始时间 | 更新时间 | 进度 | 错误字段 | 时间戳类型 |
|---|---|---|---|---|---|---|---|---|
| `registry` | `entry.id` | `entry.title`（+ `entry.phase`） | `entry.status` | `entry.startedAt` | `entry.finishedAt` | `entry.percent` | `entry.error` | epoch ms |
| `chat` | `session.id` | 会话标题（`useStore.sessions`） | 恒为 `running` | 首见时间（ref 记录） | — | — | — | epoch ms |
| `lane` | `lane.lane_id` | `lane.task_id` (+ `lane.agent_id`) | `lane.status` | `lane.started_at` | `lane.completed_at` | — | `lane.error` | epoch ms |
| `goal` | `goal.id` | **`goal.name`** | `goal.status` | `goal.started_at` | `goal.completed_at` | `goal.completion_percentage` | `goal.last_error` | **ISO 字符串** |
| `todo` | **`todo.id`（number）** | **`todo.title`** | `todo.status` | — | `todo.updated_at` | — | — | **ISO 字符串** |
| `scheduled` | `task.id` | **`task.name`** | `task.last_status` | — | `task.last_attempt` | — | `task.last_error` | **epoch ms** |

补充事实：

- `ScheduledTask` **没有** `updated_at` / `title` / `description` / `priority` 字段。
- `Todo.priority` 是 `'high' | 'medium' | 'low'`（**不是** 0-100 数字）。
- `Todo.id` 是 number，其余来源的 id 是 string；统一模型里一律转成字符串拼进 `<source>:<rawId>`。
- `Goal.created_at` / `Todo.created_at` 是 ISO 字符串；`ScheduledTask.created_at` 是 epoch ms 数字。归一函数负责转换。

### 4.3 状态归一映射表

```ts
export const GOAL_STATUS_MAP: Readonly<Record<GoalStatus, TaskCenterStatus>> = {
  pending: 'queued',
  running: 'running',
  paused: 'paused',
  completed: 'succeeded',   // 注意：Goal 用 completed，不是 succeeded
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
  Record<'never' | 'running' | 'succeeded' | 'failed', TaskCenterStatus>
> = {
  never: 'queued',
  running: 'running',
  succeeded: 'succeeded',
  failed: 'failed',
};

// Lane 映射沿用 TaskCenterWidget 中已验证的 LANE_STATUS_MAP
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
```

排序优先级（沿用现有 `STATUS_PRIORITY`，值越小越靠前）：

```ts
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

### 4.4 可见性规则（哪些任务真的出现在列表里）

不是所有数据都该显示。`todo` / `scheduled` 是"任务定义"，`goal` / `registry` / `chat` / `lane` 是"运行实例"。规则如下：

| source | 进入"进行中"列表的条件 | 进入"已完成"分组的条件 |
|---|---|---|
| `registry` | 非终态（`queued/running/awaiting_approval/paused`） | 终态（`succeeded/failed/cancelled`） |
| `chat` | 恒为进行中（后台会话流） | —— |
| `lane` | `isLaneVisible(status) || isLaneAwaitingDecision(lane)` | 其余 lane 不展示 |
| `goal` | `pending` / `running` / `paused` | `completed` → 已完成；`failed` → **失败组（需处理）** |
| `todo` | `in_progress` | `completed` → 已完成；`cancelled` → 不展示 |
| `scheduled` | `last_status === 'running'` | `last_status === 'failed'` → **失败组**；`succeeded` → 不展示（历史成功不是"待办"） |

**关键判断**：`todo` 的 `pending` 与 `scheduled` 的 `never`/`succeeded` **不进入任务中心**。一个 200 条的待办清单塞进任务中心会把真正在跑的任务淹没。待办与定时任务的"定义视图"仍由 `/todos`、`/scheduled` 页面承担；任务中心只负责"此刻正在发生什么"+"什么失败了需要处理"。

例外：`goal` 的 `pending` 状态（已排期但还没被空闲检测触发）**进入**列表——这是"闲时任务"的本体，用户最需要看到的就是它。

### 4.5 shell 子类

shell 任务在 `taskCenterStore.tasks` 里以 `kind === 'shell'` 存放（由 `registerShell` / `removeMissingShells` 维护）。归一时归入 `registry` 来源，但：

- `cancellable = status === 'running'`
- `cancelRef` 指向 shell，取消动作是 `invoke('shell_kill', { id: shellId })`
- `detailPath = null`，点击直接打开 shell 输出抽屉（沿用 `openShellStream`）
- `error` 展示 `exit=<code>`（沿用现有行为）

---

## 5. 组件设计

### 5.1 新增 / 删除 / 修改清单

**新增（9 个文件）**

| 文件 | 职责 | 预估行数 |
|---|---|---|
| `src/features/task-center/unifiedTaskModel.ts` | 类型 + 4 张状态映射表 + 6 个纯归一函数 | ~230 |
| `src/features/task-center/unifiedTaskStore.ts` | goal/todo/scheduled 三源原始列表 + 轮询刷新 | ~150 |
| `src/features/task-center/useUnifiedTasks.ts` | 合并 6 源 → 归一 → 排序 → 分组 | ~130 |
| `src/features/task-center/useTaskCenterActions.ts` | 取消/暂停/立即运行/深链跳转分发 | ~120 |
| `src/features/task-center/TaskCenterRuntimeHost.tsx` | 常驻宿主：shell 3s 轮询 + goal 10s 轮询（null 渲染） | ~90 |
| `src/features/task-center/TaskCenterPanel.tsx` | 完整页面内容：筛选 + 分组 + 卡片列表 | ~260 |
| `src/widgets/task-center/TaskCenterCard.tsx` | 统一任务卡片（分区与页面共用） | ~150 |
| `src/widgets/sidebar/sections/TaskCenterSection.tsx` | 内容列「任务」分区 | ~170 |
| `src/pages/TasksPage.tsx` | `/tasks` 路由薄壳 | ~40 |

**删除（1 个源文件 + 5 个测试）**

- `src/widgets/task-center/TaskCenterWidget.tsx`
- `src/widgets/task-center/__tests__/TaskCenterWidget.{test,a1,a4,dedupe,shells}.test.tsx` → 拆解后重写为新模型的测试

**修改（9 个文件）**

| 文件 | 改动 |
|---|---|
| `src/widgets/layout/Sidebar.tsx` | `SECTION_KEYS` 加 `'tasks'`；`renderSection` 加 `case 'tasks'`；`coreNavItems` 加 `/tasks` 与 `/goals`；rail 角标 |
| `src/widgets/layout/Layout.tsx` | 移除 `<TaskCenterWidget />`，加 `<TaskCenterRuntimeHost />` |
| `src/widgets/task-center/DeliveryDrawerHost.tsx` | 接管 `ShellStreamDrawer` 挂载（原挂在 `TaskCenterWidget` 内部） |
| `src/features/app-panels/panelRegistry.ts` | `task-center` 槽位 `floating` → `left-list`，`currentOwner` 改指新文件 |
| `src/features/app-panels/__tests__/panelRegistry.test.ts` | 更新两处硬编码断言（见 §5.10） |
| `src/App.tsx` | 新增 `/tasks` 路由（**lazy import**） |
| `src/pages/index.ts` | **不改**（加导出会破坏 `pagesIndex.p142.test.ts` 的 `exportedPageCount === 5` 断言，见 §5.9） |
| `src/shared/lib/i18n/locales/{zh,en}/taskCenter.ts` | 新建文案域文件 |
| `src/shared/lib/i18n/{zh,en}.ts` | 各自加 1 行 import + 1 行 spread |
| `electron/schedulerNotifications.ts` | `collectNotificationItems` 合并 `goal_notifications` |

**后端修改（4 个文件）**

| 文件 | 改动 |
|---|---|
| `backend/services/goal_notifications.py` | **新增**：目标完成/失败通知队列（与 `BackgroundNotificationQueue` 同构） |
| `backend/services/goal_service.py` | `_execute_loop` 中 `COMPLETED`（:230）与 `FAILED`（:246、:634）后推一条通知 |
| `backend/api/scheduled_router.py` | `drain_pending_notifications` 返回体新增 `goal_notifications` 键 |
| `backend/services/background_notifications.py` | 不改（shell 队列语义保持不变） |

### 5.2 `useUnifiedTasks` —— 聚合 hook

**纯读取，无副作用。** 任何组件都可以安全调用（侧边栏分区与页面同时挂载也不会重复请求）。

```ts
export interface UnifiedTaskGroups {
  active: UnifiedTaskEntry[];   // queued/running/paused/awaiting_approval
  failed: UnifiedTaskEntry[];    // failed
  finished: UnifiedTaskEntry[];  // succeeded/cancelled
}

export interface UnifiedTasksResult {
  groups: UnifiedTaskGroups;
  all: UnifiedTaskEntry[];
  /** 进行中 + 失败 的总数，用于 rail 角标 */
  attentionCount: number;
  /** 纯 running 的数量，用于 rail 角标细分 */
  runningCount: number;
  loading: boolean;
  error: string | null;
}

export function useUnifiedTasks(): UnifiedTasksResult;
```

实现要点：

1. 响应式读取 3 个既有 store：`useTaskCenterStore(s => s.tasks)`（`src/features/task-center/taskCenterStore.ts`）、`useChatStreamStore(s => s.sessions)`（`src/features/send-message/chatStreamStore.ts`，形状是 `Record<sessionId, SessionStreamSlots>`）、`useLaneBoardStore(s => s.lanes)`（`src/entities/orchestration/laneBoardStore.ts`）；再读 `useStore(s => s.sessions)`、`useStore(s => s.currentSessionId)`（`src/shared/lib/store`）。
2. 读取 `useUnifiedTaskStore(s => s.goals / s.todos / s.scheduledTasks)`。
3. `useMemo` 中依次调用 6 个归一函数拼装原始条目数组。
4. **chat 排除当前会话**：沿用现有去重规则——当前会话的流由 Chat 页内指示表达，任务中心只列后台会话（`TaskCenterWidget.dedupe.test.tsx` 已验证该行为）。
5. **chat 首见时间**：用 `useRef<Map<string, number>>` 记录每个后台会话流的首见时间戳（现有 `streamStartsRef` 模式）。该 ref 不进 `useMemo` 依赖——现有实现靠"维护 effect 先跑"保证首见时间已就位，沿用同一约定。
6. 排序：`STATUS_PRIORITY` 升序 → 同状态按 `startedAt` 升序（null 排最后）→ 再按 `id` 字典序兜底，保证顺序稳定。
7. 分组：按 §4.4 规则分入 `active` / `failed` / `finished`。

### 5.3 `unifiedTaskStore` —— 三源轮询 store

```ts
interface UnifiedTaskState {
  goals: Goal[];
  todos: Todo[];
  scheduledTasks: ScheduledTask[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}
```

**为什么不复用 `useGoalStore` / `useTodoStore` / `useScheduledTaskStore`**：

- `useGoalStore.load(status?)` 会读取 store 里的 `statusFilter`（`goalStore.ts:48`：`status ?? get().statusFilter ?? undefined`）。任务中心若调用 `load()`，会把用户在 `/goals` 页面设的过滤条件一并带上，导致任务中心只看到过滤后的子集。
- 三个页面 store 各自有独立的加载节奏与筛选态；任务中心需要"全量、无过滤、独立节奏"的数据视图。
- 任务中心的数据**只读**；写操作（取消 / 暂停 / 立即运行）直接调 API 客户端并就地更新本 store，不触碰页面 store。

数据来源（均为既有 API 客户端，无新增后端接口）。**注意三个客户端的返回形状并不一致**：

| 数据 | 客户端 | 调用 | 返回 | store 里存什么 |
|---|---|---|---|---|
| goals | `src/entities/autonomous-goals/goalApi.ts` | `listGoals(undefined, 200, 0)` | `GoalListResponse { items, total, limit, offset }` —— **包一层** | `resp.items` |
| todos | `src/shared/api/todoClient.ts` | `todoClient.list({ limit: 200, offset: 0, include_completed: true })` | `TodoListResponse { items, total, limit, offset }` —— **包一层** | `resp.items` |
| scheduled | `src/shared/api/scheduledClient.ts` | `scheduledClient.list()` | `ScheduledTask[]` —— **直接是数组** | 数组本身 |

要点：

- `listGoals` 的默认 `limit` 是 **50**，对"全量视图"不够，任务中心必须显式传更大的 limit（后端 `limit` 参数为可选）。
- `TodoListParams` **没有** `page_size` 字段，用的是 `limit` / `offset`。
- `include_completed: true` 是必需的：否则 completed 的 todo 拿不到，"已完成"分组会永远是空的。
- `TodoListParams.status` 传 `undefined`（不过滤），任务中心要全量。

### 5.4 `TaskCenterRuntimeHost` —— 常驻轮询宿主

`null` 渲染组件，挂在 `src/widgets/layout/Layout.tsx`（替换原 `<TaskCenterWidget />` 的位置）。

职责：

1. **shell 轮询（3s）**：完全沿用 `TaskCenterWidget.tsx:228-256` 的逻辑——`listShells()` → `registerShell` / `removeMissingShells` → `taskCenterStore`。
2. **goal 轮询（10s）**：`unifiedTaskStore.refreshGoals()`，**仅当存在非终态 goal 时才继续轮询**（全部终态则停），避免长期空转。
3. **todo / scheduled 轮询（30s）**：同理，仅当存在 `in_progress` todo 或 `running` scheduled task 时继续。

> **为什么必须常驻**：侧边栏分区在折叠状态下 `render()` 不会被调用（`SiderSection` 的 body 由 `render` prop 提供），把轮询放在分区里会导致"折叠即停止同步"——用户折叠侧边栏后，后台 shell 退出不会反映到任务中心，任务状态永远卡在 `running`。

### 5.5 `TaskCenterSection` —— 内容列分区

位置：`src/widgets/sidebar/sections/TaskCenterSection.tsx`（与 `ConversationsSection.tsx` / `GitStatusSection.tsx` 同级）。

结构（复用 `src/widgets/sidebar/SiderSection.tsx`）：

```tsx
<SiderSection
  sectionKey="tasks"
  label={t('taskCenter.section.title')}
  icon={ListTodo}
  collapsed={collapsed}
  onToggleCollapsed={onToggleCollapsed}
  maxHeight="320px"
  trailing={<span className="...">{attentionCount}</span>}
  render={() => <TaskCenterPanel variant="compact" />}
/>
```

密度约束（DESIGN.md §10）：

- 章节头 `px-3 py-1.5`（h-8 / 32px），尾随计数用 `text-ui-2xs text-muted`。
- 卡片行高 h-9（36px），与 `ConversationsSection` 的列表项对齐。
- 分组标题 `text-ui-2xs uppercase text-muted px-3 py-1`，组间 `border-t border-ui-border mt-1`。
- 分区之间用 `SiderSection` 既有的 `mt-1` 间距。

紧凑模式（`variant="compact"`）与完整模式的差异：

| | compact（内容列） | full（`/tasks` 页面） |
|---|---|---|
| 每组最多显示 | 3 条 + "还有 N 条 →" | 全部 |
| 分组 | 进行中 / 失败（**不显示已完成组**） | 进行中 / 失败 / 已完成 |
| 筛选条 | 无 | 来源筛选 chip + 状态筛选 |
| 标题行 | 无（靠章节头） | 标题 + 副标题 + 计数 |
| 清空终态 | 无 | 有（"清除已完成"按钮） |

### 5.6 卡片 `TaskCenterCard`

一张卡片 = 一行任务摘要。字段：

```
┌──────────────────────────────────────────────┐
│ [图标] 标题文字（单行省略）        [状态徽章]  │
│ [来源标签] [进度条 / 已耗时]        [取消按钮] │
└──────────────────────────────────────────────┘
```

- **图标**：按 source 取 `lucide-react` 图标（registry=`FileSpreadsheet`、chat=`MessageSquare`、lane=`Network`、goal=`Target`、todo=`ListTodo`、scheduled=`CalendarClock`）。
- **标题**：单行 `truncate`。
- **状态徽章**：复用 `taskCenter.status.*` 现有文案 + 既有色调映射（沿用 `TaskCenterWidget` 的徽章样式）。
- **进度**：`percent != null` 时渲染细进度条；否则渲染 `已耗时 Xm`（`startedAt` 为 null 时不显示）。
- **取消按钮**：`cancellable` 时显示，`onClick` 走 `useTaskCenterActions.cancel(entry)`。
- **点击**：整卡可点 → `detailPath` 存在则 `navigate(detailPath)`；shell 条目改为 `openShellStream(shellId)`。
- **无障碍**：卡片是 `<button>` 或内含 `<button>`，aria-label 含标题与状态。

### 5.7 `useTaskCenterActions` —— 动作分发

```ts
export interface TaskCenterActions {
  cancel: (entry: UnifiedTaskEntry) => Promise<void>;
  pause: (entry: UnifiedTaskEntry) => Promise<void>;
  resume: (entry: UnifiedTaskEntry) => Promise<void>;
  runNow: (entry: UnifiedTaskEntry) => Promise<void>;
  open: (entry: UnifiedTaskEntry) => void;
  clearFinished: () => void;
}
```

| source | cancel | pause / resume | runNow | open |
|---|---|---|---|---|
| `registry`（shell） | `invoke('shell_kill', { id: shellId })` | —— | —— | `openShellStream(shellId)` |
| `registry`（其它） | 不可取消（现有行为 `cancellable: false`） | —— | —— | `navigate(detailPath)` |
| `chat` | 现有会话中断机制 | —— | —— | `navigate('/chat?session=...')` |
| `lane` | 现有泳道取消 | —— | —— | `navigate('/orchestration')` |
| `goal` | `goalApi.cancelGoal(id)` | `goalApi.pauseGoal(id)` / `goalApi.startGoal(id)` | —— | `navigate('/goals/' + id)` |
| `todo` | `todoClient.cancel(id)` | —— | —— | `navigate('/todos')` |
| `scheduled` | 不可取消（改为停用） | —— | `scheduledClient.runNow(id)` | `navigate('/scheduled')` |

失败处理：捕获异常 → `toast.error(...)` → 不抛给调用方（与既有 `goalStore` / `todoStore` 的错误处理风格一致）。

### 5.8 删除 `TaskCenterWidget` 与能力迁移

| 原能力 | 新归属 |
|---|---|
| registry / chat / lane / shell 四源聚合 | `useUnifiedTasks` |
| 状态徽章与排序 | `TaskCenterCard` + `unifiedTaskModel` |
| shell 3s 轮询 | `TaskCenterRuntimeHost` |
| **shell 输出抽屉**（`ShellStreamDrawer`） | 迁到 `DeliveryDrawerHost`（两者都是全局 overlay，语义一致） |
| **交付抽屉**（`DeliveryDrawerHost`） | 不动（`Layout.tsx:215` 独立挂载，不受影响） |
| **桌宠桥接**（`TaskCenterPetBridge`） | 不动（`App.tsx:334` 独立挂载；只读 `taskCenterStore.tasks`，契约不变） |
| `clearFinished` | `unifiedTaskStore` + `taskCenterStore.clearFinished` 双通道 |

> `TaskCenterPetBridge` 依赖 `taskCenterStore.tasks` 的数据契约，本设计**完全不改** `taskCenterStore` 的结构，因此桌宠无回归。

### 5.9 侧边栏与路由改动

**`Sidebar.tsx`**（当前 728 行，未列入架构基线，上限 800 行——本次改动必须控制在 **+70 行以内**，新增逻辑一律下沉到新文件）：

```ts
const SECTION_KEYS = ['project', 'conversations', 'git', 'tasks'] as const;
```

- `renderSection` 增加 `case 'tasks'` → `<TaskCenterSection collapsed={isCollapsed} onToggleCollapsed={...} />`（约 8 行）。
- `coreNavItems` 增加 `{ path: '/tasks', label: '任务', icon: ListTodo }`。
- `toolsNavItems` 增加 `{ path: '/goals', label: '闲时目标', icon: Target }`。
- rail 角标：`SidebarNavItem` 已支持 `trailing`（rail 变体渲染为图标右上角浮层），`/tasks` 传 `AttnBadge`。

> ⚠️ **变量名冲突（实施时必读）**：`Sidebar.tsx` 已有一个**本地** `attentionCount` 变量，含义是 `pendingApprovals + pendingQuestions`（审批 + 提问），挂在 `/chat` 入口上（`Sidebar.tsx:236, 511`）。任务中心的计数语义完全不同（进行中 + 失败的任务），**必须使用不同变量名**，例如 `taskCenterBadgeCount`，避免遮蔽既有变量导致 `/chat` 角标显示错数。
>
> 两个数字的语义区别：
>
> | 位置 | 变量 | 语义 | 数据源 |
> |---|---|---|---|
> | `/chat` 入口角标 | `attentionCount`（既有） | "需要你做什么"——审批 + 提问 | `usePermissionState` + `useQuestionState` |
> | `/tasks` 入口角标 | `taskCenterBadgeCount`（新增） | "此刻有多少任务在跑或挂了"——进行中 + 失败 | `useUnifiedTasks().attentionCount` |
> | rail 底部统一总数 | `attention.total`（既有） | 各 attention 来源求和 | `useAttentionSnapshot` |
>
> **本期不把任务中心接入 `useAttentionSnapshot`**：该 feature 的 `AttentionKind` 是固定联合 `approval | question | artifact | todo | git`，新增 `task` 种类会连带改 `ATTENTION_KINDS` 顺序、`KIND_LABELS` 与 rail 底部总数口径，超出本期范围（YAGNI）。**已知缺口**：rail 底部的统一总数**不包含**任务中心的失败数；两者并列展示，标题文案需能区分。后续可另开一个"接入 attention 聚合"的小任务。

**折叠与排序复用既有机制**：`useSiderSections` 的存储键是 `sage:sider:sections:v1`，内容为 `{ order: string[], collapsed: string[] }`。新增 `'tasks'` 键后，`reconcileStoredSiderOrder`（`src/shared/lib/dnd/siderOrder.ts`）会**把新键追加到顺序末尾**，老用户的既有顺序与折叠状态不受影响；`collapsed` 会被过滤为 `defaultOrder` 中存在的键，因此 `'tasks'` 默认展开。

> 不引入 `sage:sidebar:taskCenter:collapsed:v1` 之类的独立存储键——那会与既有的 `useSiderSections` 形成第二套折叠状态源。

**`App.tsx`**：新增 `path="/tasks"` → `<TasksPage />`（`src/pages/TasksPage.tsx`）。

必须沿用既有 **lazy 路由** 模式（`App.tsx` 中所有页面路由都是 `lazy()`），不得静态 import：

```ts
const TasksPage = lazy(() => import('./pages/TasksPage').then((m) => ({ default: m.TasksPage })));
```

> ⚠️ **不得**把 `TasksPage` 加进 `src/pages/index.ts` barrel。该 barrel 的治理函数 `auditPagesBarrelGovernance()` 默认返回 `exportedPageCount: 5`，且 `src/pages/Help/__tests__/pagesIndex.p142.test.ts:10` 断言 `expect(res.exportedPageCount).toBe(5)` —— 加入第 6 个导出会让该测试红。既有 `TodoPage` 与 `ScheduledTasks` 同样**没有**进 barrel，遵循同一做法。

> `src/pages/README.md` 顶部有一句"Sage 当前页面：Chat / Knowledge / Skills / Agents / Memory / Settings"，本设计**不改**这一行（它本就不完整，`TodoPage` / `ScheduledTasks` 也没列）。

### 5.10 `panelRegistry` 与其测试

`panelRegistry.ts` 中现有条目：

```ts
{ id: 'task-center', slot: 'floating', label: '任务中心',
  migrationBatch: 'C', currentOwner: 'widgets/task-center/TaskCenterWidget.tsx:305' },
```

浮动胶囊删除后该条目必须改写，否则注册表指向一个不存在的文件：

```ts
{ id: 'task-center', slot: 'left-list', label: '任务中心',
  migrationBatch: 'C', currentOwner: 'widgets/sidebar/sections/TaskCenterSection.tsx' },
```

**这会打破 `panelRegistry.test.ts` 中的两处硬编码断言**（必须同步更新，否则 CI 红）：

1. `expect(ids).toEqual(['sider-projects', 'sider-conversations', 'sider-git'])` → 追加 `'task-center'`。
2. `expect(getPanelDefinition('task-center')?.slot).toBe('floating')` → 改为 `'left-list'`。

**影响评估**：

- `slotGeometry('left-list').exclusive === true` 不变 → `isExclusiveConflict('task-center', 'sider-git')` 变为 `true`。
- 但 `left-list` 槽位的三个既有面板（`sider-projects` / `sider-conversations` / `sider-git`）本来就互斥，且**侧边栏实际渲染并不走 `panelRegistry` 的互斥机制**（`Sidebar.tsx` 的 `sectionOrder.map` 是并列渲染）。`panelRegistry` 在此只承担"槽位登记 + 几何定义"职责。因此把 `task-center` 登记进 `left-list` 不改变实际渲染行为。
- `floating` 槽位将变为空槽位。`slotGeometry('floating')` 仍保留（几何定义不动），`exclusive: false` 的断言仍成立；仅需把 `task-center` 的槽位断言改为 `'left-list'`。

> 备选方案（保留 `task-center` 在 `floating`、另登记新 id `sider-task-center`）会造成同一功能在注册表里出现两条记录，且旧 id 的 `currentOwner` 指向已删除的文件 —— 不采用。

---

## 6. 数据流详细设计

### 6.1 首屏加载

```
Layout 挂载
  └─ TaskCenterRuntimeHost
       └─ useEffect: unifiedTaskStore.refresh()   ← goal/todo/scheduled 各拉一次
       └─ useEffect: shell 轮询（3s，立即先跑一次）

侧边栏分区 / /tasks 页面挂载
  └─ useUnifiedTasks()   ← 纯读，无请求
```

三个页面（`/todos`、`/scheduled`、`/goals`）各自 `useEffect(() => { void load(); }, [])` 的行为不变，与任务中心互不干扰。

### 6.2 轮询节奏

| 数据 | 间隔 | 停止条件 |
|---|---|---|
| shell | 3s（沿用 `SHELL_TASK_POLL_MS`） | 组件卸载 |
| goals | 10s | 全部 goal 处于终态 → 停；出现非终态 → 恢复 |
| todos | 30s | 无 `in_progress` todo → 停 |
| scheduled | 30s | 无 `running` scheduled task → 停 |
| chat | 无需轮询（`chatStreamStore` 是推送式） | —— |

### 6.3 取消动作时序

```
用户点卡片上的「取消」
  → useTaskCenterActions.cancel(entry)
  → 按 source 分发到对应 API / invoke
  → 成功后：unifiedTaskStore 局部更新该条目状态 → toast.success
  → 失败：toast.error，条目状态不变
```

`registry`（shell）取消后，3s 轮询会在下一轮把 shell 状态同步回来（沿用现有机制：先 `shell_kill`，轮询纠正）。

### 6.4 深链恢复

| source | detailPath |
|---|---|
| registry（office） | `/office` |
| registry（wiki） | `/knowledge` |
| registry（custom） | `null`（无详情页） |
| chat | `/chat?session=<encoded>` |
| lane | `/orchestration` |
| goal | `/goals/<goalId>` |
| todo | `/todos` |
| scheduled | `/scheduled` |

---

## 7. 通知机制

### 7.1 现有管道（复用，不新建）

```
后端进程内队列（bounded deque，无持久化）
  → GET /api/v1/scheduled/notifications/pending
  → Electron 主进程 15s 轮询（electron/schedulerNotifications.ts）
  → OS 通知
```

当前返回体三键：`scheduled_tasks` / `todo_reminders` / `background_tasks`。

### 7.2 新增：闲时目标完成通知

**问题**：闲时目标在后台自动跑完，用户完全不知情——这正是"看不到闲时任务"的另一半。

**实现**：

1. **新增 `backend/services/goal_notifications.py`**：与 `BackgroundNotificationQueue` 同构的进程内队列（`threading.Lock` + `deque(maxlen=100)`，无持久化），提供：
   - `push_goal_notification(goal_id, goal_name, status, detail)` —— `status` ∈ `'succeeded' | 'failed'`。
   - `drain_goal_notifications()` —— 排空并返回。

   > **为什么必须独立队列**：现有返回体的 `background_tasks` 键就是 `BackgroundNotificationQueue.drain()`（`scheduled_router.py`）。若目标通知进同一个队列，drain 会把 goal 通知混进 `background_tasks`，污染既有 shell 通知语义。独立队列 + 独立返回键是唯一零污染的做法。

2. `backend/services/goal_service.py`：
   - `_execute_loop` 中 `goal.status = GoalStatus.COMPLETED`（约 :230）之后推一条成功通知。
   - `goal.status = GoalStatus.FAILED`（约 :246 与 `_apply_degradation` 的 :634）之后推一条失败通知（含 `goal.last_error`）。
   - `cancel` 路径**不推**通知（用户主动取消，不是"完成"）。

3. `backend/api/scheduled_router.py` 的 `drain_pending_notifications` 返回体新增独立键：

   ```python
   return {
       "scheduled_tasks": svc.drain_pending_notifications(),
       "todo_reminders": todo_items,
       "background_tasks": get_background_notification_queue().drain(),
       # 2026-11-09: 闲时目标完成/失败通知（独立队列，避免污染 background_tasks）
       "goal_notifications": drain_goal_notifications(),
   }
   ```

4. `electron/schedulerNotifications.ts` 的 `collectNotificationItems(payload)` 合并 `goal_notifications`（与现有三键同构：含 `title` 才收）。

### 7.3 前端内提示

任务中心卡片上的终态条目提供"清除已完成"按钮（`/tasks` 页面）。不引入新的 toast 通道，避免与既有 `sonner` toast 打架。

---

## 8. 错误处理

| 场景 | 行为 |
|---|---|
| `unifiedTaskStore.refresh()` 某个源失败 | 该源列表保持上一份数据不变，`error` 字段记录文案，其余源正常渲染（**部分失败不阻塞整体**） |
| 三个源全部失败 | 面板显示错误态 + "重试"按钮（调 `refresh()`） |
| 目标轮询 401 | 后端未起 / token 失配。沿用现有 `BackendStatusBanner` 的统一提示，任务中心不重复报错 |
| 取消动作失败 | `toast.error`，条目状态不变，不乐观更新 |
| shell 轮询失败 | 静默（沿用现有 `catch` 注释：任务中心是增强信息） |
| 归一函数遇到未知状态值 | `switch` 的 `default` 分支映射为 `'queued'` 并在 `meta` 记 `unknownStatus`，不抛错 |
| `percent` 超出 0-100 | 归一时 `clamp` 到 `[0, 100]` |
| `startedAt` 为负数或非有限 | 归一为 `null` |

---

## 9. 国际化

**新增文案域文件**：`src/shared/lib/i18n/locales/zh/taskCenter.ts` 与 `.../en/taskCenter.ts`。

> **为什么不加进 `chatAndSider.ts`**：该文件在架构基线内（zh 825 行 / en 824 行），棘轮规则（`scripts/architecture-check.mjs:76-88`）规定**基线内文件不得增长**，超出即判违规。当前实际 824 / 823 行，余量仅 1 行，放不下新文案。新建独立文件是最干净的做法。

**聚合**：`src/shared/lib/i18n/zh.ts`（58 行）与 `en.ts`（57 行）**未列入基线**，各加 1 行 import + 1 行 spread 即可。

**键位（`taskCenter.*` 命名空间）**：

既有 `taskCenter.*` 键的分布已核实（zh / en 对称）：

| 所在文件 | 已有键 |
|---|---|
| `locales/{zh,en}/chatAndSider.ts` | `taskCenter.cancel`、`taskCenter.clearFinished`、`taskCenter.goto`、`taskCenter.status.*`（7 个）、`taskCenter.laneFallback`、`taskCenter.finishedCount`、`taskCenter.cancelFailed`、`taskCenter.shellTerminate` / `shellTerminating` / `shellClose` |
| `locales/{zh,en}/settingsAndModels.ts` | `taskCenter.chatFallback` |

> ⚠️ **新文件的键不得与上表任何键重名**。`zh.ts` / `en.ts` 用 spread 聚合，后展开的同名键会**静默覆盖**先前的（不报错、但文案丢失）。本设计新增的键全部落在 `taskCenter.section.*` / `taskCenter.source.*` / `taskCenter.group.*` / `taskCenter.action.*` / `taskCenter.filter.*` / `taskCenter.elapsed` / `tasks.page.*` 之下，与上表**无交集**。

| 键 | zh | en |
|---|---|---|
| `taskCenter.section.title` | 任务 | Tasks |
| `taskCenter.section.empty` | 暂无进行中的任务 | No active tasks |
| `taskCenter.section.viewAll` | 查看全部 | View all |
| `taskCenter.section.more` | 还有 {n} 条 → | {n} more → |
| `taskCenter.source.registry` | 长任务 | Long task |
| `taskCenter.source.chat` | 后台会话 | Background chat |
| `taskCenter.source.lane` | 编排泳道 | Lane |
| `taskCenter.source.goal` | 闲时目标 | Idle goal |
| `taskCenter.source.todo` | 待办 | Todo |
| `taskCenter.source.scheduled` | 定时任务 | Scheduled |
| `taskCenter.group.active` | 进行中 | Active |
| `taskCenter.group.failed` | 失败 | Failed |
| `taskCenter.group.finished` | 已完成 | Finished |
| `taskCenter.action.cancel` | 取消 | Cancel |
| `taskCenter.action.pause` | 暂停 | Pause |
| `taskCenter.action.resume` | 继续 | Resume |
| `taskCenter.action.runNow` | 立即运行 | Run now |
| `taskCenter.action.open` | 查看详情 | Details |
| `taskCenter.action.clearFinished` | 清除已完成 | Clear finished |
| `taskCenter.filter.all` | 全部 | All |
| `taskCenter.filter.active` | 进行中 | Active |
| `taskCenter.filter.failed` | 失败 | Failed |
| `taskCenter.filter.finished` | 已完成 | Finished |
| `taskCenter.elapsed` | 已耗时 {duration} | {duration} elapsed |
| `tasks.page.title` | 任务中心 | Task Center |
| `tasks.page.subtitle` | 闲时目标、后台任务、待办与定时任务的统一视图 | Unified view of idle goals, background tasks, todos and scheduled tasks |
| `tasks.page.empty.title` | 暂无任务 | No tasks |
| `tasks.page.empty.hint` | 从对话发起长任务，或在待办 / 定时任务页创建 | Start a long task from chat, or create one in the todo / scheduled pages |
| `tasks.page.error` | 加载失败 | Failed to load |
| `tasks.page.retry` | 重试 | Retry |

沿用既有：`taskCenter.status.*`（7 个）、`taskCenter.cancel`、`taskCenter.clearFinished`、`taskCenter.goto`、`taskCenter.chatFallback`、`taskCenter.laneFallback`、`taskCenter.cancelFailed`。

---

## 10. 测试策略

### 10.1 单元测试（vitest）

| 文件 | 覆盖点 |
|---|---|
| `src/features/task-center/__tests__/unifiedTaskModel.test.ts` | 6 个归一函数的字段映射；4 张状态映射表全枚举；`percent` clamp；ISO↔epoch 转换；未知状态兜底 |
| `src/features/task-center/__tests__/useUnifiedTasks.test.tsx` | 六源合并；chat 排除当前会话；§4.4 可见性规则逐条（pending todo 不出现、succeeded scheduled 不出现、failed goal 进失败组）；排序稳定性；计数正确 |
| `src/features/task-center/__tests__/unifiedTaskStore.test.ts` | 三源分别失败时的部分成功语义；轮询停止条件 |
| `src/features/task-center/__tests__/useTaskCenterActions.test.ts` | 按 source 分发到正确的 API / invoke；失败时 toast.error 且不乐观更新 |
| `src/widgets/task-center/__tests__/TaskCenterCard.test.tsx` | 徽章渲染；percent 有/无两条分支；cancellable 决定取消按钮；点击 → 路由 / shell 抽屉；aria-label |

### 10.2 组件测试

| 文件 | 覆盖点 |
|---|---|
| `src/widgets/sidebar/sections/__tests__/TaskCenterSection.test.tsx` | 渲染卡片；空态；compact 每组最多 3 条 + "还有 N 条"；折叠态不渲染 body |
| `src/features/task-center/__tests__/TaskCenterPanel.test.tsx` | 分组；筛选 chip；清除已完成；错误态 + 重试 |

### 10.3 迁移既有测试

`TaskCenterWidget.*.test.tsx` 五个文件按行为重写到新模型：

| 原测试 | 去向 |
|---|---|
| `TaskCenterWidget.test.tsx` | → `useUnifiedTasks.test.tsx`（四源聚合） |
| `TaskCenterWidget.dedupe.test.tsx` | → `useUnifiedTasks.test.tsx`（chat 排除当前会话 + 首见时间） |
| `TaskCenterWidget.shells.test.tsx` | → `TaskCenterRuntimeHost` 的 shell 轮询用例 |
| `TaskCenterWidget.a1/a4.test.tsx` | → `TaskCenterCard.test.tsx`（状态徽章 / 交付抽屉入口） |
| `DeliveryDrawerHost.p140.test.ts` | 保留（`DeliveryDrawerHost` 不动） |
| `ShellStreamDrawer.test.tsx` | 保留（组件不动，改由 `DeliveryDrawerHost` 挂载） |

### 10.4 后端测试

后端测试目录约定：`backend/tests/unit/`（服务/工具）、`backend/tests/api/`（路由）、`backend/tests/scheduler/`（调度器）。已有 `backend/tests/unit/test_goal_service.py`、`backend/tests/api/test_autonomous_goals_routes.py` 等先例。

| 文件 | 覆盖点 |
|---|---|
| `backend/tests/unit/test_goal_notifications.py` | 目标完成后队列里出现通知；失败后出现失败通知；`drain` 后清空；队列只出 goal 项（不混入 shell 队列） |
| `backend/tests/api/test_scheduled_router_notifications.py` | `/scheduled/notifications/pending` 返回体含 `goal_notifications` 键；既有三键不受影响 |
| `backend/tests/unit/test_goal_service_notification.py` | `COMPLETED` / `FAILED` 两条路径都推通知；`cancel` 不推 |
| `electron/__tests__/schedulerNotifications.test.ts` | `collectNotificationItems` 合并 `goal_notifications`；无 `goal_notifications` 字段时不崩溃；缺 title 的条目被丢弃（既有行为） |

### 10.5 回归与门禁

- `npm run lint`（含 FSD 分层规则）—— 新文件必须通过 zones 校验。
- `node scripts/architecture-check.mjs` —— 新增文件均 < 800 行；`Sidebar.tsx` 增长 < 70 行；`chatAndSider.ts` **不得增长**；`zh.ts` / `en.ts` 增长 2 行（未基线，安全）。
- `npx vitest run` —— 全绿（含 `src/pages/Help/__tests__/pagesIndex.p142.test.ts` 的 barrel 断言未被打破）。
- `npm run build` —— 通过 Vite chunk 预算（总 ≤ 12MB，单 chunk ≤ 1.95MB）。
- `npm run test:coverage` —— 新增文件覆盖率 ≥ 80%（全局规则）。
- Playwright 冒烟：桌面端启动 → 侧边栏出现"任务"分区 → `/tasks` 页面可打开 → 卡片可取消。
- 后端：`/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit backend/tests/api -q` 全绿。

### 10.6 双分支

- `release/win7` 的 CI 跑 Python 3.8 + pydantic 1.x。
- 后端新增代码必须 py3.8 兼容：**不使用** PEP 604（`X | Y`）、不使用 `list[str]` 内建泛型注解（用 `typing.List` / `typing.Optional`）、不使用 `match` 语句。
- 前端两个分支共用同一套 TS 代码，无差异。

---

## 11. 实施计划（M1 – M6）

> 里程碑按"可独立验证"拆分。每个里程碑结束时 `npm run lint && node scripts/architecture-check.mjs && npx vitest run` 必须绿。

### M1 —— 统一模型与归一表（纯函数，无 UI）

- 新建 `src/features/task-center/unifiedTaskModel.ts`：类型、4 张状态映射表、6 个归一函数。
- 新建 `src/features/task-center/__tests__/unifiedTaskModel.test.ts`。
- **验收**：单测覆盖全部映射分支；lint / 架构检查绿。

### M2 —— 聚合 store 与 hook

- 新建 `src/features/task-center/unifiedTaskStore.ts`（三源 + 轮询 + 部分失败语义）。
- 新建 `src/features/task-center/useUnifiedTasks.ts`（合并 + 分组 + 计数）。
- 新建 `src/features/task-center/useTaskCenterActions.ts`（动作分发）。
- 新建 `src/features/task-center/__tests__/useUnifiedTasks.test.tsx`、`unifiedTaskStore.test.ts`、`useTaskCenterActions.test.ts`。
- **验收**：六源合并正确；§4.4 可见性规则逐条有测试覆盖。

### M3 —— 卡片与分区（替换浮动胶囊）

- 新建 `src/widgets/task-center/TaskCenterCard.tsx` + 测试。
- 新建 `src/widgets/sidebar/sections/TaskCenterSection.tsx` + 测试。
- 新建 `src/features/task-center/TaskCenterRuntimeHost.tsx`（shell 轮询迁入）。
- 新建 `src/features/task-center/TaskCenterPanel.tsx`（full 模式内容）。
- 改 `Layout.tsx`：`<TaskCenterWidget />` → `<TaskCenterRuntimeHost />`。
- 改 `DeliveryDrawerHost.tsx`：接管 `ShellStreamDrawer` 挂载。
- 改 `Sidebar.tsx`：`SECTION_KEYS` + `renderSection` + nav 项 + rail 角标。
- 改 `App.tsx`：新增 `/tasks` 路由 + `src/pages/TasksPage.tsx`。
- 改 `panelRegistry.ts` + `panelRegistry.test.ts`。
- 删除 `TaskCenterWidget.tsx` 与其 5 个测试（行为迁入新测试）。
- **验收**：桌面端侧边栏出现"任务"分区；`/tasks` 页面可打开；shell 输出抽屉仍可用；交付抽屉与桌宠无回归。

### M4 —— i18n

- 新建 `src/shared/lib/i18n/locales/{zh,en}/taskCenter.ts`；聚合进 `zh.ts` / `en.ts`。
- i18n key-parity 测试绿（`src/shared/lib/i18n/__tests__/`）。
- **验收**：中英文键集完全一致；`chatAndSider.ts` 行数不变。

### M5 —— 目标完成通知（后端 + Electron）

- 新增 `backend/services/goal_notifications.py`。
- 改 `backend/services/goal_service.py`：`COMPLETED` / `FAILED` 推通知。
- 改 `backend/api/scheduled_router.py`：返回体加 `goal_notifications`。
- 改 `electron/schedulerNotifications.ts`：`PendingNotificationsPayload` 加 `goal_notifications?: PendingNotificationItem[]`，`collectNotificationItems` 合并新键。
- 后端测试 3 个文件 + `electron/__tests__/schedulerNotifications.test.ts` 补 1 例。
- **验收**：`/scheduled/notifications/pending` 返回四键；目标完成后 15s 内收到 OS 通知；`background_tasks` 语义不变。
- **py3.8 兼容**：不用 PEP 604 / 内建泛型注解。

### M6 —— 文档归档与双分支同步

- 删除 `docs/plans/2026-10-28_idle-deferred-task-execution.md`（功能已实现并归档）。
- 新增 `docs/technical/146-sidebar-task-center.md`（main）/ 对应章节（win7）。
- 新增 `docs/user-manual/46-task-center.md`（main）/ 对应章节（win7）。
- 在 `docs/superpowers/specs/README.md` 增加一行索引，状态标 `已实施`。
- 提交 main → PR → cherry-pick 到 `release/win7` → py38 验证。

---

## 12. 风险与缓解

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | `Sidebar.tsx` 当前 728 行，未列入基线，逼近 800 上限 | 架构检查红 | 新增逻辑全部下沉到 `TaskCenterSection.tsx`；`Sidebar.tsx` 改动控制在 +70 行内；M3 结束立即跑 `architecture-check.mjs` |
| R2 | `panelRegistry.test.ts` 两处硬编码断言被打破 | CI 红 | M3 内同步更新断言，并在本 spec §5.10 写明改法 |
| R3 | 删除 `TaskCenterWidget` 影响 4 处挂载点 | 桌宠 / 交付抽屉 / shell 抽屉 / 布局 | §5.8 逐项列出归属；`taskCenterStore` 数据契约保持不变，桌宠无回归；M3 用 Playwright 冒烟覆盖 |
| R4 | 轮询放进侧边栏分区，折叠即停 | 后台任务状态卡死 | 轮询统一放 `TaskCenterRuntimeHost`（常驻 Layout），§5.4 |
| R5 | `useGoalStore.load()` 的 `statusFilter` 污染 | 任务中心只看到过滤后的目标 | 任务中心使用独立的 `unifiedTaskStore`，不复用页面 store，§5.3 |
| R6 | `chatAndSider.ts` 触及架构棘轮 | 架构检查红 | 新建独立文案域文件，§9 |
| R7 | 目标通知混进 `background_tasks` | 既有 shell 通知语义被污染 | 目标通知走独立队列 + 独立返回键，§7.2 |
| R8 | `release/win7` 的 Python 3.8 不支持新语法 | win7 CI 红 | M5 明确禁用 PEP 604 / 内建泛型注解；cherry-pick 后用 `sage-backend-py38` 跑后端测试 |
| R9 | 内容列分区与会话分区争抢垂直空间 | 会话列表被压缩 | 分区 `maxHeight=320px` + 内部滚动；compact 模式每组最多 3 条；默认 `min-h-[120px]` 保护会话分区 |
| R10 | 六源状态词表继续分化 | 归一表失真 | 归一表集中在一处 + 全枚举单测；新增来源必须补映射表（测试会提醒） |
| R11 | `/tasks` 路由与既有路由冲突 | 导航异常 | 路由名与现有 `/todos` `/scheduled` `/goals` 无冲突（已核对 `App.tsx`） |
| R12 | 把 `TasksPage` 加进 `src/pages/index.ts` barrel | `pagesIndex.p142.test.ts` 的 `exportedPageCount === 5` 断言失败 | **不加进 barrel**（§5.9）；既有 `TodoPage` / `ScheduledTasks` 同样未加 |
| R13 | 三个 API 客户端返回形状不一致（两包一层、一包一层、直接数组），取错字段 | 任务列表空白 | §5.3 已逐条写明；`unifiedTaskStore` 单测覆盖三个源的解包 |
| R14 | 新 i18n 键与既有 `taskCenter.*` 键同名，spread 聚合时静默覆盖 | 文案丢失且无报错 | §9 列出既有键全表；新键全部落在 `taskCenter.section/source/group/action/filter` 子树下；中英文键集对齐测试兜底 |
| R15 | 在 `Sidebar.tsx` 里用 `attentionCount` 命名任务计数，遮蔽既有的审批+提问计数 | `/chat` 角标显示错数 | §5.9 明确变量名用 `taskCenterBadgeCount`；两处计数语义对照表已列出 |
| R16 | 任务中心的失败数未接入 `useAttentionSnapshot`，rail 底部统一总数不含它 | 用户看到两个口径不同的数字 | §5.9 已列为**已知缺口**并写明不在本期范围；两处角标的 `title` 文案需能区分 |

---

## 13. 双分支同步

| 项 | main | release/win7 |
|---|---|---|
| 前端代码 | 同一套 TS | cherry-pick 相同内容 |
| 后端 Python | 3.10 / pydantic 2.x | 3.8 / pydantic 1.x（M5 需适配） |
| 文档编号 | 技术 §146 / 用户 §46 | 技术 §150+ / 用户 §47+（按 win7 现有最大编号顺延） |
| 同步方式 | — | **cherry-pick**，禁止 merge |

cherry-pick 前先 `git diff origin/release/win7` 确认 win7 没有已存在的独立实现（避免重复 PR，见项目内「win7-sync 合并已带入待同步提交」经验）。

---

## 14. 文档归档（M6）

| 文档 | 动作 |
|---|---|
| `docs/plans/2026-10-28_idle-deferred-task-execution.md` | **删除**（功能已实现并并入技术/用户手册） |
| `docs/technical/146-sidebar-task-center.md` | 新建（main） |
| `docs/technical/<win7 编号>-sidebar-task-center.md` | 新建（win7） |
| `docs/user-manual/46-task-center.md` | 新建（main） |
| `docs/user-manual/<win7 编号>-task-center.md` | 新建（win7） |
| `docs/superpowers/specs/README.md` | 增加索引行，状态 `已实施` |
| `docs/superpowers/specs/2026-11-09-sidebar-task-center-design.md` | 保留（本文档） |

---

## 附录 A：现状核实清单

本 spec 的每一条现状断言均已逐行核对源码，核实时间 2026-11-09。

| 断言 | 核实结果 |
|---|---|
| `/goals` 路由存在但无导航入口 | ✅ `src/App.tsx:317` 有路由；`Sidebar.tsx:109-127` 三组 nav 无 `/goals` |
| `useGoalStore` 已存在 | ✅ `src/entities/autonomous-goals/goalStore.ts:37` |
| `useTodoStore` 已存在 | ✅ `src/entities/todo/todoStore.ts:33` |
| `useScheduledTaskStore` 已存在 | ✅ `src/entities/scheduled/taskStore.ts:22` |
| `taskCenterStore` 是单一 `tasks` 映射（无 4 个 slice） | ✅ `TaskCenterEntry` + `tasks: Record<string, TaskCenterEntry>` |
| 4 个来源是 4 个独立 store / API | ✅ registry=`taskCenterStore`、chat=`chatStreamStore`+`useStore`、lane=`laneBoardStore`、shell=`listShells()` 轮询 |
| shell 条目存于 `taskCenterStore.tasks` 且 `kind==='shell'` | ✅ `TaskCenterWidget.tsx:262, 305` |
| `TaskCenterWidget` 496 行 | ✅ |
| `Sidebar.tsx` 728 行，未列入架构基线 | ✅ 基线 97 个文件不含它 |
| `SECTION_KEYS = ['project','conversations','git']` | ✅ |
| 折叠状态存于 `sage:sider:sections:v1` 的 `{order, collapsed}` | ✅ `useSiderSections.ts` |
| 新 section key 会被追加到顺序末尾 | ✅ `reconcileStoredSiderOrder`（`src/shared/lib/dnd/siderOrder.ts`） |
| `SidebarNavItem` 支持 `trailing` 角标（rail + row 双形态） | ✅ `src/widgets/layout/SidebarNavItem.tsx` |
| `DeliveryDrawerHost` 独立于 `TaskCenterWidget` 挂载 | ✅ `Layout.tsx:215` |
| `TaskCenterPetBridge` 独立挂载，只读 `taskCenterStore.tasks` | ✅ `App.tsx:334` |
| `ShellStreamDrawer` 挂在 `TaskCenterWidget` 内部 | ✅ `TaskCenterWidget.tsx:493` → **必须迁移** |
| 目标路由支持 start/pause/cancel | ✅ `backend/api/autonomous_goals_router.py` |
| 目标**没有**任何 OS 通知支持 | ✅ `drain_pending_notifications` 只返回 `scheduled_tasks` / `todo_reminders` / `background_tasks` |
| `background_tasks` 键就是 `BackgroundNotificationQueue.drain()` | ✅ `scheduled_router.py` |
| `chatAndSider.ts` 在架构基线内（zh 825 / en 824） | ✅ 棘轮禁止增长 |
| `zh.ts`(58) / `en.ts`(57) 未列入基线 | ✅ |
| 目标通知需独立队列（否则污染 `background_tasks`） | ✅ 由上一条推出 |
| `Todo.priority` 是 `'high'\|'medium'\|'low'` | ✅ `templateAndTaskTypes.ts:384-407` |
| `Todo.id` 是 number；`Todo.created_at` 是 ISO 字符串 | ✅ 同上 |
| `ScheduledTask` 无 `updated_at` / `title` / `description` / `priority` | ✅ `domainEntityTypes.ts:531` |
| `ScheduledTask.created_at` 是 epoch ms 数字 | ✅ 同上 |
| `Goal` 用 `completed` 而非 `succeeded` | ✅ `entities/autonomous-goals/types.ts:9` |
| `Goal.created_at` 是 ISO 字符串 | ✅ 同上 |
| `LaneStatus` 8 个取值 | ✅ `domainEntityTypes.ts:579-631` |
| `eslint.config.js` FSD 分层全为 `error` | ✅ `:60-110` |
| `shared` 不得导入 `features` | ✅ → 状态归一表必须放 `features` 层 |
| `features → features` 允许 | ✅ 先例 `src/features/attention/useAttentionSnapshot.ts:20` → `../changes/changesListStore` |
| `useGoalStore.load(status?)` 会读取 `statusFilter` | ✅ `goalStore.ts:48` |
| Electron 轮询间隔 15s | ✅ `SCHEDULER_NOTIFICATION_POLL_MS = 15_000` |
| shell 轮询间隔 3s | ✅ `SHELL_TASK_POLL_MS = 3_000` |
| rail 有 `overflow-y-auto`，加 nav 项安全 | ✅ `Sidebar.tsx:482` |
| 内容列 nav 容器有 `overflow-y-auto` 作为兜底 | ✅ `Sidebar.tsx:649` |
| `/tasks` 与既有路由无冲突 | ✅ `App.tsx:272-320` |
| chat 流 store 是 `useChatStreamStore`，形状 `Record<sessionId, SessionStreamSlots>` | ✅ `src/features/send-message/chatStreamStore.ts:338, 493` |
| lane store 是 `useLaneBoardStore`，字段 `lanes` + `cancel` | ✅ `src/entities/orchestration/laneBoardStore.ts:24, 34` |
| `AttnBadge` 在 `src/shared/ui/AttnBadge.tsx`，`Sidebar.tsx:511` 已有 `count` 用法可照抄 | ✅ |
| `listGoals(status?, limit=50, offset=0)` 返回 `GoalListResponse{items,total,limit,offset}` | ✅ `goalApi.ts:21` / `types.ts:79-84` |
| `todoClient.list(params?)` 返回 `TodoListResponse{items,total,limit,offset}` | ✅ `todoClient.ts:29` / `templateAndTaskTypes.ts:445-450` |
| `TodoListParams` 用 `limit`/`offset`，**无** `page_size`；有 `include_completed` | ✅ `templateAndTaskTypes.ts:452-461` |
| `scheduledClient.list()` 直接返回 `ScheduledTask[]` | ✅ `scheduledClient.ts:17-19` |
| 既有 `taskCenter.*` i18n 键分布 | ✅ `chatAndSider.ts`（cancel / clearFinished / goto / status.* / laneFallback / finishedCount / cancelFailed / shell*）+ `settingsAndModels.ts:313`（chatFallback） |
| `App.tsx` 页面路由全部走 `lazy()` | ✅ `App.tsx:47, 74, 86, 89` |
| `src/pages/index.ts` 治理函数默认 `exportedPageCount = 5`，被测试硬断言 | ✅ `src/pages/index.ts` + `src/pages/Help/__tests__/pagesIndex.p142.test.ts:10` |
| 后端测试目录约定 `unit/` `api/` `scheduler/` | ✅ 已有 `backend/tests/unit/test_goal_service.py`、`backend/tests/api/test_autonomous_goals_routes.py` |
| `goal_service.py` COMPLETED / FAILED 赋值点 | ✅ `:230`（`_execute_loop`）、`:246`、`:634`（`_apply_degradation`，定义在 `:599`） |
| `scheduled_router.py` 返回体三键 | ✅ `:254-257` |
| `PendingNotificationsPayload` 三键 + `PendingNotificationItem` 形状 | ✅ `electron/schedulerNotifications.ts:12-28` |
| `collectNotificationItems` 合并三数组并丢弃无 title 项 | ✅ `electron/schedulerNotifications.ts:43-49` |
| `electron/__tests__/schedulerNotifications.test.ts` 已存在 | ✅ |
| `src/features/autonomous-goals/GoalListPage.tsx` / `GoalDetailPage.tsx` 存在 | ✅ |
| `src/pages/TodoPage.tsx` / `src/pages/ScheduledTasks.tsx` 存在且**未**进 barrel | ✅ |
| 5 个 `TaskCenterWidget.*.test.tsx` + `DeliveryDrawerHost.p140.test.ts` + `ShellStreamDrawer.test.tsx` 均存在 | ✅ `src/widgets/task-center/__tests__/` |
