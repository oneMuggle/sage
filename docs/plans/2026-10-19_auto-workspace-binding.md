# 工作区自动绑定改进方案

> 创建日期：2026-10-19
> 分支：feat/auto-workspace-binding
> 状态：已完成 ✅

## 背景与目标

### 问题

当前 Sage 新建会话（Ctrl+N / Welcome 页面）后，会话**没有默认工作区绑定**。用户尝试查看变更、预览文档、导入 Office 文件时，会遇到 403 `workspace_not_bound` 错误。这是用户困惑的主要来源。

### 根因

- `store.createSession()` 只创建会话记录，不触发 `bind_session_workspace()`
- `SessionWorkspaceProvider` 被动读取绑定状态，无 fallback / 自动探测
- Electron 启动时不探测项目目录
- 系统中不存在 `autoBind` / `defaultWorkspace` 等自动绑定机制

### 目标

参考主流 AI 编程工具（Cursor / Claude Code / Aider / Windsurf）的工作区模型，实现三层递进改进：

| 优先级 | 方案 | 收益 |
|--------|------|------|
| **P0** | 智能引导：用引导组件替代 403 报错 | 消除用户困惑 |
| **P1** | 继承上次工作区：新会话自动绑定上次使用的路径 | 覆盖高频场景 |
| **P2** | 自动探测项目根：启动时探测 .git/manifest 并绑定 | 零配置体验 |

---

## 涉及的文件与模块

### 前端

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/app/providers/SessionWorkspaceProvider.tsx` | 修改 | P1: bind 成功后持久化 lastWorkspacePath |
| `src/shared/lib/store.ts` | 修改 | P1: createSession 后检查 lastWorkspacePath 并自动 bind |
| `src/widgets/chat/changes/ChangesSection.tsx` | 修改 | P0: 检测 notBound 时渲染引导组件 |
| `src/features/workspace/WorkspaceBindModal.tsx` | 修改 | P0: 暴露为可复用的引导入口 |
| `src/features/workspace/WorkspaceEmptyGuard.tsx` | **新增** | P0: 未绑定工作区时的引导组件 |
| `src/shared/lib/lastWorkspace.ts` | **新增** | P1: lastWorkspacePath 的读写工具 |
| `electron/main.ts` | 修改 | P2: 启动时探测项目根 |
| `electron/projectDetector.ts` | **新增** | P2: 项目根探测逻辑 |

### 后端

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| 无 | — | P0/P1 纯前端改动；P2 探测逻辑也在 Electron 主进程（Node.js 侧），不需要后端改动 |

### 测试

| 文件 | 说明 |
|------|------|
| `src/features/workspace/__tests__/WorkspaceEmptyGuard.test.tsx` | P0 引导组件测试 |
| `src/shared/lib/__tests__/lastWorkspace.test.ts` | P1 持久化工具测试 |
| `electron/__tests__/projectDetector.test.ts` | P2 探测逻辑测试 |

---

## 技术方案

### P0: 智能引导（替代 403 报错）

**核心思路**：将"错误"转化为"引导"。当用户访问需要工作区的功能但 `binding === null` 时，显示引导组件而不是报错。

**新增组件 `WorkspaceEmptyGuard.tsx`**：

```
渲染效果：
┌─────────────────────────────────────┐
|  📂 绑定工作区以使用此功能          |
|                                     |
|  当前会话尚未绑定工作区目录。       |
|  绑定后可查看文件变更、预览文档等。 |
|                                     |
|  [选择目录...]                      |
└─────────────────────────────────────┘
```

**改动点**：

1. `ChangesSection.tsx` 第 93 行 `notBound` 检测后，渲染 `<WorkspaceEmptyGuard feature="changes" />` 替代错误文案
2. `DocumentPreview.tsx` 预览区域检测 `binding === null` 时渲染 `<WorkspaceEmptyGuard feature="preview" />`
3. `ChatInput.tsx` @菜单 Office 导入检测 `binding === null` 时渲染 `<WorkspaceEmptyGuard feature="office" />`

### P1: 继承上次工作区

**核心思路**：用户手动 bind 成功后，将路径持久化到 localStorage。新会话创建后，检查该路径，存在且有效则自动 bind。

**新增工具 `lastWorkspace.ts`**：

```typescript
const LAST_WORKSPACE_KEY = 'sage.lastWorkspacePath';

