# 后台任务与定时轮询能力优化 · Phase 0

> 日期：2026-11-05
> 分支：`feat/background-task-phase0`
> 状态：实施中

## 背景与目标

Sage 在后台任务 / 定时调度 / 完成通知 / 避免无效刷新四个维度的现状评分约 6/10。
基础设施（APScheduler、NDJSON 事件、EventHub 断点续传、ChatDispatcher 后台派发、
BashSessionRegistry、WakeScheduler、OS 通知 + 托盘 + 桌宠）齐备，但有 5 处明确缺口
导致"主会话持续刷新无效信息" + "后台完成无感知" + "LLM 无法挂后台/定时唤醒"：

1. 主窗口未设 `backgroundThrottling: false`，最小化/隐藏后 SSE/tick 被 Chromium 节流
2. 定时任务触发时仅插 messages 表，renderer 收不到事件，无 OS 通知
3. `TodoReminderScheduler._pending_notifications` 后端累积无消费端（Task 12 遗留）
4. 仓库未使用 `setOverlayIcon / setBadgeCount / flashFrame`，任务栏无完成/失败信号
5. 多处前端"无效刷新"（60s 无条件轮询 / `loadSessions` 全量 / 流结束后 3 次补刷）
6. 通知无总开关、无后台任务通知开关
7. `ChatService.sleep_for/sleep_until/wake_on` 已有代码但只被单元测试调用，未暴露 LLM 工具

**Phase 0 目标**（1–2 周，低成本高收益）：修复痛点 + 接线既有能力，让
"后台任务完成 / 定时任务触发 / todo 到期"能被用户感知到，同时消除主会话
无效刷新。Phase 1（后台任务一等公民 LLM 工具：background_task / wait_for /
schedule_wakeup）另起 plan，本 plan 不涵盖。

## 涉及的文件与模块

### Electron 主进程
- `electron/main.ts`：主窗口 `webPreferences` 加 `backgroundThrottling: false`；
  新增 `flashFrame()`/`setOverlayIcon()` IPC；`new Notification` 三处读配置
- `electron/ipc-manifest.json`：新增 `notify:task-completed` / `notify:set-overlay` 等 channel
- 新增 `electron/notifyOverlay.ts`：封装任务栏角标（Windows overlay / macOS dock badge）

### 后端
- `backend/services/scheduler.py`：`_fire` 增加 emit `session_notify` 事件
- `backend/api/v1/chat_stream_support.py` 或 `legacy_chat_routes.py`：暴露
  `POST /chat/stream/{id}/suspend|resume`
- `backend/core/legacy/tools/`：新增 `wake_session_at` LLM 工具
- `backend/scheduler/todo_reminder.py`：暴露 `GET /scheduler/todo-reminders/pending`
  端点（只返回 + 排空）
- `backend/main.py`：注册新路由
- `backend/entities/settings.py` / `settingsRegistry` 等价物：新增 `notifications.*` 配置

### 前端
- `src/entities/setting/settingsRegistry.ts`：注册 `notifications.enabled` /
  `notifications.backgroundTasks`
- `src/pages/settings/BasicTab.tsx` 或新建 `NotificationsTab.tsx`：通知开关 UI
- `src/widgets/chat/SessionUsageBadge.tsx`：加 `active` 条件
- `src/widgets/chat/ContextMeter.tsx`：加 `active` 条件
- `src/features/send-message/useChat.ts`：`session_updated` 改增量；
  流结束后取消补刷（若标题已生成）
- `src/features/send-message/chatStreamRuntime.ts`：同上

### 测试
- `electron/__tests__/notifyOverlay.test.ts`
- `electron/__tests__/schedulerNotify.test.ts`
- `backend/tests/unit/test_todo_reminder_pending_endpoint.py`
- `backend/tests/unit/test_wake_session_tool.py`
- `src/widgets/chat/__tests__/SessionUsageBadge.active.test.tsx`
- `src/widgets/chat/__tests__/ContextMeter.active.test.tsx`
- `src/features/send-message/__tests__/useChat.sessionUpdatedIncremental.test.ts`

## 技术方案

### P0.1 主窗口 backgroundThrottling

```ts
// electron/main.ts createMainWindow
new BrowserWindow({
  webPreferences: {
    ...
    backgroundThrottling: false, // 新增：隐藏/最小化后不再节流
  }
})
```
影响：SSE 事件流 / 1s tick / retry 倒计时在最小化期间不再被 Chromium 拖慢。
已知副作用：CPU 占用略升，仅主窗口隐藏期间。`will-change` 无。

### P0.2 任务栏角标 / 闪烁

