# 渲染层 BackendNotReadyError 自愈 + 错误呈现去噪

> 接续 PR #2980（方案 A，主进程 IPC 就绪队列，已合并 main `935b9344a` / 已推 win7 PR #2983）。

## 背景与目标

方案 A 把冷启动期间 `backendLifecycle !== 'ready'` 的请求改为**入队等待**，消除"后端还没起 → 所有 invoke 立刻被拒"的根因。但还有三类尾巴：

1. **B 渲染层无自愈**：一次性 `useEffect` 拉取失败后不会在 `backend:ready` 后重放。一旦队列溢出（>200）、退出期 rejectAll、demo 模式、或未来生命周期竞争窗口，失败会永远挂住（侧边栏空、聊天空、文档工作台红条）。
2. **C 错误文案直出**：Electron 把 `BackendNotReadyError` 包装成 `Error invoking remote method 'sage:invoke': BackendNotReadyError: 后端服务尚未就绪...`，`desktopInvoke.ts` 把它原样透传到 UI；文档工作台顶层红条直出原始 IPC 文案，`ProjectsOverview` 无 try/catch 直接 unhandled rejection。
3. **项目总览无错态**：`ProjectsOverview.tsx` 没有错误态展示，一旦失败静默空白。

目标（用户零负担）：
- 后端就绪后自动重放失败的首屏拉取，红条自动消失。
- 若持续失败，文案友好、可识别（不再是裸 IPC 字符串）。
- 失败页面显示"正在重试…"而非空白。

## 涉及的文件与模块

| 路径 | 作用 |
|---|---|
| `src/shared/api/desktopInvoke.ts` | 剥离 IPC 包装前缀；`BACKEND_NOT_READY_MARKER` 已存在 |
| `src/shared/lib/backendReadySignal.ts`（新增）| 集中 `onBackendReady(cb)` 单例订阅 helper |
| `src/app/providers/SessionWorkspaceProvider.tsx` | 订阅 `onBackendReady`，`status==='error'` 时重放 `refresh()` |
| `src/widgets/layout/Sidebar.tsx` | 订阅 `onBackendReady`，sessions 空时重放 `loadSessions()` |
| `src/pages/Chat.tsx` | 订阅 `onBackendReady`，messages 空时重放 `loadMessages()` |
| `src/pages/ProjectsOverview.tsx` | 加 try/catch + 错误态 + 重试 |
| `src/widgets/system/BackendStatusBanner.tsx` | 文案参考（只读，不改动） |
| `electron/backendReadyQueue.ts` | 方案 A 队列（已在 main；本次不改动） |

## 技术方案

### C. 错误呈现去噪

**C1. `desktopInvoke.ts` 剥离 IPC 包装**

当前：
```ts
if (raw.includes(BACKEND_NOT_READY_MARKER)) {
  throw new Error(raw);  // "Error invoking remote method 'sage:invoke': BackendNotReadyError: 后端服务尚未就绪..."
}
```

改为：
```ts
if (raw.includes(BACKEND_NOT_READY_MARKER)) {
  // 剥离 Electron IPC 包装前缀,只留业务文案。
  const cleaned = raw.replace(/^Error invoking remote method '[^']+':\s*/, '')
                      .replace(/^BackendNotReadyError:\s*/, '');
  throw new Error(cleaned);
}
```

`backendRequest` 的 raw 通道（`src/shared/api/backendRequest.ts`）同样处理（如有必要）。

**C2. `ProjectsOverview.tsx` 加错态**

- `load` 包 try/catch；失败时 `setError(errorMessage(err))` 而不是 unhandled rejection。
- 顶部显示友好 banner（与文档工作台红条风格一致）+ 重试按钮。

### B. 渲染层自愈

**B1. 集中订阅 helper**

新增 `src/shared/lib/backendReadySignal.ts`：
```ts
type Handler = () => void;
const handlers = new Set<Handler>();
let installed = false;
function ensure() {
  if (installed) return;
  const api = window.electronAPI;
  if (!api?.listen) return;
  installed = true;
  void api.listen('backend:ready',      () => handlers.forEach(fn => fn()));
  void api.listen('backend:reconnected', () => handlers.forEach(fn => fn()));
}
export function onBackendReady(handler: Handler): () => void {
  ensure();
  handlers.add(handler);
  return () => { handlers.delete(handler); };
}
```

React hook `useBackendReadyTick(): number` 暴露"就绪事件计数"，组件加进 effect deps 即可自动重放。

**B2. 三处订阅**

- `SessionWorkspaceProvider`：`status === 'error'` 时，on ready 自动 `refresh()`。
- `Sidebar`：`sessions.length === 0` 时，on ready 自动 `loadSessions()`。
- `Chat`：`messages.length === 0 && currentSessionId` 时，on ready 自动 `loadMessages()`。

### 不做什么

- 不删除主进程就绪门禁（防止对旧端口/stale 进程发请求）。
- 不引入固定定时重试（依赖事件驱动,避免无效轮询）。
- 不动 `BackendStatusBanner`（用户可见 banner 已存在）。

## 实施步骤

- [ ] 步骤 1：剥离 IPC 包装前缀 + 友好文案（`desktopInvoke.ts`）
- [ ] 步骤 2：`ProjectsOverview.tsx` 加错态
- [ ] 步骤 3：新增 `src/shared/lib/backendReadySignal.ts`（单例 helper + hook）
- [ ] 步骤 4：`SessionWorkspaceProvider` / `Sidebar` / `Chat` 订阅重放
- [ ] 步骤 5：tsc + vitest + 受影响的组件单测（含 `SessionWorkspaceProvider` 现有测试）
- [ ] 步骤 6：提交 + 开 PR
- [ ] 步骤 7：win7 PR #2983 状态跟进；若队列 PR 已合 win7,本 PR cherry-pick 到 win7（或等主分支合入后由 win7-sync 流程承载）

## 风险评估

- **队列溢出**：方案 A 上限 200,正常冷启动 ~50 个请求；极端场景（如启动瞬间批量重渲染）仍可能溢出。B 的 on-ready 重放作为兜底。
- **事件丢失**：若 `onBackendReady` 订阅发生在 ready 事件**之后**（组件懒加载），会漏掉。当前三处订阅都在组件顶层 useEffect 早期安装，且 `useBackendReadyTick` 的计数从订阅后开始，首次订阅时若当前已经是 ready 状态应**不触发**（避免重复拉取已成功的数据）。
- **竞态**：SessionWorkspaceProvider 已有 `requestIdRef` 防过期覆盖,本次沿用。
- **win7 同步**：本改动全部在 renderer;cherry-pick 应干净。若与 win7 有冲突,按双分支规则适配 py38 / `backendRequest` raw 通道。

## 验收标准

- 实机冷启动（含队列禁用模拟：改 queue 容量=0 强制 fallthrough），文档工作台红条在 ready 后 <1s 自动消失;侧边栏非空;聊天页消息恢复。
- 队列正常启用时,`~/.config/sage/logs/sage-*.ndjson` 中 `invoke blocked` 计数为 0;renderer `store.loadSessions failed` / `store.loadMessages failed` 计数为 0。
- tsc 通过;vitest 通过（受影响的 SessionWorkspaceProvider、Sidebar、Chat、ProjectsOverview 单测全部绿）。
- PR 描述附冷启动日志 diff 截图。
