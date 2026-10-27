# `src/` 收敛第 2 批：chat / 投递通道整链（2026-10-27）

> 上一批：`docs/mcp-win7-converge-src-types-adr-20261027.md`（PR #2579，types 布局裁决）。
> 上游计划：`docs/mcp-win7-convergence-plan-20261025.md`。
> 本文记录本批的判定依据、逐文件结论，以及被推迟到后续批次的项。

## 1. 基线

| 分支 | commit | 说明 |
|---|---|---|
| `release/win7` | `5037d42b` | #2579 合并后；相对上一批又落了 #2568–#2578 若干 PR |
| `main` | `6885594` | types 层已与本分支符号 212/212 全等 |
| merge-base | `476904b4` | 与上一批相同 |

在本基线上重扫 `src/`（1702 main 文件 / 1708 win7 文件 / 646 base 文件），bucket 分布：

| bucket | 数量 | 含义 |
|---|---|---|
| both | 46 | 两侧自 base 起都改过 → 逐 hunk 裁决 |
| nobase-both | 49 | base 之后两侧各自新增且内容不同 |
| mainly-add | 19 | 只有 main 新增 |
| win7-add | 19 | 只有 win7 新增 |
| 一侧删除 | 6 | main 删 / win7 留 |
| safe-main | 1 | 只有 main 改过 |

本批只取 **chat 域（投递通道 + 右栏链路）**，其余留给后续批次。

## 2. 关键判断：win7 的投递实现已被 main 取代

win7 侧自 base 起的 chat 改动是 **P1-6「可见队列」**：`useChat` 用 `pendingMessagesRef` + `useState` 双写保存待发消息，
暴露 `pendingMessages / cancelPending / clearPendingForSession`，由 `PendingQueueStrip` 在输入框上方常驻展示。

main 侧把同一问题做成了 **P2-a 三通道投递**（`#1334`）：队列搬进 `chatStreamStore`（`QueuedSendOptions` 可重放完整调用快照），
UI 换成 `PendingQueuePanel`（暂停/继续/编辑/置顶/立即发送）+ `DeliverySendGroup`（插话 / 排队 / 打断并发送），
并支持 `pendingQueue` / `queuePaused` 会话槽位。

结论：**win7 的实现是 main 的严格前身**，不存在平台分支或 win7 独有能力。逐文件核对 win7-only 行后确认（下表「win7-only 行」列）：

| 文件 | win7-only 行 | 性质 |
|---|---|---|
| `features/send-message/useChat.ts` | 104 | P1-6 ref 队列 + 注释 |
| `pages/Chat.tsx` | 16 | `PendingQueueStrip` 接线 |
| `widgets/chat/PermissionModeSwitch.tsx` | 0 | 纯 main 领先 |
| `widgets/chat/ChatInput.tsx` | 1 | `handleSend` 被 main 重构 |
| `widgets/chat/InputCard.tsx` | 7 | 发送按钮文案块被 `DeliverySendGroup` 取代 |
| `widgets/chat/changes/ChangesSection.tsx` | 13 | 仅 JSX 换行；截断提示 main 也有 |
| `widgets/chat/progress/ProgressSection.tsx` | 2 | 样式类名 |
| `features/send-message/chatStreamStore.ts` | 23 | main 多出 `QueuedSendOptions` / `memory_refs` / `rag_citations` |

全仓 `grep win7|Win7|WIN7|Windows|平台` 在 win7-only 行中 **0 命中**，确认无平台分支。

## 3. 逐文件结论

### 3.1 取 main（17 个实现文件）

`features/send-message/{chatStreamStore,useChat}.ts`、`pages/Chat.tsx`、
`widgets/chat/{ChatInput,InputCard,index,RightPanel,PermissionModeSwitch}.tsx`、
`widgets/chat/changes/{ChangesSection,FileChangeCard}.tsx`、`widgets/chat/progress/ProgressSection.tsx`、
`widgets/chat/{ChatInlineError,MessageMarkdownParts,WorkspaceBranchPicker}.tsx`、
`pages/chat/useChatMessageActions.ts`、`features/chat/useQuoteDraft.ts`、`features/right-panel/rightPanelStore.ts`。

### 3.2 `rightPanelStore`：main 主动收敛了 Tab 结构