- Windows：`win.setOverlayIcon(iconPath, 'N tasks failed')` — 失败/等待审批
- macOS：`app.dock.setBadge('3')` — 未读通知数
- 跨平台 fallback：`win.flashFrame(true)` 直到窗口被 focus
- 新增 IPC `sage:notify:set-attention(count, kind)`，renderer 通过 `useAttentionSnapshot`
  聚合结果推送

### P0.3 定时任务触发推 OS 通知

`backend/services/scheduler.py:_fire` 末尾追加：
```python
# 触发 OS 通知（复用现有 sage:session:notify 通道）
yield_chat_stream_event(session_id, {
    "type": "session_notify",
    "body": f"定时任务已触发：{task.name}",
    "sessionId": session_id,
})
```
renderer 已有 `sage:session:notify` 路径，无需新增通知代码。

### P0.4 TodoReminder 接线

后端新增端点：
```python
@router.get("/scheduler/todo-reminders/pending")
async def pop_pending_todo_reminders() -> list[TodoReminder]:
    return get_todo_reminder_scheduler().drain_pending()
```
Electron 主进程新增 15s 轮询（独立于 renderer）：
```ts
setInterval(async () => {
  const pending = await invoke('scheduler_todo_reminders_pop')
  for (const r of pending) new Notification({...})
}, 15_000)
```
注意：`drain_pending` 必须**原子**排空，避免主进程多次拉取到同一条。

### P0.5 暴露 Wake/Suspend

REST：
- `POST /chat/stream/{id}/suspend` → `ChatService.sleep_for(id, seconds)`
- `POST /chat/stream/{id}/resume` → `ChatService.wake_now(id)`
- `POST /chat/stream/{id}/wake-at` body `{at: ISO8601}` → `ChatService.sleep_until(id, at)`

LLM 工具 `wake_session_at`：
```python
class WakeSessionAtTool(BaseTool):
    name = "wake_session_at"
    description = "让当前会话在指定时刻（ISO-8601 或 N 秒后）自动唤醒，并注入唤醒原因"
    parameters = {
        "at": str,  # ISO-8601 或 "in:30s" 格式
        "reason": str,  # 唤醒后注入的上下文
    }
```
工具内部调 `ChatService.sleep_until(session_id, parsed_at)` 并 `ChatService.append_wake_context(session_id, reason)`。

### P0.6 通知设置项

```ts
// settingsRegistry.ts
register({
  key: 'notifications.enabled',
  type: 'boolean',
  default: true,
  scope: 'user',
})
register({
  key: 'notifications.backgroundTasks',
  type: 'boolean',
  default: true,
  scope: 'user',
})
```
Electron 三处 `new Notification` 前先读 `notifications.enabled`；后台任务相关
（定时任务触发 / TodoReminder / 子代理完成）额外受 `notifications.backgroundTasks` 控制。

### P0.7 修复无效刷新

| 位置 | 修复 |
|---|---|
| `SessionUsageBadge.tsx:72` | 加 `active` 条件（仅当 run 活跃或有最近 5 分钟变更时轮询） |
| `ContextMeter.tsx:78` | 同上 |
| `useChat.ts:674` `session_updated` | 按 subtype 增量：`title_updated` → `updateSession`；`binding_changed` → `updateSession`；其它 → 仍全量（保险） |
| `useChat.ts:633/637/638` 三次补刷 | 第二次/第三次补刷前检查 `session.title` 是否已生成，是则跳过 |
| `chatStreamRuntime.ts:378/409` | 重接路径同 useChat 改增量 |

## 实施步骤

- [x] M1：写 plan 文档（本文件）
- [x] M2：P0.1 主窗口 backgroundThrottling
  - 改 `electron/main.ts`（1037-1049 webPreferences 块）
  - 注：Chromium 运行时选项，需真窗口验证，无直接单测
- [x] M3：P0.7 修复 5 处无效刷新
  - `SessionUsageBadge` / `ContextMeter` 60s 轮询改为仅流式活跃时启用
  - `useChat` `session_updated` 标题事件改增量 `updateSession`；流结束后补刷仅标题缺失时执行
  - `chatStreamRuntime` 重接路径的 `loadSessions` 保留（一次性、且是 run_status 徽章权威来源，非轮询）
  - 新增 3 个测试文件（6 例），相关既有 27 例全绿
