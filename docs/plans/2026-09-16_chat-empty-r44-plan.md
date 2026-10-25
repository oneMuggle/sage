# 聊天空态引导优化（第四十四轮批次 A）实施计划

> 日期: 2026-09-16 · 分支: `feat/chat-empty-r44` · 基于 main @ 2a644a1f
> 来源: 差距分析 D6 前端报告——"聊天区空状态仅两行文字，无建议
> 提示词、无能力引导"。与并发车道零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 实施

`MessageList.tsx` 空态增强：`messages.length === 0` 时在欢迎文案
下方渲染 3–4 条建议提示词按钮（复用 Welcome 的
`defaultRecommendations` 数据源），点击后将 prompt 文本通过
`onSuggestionClick` 回调传给 Chat.tsx → ChatInput 预填输入框。

- `MessageList` 新增 `onSuggestionClick?: (prompt: string) => void` prop
- `Chat.tsx` 传入回调 → `setValue`（通过 `injectedDraft` 通道或
  `handleSendMessage` 预填）

## 测试

- 空态建议按钮渲染 + 点击回调。既有 197 例回归。