win7 的右栏是 6 Tab（`progress / outline / trajectory / changes / preview / artifacts`）；
main 于 2026-10-14 把 trajectory 折进 progress、preview 折进 changes，并补了 localStorage 旧值迁移
（`migrateLegacyTab`：`trajectory → progress`、`preview → changes`），同时把 `previewFilePath` 换成
`previewOnSelect` + `autoPreviewMode`。**这是 main 的新设计，不是 win7 的缺失**，故取 main，
`RightPanel.tsx` 与 `RightPanel.test.tsx` 同步取 main（win7 的 `TrajectoryPane` / `DocumentPreview` 文件本身保留在仓里，
后续若要把 trajectory 重新接回，属于产品决策而非收敛问题）。

### 3.3 `BtwOverlay.tsx`：三方合并而非整份取用

该文件的 win7 侧有 **KaTeX 渲染**（`BtwOverlay.latex.test.tsx` 断言），main 侧有其它改动。
整份取 main 会让 `BtwOverlay.latex.test.tsx` 变红（2 用例），因此走 `git merge-file` 三方合并，
保留 KaTeX 分支的同时吸收 main 其余改动；合并后 `BtwOverlay{,.latex,.sources}` 共 15 用例全绿。

### 3.4 新增（main 独有）

`features/send-message/{deliveryMode,orchSteer}.ts`、`features/send-message/__tests__/{chatStreamStore.queue,transparencyPayload,useChat.delivery}.test.ts`、
`widgets/chat/{DeliverySendGroup,PendingQueuePanel}.tsx`、`widgets/chat/__tests__/{Message.blocked,PendingQueuePanel}.test.tsx`、
`shared/lib/permissionInsights.ts`（+ 测试，`PermissionModeSwitch` 依赖）。

### 3.5 删除（被取代）

| 文件 | 理由 |
|---|---|
| `widgets/chat/PendingQueueStrip.tsx`（+ 测试） | 被 `PendingQueuePanel` 取代；引用点只有 `Chat.tsx` 与 `widgets/chat/index.ts`，二者均已取 main |
| `features/send-message/index.ts` | main 已删除；全仓 0 importer（`git grep "from '@/features/send-message'"` 与相对路径写法均 0 命中） |

### 3.6 i18n：只插缺失键

`chat` / `settings.permission` 域共缺 **23 个键 × 2 语言**：

`chat.send_while_running`、`chat.queue_{title,paused,resume,clear,send_now,edit,top,remove,timing,timing_paused}`、
`chat.delivery_{menu,steer,steer_short,steer_hint,queue,queue_short,queue_hint,interrupt,interrupt_short,interrupt_hint}`、
`settings.permission.rules.shadowed{,_title}`。

按锚点（`'chat.send'` 之后、`'settings.permission.rules.plugin_missing'` 之后）插入，**不整份覆盖** locale 文件，
避免丢掉 win7 独有的键。插入后 `tsc` 报过一次 TS1117（重复键 `chat.steering_badge`，win7 原本就有），已去重。

## 4. 明确推迟的项（本批不碰）

| 项 | 原因 |
|---|---|
| `widgets/chat/ShikiCodeBlock.tsx` | main 版改用 `shiki/core` + `@shikijs/{langs,themes}` 动态导入；win7 `package.json` 无这两个依赖 → 与依赖批一起做，避免半截状态 |
| `WorkspaceBranchPicker.tsx` | 内容与 main **完全一致**（去空白后 token 序列相同），仅 win7 blob 是 CRLF；归入行尾归一化专项，不进本批 diff |
| 剩余 both / nobase-both 的非 chat 文件 | settings 域、settings 域测试、arena、memory、wiki 等，后续批次 |
| `package.json` / 依赖面 | 独立批次 |

## 5. 闸门

| 闸门 | 结果 |
|---|---|
| `tsc -p tsconfig.json --noEmit` | 0 error |
| `tsc -p tsconfig.electron.json --noEmit` | 0 error |
| vitest `features/send-message/__tests__` | 191 用例 0 失败 |
| vitest `widgets/chat/__tests__` | 636 用例 0 失败 |
| vitest `pages/__tests__/Chat.*` | 40 用例 0 失败 |
| vitest `features/chat` + `shared/lib` + `App.sessionDeeplink` | 451 用例 0 失败 |
| vitest `widgets/task-center` + `pages/settings` | 333 用例 0 失败 |
| 合计 | **1651 用例 0 失败** |

## 6. 规模

45 文件，+2557 / −705（含 2 个删除的文件树、19 个新增测试/实现文件）。
已剔除 2 个"仅换行差异"的文件（`WorkspaceBranchPicker.tsx`、`useChat.taskBoardEvents.test.ts`）以免 diff 噪音。
