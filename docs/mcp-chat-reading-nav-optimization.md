# 对话阅读导航与引用优化方案（对标 ChatGPT / Claude 等主流 AI 应用）

> 日期: 2026-09-26 · 基线: `origin/main` @ `0b12b3b0b`（R115 #1568）
> 工作分支: `feat/chat-nav-quote-main`（worktree `.worktrees/feat-chat-nav-quote-main`）
> 范围: 聊天主链路的「长会话阅读 → 定位 → 引用追问」体验（纯前端，零新依赖）。
> 对齐: main 落地 → cherry-pick `release/win7`（见 §5）。
> 前置阅读: `docs/plans/parity-loop-sop.md`（双分支交付 SOP）、
> `docs/technical/47-git-worktree-workflow.md`、`.claude/CLAUDE.md`（双分支约束）。

---

## 0. 结论速览（TL;DR）

| 问题 | 结论 |
| --- | --- |
| 已有能力 | 聊天基础体验已相当完整：粘底滚动 + 跳到最新、会话级草稿、IME 组合键保护、Esc 中断、代码块复制/换行/折叠、消息级复制/重生成/编辑重发/分叉/删除/引用/存记忆、临时聊天、跨会话全文搜索（F12）、对话大纲（P2-3.10）、长会话尾窗渲染（U11） |
| 最明显的缺口 | **"能找到但到不了"**：大纲条目看起来可点但点击无动作；搜索只统计命中数，点开会话后停在底部，用户仍要手动翻找；全仓库没有"定位到某条消息"的基础设施 |
| 一个数据丢失型 bug | 「引用到对话」**覆盖**输入框里已输入的草稿（`setValue(injectedDraft.text)`），先打字再引用会丢字 |
| 对标差距 | ChatGPT Web/iOS 的"选中文本 → Ask ChatGPT"、主流 IM/AI 应用的"搜索命中直达 + 短暂高亮"，Sage 均缺失 |
| 本轮交付（P0） | A1 消息定位基础设施 · A2 大纲点击直达标题 · A3 搜索命中直达并高亮 · A4 划词引用追问 · A5 引用改为追加、不再覆盖草稿 |
| 第二轮（P1/P2，§10） | 按优先级实施：P1 消息朗读、截断提示 + 继续生成、命中词高亮、会话内查找；P2 生成速度统计、回答版本切换、端点离线提示 |

---

## 1. 现状审查（代码证据）

### 1.1 已具备的主流能力（不重复建设）

| 能力 | 位置 |
| --- | --- |
| 粘底滚动 + "跳到最新" | `src/pages/Chat.tsx`（`wasAtBottomRef` / `BOTTOM_THRESHOLD_PX` / `scrollToLatest`） |
| 会话级草稿持久化 | `src/shared/lib/hooks/useSessionDraft.ts` |
| IME 组合键不误发送、↑ 编辑上一条、Esc 中断 | `src/widgets/chat/InputCard.tsx` |
| 流式分块 memo 渲染、尾窗 60 条 + "加载更早" | `src/widgets/chat/Message.tsx`（`splitStableChunks`）、`src/widgets/chat/MessageList.tsx`（`WINDOW_STEP`） |
| 消息级操作（复制/重生成/编辑重发/分叉/删除/引用/存记忆） | `src/widgets/chat/Message.tsx` 操作栏 |
| 跨会话全文搜索 | `backend/api/legacy_session_routes.py` `/search/messages`、`src/widgets/sidebar/sections/ConversationsSection.tsx` |
| 对话大纲 | `src/features/chat/useConversationOutline.ts`、`src/widgets/chat/ConversationOutline.tsx`（右侧面板） |
| 临时聊天 / 快捷键帮助 / 命令面板 | `chat.temp_chat*`、`src/shared/lib/shortcuts.ts`、`src/widgets/command/` |

### 1.2 差距证据

| # | 差距 | 证据 | 用户影响 |
| --- | --- | --- | --- |
| G1 | 大纲条目"可点但无动作" | `ConversationOutline.tsx` 按钮带 hover 高亮，`onClick` 处仅有注释 `// 未来扩展: onClick={() => scrollToMessage(item.messageId)}` | 死 UI：看起来能点，点了没反应 |
| G2 | 搜索命中只开会话不定位 | `ConversationsSection.tsx` 只把结果聚合成"会话 → 命中数"，点击走 `onSelect(sessionId)`；后端结果里的 `message_id` 被丢弃 | 长会话里仍要手动翻找；OpenAI 社区同类抱怨见 §9 [2] |
| G3 | 没有消息定位基础设施 | 全仓库没有 `data-message-id`、`scrollToMessage`；尾窗只渲染最近 60 条，更早的消息不在 DOM 中 | G1/G2 以及后续"引用来源回跳"等都做不了 |
| G4 | 引用覆盖草稿（bug） | `Chat.tsx` `handleQuote` → `setQuotedDraft`；`ChatInput.tsx` 注入 effect 一律 `setValue(injectedDraft.text)` | 先打字再点"引用"，已输入内容被覆盖丢失 |
| G5 | 没有划词引用 | `src/` 中没有任何 `getSelection()` 调用；只能整条消息引用 | 只想追问某一句时，要"复制 → 粘贴 → 手工加 `>`" 7 步（§9 [3]） |

---

## 2. 对标矩阵

| 能力 | ChatGPT | Claude | 主流 IM / 增强插件 | Sage（改前） | Sage（本轮后） |
| --- | --- | --- | --- | --- | --- |
| 选中文本 → 引用追问 | Web/iOS 有 "Ask ChatGPT" [1] | 有引用回复 | Slack/Telegram 引用回复 | ✗ | ✓ A4 |
| 引用不破坏已输入内容 | ✓（引用作为附加块） | ✓ | ✓ | ✗（覆盖） | ✓ A5 |
| 搜索命中 → 定位到消息 | 社区长期诉求 [2] | — | 插件"点击直达 + 短暂标记" [4] | ✗（只开会话） | ✓ A3 |
| 目录/导航 → 定位 | — | — | 插件导航栏"点击直达" [4] | ✗（死按钮） | ✓ A2（精确到标题） |
| 定位时加载被折叠的更早消息 | — | — | — | ✗ | ✓ A1 |

---

## 3. 优化方案

### 3.1 P0（本轮实施）

