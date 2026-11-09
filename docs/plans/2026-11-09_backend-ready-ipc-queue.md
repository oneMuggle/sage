# 后端就绪前 IPC 请求队列化（修复启动初期会话列表为空 / 工作台报"后端服务未就绪"）

- 日期：2026-11-09
- 分支：`fix/backend-ready-ipc-queue`
- 关联：PR #2976（启动性能优化，本回归的引入方）

## 背景与目标

### 现象

PR #2976 将主窗口提前到「渲染层首帧即显示」，不再等待 Python 后端就绪
（实测窗口 21:35:55 显示，后端 21:36:07 才 ready，约 12 秒窗口期）。
窗口期内渲染层挂载即发起首屏 IPC 请求，全部被主进程的 readiness gate 以
`BackendNotReadyError` 拒绝：

- `src/shared/lib/store.ts:263` `loadSessions` — catch 后仅打日志，**侧边栏历史会话永久为空**；
- `src/app/providers/SessionWorkspaceProvider.tsx` mount 时 `bind/refresh` —
  error 写入 state 后不再重置，**文档工作台顶部常驻红色"后端服务尚未就绪"横幅**
  （`src/pages/Office.tsx:596-603` 原样渲染 `workspaceError`）；
- `src/widgets/chat/...` `loadMessages` 等其他首屏请求同样丢失。

这些组件都是一次性请求、无重试路径，窗口期内失败的调用不会在后端就绪后补齐。

### 目标

采用**更治本**的主进程方案：后端处于 `idle`/`starting` 生命周期时，
IPC 请求（`sage:invoke` / `sage:backend-request`）不再立即抛错，而是
**入队等待**；后端 `ready` 后按 FIFO 顺序自动下发；仅在
不可恢复的终止状态下才拒绝（应用退出、自动重启次数耗尽）。

渲染层组件无需改动：首屏请求会一直 pending 到后端就绪后正常返回，
UI 保持 loading 态而非错误态。

## 涉及的文件与模块

| 文件 | 改动 |
|------|------|
| `electron/backendReadyQueue.ts`（新增） | 队列核心逻辑（纯函数/可单测，不依赖 Electron 运行时） |
| `electron/__tests__/backendReadyQueue.test.ts`（新增） | 队列单测：FIFO、flush、rejectAll、上限、单次 flush |
| `electron/main.ts` | ① 两个 IPC handler 的 gate 处改为入队；② `waitForBackend` 成功处 flush；③ 应用退出 / 重启耗尽时 rejectAll；④ SAGE_SKIP_BACKEND / demo 模式 ready 处 flush（空队列，占位保持一致性） |
| `docs/plans/2026-11-09_backend-ready-ipc-queue.md`（本文件） | 方案与实施记录 |

不改动的部分：`electron/invoke.ts` 的 `BackendNotReadyError` 保留（终止状态下仍使用）；

- `src/shared/api/desktopInvoke.ts` 保持原样（错误透传契约不变）；
- 渲染层所有组件不改 —— 这是本方案"治本"的核心收益。

## 技术方案

### 队列模块 API（electron/backendReadyQueue.ts）

```ts
export interface BackendReadyQueue {
  enqueue<T>(task: () => Promise<T>, label: string): Promise<T>;
  flush(): void;          // 后端 ready：按 FIFO 依次执行全部任务
  rejectAll(reason: Error): void;  // 终止状态：全部拒绝
  size(): number;         // 观测/测试
}

export function createBackendReadyQueue(options?: {
  maxSize?: number;            // 默认 200，防止渲染层轮询导致无界增长
  onOverflow?: (label: string) => void;
  logger?: { warn: (msg: string, meta?: unknown) => void };
}): BackendReadyQueue;
```

语义：

- `enqueue` 返回的 promise 在任务执行完成/失败时 resolve/reject；
- 队列超过 `maxSize` 时，新请求立即以 `BackendNotReadyError` 拒绝（视为过载，
  保持与旧行为兼容，且防止内存无界增长）；
- `flush` 之后到达的新请求由 main.ts 按 lifecycle 判断直接执行，不再入队；
- `flush` 与 `rejectAll` 均只生效一次（幂等，防重入）。

### main.ts 接线

