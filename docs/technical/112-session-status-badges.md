# 会话状态徽章

> 实施于 2026-10-30（feat/retry-visibility-session-status）。

## 背景

侧栏会话条目（`SessionItem.tsx`）此前只有「运行中 / 运行失败 / 刚完成」等少数
可见状态，且「运行中」完全依赖前端本地流槽位。两类真实场景因此不可见：

1. **LLM 重试中**：后端有完整的 `AgentState.RETRY` → `RetryEvent` →
   聊天区 `RetryBanner` 链路，但侧栏不知道，重试期间只显示普通转圈。
   代理超时类 504 每次尝试可长达 60 秒，用户无法判断"在生成"还是"在退避重试"。
2. **后台运行中**：刷新页面、多窗口、调度器/自主任务触发时，数据库
   `sessions.run_status='running'` 但本地没有流槽位，旧实现不渲染任何标志。

## 徽章优先级

从高到低（同一会话最多命中一个运行类徽章）：

| 优先级 | 条件 | 徽章 | testid | i18n key |
| --- | --- | --- | --- | --- |
| 1 | 有待审批 / 待回答问题 | 琥珀色脉冲圆点 | `session-attention` | `session.attention` |
| 2 | 本地流槽位存在且 `retryInfo != null` | 琥珀色旋转 `RefreshCw` | `session-retrying` | `session.status_retrying` |
| 3 | 本地流槽位存在（非重试） | 主色旋转 `Loader2` | `session-running` | `session.status_running` |
| 4 | 无本地流但 DB `run_status='running'` | 灰色旋转 `Loader2` | `session-running-background` | `session.status_running_background` |
| 5 | 无本地流且 DB `run_status='failed'` | 红色 `AlertCircle`（tooltip 带 `last_error`） | `session-failed` | `session.status_failed` |
| 6 | 无本地流且 DB `run_status='suspended'` | 灰色 `PauseCircle` | `session-suspended` | `session.status_suspended` |
| 7 | 刚完成 60 秒内 | 绿色 `Check` | `session-completed` | `session.status_completed` |
| 8 | 有启用的定时任务 | 灰色 `Clock` | `session-cron` | `session.cron_badge` |

「重试中」tooltip 格式：`重试中（{attempt}/{max}）: {error_message}`。

## 数据来源

- **重试中**：`useChatStreamStore` 的按会话流槽位
  `sessions[sessionId].streaming.retryInfo`（`RetryInfo`：`attempt` /
  `max_attempts` / `error_type` / `error_message` / `delay`）。由
  `setRetryInfo()` 在 SSE `state='retry'` 事件到达时写入；非 retry 状态到达
  3 秒后清空。**纯前端信号，无后端字段**。
- **运行中 / 后台运行中**：`isLive = slots.streaming != null` 决定前者；
  `sessions.run_status`（数据库列）决定后者。

## 后端 `run_status` 写入链路

取值：`idle`（无运行）/ `running`（活跃流）/ `suspended`（等待唤醒）/
`completed`（上一轮成功）/ `failed`（上一轮失败，配 `last_error`）。

| 时机 | 写入值 | 代码位置 |
| --- | --- | --- |
| 流开始 | `running` | `backend/api/legacy_routes.py`（producer 起始处） |
| 流结束（终态） | `completed` / `failed` / `suspended` / `idle`（用户取消） | `backend/api/legacy_routes.py`（finally 收口） |
| 启动恢复 | 遗留 `running` → `failed`（"应用重启，运行中断"） | `SessionRepository.recover_stale_run_states()`，`backend/main.py` 启动时调用 |

## 已知限制

- 会话列表没有 `run_status` 轮询：DB 变更只在流结束、创建/重命名/删除、
  侧栏挂载等时机通过整表 `loadSessions()` 拉取；其他客户端/调度器改状态
  可能延迟可见（本地流槽位信号仍是实时的）。
- 「已中断」与真失败都落在 `failed`，仅 `last_error` 文案不同；如需区分
  需新增独立状态值（本次未做）。
- 「已取消」当前写回 `idle`，不显示徽章。

## 测试

`src/widgets/session/__tests__/SessionItem.status-badges.test.tsx`：

- 流槽位携带 `retryInfo` → 渲染 `session-retrying`，不渲染 `session-running`；
- 无 `retryInfo` → 渲染普通 `session-running`；
- DB `running` 且无流槽位 → 渲染 `session-running-background`。