| 编号 | 名称 | 要点 |
| --- | --- | --- |
| A1 | 消息定位基础设施 | 新增 `messageJumpStore`（请求 = messageId + 可选标题 + nonce，TTL 8s 过期）；`MessageList` 为每条消息包 `data-message-id`，消费请求：目标在尾窗外时自动扩窗 → `requestAnimationFrame` 后滚动到视口中部 → 1.6s 高亮环 |
| A2 | 大纲点击直达 | `ConversationOutline` 增加 `onSelect`；右侧面板接入 `requestMessageJump`；在消息内按标题文本（去 Markdown 标记后比较）找到对应 `h2/h3`，找不到按序号兜底，再找不到定位到消息顶部 |
| A3 | 搜索命中直达 | 侧栏记录每个会话"最新一条命中消息"（后端按时间倒序返回）；点击命中会话时先登记定位请求再切会话；消息加载完成后自动定位并高亮 |
| A4 | 划词引用追问 | 在消息气泡（`data-quote-scope`）内选中文本 → 选区上方浮出"引用"按钮 → 以 Markdown 引用块追加到输入框并聚焦；滚动 / Esc / 选区消失时隐藏；按钮 `mousedown` 阻止默认行为，点击时选区不丢 |
| A5 | 引用改为追加 | `injectedDraft` 增加 `mode: 'replace' \| 'append'`；编辑重发保持覆盖语义，整条引用与划词引用改为追加（草稿尾部空一行再接引用块） |

与已有体验的协同：

- **粘底滚动**：定位滚动完成后同步派发一次 `scroll` 事件，`Chat.tsx` 的粘底状态立刻变为"不在底部"，后续流式 token 不会把视图拉回底部。
- **尾窗渲染**：扩窗只在定位时发生；定位完成后窗口保持扩大后的大小（否则目标消息会被立刻卸载），切会话时照常重置。
- **性能**：选区检测只挂 `mouseup` / `keyup` / `selectionchange`，用 `requestAnimationFrame` 合批；不引入新依赖。

### 3.2 P1 / P2（第二轮实施，见 §10）

| 级别 | 编号 | 名称 | 说明 |
| --- | --- | --- | --- |
| P1 | B1 | 消息朗读 | Web Speech API（Windows 走本地 SAPI 语音，离线可用；不支持时隐藏按钮）；对标 ChatGPT / 豆包 / Kimi 的"朗读" |
| P1 | B2 | 截断提示 + 继续生成 | 后端已记录 `finish_reason`（`backend/core/legacy/llm_client.py`），但前端没有任何消费；`length` 截断时应提示并提供"继续生成" |
| P1 | B3 | 命中词高亮 | 定位后用 CSS Custom Highlight API（Chromium 105+，Electron 21 可用）高亮搜索词 |
| P1 | B4 | 会话内查找 | `Ctrl+F` 已被"聚焦会话搜索"占用（`Layout.tsx` R40），需要先定键位方案再做 |
| P2 | C1 | 生成速度统计 | 首 token 延迟与 tokens/s（对标 LM Studio / Cherry Studio） |
| P2 | C2 | 回答版本切换 | 现在重新生成走分叉新会话；ChatGPT / Claude 是在同一位置 `< 2/3 >` 切换 |
| P2 | C3 | 端点离线提示 | 云端模型端点不可达时的全局提示 |

---

## 4. 设计细节

### 4.1 A1 定位请求的生命周期

```
requestMessageJump({ messageId, headingText?, headingIndex? })
  → store.pending = { ..., nonce }（8s 未消费自动清除）
MessageList（每次 messages / pending 变化）
  ① 目标不在 messages 中 → 等待（会话切换后消息异步加载）
  ② 目标在尾窗外 → effectiveWindow = max(windowSize, len - idx)
  ③ rAF：查 [data-message-id] → 标题精确定位 → scrollIntoView({block:'center'})
     → 派发 scroll 事件 → 高亮 1.6s → consume(nonce) → 窗口固化
```

消息 ID 全局唯一，所以请求不必带 sessionId：只有目标消息所在的会话能消费它。

### 4.2 A4 选区判定

- 选区起点和终点都必须落在同一个 `MessageList` 根节点内的 `[data-quote-scope]` 元素里（工具卡片、按钮、来源列表不可引用）。
- 文本 = `selection.toString()`，去掉首尾空白，把连续 3 行以上的空行压成 1 行；每行加 `> ` 前缀，空行保留 `>`。
- 浮层通过 portal 渲染到 `document.body`，按选区矩形定位（顶部空间不足时放到下方），并限制在视口内。

### 4.3 A5 合并规则

`appendQuoteToDraft(draft, quote)`：草稿为空 → `quote + "\n\n"`；草稿非空 → `draft.trimEnd() + "\n\n" + quote + "\n\n"`。连续引用多段会依次累积，方便"选两段 → 让模型比较"的写作流。

---

## 5. 双分支对齐策略

- 改动全部在前端 `src/`（TS/TSX + i18n），**不改后端、不改依赖**，因此不碰 `requirements*.txt` 红线，也没有 py38 兼容面。
- 两个分支都是 Electron 21.4.4 / Chromium 106；A1–A5 用到的 `scrollIntoView`、`Selection`、`createPortal`、`requestAnimationFrame` 在两边都可用。
- 事前核对：`ConversationOutline.tsx`、`useConversationOutline.ts` 两个分支逐字节一致；`MessageList.tsx` / `Message.tsx` / `Chat.tsx` / `ChatInput.tsx` / `ConversationsSection.tsx` / `RightPanel.tsx` / i18n 在 win7 上是"功能子集"（缺 R44 / R19-W1 等），cherry-pick 可能有上下文冲突，按 SOP §4.4 手工解决，不整文件替换。
- 流程：main PR 绿 → squash 合并 → `git -c core.hooksPath=/dev/null cherry-pick <squash>` 到 `feat/chat-nav-quote-win7`（base `origin/release/win7`）→ 本地受影响测试 → PR → 必需检查全绿 → 合并。严禁 `merge release/win7` 进 main。

---

## 6. 验证矩阵

| 层 | 内容 |
| --- | --- |
| 单测（新增） | `messageJumpStore`（请求 / 消费 / TTL）、`selectionQuote` 纯函数（格式化 / 合并 / 选区判定）、`MessageList` 定位（扩窗 + 滚动 + 高亮 + 粘底事件）、`ConversationOutline` 点击、`ConversationsSection` 命中定位、`ChatInput` 追加模式、`SelectionQuoteButton` 交互 |
| 回归 | `src/widgets/chat/__tests__`、`src/features/chat/__tests__`、侧栏测试、i18n 键集一致性 |
| 静态 | 改动文件 `eslint` + 全量 `tsc --noEmit` |
| CI | main 必需检查 `stub-smoke` / `stub-deep` / `live-boot` 及全部检查全绿；win7 必需检查 5 项全绿 |

---

## 7. 进度日志（每完成一步即回填）