- [x] M4：P0.6 通知设置项
  - `src/entities/setting/settingsRegistry.ts` 未改（偏好主进程持有，与 closeToTray 同模式）
  - `electron/notificationPrefs.ts` 新模块：JSON 读写 + 路径解析
  - `electron/main.ts` 新增 `sage:notification-prefs:get/set` IPC + 三处 `new Notification` 门控
  - `electron/preload.ts` + `src/shared/types/electron-api.d.ts` 暴露 `getNotificationPrefs/setNotificationPrefs`
  - `src/pages/settings/BasicTab.tsx` 新增 `NotificationPrefsCard`（两开关：总开关 + 后台任务）
  - i18n `zh`/`en` 各加 5 个键
  - 新增 `electron/__tests__/notificationPrefs.test.ts`（5 例）
- [x] M5：P0.2 任务栏角标 / 闪烁
  - `electron/notifyOverlay.ts` 新模块：纯决策函数 + 副作用应用（flashFrame + macOS dock badge）
  - `electron/main.ts` 新增 `sage:notify:set-attention` IPC + 主窗口 `focus` 事件清除
  - `src/widgets/system/TaskbarAttentionBridge.tsx` 桥接组件（读 `useAttentionSnapshot` → IPC）
  - `src/widgets/layout/Layout.tsx` 挂载桥接
  - `electron/preload.ts` + `electron-api.d.ts` 暴露 `setTaskbarAttention`
  - 新增 `electron/__tests__/notifyOverlay.test.ts`（7 例）
- [x] M6：P0.3 定时任务触发推 OS 通知
  - `backend/services/scheduler.py` 新增内存通知队列 + `_push_notification` / `drain_pending_notifications`；`_fire` finally 链投递
  - `backend/api/scheduled_router.py` 新增 `GET /scheduled/notifications/pending` 端点（原子排空双队列）
  - `electron/schedulerNotifications.ts` 新模块：15s 轮询 + 转 OS 通知
  - `electron/main.ts` 启动轮询器（演示模式跳过）
  - 命令路由 `electron/commandRoutes/settings.ts` + manifest 重生成（+1 条）
  - `electron/__tests__/schedulerNotifications.test.ts`（6 例）
  - `backend/services/__tests__/test_scheduler.py::TestDesktopNotifications`（4 例）
- [x] M7：P0.4 TodoReminder 通知接线
  - 与 M6 共享 `GET /scheduled/notifications/pending` 端点：排空 scheduler + todo 两路队列
  - 主进程轮询器同时消费
- [x] M8：P0.5 暴露 Wake/Suspend REST + LLM 工具
  - `backend/api/wake_router.py`：`POST /sessions/{id}/wake` REST
  - `backend/tools/wake_tool.py`：LLM 工具 `wake_session_at`（相对/绝对/epoch 时间解析）
  - `backend/domain/tool_names.py`：`SCHEDULE_TOOLS` 加 `wake_session_at`
  - `backend/tools/permissions.py`：`TOOL_CAPABILITIES` + `SELF_MODIFY_TOOLS` 加
  - `backend/tools/tool_bundles.py::_install_schedule` 注册
  - `backend/main.py` 挂载路由
  - `backend/tests/unit/test_wake_tool.py`（10 例）+ `backend/tests/integration/test_wake_api.py`（5 例）
  - `backend/tests/unit/test_tool_bundles_parity.py` 同步：快照 111→112、getter 转发过滤、schedule 期望 3→4
- [ ] M9：集成测试 + 文档归档
  - E2E：最小化窗口 → 触发定时任务 → 验证 OS 通知
  - E2E：后台 bash → 完成 → 验证任务栏角标
  - 归档至 `docs/technical/`（新章节或并入 §117）+ `docs/user-manual/`

## 风险评估与依赖

| 风险 | 缓解 |
|---|---|
| P0.1 `backgroundThrottling: false` 可能增加 CPU 占用 | 仅隐藏/最小化期间；设实验观察 1 周，必要时加开关 |
| P0.3 通知风暴：高频定时任务触发时 | 复用 `SESSION_NOTIFY_THROTTLE_MS=3000` 节流 |
| P0.4 `drain_pending` 并发安全 | SQLite 事务 + SELECT FOR UPDATE；或 Python threading.Lock |
| P0.5 `wake_session_at` 与现有迭代预算冲突 | 工具仅负责挂起/唤醒；唤醒后由 iteration_budget 重新审计 |
| P0.7 `session_updated` 增量改造可能漏事件 | 灰度：先保留全量 fallback，仅白名单 subtype 走增量 |

### 依赖
- 无跨团队依赖
- 不依赖 release/win7 分支同步（后续 cherry-pick 即可）
- 不涉及新依赖包

## 不在范围内

- Phase 1 的 LLM 工具 `background_task / wait_for / schedule_wakeup`（独立 plan）
- 后台 Bash 持久化（Phase 1）
- Webhook / Slack 外发（Phase 3）
- 云端后台代理（Phase 3 可选）
