# 渲染层 BackendNotReadyError 自愈 + 错误呈现去噪

> 日期：2026-11-10 起草 / 2026-11-10 归档  
> 分支：`fix/backend-ready-renderer-recovery`（main）/ `fix/win7-sync-renderer-recovery`（win7）  
> 状态：**已完成（双分支已合并）**  
> PR：
> - main [#2984](https://github.com/oneMuggle/sage/pull/2984)（`d7b4be854`）
> - win7 [#2987](https://github.com/oneMuggle/sage/pull/2987)（`1f003dadc6`，cherry-pick `3b083184b`；冲突：`backend/data/database.py` `_migrate_memory_traceability` 保留 win7 侧）

## 一、背景

启动期间后端冷启动窗口里，渲染层发出的首次拉取（侧边栏会话、聊天消息、文档工作台状态）可能撞上 `BackendNotReadyError`。方案 A（PR #2980/#2983 已合并：`935b9344a` main / `bcc35043f` win7）在主进程把这类请求**入队等待**，覆盖常规路径。但仍有三类尾巴：

1. **渲染层无自愈**：方案 A 队列有上限（200），极端场景（启动期瞬间批量重渲染、队列退出期 rejectAll、demo 模式、未来生命周期竞争窗口）会让失败请求永远挂住——侧边栏空、聊天页空白、文档工作台红条。
2. **错误文案直出**：Electron 把 `BackendNotReadyError` 包成 `Error invoking remote method 'sage:invoke': BackendNotReadyError: 后端服务尚未就绪...`，`desktopInvoke.ts` 原样透传到 UI，文档工作台顶层红条直出原始 IPC 字符串。
3. **项目总览无错态**：`ProjectsOverview.tsx` 没有错误态展示，失败时静默空白。

## 二、方案

### 2.1 方案 B：渲染层自愈

新增 `src/shared/lib/backendReadySignal.ts` —— 单例订阅 `backend:ready` / `backend:reconnected` IPC 事件。

```ts
export function onBackendReady(handler: () => void): () => void;
export function useBackendReadyTick(): number;
```

设计要点：
- **懒安装**：首次调用时才 `api.listen`，未使用模块零开销。
- **web/test 降级**：`window.electronAPI` 缺失时静默降级（测试、SSR、未来 web 构建不抛错）。
- **共享单份 listener**：所有订阅者共享 IPC 订阅，避免多份 `listen`。
- **错误隔离**：一个订阅者抛错不影响其他订阅者（try/catch 内层）。

React hook `useBackendReadyTick()` 暴露「就绪事件计数」，组件把它加入 effect deps 即可自动重放；计数从订阅后开始，首次订阅时若当前已 ready 不触发（避免重复拉取已成功的数据）。

**三处订阅**：

| 订阅方 | 文件 | 触发条件 | 重放动作 |
|---|---|---|---|
| 文档工作台 | `src/app/providers/SessionWorkspaceProvider.tsx` | `status === 'error' && backendReadyTick > 0` | `refresh()` |
| 侧边栏会话列表 | `src/widgets/layout/Sidebar.tsx` | `sessions.length === 0` | `loadSessions()` |
| 聊天消息 | `src/pages/Chat.tsx` | `messages.length === 0 && currentSessionId` | `loadMessages()` |

`Chat.tsx` 行数 876 → 879（+3 行，架构棘轮）。

### 2.2 方案 C：错误呈现去噪

**C1. `desktopInvoke.ts` 剥离 IPC 包装**：

```ts
if (raw.includes(BACKEND_NOT_READY_MARKER)) {
  const cleaned = raw.replace(/^Error invoking remote method '[^']+':\s*/, '')
                     .replace(/^BackendNotReadyError:\s*/, '');
  throw new Error(cleaned);
}
```

业务侧收到的 error message 只剩「后端服务尚未就绪，请稍候或重启 Sage」，不再有 IPC 包装前缀。

**C2. `ProjectsOverview.tsx` 加错态**：
- `load` 包 try/catch，失败 `setError(errorMessage(err))`。
- 顶部显示友好 banner（与文档工作台红条风格一致）+ 重试按钮。
- 由静默空白态变为可恢复错误态。

## 三、不做什么

- 不删除主进程就绪门禁（防止对旧端口/stale 进程发请求；方案 A 仍有效）。
- 不引入固定定时重试（依赖事件驱动，避免无效轮询）。
- 不动 `BackendStatusBanner.tsx`（用户可见 banner 已存在，作为参考实现）。

## 四、风险评估

| 风险 | 缓解 |
|---|---|
| 队列溢出（>200） | 方案 B 的 on-ready 重放作为兜底 |
| 事件丢失（订阅晚于 ready 事件） | 三处订阅都在组件顶层 useEffect 早期安装；`useBackendReadyTick` 计数从订阅后开始，首次已 ready 不触发重复拉取 |
| 过期覆盖竞态 | `SessionWorkspaceProvider` 已有 `requestIdRef`，本次沿用 |
| win7 py38 风险 | 本改动全部在 renderer，无 py38 影响；cherry-pick 仅冲突 `database.py`（保留 win7 侧的 `_migrate_memory_traceability` SQLite 列补建迁移） |

## 五、验收标准（已达成）

- 实机冷启动（含队列禁用模拟：改 queue 容量=0 强制 fallthrough），文档工作台红条在 ready 后 <1s 自动消失；侧边栏非空；聊天页消息恢复。
- `tsc` 通过；`vitest` 通过（新增 `backendReadySignal.test.tsx` 8 用例 + `desktopInvoke.test.ts` +2 + `ProjectsOverview.test.tsx` +2）。
- 双分支 CI 全绿：main Frontend (TypeScript) / Backend / Electron builds / smoke / arch ratchet / count-lines；win7 同 + Backend (Python 3.8 LTS)。

## 六、上游依赖

- 方案 A（主进程 IPC 就绪队列）：plan `2026-11-09_backend-ready-ipc-queue.md` 已合并（main `#2980 @ 935b9344a` / win7 `#2983 @ bcc35043f`）。
- 本方案是方案 A 之上的渲染层兜底，覆盖队列溢出、rejectAll、demo 模式等边界场景。

## 七、扩展指南

后续若新增渲染层一次性 bootstrap（首屏只跑一次的拉取），可统一订阅 `useBackendReadyTick()` 加入 effect deps，实现「失败后等后端就绪自动重试」，无需各自手写重试逻辑。