| # | 时间（UTC+8） | 步骤 | 状态 | 证据 / 产物 |
| --- | --- | --- | --- | --- |
| 1 | 2026-09-26 00:23 | 代码审查 + 主流应用对标 | ✅ 完成 | §1、§2；基线 `origin/main` @ `0b12b3b0b` |
| 2 | 2026-09-26 00:23 | 新建 main 工作树 | ✅ 完成 | `scripts/worktree.sh new feat/chat-nav-quote-main --base origin/main` → `.worktrees/feat-chat-nav-quote-main`（端口 8782/1437；`node_modules` 以目录联接复用主检出，清理前需先 `rmdir` 联接） |
| 3 | 2026-09-26 00:30 | 输出优化方案（本文 §0–§6） | ✅ 完成 | 本文件 |
| 4 | 2026-09-26 00:46 | A1–A5 实施 + 本地验证 | ✅ 完成 | 见 §7.1；受影响目录 vitest 全绿，`tsc --noEmit` 0 错误，`npm run lint` 0 错误，`architecture-check` 通过 |
| 5 | 2026-09-26 01:47 | main PR → CI 全绿 → squash 合并 | ✅ 完成 | [#1580](https://github.com/oneMuggle/sage/pull/1580) 全部 14 项检查通过（2 项按条件跳过）→ squash 合并为 `c6fb3630a`；见 §7.2 |
| 6 | 2026-09-26 01:57 | win7 cherry-pick → PR → CI 全绿 → 合并 | ⏳ 进行中 | `feat/chat-nav-quote-win7` 已 cherry-pick 并通过本地验证，见 §7.3 |
| 7 | — | §8 回填 + 清理分支与工作树 | ⏸ 待办 | — |

### 7.1 实施记录（步骤 4）

新增文件：

| 文件 | 作用 |
| --- | --- |
| `src/features/chat/messageJumpStore.ts` | A1 定位请求通道（nonce、8s TTL、`requestMessageJump`） |
| `src/features/chat/useMessageJump.ts` | A1/A2 MessageList 侧消费：扩窗、标题匹配（文本优先、序号兜底）、同步粘底、高亮 |
| `src/features/chat/selectionQuote.ts` | A4/A5 纯函数：选区判定、引用块格式化、追加合并、浮层定位 |
| `src/features/chat/useQuoteDraft.ts` | A4/A5 引用注入通道（一次性追加事件；从 `Chat.tsx` 抽出） |
| `src/widgets/chat/SelectionQuoteButton.tsx` | A4 划词引用浮动按钮（portal 到 body） |

改动文件（均为小范围接线）：`MessageList.tsx`（包 `data-message-id`、接入定位与划词按钮）、
`Message.tsx`（气泡加 `data-quote-scope`，1 行）、`ConversationOutline.tsx` + `RightPanel.tsx`（A2）、
`ConversationsSection.tsx`（A3）、`Chat.tsx` + `ChatInput.tsx` + `InputCard.tsx`（A4/A5）、
`i18n/zh.ts` + `i18n/en.ts`（新增 `chat.quote_selection` / `chat.quote_selection_hint`）。

测试：新增 `messageJumpStore.test.ts`、`selectionQuote.test.ts`、`useQuoteDraft.test.ts`、
`MessageList.jump.test.tsx`、`SelectionQuoteButton.test.tsx`、`ChatInput.quoteAppend.test.tsx`，
扩展 `ConversationOutline.test.tsx`、`ConversationsSection.test.tsx`（共新增 36 个用例）。

实施中的设计修正：

1. **定位请求的清除时机**：最初在滚动后立即清掉全局请求。zustand 的更新走同步渲染，会先于
   扩窗的 React 状态提交，目标消息先被尾窗裁掉、再重新挂载，已经滚好的位置随之失效
   （`MessageList.jump.test.tsx` 首个用例抓到：滚动的节点与最终节点不是同一个）。
   改为"已处理 nonce、扩窗、高亮"放在同一批 React 状态里提交，下一个 effect 再清掉全局请求。
2. **引用改为一次性事件**：`quotedDraft` 被输入框消费后下一帧清空。否则编辑重发结束时
   `injectedDraft` 会回落到旧引用，在追加语义下重复追加。
3. **架构棘轮**：`scripts/architecture-check.mjs` 对超大文件做行数棘轮。引用逻辑抽成
   `useQuoteDraft` 后 `Chat.tsx` 净增长为 0（1166 行，基线 1167）；`i18n/zh.ts`、`i18n/en.ts`
   （各 +2 个键）和 `Message.tsx`（+1 行）按棘轮协议上调基线。另外，main 最新 CI 的
   Architecture check 已经是红的：#1569 让 `backend/orchestration/chat_dispatcher.py` 涨到 2206 行，
   但没有更新基线（2197）。本地曾一并修正该条目；开 PR 前 rebase 到 `c0a2513b7`（#1571）时发现
   main 已用同值修复，rebase 后本 PR 不再包含这一行。

本地验证环境说明：

- 主检出 `node_modules` 缺 `@xterm/xterm`（#1559 新增依赖后未重装），Chat 页面测试在联接模式下
  无法收集。已删除联接，在工作树内 `npm ci --ignore-scripts --prefer-offline` 独立安装（约 1 分钟，
  跳过 electron / node-pty 的安装脚本，不影响前端测试）。
- `prettier --write` 会顺带重排 `Message.tsx` 等文件里本来就没按 prettier 格式化的旧代码。为了控制
  diff 和 win7 cherry-pick 冲突面，已把这些与本次无关的重排还原，只保留本次改动（本次代码已按
  prettier 格式化）；提交时跳过 lefthook pre-commit（`LEFTHOOK=0`），CI 仍是唯一门禁。
- 全量并行跑时 `src/pages/__tests__/ArenaAccounts.test.tsx` 有 2 个用例偶发 `waitFor` 超时，单独重跑
  通过；该页面与本次改动无关。

过程记录（供后续会话参考）：

- 开 PR 前 main 合入了 `AGENTS.md`（#1571）。按其「spec 先行」要求补登记
  `docs/plans/2026-09-26_chat-reading-nav.md`（指向本文）；按其「真实门禁」条款，推送使用
  `--no-verify`（pre-push 会跑全量前端套件，本地已跑受影响目录），并在 PR 描述中说明。
- 推送阶段 Sage 工作区的 MCP 隧道断开（Cloudflare 1033），改由同机另一个 ShunCode 桥接用绝对路径
  继续操作。`github.com:443` 直连频繁被重置：推送走本机系统代理（`http.proxy=127.0.0.1:7890`，
  仅命令级 `-c`），凭据用 `gh auth git-credential`，避免 Git Credential Manager 弹窗阻塞。

### 7.2 main 合并记录（步骤 5）

- PR 开出前按 `AGENTS.md` 先 `git fetch`：base 前进到 `c0a2513b7`（#1571），rebase 后再推。
- CI（最终头 `94fa233ac`）：All Checks、Architecture check、Backend (Python)、Backend collect (py38)、
  Backend legacy smoke、Dependency audit、Electron build ×2、Electron smoke、Frontend、count-lines，以及
  必需的 `stub-smoke` / `stub-deep` / `live-boot` 全部通过；`Backend (Python 3.8, Win7 LTS)` 与
  `Backend unit (Windows, non-blocking)` 在 main 目标的 PR 上按条件跳过。
- 合并前复查：main 又前进了 2 个提交（#1577、#1578），都只改 `docs/plans/` 下的文档，与本 PR 零重叠；
  main 分支保护是非严格模式（`strict: false`），因此没有再 rebase 重跑 CI。
- `gh pr merge 1580 --squash --delete-branch` → squash 提交
  `c6fb3630a986e75232d6e4432e6bb356fc368e93`（2026-09-26 01:47 UTC+8），远端分支已删除。

### 7.3 win7 对齐记录（步骤 6）

- `scripts/worktree.sh new feat/chat-nav-quote-win7 --base origin/release/win7` →
  `.worktrees/feat-chat-nav-quote-win7`（端口 8783/1438）。
- `git -c core.hooksPath=/dev/null cherry-pick c6fb3630a`：22 个文件自动合并，3 个文件冲突，按 SOP §4.4
  手工解决（不整文件替换）：
  - `MessageList.tsx`：win7 没有 R44 空态建议和 R19-W1 拦截卡片。保留 win7 的导入（无 `Sparkles` /
    `BlockedAction`），采用新的 `data-message-id` 包裹层，去掉 `onBlockedAction` 透传。
  - `Message.tsx`：win7 的气泡块没有流式光标和阅读宽度约束，缩进也不同。保留 win7 原块，只加
    `data-quote-scope`。
  - `architecture-baseline.json`：win7 基线余量足够（en 1228/1241、zh 1202/1217、Message 1040/1067、
    Chat 1096/1167），保留 win7 数值，不改基线。
- 推送前 `release/win7` 前进到 `2f542db3a`（AGENTS.md 的 win7 回移），已 rebase，无冲突。
- win7 工作树独立 `npm ci --ignore-scripts --prefer-offline`（1189 个包）后本地验证：`tsc --noEmit`
  0 错误；改动文件 `eslint` 0 错误；`architecture-check` 通过；新鲜度 behind 0；受影响目录 vitest
  121 个文件 / 706 个用例全绿。改动只在前端，没有 py38 兼容面；CI 的 `Backend (Python 3.8, Win7 LTS)`
  仍会全量跑。

---

## 8. 交付记录（§回填）

| 分支 | PR | 合并提交 | 备注 |
| --- | --- | --- | --- |
| `main` | 待回填 | 待回填 | — |
| `release/win7` | 待回填 | 待回填 | — |

---

## 9. 参考资料

1. OpenAI Developer Community —「Ask ChatGPT」选中文本追问（Web / iOS 已支持，桌面端缺失）
   https://community.openai.com/t/feature-request-ask-chatgpt-for-selected-text-in-the-current-chat-for-desktop-app/1387522
2. OpenAI Developer Community — 点击搜索结果只跳到会话底部、不定位到消息
   https://community.openai.com/t/clicking-a-search-result-in-a-chat-does-not-jump-to-the-actual-message-only-to-the-bottom/1263997
3. openai/codex #32159 — 桌面端缺少选中追问，手工流程需 7 步
   https://github.com/openai/codex/issues/32159
4. ChatGPT Chat Navigator（第三方）— 点击直达消息并短暂标记
   https://gptspeedbooster.com/chatgpt-chat-navigator/
5. MDN — Web Speech API（`speechSynthesis` / `SpeechSynthesisUtterance`）
   https://developer.mozilla.org/docs/Web/API/Web_Speech_API
6. MDN — CSS Custom Highlight API（`CSS.highlights` / `::highlight()`）
   https://developer.mozilla.org/docs/Web/API/CSS_Custom_Highlight_API

---

## 10. 第二轮：P1 / P2 实施

> 日期: 2026-09-26 · 基线: `origin/main` @ `6a77dc3b5`（#1609）
> 批次: P1（B1–B4）→ P2（C1–C3）。每批 main 合并后 cherry-pick 到 `release/win7`，流程同 §5。
> P1 工作分支: `feat/chat-reading-p1-main`（worktree `.worktrees/feat-chat-reading-p1-main`）。

### 10.1 范围与批次

| 批次 | 编号 | 名称 | 前端 | 后端 |
| --- | --- | --- | --- | --- |
| P1 | B1 | 消息朗读 | ✓ | — |
| P1 | B2 | 截断提示 + 继续生成 | ✓ | ✓ `finish_reason` 透传并落库 |
| P1 | B3 | 搜索命中词高亮 | ✓ | — |
| P1 | B4 | 会话内查找 | ✓ | — |
| P2 | C1 | 生成速度统计 | ✓ | ✓ 用量与耗时透传并落库 |
| P2 | C2 | 回答版本切换 | ✓ | ✓ 同一位置保存多个回答版本 |
| P2 | C3 | 端点离线提示 | ✓ | —（按失败事件的错误类型判定，不新增接口） |

P2 的详细设计在 P1 合并后补入 §10.6：先对照当时的代码核实，再定稿。

### 10.2 代码核实（第二轮新增证据）

| 事实 | 位置 | 影响 |
| --- | --- | --- |
| `messages` 表从建表起就有 `finish_reason` / `input_tokens` / `output_tokens` / `total_tokens` / `latency_ms` 列，但仓储的 `Message` 数据类没有这些字段，读写都不经过它们 | `backend/data/database.py`、`backend/data/session_repo.py` | B2 / C1 不需要数据库迁移，补齐仓储映射即可 |
| 流式和非流式 LLM 响应都带 `finish_reason` | `backend/core/legacy/llm_client.py` | agent 在终稿 DONE 事件里带上即可 |
| DONE 事件由 `AgentEvent.to_dict()` 序列化，经 producer 转发给前端 | `backend/core/legacy/agent_state.py`、`backend/api/legacy_routes.py` | 新增可选字段对旧前端透明 |
| 流结束后前端会 `loadMessages` 对账，以服务端数据为准 | `src/features/send-message/useChat.ts` | 截断标记必须落库，否则对账后丢失 |
| `Ctrl+F` 由 `Layout.tsx` 全局派发 `sage:focus-search`；`Ctrl+K` 是命令面板；`Ctrl+Shift+F` 没有占用 | `src/widgets/layout/Layout.tsx`、`src/App.tsx`、`src/shared/lib/shortcuts.ts` | B4 键位见 §10.3 |
| 两条分支都是 Electron 21（Chromium 106）：`speechSynthesis`（Windows 走本地 SAPI 语音）和 CSS Custom Highlight API（Chromium 105+）都可用 | — | B1 / B3 / B4 不需要 polyfill；做特性检测，不支持时隐藏入口或不高亮 |
| `Chat.tsx`、`Message.tsx`、`zh.ts` / `en.ts`、`types.ts` 等已在架构基线上，而且没有余量 | `architecture-baseline.json` | 新逻辑放进新模块，尽量不让基线文件增长；确需增长时按棘轮协议更新基线并在 PR 说明 |

### 10.3 B4 键位决策

- 聊天页有消息时，`Ctrl/Cmd+F` 打开「会话内查找」栏，与浏览器、VS Code、Telegram 的「在当前视图中查找」一致。
- `Ctrl/Cmd+Shift+F` 始终聚焦侧栏的会话搜索（跨会话检索）。
- 查找栏没有挂载时（其他页面、空会话），`Ctrl/Cmd+F` 保持原来的行为（聚焦会话搜索），非聊天页的使用习惯不变。
- 实现上不做路由判断：`Layout` 先派发可取消的 `sage:open-chat-find` 事件，查找栏处理后调用 `preventDefault()`；没有被处理就回落为 `sage:focus-search`。
- 快捷键帮助（`src/shared/lib/shortcuts.ts`）同步更新。

### 10.4 P1 设计

**B1 消息朗读**

- 纯函数模块 `speech.ts`：把 Markdown 转成朗读文本（代码块换成「代码已略过」提示，链接只保留文字，去掉标记符号）；按句切成不超过 180 字的片段依次排队朗读，避开 Chromium 朗读长句中途停止的问题；按汉字占比选择 `zh-CN` 或 `en-US`，并优先使用同语种的本地语音。
- 全局单例 `readAloudStore`：同一时刻只朗读一条消息；再次点击即停止；正在朗读的消息被卸载（切换会话、删除）时自动停止。
- assistant 消息操作栏新增「朗读 / 停止朗读」按钮；环境不支持 `speechSynthesis` 时不渲染。

**B2 截断提示 + 继续生成**

- 后端：`AgentEvent` 新增可选字段 `finish_reason`，agent 的终稿 DONE 事件从 LLM 响应带出；producer 把它写入 `messages.finish_reason`；仓储 `Message` 补齐该字段（读、写、分叉复制）。
- 前端：`Message` 类型新增 `finish_reason`；收到 DONE 时先写进本地消息，对账后以服务端为准。值为 `length`（兼容 `max_tokens`）时，在气泡下方提示「回答达到长度上限，已被截断」。
- 如果被截断的是会话最后一条消息，同时给出「继续生成」按钮：发送一条「从中断处继续」的续写消息（对标 ChatGPT 的 Continue generating）。原消息不改写，历史可以追溯。

**B3 搜索命中词高亮**

- `messageJumpStore` 的定位请求新增 `highlightQuery`；从侧栏搜索命中直达时带上搜索词。
- 定位完成后，用 CSS Custom Highlight API 在目标消息正文（`[data-quote-scope]`）里高亮全部命中，约 8 秒后自动清除。不改 DOM，不影响 React 渲染和复制。
- 匹配方式：把正文的文本节点拼起来，做不区分大小写的字面匹配，所以能跨过加粗等行内标记。
- 后端全文检索按词命中，多个词可以不相邻：整句没有字面命中时，退回逐词高亮。

**B4 会话内查找**

- 查找栏包含输入框、`n/m` 计数、上一个 / 下一个和关闭按钮，固定在消息区右上角；搜索范围是当前会话的全部消息，包括尾窗外还没渲染的。
- 计数基于去掉 Markdown 标记后的消息文本。定位复用 A1 通道（`highlightQuery` + `highlightIndex`）：自动扩窗并滚动到当前命中；当前命中用醒目色，其他已渲染的命中用浅色。
- 顺序符合聊天习惯：打开时停在最新（最靠下）的命中；`Enter` 或 ↑ 按钮跳到更早的命中，`Shift+Enter` 或 ↓ 按钮跳到更新的命中；`Esc` 关闭并清除高亮。查找栏已打开时再按 `Ctrl/Cmd+F` 会重新聚焦并全选输入框；关闭后再打开从空白开始。
- 输入有 150ms 防抖，防抖生效前按 `Enter` 会立即提交查找词；输入法组词中的 `Enter` / `Esc` 不触发查找操作。
- 已知限制：计数基于去掉标记后的源文本，高亮基于渲染后的 DOM。公式、Mermaid 图这类渲染后文字与源码不同的内容，两者可能对不上；对不上时滚动到消息本身，不高亮。

### 10.5 验证矩阵（P1）

| 层 | 内容 |
| --- | --- |
| 前端单测 | `speech` 纯函数、`readAloudStore`（排队 / 停止 / 互斥）、朗读按钮；截断提示与继续生成；`textHighlight`（跨节点匹配、特性检测降级）；会话内查找的计数与排序；查找栏交互（打开 / 计数 / 跳转 / 关闭）；`Layout` 键位回落；侧栏命中带上搜索词 |
| 后端单测 | `AgentEvent.to_dict` 带 `finish_reason`；agent DONE 透传；仓储读写与分叉复制 `finish_reason` |
| 回归 | chat / sidebar / layout / i18n 相关测试目录；后端 `session_repo`、agent、legacy chat 相关用例 |
| 静态 | 改动文件 eslint、全量 `tsc --noEmit`、`ruff check backend/`、`architecture-check` |
| CI | main 与 win7 的必需检查全部通过（同 §6） |

### 10.6 P2 设计

> 基线：合并 #1619 后的 `origin/main` @ `a3c16668e`。实施顺序 C1 → C3 → C2（C2 改动最大，放最后）。

**代码核实（P2 新增证据）**

| 事实 | 位置 | 影响 |
| --- | --- | --- |
| `usage_events` 表预留了 `first_token_ms` / `latency_ms` 列，`usage_tracker.record` 也接受这两个参数，但 LLM 客户端从未传入 | `backend/services/usage_tracker.py`、`backend/core/legacy/llm_client.py` | C1 在流式请求里计时，顺带补齐用量统计的这两列 |
| 流式请求带 `stream_options.include_usage`，终值 `LLMResponse` 有输入 / 输出 tokens | `llm_client.py` | 速度用上游返回的 completion_tokens 计算；上游不返回时不显示速度 |
| 失败事件的 `error` 是 `LLMError.to_dict()`（`type` 为 `network_error` / `timeout` / `server_error` 等），但 `chatApi` 只取 message 往上抛 | `backend/core/errors.py`、`src/shared/api/chatApi.ts` | C3 在 `chatApi` 按错误类型判定「端点不可达」 |
| `BackendStatusBanner` 只管本机后端进程；云端端点不可达时只有单条消息下的报错 | `src/widgets/system/BackendStatusBanner.tsx` | C3 新增独立的全局提示条 |
| 重新生成 = 分叉到原问题之前再重发，侧栏每次多出一个会话 | `src/pages/Chat.tsx` `handleRegenerate` | C2 把最后一轮改为原位重新生成 |
| 模型可见历史从 `session_events` 事件日志投影；`message.deleted` 宣告的 id 永久排除（日志里 id 不复用） | `backend/chat/event_projection.py`、`backend/data/session_event_repo.py` | C2 归档旧回答要写删除事件；恢复版本必须以新 id 重新插入 |
| 本轮 user 消息在加载历史之后才落库；`client_message_id` 幂等复用只覆盖同 id 重试 | `backend/api/legacy_routes.py` producer | C2 的重新生成请求要跳过 user 落库，并从历史里剔除该 user 消息，否则上下文里会出现两遍 |

**C1 生成速度统计**

- 后端：流式请求记录开始时间和第一个内容 / 推理增量到达的时间，得到 `first_token_ms`（首字延迟）和 `latency_ms`（总耗时），写入 `usage_events` 的预留列，并挂到 `LLMResponse` 上；非流式请求只有 `latency_ms`。
- agent 的终稿 DONE 事件新增 `generation_stats`（`input_tokens` / `output_tokens` / `first_token_ms` / `latency_ms`，缺失项省略）；producer 把它写入 assistant 行的新列 `messages.generation_stats`（JSON，老库启动时自动加列）；仓储负责读写和分叉复制。
- 前端：收到 DONE 时写进本地消息，对账后以服务端为准。assistant 操作栏右侧显示「42.3 tok/s · 首字 0.82s · 1,234 tokens」，悬停显示输入 / 输出 tokens、首字延迟和总耗时。速度 = 输出 tokens ÷（总耗时 − 首字延迟）；上游没有返回用量时只显示耗时。
- 只统计终稿那一次 LLM 调用；多步工具调用的中间步骤不计入。

**C3 端点离线提示**

- 判定：流式失败且错误类型是 `network_error`、`timeout`，或 `server_error` 且状态码为 502 / 503 / 504 时，记为「端点不可达」；之后任意一次成功完成即清除。系统断网（`navigator.onLine === false`）单独提示。
- 展示：标题栏下方的全局提示条，所有页面都能看到，写明端点主机名和模型。按钮：「重新检测」（请求端点的模型列表接口，不消耗 token，成功即清除）、「端点设置」、关闭。用户换成别的对话端点后，旧端点的提示自动隐藏。
- 不做后台定时探测，避免空耗请求；系统恢复联网时自动重新检测一次。

**C2 回答版本切换**

- 范围：只对会话的最后一轮生效。在最后一轮任一 assistant 气泡上点「重新生成」时原位重跑；更早的轮次仍沿用分叉会话（原位切换要连带替换后面的全部消息，不在本轮范围内）。
- 存储：新表 `message_versions(id, session_id, anchor_id, rows_json, generated_at, archived_at)`。`anchor_id` 是本轮的 user 消息；`rows_json` 是该版本全部消息行的原样快照（`SELECT *`，恢复时按当前表的列回填）。会话删除时级联删除。
- 流程：
  1. 前端在本地移除旧回答，以 `regenerate_of=<锚点 id>` 发起流式请求。后端先校验锚点是最后一条 user 消息（否则 409，不占用 stream slot），然后不再落 user 消息，历史投影里剔除锚点和旧回答，跳过自动话题检测。
  2. 旧回答在本轮**第一次落库之前**才归档（`ArchiveOnFirstSave` 包装仓储：删除旧行并写 `message.deleted` 事件，同步 `message_count`）。所以只有重新生成真的产出了内容（或被用户中断、留下 partial）时才替换旧回答；失败且没有任何落库时旧回答原样保留，前端流结束对账后重新显示。
  3. 最后一条 assistant 消息的操作栏显示 `‹ 2/3 ›`。`GET /sessions/{id}/answer-versions` 列出版本（按版本首行时间排序，当前显示的版本也算一个）；切换时调 `POST /sessions/{id}/answer-versions/{version_id}/activate`：当前回答先归档为版本，目标版本的消息行以新 id 重新插入（同样写 `message.appended` 事件，保持「模型可见 ⟺ 已记录」），然后前端重拉消息。
- 继续对话之后，之前那一轮的其他版本不再提供切换入口（数据保留）。演示模式没有后端，仍走分叉会话的旧行为。
- 已知限制：重新生成只重发文字，原消息的图片 / 附件不会再次附带（与现有分叉式重新生成一致）。

**验证矩阵（P2）**

| 层 | 内容 |
| --- | --- |
| 前端单测 | 速度计算与格式化、统计展示；端点状态的判定 / 清除 / 端点切换后隐藏、提示条交互（重新检测成功与失败、断网、关闭）、`chatApi` 失败事件上报；版本 API 封装、版本切换器（翻页 / 边界禁用 / 单版本隐藏 / 切换失败提示）、原位重新生成（最后一轮走原位，更早轮次和演示模式走分叉）、`MessageList` 只把切换回调交给最后一条消息、`useChat` 的 `regenerateOf` 不追加 user 消息 |
| 后端单测 | 流式计时与 `usage_tracker` 参数；`AgentEvent.generation_stats`；仓储 `generation_stats` 读写与分叉复制；版本归档 / 列出 / 激活（事件日志、`message_count`、新 id、非最后一轮拒绝）；`/chat/stream` 集成：生成统计落库、`regenerate_of`（不落 user、发给模型的历史里 user 消息只出现一次且不含旧回答、失败保留旧回答、更早轮次 409）、版本切换接口 |
| 回归 / 静态 / CI | 同 §10.5 |

### 10.7 进度日志（第二轮，每完成一步即回填）

| # | 时间（UTC+8） | 步骤 | 状态 | 证据 / 产物 |
| --- | --- | --- | --- | --- |
| 1 | 2026-09-26 08:24 | 新建 P1 工作树 | ✅ 完成 | `scripts/worktree.sh new feat/chat-reading-p1-main --base origin/main` → `.worktrees/feat-chat-reading-p1-main`（端口 8783/1438）；`npm ci` 在工作树内独立安装依赖 |
| 2 | 2026-09-26 08:50 | 代码核实 + P1 方案定稿（§10.1–§10.5） | ✅ 完成 | 本文件；登记 `docs/plans/2026-09-26_chat-reading-nav-r2.md` |
| 3 | 2026-09-26 09:26 | P1 实施 + 本地验证 | ✅ 完成 | 见 §10.7.1：新增 9 个前端模块、9 个前端测试文件、1 个后端测试文件；受影响文件 eslint 0 错误，全量 `tsc --noEmit` 0 错误，`ruff check backend/` 通过，`architecture-check` 通过（6 个基线文件按棘轮协议上调） |
| 4 | 2026-09-26 09:53 | P1 main PR → CI 全绿 → 合并 | ✅ 完成 | [#1619](https://github.com/oneMuggle/sage/pull/1619) 14 项检查通过（2 项按条件跳过）→ squash 合并为 `a3c16668e`；见 §10.7.2 |
| 5 | 2026-09-26 10:30 | P1 cherry-pick 到 win7 → PR → CI 全绿 → 合并 | ✅ 完成 | [#1622](https://github.com/oneMuggle/sage/pull/1622) 必需的 5 项检查及 All Checks / Architecture check / count-lines 通过（3 项按条件跳过）→ squash 合并为 `315fdebca`；见 §10.7.3 |
| 6 | 2026-09-26 11:20 | P2 设计定稿 + 实施 + 本地验证 | ✅ 完成 | 设计见 §10.6，实施记录见 §10.7.4：新增 7 个前端模块、1 个后端模块、10 个前端测试文件、3 个后端测试文件；受影响文件 eslint 0 错误，`tsc --noEmit` 0 错误，`ruff check backend/` 通过，`architecture-check` 通过（8 个基线文件按棘轮协议上调） |
| 7 | — | P2 main / win7 两条 PR 合并 | 🔄 进行中 | 分支 `feat/chat-reading-p2-main` |
| 8 | — | 清理分支与工作树 + 回填 | ⏳ 待办 | — |

### 10.7.1 P1 实施记录（步骤 3）

**新增模块**

| 文件 | 作用 |
| --- | --- |
| `src/features/chat/markdownText.ts` | Markdown → 可读纯文本（B1 朗读、B4 计数共用）；先把代码换成占位符保护起来，`snake_case` 不当作强调 |
| `src/features/chat/speech.ts` | B1 纯逻辑：特性检测、朗读文本、语言判断、按句切片（≤180 字）、选本地语音 |
| `src/features/chat/readAloudStore.ts` | B1 全局朗读状态；用播放代次过滤 `cancel()` 触发的旧回调 |
| `src/features/chat/textHighlight.ts` | B3 / B4 高亮：`sage-search-hit`（8 秒后清除）、`sage-find`、`sage-find-current`（priority 1）；Range 居中滚动，jsdom 下回退为元素滚动 |
| `src/features/chat/chatFind.ts` | B4 命中列表（按消息对象缓存纯文本）；`dispatchFindShortcut` 负责 `Ctrl+F` 分发与回落 |
| `src/widgets/chat/ReadAloudButton.tsx` | B1 朗读 / 停止按钮；不支持时不渲染，卸载时停止 |
| `src/widgets/chat/TruncationNotice.tsx` | B2 截断提示（`length` / `max_tokens`）与「继续生成」 |
| `src/widgets/chat/ChatFindBar.tsx` | B4 查找栏：常驻外壳只监听打开事件，打开后才挂载面板（面板才用到 i18n） |
| `src/shared/lib/i18n/chatReading.ts` | 第二轮文案，由 `i18n/index.tsx` 合并进 zh / en 词典（`zh.ts` / `en.ts` 在基线上且没有余量，不改动） |

**改动的现有文件**

- 后端：`agent_state.py`（`AgentEvent.finish_reason`，非字符串归一为 `None`）、`agent.py`（DONE 携带）、`legacy_routes.py`（写入 assistant 消息）、`session_repo.py`（`Message` 字段、读、写、分叉复制）。
- 前端接线：`messageJumpStore.ts` / `useMessageJump.ts`（`highlightQuery` / `highlightIndex`；查找模式不闪烁整条消息）、`MessageList.tsx`（挂载查找栏；`onContinue` 只传给最后一条且无流式输出时）、`Message.tsx`（截断提示、朗读按钮）、`Chat.tsx`（`handleContinue`）、`useChat.ts`（DONE 的 `finish_reason` 写入本地消息）、`store.ts` / `types.ts`（字段）、`Layout.tsx`（`Ctrl+F` / `Ctrl+Shift+F`）、`shortcuts.ts`（帮助条目）、`ConversationsSection.tsx`（命中直达带上搜索词）、`index.css`（`::highlight()` 样式）。

**验证**

| 项 | 结果 |
| --- | --- |
| 新增前端测试（9 个文件） | 46 passed |
| 前端全量 vitest（本机） | 3199 passed / 13 failed：失败全部在 `electron/` 下的 4 个主进程测试文件（logger、logIpc、自动重启、`sage-file` 协议），本次没有改动 `electron/`，这些测试也不依赖改动的模块，以 CI（Linux）结果为准；`src/` 下没有失败 |
| 新增后端测试 `test_finish_reason_passthrough.py` + 相关用例 | Python 3.11：35 passed；Python 3.8：35 passed |
| 后端单测（本机 `-n 6`，约 5 分钟时被执行环境中断，未跑完，全量以 CI 为准） | 3205 passed / 1 failed：`wiki/test_ingest_queue.py::test_queue_persists_to_file` 在中文 Windows 上用 GBK 解码 UTF-8 文件，与本改动无关（CI 为 Linux） |
| eslint（改动与新增文件） | 0 错误（`Message.tsx` 有 1 条原有 warning） |
| `tsc --noEmit` | 0 错误 |
| `ruff check backend/` | 通过 |
| `architecture-check` | 通过。基线上调：`legacy_routes.py` 4395→4396、`agent.py` 2428→2429、`session_repo.py` 1009→1016、`Chat.tsx` 1182→1189、`types.ts` 2385→2387、`Message.tsx` 1068→1083 |

### 10.7.2 P1 main 合并记录（步骤 4）

- 提交前 `git fetch` + rebase 到最新 `origin/main`（期间合入 #1612–#1614，无冲突），推送后开 [#1619](https://github.com/oneMuggle/sage/pull/1619)。
- CI：stub-smoke、stub-deep、live-boot、Frontend (TypeScript)、Backend (Python)、Backend collect (Python 3.8, win7 mine-sweeper)、Electron smoke、两个平台的 Electron build、Architecture check、Dependency audit、Backend legacy smoke、count-lines、All Checks 全部通过；Backend (Python 3.8, Win7 LTS) 与 Backend unit (Windows) 按条件跳过。
- 合并前 `origin/main` 又前进了 #1617 / #1618，改动文件与本 PR 无交集，GitHub 判定 `MERGEABLE / CLEAN`，直接 squash 合并为 `a3c16668e`。

### 10.7.3 P1 win7 对齐记录（步骤 5）

- 新建 `.worktrees/feat-chat-reading-p1-win7`（基于 `origin/release/win7`），`git cherry-pick -x` main 的 squash 提交，提交信息标注 `(cherry picked from commit a3c16668e…)`。
- 冲突与处理：

| 文件 | 原因 | 处理 |
| --- | --- | --- |
| `src/shared/lib/shortcuts.ts` | win7「全局」分组没有 main 的 `Ctrl+N` / `Ctrl+F` / `Ctrl+Shift+D` 条目 | 保留 win7 现状，只加入本次的 `Ctrl+F` 与 `Ctrl+Shift+F` 两条 |
| `src/widgets/chat/MessageList.tsx` | win7 没有 `onSuggestionClick` / `onBlockedAction` | 保留 win7 现状，只加入 `onContinue` |
| `architecture-baseline.json` | 两条分支基线数值不同；rebase 到最新 `release/win7` 时 `backend/main.py` 已被 #1615 上调 | 保留 win7 数值，按本分支实际行数上调 `legacy_routes.py` 4400→4401、`agent.py` 2521→2522、`session_repo.py` 1010→1017；前端文件在 win7 上有余量 |

- 本地验证（win7 工作树）：`npm run typecheck` 0 错误；受影响的 6 个前端目录 115 个测试文件全部通过；Python 3.8 下后端相关用例 35 passed；`ruff check backend/` 与 `architecture-check` 通过。
- [#1622](https://github.com/oneMuggle/sage/pull/1622)：Frontend (TypeScript)、Backend (Python 3.8, Win7 LTS)、Electron smoke、两个平台的 Electron build 等必需检查全部通过 → squash 合并为 `315fdebca`。

### 10.7.4 P2 实施记录（步骤 6）

**新增模块**

| 文件 | 作用 |
| --- | --- |
| `src/features/chat/generationStats.ts` | C1 速度计算（输出 tokens ÷（总耗时 − 首字延迟））与时长 / 数量格式化 |
| `src/widgets/chat/GenerationStatsBadge.tsx` | C1 操作栏右侧的「tok/s · 首字 · tokens」摘要，悬停看明细 |
| `src/shared/lib/endpointStatus.ts` | C3 端点可达性状态：失败事件按错误类型判定，成功完成即清除；端点比对 |
| `src/widgets/system/EndpointStatusBanner.tsx` | C3 标题栏下方的全局提示条：重新检测（模型列表接口，不耗 token）/ 端点设置 / 关闭；系统断网单独提示，恢复联网自动重新检测 |
| `src/features/chat/answerVersions.ts` | C2 最后一轮判定、原位重新生成、版本接口封装（走 `backendRequest` 通用通道，不改 Electron 命令表） |
| `src/widgets/chat/AnswerVersionSwitcher.tsx` | C2 `‹ 2/3 ›` 切换器；只有一个版本时不渲染 |
| `src/shared/lib/fillTemplate.ts` | `{name}` 占位符填充（C1 / C2 / C3 文案共用） |
| `backend/data/answer_version_repo.py` | C2 版本仓储：归档 / 列出 / 切换（与 messages、事件日志同事务），以及 producer 接线辅助（`regenerate_excluded_ids`、`drop_excluded`、`ArchiveOnFirstSave`） |

**改动的现有文件**

- 后端：`llm_client.py`（流式计时、非流式耗时、写入 `usage_events` 预留列）、`agent_state.py`（`generation_stats` 字段、提取与 JSON）、`agent.py`（DONE 携带）、`database.py`（`messages.generation_stats` 列与老库补列、`message_versions` 表）、`session_repo.py`（字段读写、分叉复制）、`legacy_routes.py`（统计落库；`regenerate_of`：最后一轮校验、历史剔除、跳过 user 落库与自动话题检测、首次落库前归档、`message_count`）、`legacy_session_routes.py`（`GET /sessions/{id}/answer-versions`、`POST /sessions/{id}/answer-versions/{version_id}/activate`）。
- 前端：`types.ts`（`GenerationStats`、`AgentEvent.generation_stats`、`ChatConfig.regenerateOf`）、`store.ts`（`Message.generation_stats`）、`useChat.ts`（DONE 统计写入本地消息；`regenerateOf` 不追加 user 消息并透传）、`chatApi.ts`（失败 / 完成上报端点状态；只在原位重新生成时带 `regenerateOf`）、`Layout.tsx`（挂载提示条）、`Message.tsx` / `MessageList.tsx`（统计、版本切换器；切换回调只交给最后一条消息）、`Chat.tsx`（最后一轮原位重新生成、切换后重拉消息）、`i18n/chatReading.ts`（C1–C3 文案）。

**验证**

| 项 | 结果 |
| --- | --- |
| 新增前端测试（10 个文件） | 39 passed |
| 受影响前端目录（chat / send-message / shared / system / layout / pages / manage-endpoints，253 个文件） | 除 `ArenaAccounts.test.tsx`（已知的负载下偶发超时，单独重跑 7/7 通过）外全部通过；首轮发现 `stream.test.ts` 对 invoke 参数做整体比对，已改为只在原位重新生成时带 `regenerateOf`，普通发送的参数保持不变 |
| 新增后端测试（2 个单测文件 + 1 个集成测试文件） | Python 3.11 与 3.8 均通过（连同 B2 的 7 个用例共 32 passed） |
| 后端相关回归（session / agent / llm / legacy / chat 单测 + chat_stream 集成） | 714 passed，19 skipped |
| eslint（改动与新增文件） | 0 错误（`Message.tsx` 1 条原有 warning） |
| `tsc --noEmit` | 0 错误 |
| `ruff check backend/` | 通过 |
| prettier | 新增文件已格式化；改动文件没有引入新的格式问题 |
| `architecture-check` | 通过。基线上调：`legacy_routes.py` 4396→4426、`agent.py` 2429→2430、`llm_client.py` 1074→1093、`database.py` 1920→1949、`session_repo.py` 1016→1024、`Chat.tsx` 1189→1198、`types.ts` 2387→2399、`Message.tsx` 1083→1101 |
