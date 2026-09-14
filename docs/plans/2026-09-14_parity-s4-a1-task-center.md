# 对标 Sprint 2（parity-s4）A1——任务中心统一状态机

> 日期: 2026-09-14 · 基线: origin/main `6ee8e6cd`
> 分支: `feat/parity-s4` · worktree: `.worktrees/feat-parity-s4`
> 上游方案: 《Sage优化建议方案》主题 A（Agent 工作台）之 A1

## 1. 背景

任务中心 P4/P5/P7 已落地悬浮胶囊：聚合 taskCenterStore 注册任务
（office/wiki）+ 后台会话聊天流，可跳转。但三处短板：

1. **无状态机**：store 只有"存在=跑 / 删除=完"两种隐式状态，无
   queued/awaiting_approval/paused/failed/cancelled 表达；失败无处展示；
2. **不可操作**：widget 条目只能跳转，不能取消后台流/编排 lane，
   不能重试、不能清理已完成；
3. **编排不可见**：多 agent lane 跑批时用户切走页面即失联，任务中心
   看不到 lane（对标 Cursor Agents Window 的核心差距）。

## 2. 方案

### 2.1 store：七态状态机（`taskCenterStore.ts`）

- 新增 `TaskStatus = queued|running|awaiting_approval|paused|succeeded|failed|cancelled`；
- `TaskCenterEntry` 扩展：`status`（默认 running，与现有调用方语义一致）、
  `error?`、`finishedAt?`、`sessionId?`、`runId?`；
- 新增动作：`completeTask(id, status, error?)`（终态保留，供"最近完成"展示）、
  `removeTask(id)`、`clearFinished()`；
- `finishTask(id)` **保持 legacy 删除语义**：现有 office/wiki 调用方行为零变化。

### 2.2 chat 流取消句柄全局化（`useChat.ts`）

- `ActiveStreamHandle` 注册表从 hook 内 ref 提升为模块级 `Map<sid, handle>`
  （多 hook 实例/StrictMode 下更稳健，行为不变）；
- 新增导出 `cancelSessionStream(sid): Promise<boolean>`：unlisten 前端监听 +
  后端 interrupt（复用 MEDIUM-1 既有链路，fire-and-forget）；
- hook 内 markStreamActive/markStreamIdle 同步读写模块级表。

### 2.3 widget 升级（`TaskCenterWidget.tsx`）

- 条目三源聚合：registry 任务 + 后台 chat 流 + 编排 lane（读
  `laneBoardStore.lanes` 的 active/blocked，不过度拉取）；
- 每条目：状态徽章（图标+色）、失败时错误行、运行时取消按钮
  （chat 流→`cancelSessionStream`，lane→`laneBoardStore.cancel`）、
  终态条目保留展示 + "清除已完成"按钮；
- 失败 chat 条目提供"前往处理"（跳转会话，复用页内 InterruptedRunBanner
  重发链路，不在胶囊内重发）。

### 2.4 i18n

- `zh.ts`/`en.ts` 新增 `taskCenter.*` 约 10 个 key（状态/取消/清除/错误）。

## 3. 不做的事

- office/wiki 任务的后端取消（无取消端点，本批只做状态展示）；
- 任务持久化（刷新丢失，与胶囊定位一致；持久化随 A4 交付包做）；
- 后台完成通知（归 G/A3）；
- 后端改动（本批零后端变更）。

## 4. 测试

- store：complete/clearFinished/remove 语义 + finishTask legacy 语义 + 幂等注册保持；
- widget：取消按钮调 cancelSessionStream / lane cancel；失败条目渲染错误行；
  清除已完成移除终态条目；空闲不渲染（既有）；
- 回归：`vitest run` 相关 suite + `tsc --noEmit`。

## 5. win7 对齐

- 纯前端改动，无新依赖、无 IPC/后端变更，Electron 21 安全 API；
- 新功能按 `31-win7-lts.md` §2 不进 `release/win7`，本批零 cherry-pick 面；
- TypeScript/React 写法与既有代码同代，无新语法风险。