`sage:invoke` 与 `sage:backend-request` 的结构改为：

```ts
const run = async () => { /* 原有 post-gate 逻辑整体搬入 */ };

if (backendLifecycle !== 'ready') {
  if (appIsQuitting || isBackendTerminallyFailed()) {
    throw new BackendNotReadyError();
  }
  logger.info('ipc: request queued until backend ready', { cmd, lifecycle });
  return enqueueBackendReady(run, `invoke:${cmd}`);
}
return run();
```

注意：`sage:backend-request` 的入参形状校验 / 路径白名单校验保持在入队**之前**
（非法请求立即失败，不占用队列）。

flush 时机：

| 位置 | 事件 |
|------|------|
| `waitForBackend()` 中 `backendLifecycle = 'ready'` 之后 | 冷启动 / 自动重启成功 |
| `SAGE_SKIP_BACKEND` 模式 `backendLifecycle = 'ready'` | 外部后端模式 |
| demo 模式 `backendLifecycle = 'ready'` | 空队列占位 |
| `scheduleBackendRestart()` 重启耗尽（`attempt === -1`） | **rejectAll** |
| app `before-quit` / `window-all-closed` 清理路径 | **rejectAll** |

不设单请求超时：等待时长与后端启动时长一致（慢机器 90s+ 也不会误杀）。
渲染层若在等待期间卸载，promise 的 resolve 落在已销毁的 frame 上，是 IPC 的无害 no-op。

### 生命周期判定

- `idle`：可能是"尚未 spawn"（冷启动窗口）或"进程退出待重启"（自动重连窗口）→ **入队**；
  唯一例外是重启已耗尽（`restartCount >= MAX_RESTART_ATTEMPTS` 且无 restartTimer）→ 拒绝。
- `starting`：→ **入队**。
- `stopping`：→ 立即拒绝。
- `ready`：→ 直接执行。

## 实施步骤

- [x] 步骤 1：新建 `electron/backendReadyQueue.ts`（纯队列实现）
- [x] 步骤 2：先写单测 `electron/__tests__/backendReadyQueue.test.ts`（RED→GREEN）
- [x] 步骤 3：`electron/main.ts` 接入：两个 handler 的 gate 改为入队
- [x] 步骤 4：flush / rejectAll 时机接入（waitForBackend / skip-backend / demo / 退出 / 重启耗尽）
- [x] 步骤 5：`npx vitest run electron/__tests__/` 全量（76 文件 699 用例全绿）+ `npm run build:electron` 通过
- [x] 步骤 6：worktree 内起 Vite（:1551）+ Electron（:8896，独立 profile + DB 快照）实机验证：
      22:37:33 起 20+ 条 `ipc: invoke queued until backend ready`；
      22:37:49 `main: flushing queued ipc requests` → `main: backend ready`；
      全日志 0 次 `BackendNotReadyError` / 0 次 `store.loadSessions failed` /
      0 次 `store.loadMessages failed` / 0 次「后端服务尚未就绪」；
      `/api/v1/sessions` 返回历史会话（"Sage三步上手"）；
      唯一失败是既有 idle/activity 422（与本修复无关）
- [ ] 步骤 7：lint / typecheck / 提交 PR（eslint 与两套 tsc 已过，待提交）

## 风险评估与依赖

| 风险 | 评估 |
|------|------|
| 请求长时间 pending（后端彻底起不来） | 健康超时后有对话框引导用户重试/退出；退出路径 rejectAll 兜底，不会悬挂到进程结束 |
| 队列积压 | 上限 200 + 溢出即拒绝；首屏请求量约十余个，远低于上限 |
| 流式命令入队 | `agent_chat_stream` 等在启动窗口内几乎不可能被用户触发；入队语义仍是"就绪后执行"，无副作用风险 |
| 后端崩溃-重启窗口 | 该窗口内新请求入队，重连成功后自动服务，用户体验优于报错 |
| 既有测试 | `backendNotReadyError.test.ts` 只测错误类型，不受影响；`ipc-contract.test.ts` 等待就绪后调用，不受影响 |
| 无渲染层改动 | 回归面小；Sidebar / WorkspaceProvider 等组件行为保持原契约（请求只是晚一点返回） |
