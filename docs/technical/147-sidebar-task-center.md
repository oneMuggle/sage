# 侧边栏任务中心（Sidebar Task Center）

> 把闲时目标、后台任务、待办、定时任务、Lane 编排、会话内运行等六类来源统一收口到侧边栏一处可见 + `/tasks` 页面管理。删除原右下角浮动胶囊，入口改走侧边栏 rail。闲时目标终态（完成/失败）走独立通知队列，不污染 `background_tasks`。

---

## 章节目录

| # | 主题 | 一句话简介 |
|---|---|---|
| 1 | [架构概览](#1-架构概览) | 六源归一 + 三面（rail / 分区 / 页面） |
| 2 | [六源归一表](#2-六源归一表) | 每个来源的 store/API 与关键字段差异 |
| 3 | [轮询与可见性](#3-轮询与可见性) | 折叠即停、`visibilitychange` 挂起、`TaskCenterRuntimeHost` |
| 4 | [通知链路](#4-通知链路) | 独立 `GoalNotificationQueue` + Electron `collectNotificationItems` |
| 5 | [panelRegistry 槽位迁移](#5-panelregistry-槽位迁移) | `floating` → `left-list`，交付/Shell 抽屉归属 |
| 6 | [双分支差异](#6-双分支差异) | main vs release/win7 的 Python/依赖差异 |
| 7 | [排障](#7-排障) | 常见问题与诊断路径 |

---

## 1. 架构概览

```
┌──────────────────────────────────────────────────────────┐
│ TaskCenterRuntimeHost（Layout 挂载，跨路由常驻）         │
│  ├─ unifiedTaskStore（状态归一）                         │
│  ├─ 6 个 poller（registry/chat/lane/goal/todo/scheduled）│
│  └─ collapsedSections（折叠即停轮询）                    │
└──────────────────────────────────────────────────────────┘
        │
        ├─► Sidebar 分区（rail 入口 + 内容列 max-h 320）
        │
        ├─► /tasks 页面（TaskCenterPanel variant="full"）
        │
        └─► OS 通知（Electron consume + Notification API）
```

**三个可见面**：

| 面 | 入口 | 用途 |
|---|---|---|
| rail 徽章 | Sidebar 左侧图标 | `attentionCount`（可取消/失败）红点 |
| 侧边栏分区 | Sidebar 折叠卡 | 每组 3 条，展开看更多 |
| 完整页面 | `/tasks` 路由 | 六源全量、筛选、详情深链 |

**设计动机**：闲时目标在 v0.4.9-alpha.78 已实现但无侧栏入口（用户须手敲 `#/goals`），本特性补上可发现性。详见 spec `docs/superpowers/specs/2026-11-09-sidebar-task-center-design.md` §1。

---

## 2. 六源归一表

| 来源 | store / API | 关键字段差异 |
|---|---|---|
| registry | `useTaskCenterStore.tasks` | `startedAt` epoch ms；`kind==='shell'` 走 shell 分支 |
| chat | `useChatStreamStore.sessions` | 排除当前会话；首见时间由 ref 记录 |
| lane | `useLaneBoardStore.lanes` | `succeeded` 且未决议 → awaiting_approval |
| goal | `listGoals(undefined, 200, 0)` | 返回 `{items}`；时间戳是 ISO 字符串 |
| todo | `todoClient.list({limit, offset, include_completed})` | 返回 `{items}`；`id` 是 number |
| scheduled | `scheduledClient.list()` | 裸数组；`last_status` 决定是否展示 |

**归一形状**：`UnifiedTaskEntry`（定义 `src/features/task-center/unifiedTaskModel.ts`）：

```ts
{
  id: string;              // 全局唯一 `${source}:${rawId}`
  source: 'registry' | 'chat' | 'lane' | 'goal' | 'todo' | 'scheduled';
  title: string;
  status: 'running' | 'awaiting_approval' | 'succeeded' | 'failed' | 'cancelled' | 'pending';
  progress?: number;       // 0-100，来源不给则 undefined（不伪造）
  startedAt: string;       // 一律 ISO
  cancelRef?: { source, rawId };  // 取消时回传源端
  openTarget?: 'shell' | 'delivery' | { path: string };  // A4 深链
}
```

**状态映射**：四个状态表统一在 `unifiedTaskModel.ts` 的 `mapRegistryStatus` / `mapLaneStatus` / `mapGoalStatus` / `mapScheduledStatus`，禁止散落。`todo` 与 `chat` 无自有状态机，直接推断。

---

## 3. 轮询与可见性

- **轮询宿主**：`TaskCenterRuntimeHost`（`src/features/task-center/TaskCenterRuntimeHost.tsx`）挂在 `Layout`，跨路由存活。
- **折叠即停**：`collapsedSections.has(sectionId)` 为 true 时该 section 的 poller 不调度（节省请求）。
- **visibilitychange**：`document.hidden === true` 时所有 poller 挂起，回到前台时立刻补一次。
- **首屏**：`TaskCenterRuntimeHost` 在 mount 时立即触发一次 fetch，不等 interval。
- **卸载**：`before-quit` 时 `unifiedTaskStore.dispose()` 清所有 poller，防泄漏。

---

## 4. 通知链路

**独立队列**：`GoalNotificationQueue`（`backend/services/goal_notification_queue.py`），与 `background_tasks` 的 `TaskQueue` 完全隔离（risk R7 缓解）。

**写入时机**：`goal_service` 在 goal 状态变为 `succeeded` / `failed` 时调用 `GoalNotificationQueue.push(goal)`。

**返回端点**：`GET /api/v1/goals/notifications/pending` 返回并清空队列，四键：

```ts
{
  goal_id: str;
  title: str;
  status: 'succeeded' | 'failed';
  completed_at: str;  // ISO
}
```

**前端消费**：Electron 的 `collectNotificationItems`（`electron/main.ts`）合并 `goal_notifications` 到系统通知队列。前端内提示走 `useTaskCenterActions().toast`（仅 error 行）。

---

## 5. panelRegistry 槽位迁移

| 旧槽位 | 新槽位 | 原因 |
|---|---|---|
| `floating`（右下角胶囊） | `left-list`（侧边栏分区） | rail 入口可见性 > 浮动 |

**交付抽屉归属**：`DeliveryDrawerHost` 与 `ShellStreamDrawer` 保留在 `Layout`，通过 `deliveryBlock` 局部变量并列渲染（不再多处早退，避免吞掉 shell 抽屉）。

**能力迁移**：原 `TaskCenterWidget` 的 4 类任务来源（registry / chat / lane / shell）、交付抽屉、桌宠桥接、shell 输出抽屉全部保留，仅挂载位置变化。

---

## 6. 双分支差异

| 项 | main | release/win7 |
|---|---|---|
| Python | 3.10 | 3.8（类型注解禁 `dict[str,str]`，用 `Dict[str,str]` + `from __future__ import annotations`） |
| pydantic | 2.x | 1.x（`model_config` + `class Config` 共存会 UserError；shim `conlist min_items`） |
| 依赖文件 | `backend/requirements.txt` | `backend/requirements-py38.txt` |
| CI | `ci.yml` + `release.yml` | `ci.yml`(py38) + `release-win7.yml` |
| 同步方式 | — | cherry-pick，非 merge |

**py3.8 适配要点**（已在 T13 + Step 10 验证）：

- `Optional[X]` 显式签名（不用 `X | None`）
- `zip(...)` 不带 `strict=`（用 `# noqa: B905` 注释）
- `datetime.utcnow()` 替换为带时区版本（py3.8 无 `datetime.UTC`）

---

## 7. 排障

| 症状 | 诊断 |
|---|---|
| 侧边栏没看到任务分区 | 检查 `Sidebar.tsx` 是否导入 `TaskCenterSection`；rail 入口需要 `attentionCount > 0` |
| `/tasks` 页面空白 | 浏览器控制台看 `useUnifiedTasks()` 是否报错；确认 `TaskCenterRuntimeHost` 挂在 `Layout` |
| 闲时目标完成但没收到系统通知 | `GET /api/v1/goals/notifications/pending` 手动打；Electron 看 `collectNotificationItems` 日志 |
| 任务卡片点不开详情 | `UnifiedTaskEntry.openTarget` 缺失；`useTaskCenterActions().open()` 回落 `detailPath` |
| 折叠后再展开，任务卡住 | `collapsedSections.delete(sectionId)` 没触发；查 `toggleCollapsed` |
| Shell 抽屉不显示 | `DeliveryDrawerHost` 的 `deliveryBlock` 渲染顺序；确认 fragment 并列而非多处早退 |

**相关文档**：

- spec：`docs/superpowers/specs/2026-11-09-sidebar-task-center-design.md`
- 闲时目标调度：`docs/technical/137-scheduled-task-auto-execute.md`
- 编排泳道：`docs/technical/42-chat-multi-agent-orchestration.md`
- 通知系统：`docs/technical/16-observability.md`
