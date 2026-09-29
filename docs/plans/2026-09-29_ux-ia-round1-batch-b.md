# UX-IA Round 1 批次 B：聊天区会话级提示按优先级合并

> 日期：2026-09-29 · 基线：`origin/main` @ `fbe617925`
> 工作分支：`feat/ux-ia-p1b-main`（worktree `.worktrees/ux-ia-p1b-main`）→ cherry-pick `release/win7`
> 总方案：`docs/plans/2026-09-29_ux-ia-round1.md`（#1839，§1.2「状态横幅合并」、§4 一期）

---

## 0. 结论速览

| 问题 | 结论 |
| --- | --- |
| 差距 | 聊天区顶部三类会话级提示（对话出错 / 运行中断 / 话题切换）各自独立渲染，最坏同时堆叠 3 条，挤压消息区 |
| 对标 | ChatGPT / Claude：同一时刻只以一条提示打扰用户，其余可展开查看 |
| 本批交付 | `ChatNoticeStack`：按优先级（错误 > 中断 > 话题切换）只展示最重要的一条，其余折叠为「另有 N 条提示」；内联错误条抽出为 `ChatInlineError`（`Chat.tsx` 净减 3 行、JSX 更扁平） |
| 行为兼容 | 单条提示时渲染与改前一致；各提示自身的交互（重试 / 关闭 / 重发 / 忽略 / 恢复上下文）与 testid 不变；R17-D「只渲染归属当前会话的错误」语义不变 |

---

## 1. 现状与范围校正

总方案 §1.2 曾列出 5 种状态横幅。复核源码后校正：

| 组件 | 位置 | 性质 | 本批处理 |
| --- | --- | --- | --- |
| 内联错误条（R17-D） | `src/pages/Chat.tsx` 顶部 | 会话级横幅 | 合并 |
| `InterruptedRunBanner` | `Chat.tsx` 顶部 | 会话级横幅 | 合并 |
| `TopicShiftBanner` | `Chat.tsx` 顶部 | 会话级横幅（10s 自动消失） | 合并 |
| `CompactBanner` / `TruncationNotice` | `Message.tsx` 消息流内 | 内联于消息，随消息滚动 | 不动（非横幅） |
| `ContextPressureBadge` | 输入框上方 | 徽章 | 不动（批次 C 并入 Composer 工具条） |
| 配置缺失警告 `config-warning` | 输入框上方 | 阻断型提示 | 不动（与输入禁用联动） |

## 2. 设计

- `src/widgets/chat/ChatNoticeStack.tsx`：输入 `notices: (ChatNotice | false | null | undefined)[]`，过滤后按 `priority` 降序；折叠态只渲染首条 + 切换按钮（`data-testid="chat-notice-toggle"`、`aria-expanded`）；展开态按优先级渲染全部。`CHAT_NOTICE_PRIORITY = { error: 30, interrupted: 20, topicShift: 10 }`。
- `src/widgets/chat/ChatInlineError.tsx`：原内联 JSX 原样抽出（testid `chat-inline-error` / `chat-error-retry` 保留）。
- `src/pages/Chat.tsx`：三段条件渲染替换为一个 `<ChatNoticeStack notices={[...]}/>`。

## 3. 验证矩阵

| 类型 | 命令 | 结果（main） |
| --- | --- | --- |
| 单测 | `vitest run src/widgets/chat src/pages` | 127 files 全绿（含新增 `ChatNoticeStack.test.tsx` 5 例） |
| 类型 | `tsc --noEmit` | 0 错误 |
| lint | eslint（改动文件） | 0 问题 |

## 4. 交付号

| 分支 | PR | squash SHA |
| --- | --- | --- |
| main | 待回填 | 待回填 |
| release/win7 | 待回填 | 待回填 |
