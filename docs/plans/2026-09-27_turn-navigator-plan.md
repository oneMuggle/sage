# 对标批次：U1 轮次导航器（ConversationTurnNavigator 对标）

日期：2026-09-27 ｜ 关联：`docs/plans/2026-09-24_zcode-parity-gap-analysis.md`（U1 行）
参照：ZCode `ConversationTurnNavigator.tsx`——多轮对话间快速跳转的导航控件

## 0. 结论速览

sage 已有「消息定位」全部基建（A1 全局跳转通道 `messageJumpStore`、A2 大纲、
A3 搜索命中直达），缺的只是**轮次粒度**的导航入口。本批实现：

- 新 hook `useConversationTurns(sessionId)`：从 messages 提取轮次列表——
  每条 `role === 'user'` 的普通消息（subtype 为空）即一轮的开始；
  条目 = { 轮次序号（1 起）、起始消息 ID、用户输入预览（截断 48 字符） }。
- RightPanel「目录」上方新增「轮次」分组（`TurnList` 组件，样式对齐
  `ConversationOutline`）：点击条目 → `requestMessageJump({ messageId })`
  滚动到该轮 user 消息并闪烁。
- 数据为纯前端 memo 派生（messages 已在 store），零后端改动。

## 1. 为什么挂在 RightPanel 而不是独立浮层

- ZCode 的 TurnNavigator 是对话流内浮层；sage 的 RightPanel 已是导航面板
  的事实挂载点（目录/任务树/变更都在），加分组零布局改动、与大纲互补
  （大纲按标题、轮次按用户输入）。
- 独立浮层涉及 MessageList 定位与 z-index 交互，成本高收益同——列为
  后续可选演进。

## 2. 实现细节

### 2.1 `useConversationTurns`（features/chat/useConversationTurns.ts）

```ts
export interface TurnItem {
  index: number;        // 1 起的轮次序号
  messageId: string;    // 该轮 user 消息 ID（跳转目标）
  preview: string;      // 用户输入前 48 字符（换行折叠为空格）
}
```

- 过滤规则：`role === 'user' && !subtype && session_id 匹配`。
  tool/段切换 marker（subtype='topic_separator'）不算轮次起点。
- 长会话性能：memo 派生，单次 O(n)（与大纲同量级，大纲已验证可承受）。

### 2.2 `TurnList` 组件（widgets/chat/TurnList.tsx）

- props：`items: TurnItem[]`、`onSelect(item)`；样式复用 ConversationOutline
  的行样式（px-3/py-1.5/truncate/hover），条目左侧显示轮次序号徽标。
- 空状态复用大纲的友好提示（「对话开始后这里会列出每一轮提问」）。

### 2.3 RightPanel 接线

- `useConversationTurns(sessionId)` 与大纲并排取数；
- 目录分组上方渲染「轮次」分组（`data-testid="turn-list"`），
  onSelect → `requestMessageJump({ messageId: item.messageId })`。

## 3. 测试

- `useConversationTurns`：混合消息流（user/assistant/tool/topic_separator）
  只出普通 user 行、序号 1 起、preview 截断。
- `TurnList` 渲染：条目数/序号/预览/点击回调。
- RightPanel 集成：轮次分组出现、点击触发 requestMessageJump
  （mock store 断言 pending.messageId）。

## 4. 验收

typecheck 0；触碰点 vitest 全绿；全量 vitest 无新增失败；
gap-analysis U1 行 → ✅（附 PR 号）。