export function getLastWorkspacePath(): string | null
export function setLastWorkspacePath(path: string): void
export function clearLastWorkspacePath(): void
```

**改动点**：

1. `SessionWorkspaceProvider.tsx` 的 `bind` 回调成功后调用 `setLastWorkspacePath(workspacePath)`
2. `store.ts` 的 `createSession` 成功后：
   - 读取 `getLastWorkspacePath()`
   - 如有值，调用 `workspaceApi.bind(sessionId, lastPath)`
   - 若 bind 失败（路径不存在），调用 `clearLastWorkspacePath()` 并静默跳过

### P2: 自动探测项目根

**核心思路**：Electron 启动时，从 `process.cwd()` 开始向上遍历，查找 `.git/` 目录或 manifest 文件（`package.json` / `pyproject.toml` / `Cargo.toml` / `go.mod`），将找到的目录作为默认工作区。

**新增 `electron/projectDetector.ts`**：

```typescript
const PROJECT_MARKERS = ['.git', 'package.json', 'pyproject.toml', 'Cargo.toml', 'go.mod'];

export function detectProjectRoot(startDir: string): string | null
// 从 startDir 向上遍历（最多 5 层），找到第一个含 marker 的目录
// 找不到返回 null
```

**改动点**：

1. `electron/main.ts` 启动时调用 `detectProjectRoot(process.cwd())`，结果存为模块级变量
2. 通过 IPC 暴露：`invoke('get_detected_project_root')`
3. `store.ts` 的 `createSession` 中，若 P1 的 lastWorkspacePath 不存在，则尝试从 IPC 获取 detectedProjectRoot 并自动 bind
4. 探测优先级：lastWorkspacePath > detectedProjectRoot > null（跳过）

---

## 实施步骤

- [x] **M1 (P0)**: 新增 `WorkspaceEmptyGuard.tsx` 组件 + 单元测试 ✅ 8/8
- [x] **M2 (P0)**: 在 `ChangesSection.tsx` 中替换错误文案为引导组件 ✅ 18/18 存量测试通过
- [x] **M3 (P1)**: 新增 `lastWorkspace.ts` 工具 + 单元测试 ✅ 7/7
- [x] **M4 (P1)**: 修改 `SessionWorkspaceProvider.tsx`，bind 成功后持久化路径 ✅ 29/29 provider 测试通过
- [x] **M5 (P1)**: 修改 `store.ts` 的 `createSession`，自动 bind lastWorkspacePath ✅ 14/14 store 测试通过
- [x] **M6 (P2)**: 新增 `electron/projectDetector.ts` + 单元测试 ✅ 9/9
- [x] **M7 (P2)**: 修改 `electron/main.ts`，启动时探测 + IPC 暴露 ✅ preload + 类型定义
- [x] **M8 (P2)**: 修改 `store.ts`，createSession 按优先级尝试 bind ✅ lastWorkspace → detectedProjectRoot → null
- [x] **M9**: 集成验证 + 跑全量测试 ✅ 3807/3807 前端测试 + 18/18 后端工作区测试

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| lastWorkspacePath 指向已删除目录 | bind 失败 | try-catch 静默跳过 + clearLastWorkspacePath |
| 项目根探测误判（HOME 有 .git） | 绑定到错误目录 | 限制向上遍历深度（最多 5 层） |
| 自动 bind 的会话用户想换工作区 | 需要手动 revoke | WorkspaceBindModal 已有此功能 |
| worktree 场景探测到错误根 | 绑定到主仓库 | 探测使用 Electron 启动目录 |
