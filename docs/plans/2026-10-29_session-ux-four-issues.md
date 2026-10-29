# 2026-10-29 会话 UX 四项修复

> 状态：**完成**（PR #2646 CI 全绿，等待人工合并）
> 分支：`fix/session-ux-four-issues`（已 rebase 到 `origin/main` e5f164677）
> 触发：用户在实际使用过程中发现 4 个 UX 问题，集中在会话失败后的可见性、折叠机制、轮次计数和滚动按钮位置。

## 1. 背景与目标

用户反馈的 4 个问题：

1. **失败横幅缺失**：会话失败后切换到该会话，失败原因只能从侧栏图标的 hover 提示看到，聊天区顶部没有醒目的横幅。
2. **折叠机制不透明**：有的会话失败或成功后，消息自动收纳，需要点击才能展开，用户不清楚触发原因。
3. **轮次计数重置**：会话失败后"继续"，ReAct 轮次从 0 重新计数，而不是接着上次的进度。
4. **滚动按钮位置错误**："跳转到最新"按钮嵌在 `ActiveAgentIndicator` 下方（文档流内），应改为会话区底部居中的浮动按钮（`sticky`），避免遮挡。

## 2. 涉及的文件与模块

| 文件 | 职责 | 改动 |
|---|---|---|
| `src/widgets/chat/SessionFailedBanner.tsx` | 新建：失败原因横幅组件 | 新增 |
| `src/widgets/chat/ChatNoticeStack.tsx` | 会话级通知栈（优先级 + 折叠） | 新增 `sessionFailed` 优先级 |
| `src/widgets/chat/TurnGroup.tsx` | 对话轮次折叠组件 | 加 `useEffect` 同步 `defaultExpanded` 到本地态 |
| `src/features/send-message/chatStreamStore.ts` | 流式状态存储 | 新增 `iterationOffset` 字段；`clearStream` 累加 |
| `src/pages/Chat.tsx` | 聊天页布局 | 接入失败横幅；滚动按钮迁移到 `scrollRef` 内 `sticky` |
| `src/widgets/chat/ActiveAgentIndicator.tsx` | "第 N 轮" 显示 | 接收 `iterationOffset` 并叠加 |

## 3. 技术方案

### 3.1 失败横幅

**根因**：失败原因（`session.last_error`）目前只在 `SessionItem` 的图标 `title` 里显示。聊天页本身对"会话失败"没有横幅。

**方案**：新建 `SessionFailedBanner` 组件，在聊天页检测到 `currentSession?.run_status === 'failed'` 且 `last_error !== INTERRUPTED_RUN_ERROR`（避免与中断横幅重复）时，作为 `ChatNoticeStack` 的一条新通知推入。

```ts
// ChatNoticeStack.tsx 新增优先级
export const CHAT_NOTICE_PRIORITY = {
  error: 30,            // 本次会话内的临时错误
  sessionFailed: 25,    // 会话级失败终态（新）
  interrupted: 20,      // INTERRUPTED_RUN_ERROR
  topicShift: 10,
};
```

**横幅内容**：红色背景 + 失败原因（经 `mapAgentErrorToText` 翻译）+ "重新发送" 按钮（复用 `retryInterruptedRun` 逻辑）。

### 3.2 折叠展开同步

**根因**：`TurnGroup` 用 `useState(defaultExpanded ?? false)` 捕获初始值，但 `defaultExpanded` 在运行中/运行后切换（`runStatus !== 'running'`）时不会触发本地 `expanded` 更新。

**方案**：加 `useEffect`：当 `defaultExpanded` 从 false 变为 true 时，把本地 `expanded` 也翻成 true（单向同步，避免手动折叠后又被覆盖）。

```ts
// TurnGroup.tsx
useEffect(() => {
  if (defaultExpanded && !expanded) setExpanded(true);
}, [defaultExpanded, expanded]);
```

### 3.3 轮次计数累加

**根因**：后端 `run_loop` 的 `iteration` 是 `for i in range(max_iterations)` 局部计数器，不落库、不跨 run 继承。前端 `chatStreamStore` 每次 `startStream` 把 `iteration` 重置为 0，`clearStream` 不保存。

**方案（前端累加）**：
1. 在 `SessionStreamSlots` 新增 `iterationOffset: number`（默认 0）。
2. `clearStream` 时读取当前 `streaming.iteration`（= 本次 run 达到的最大轮次 i），累加到 `iterationOffset`：`offset = offset + i + 1`（+1 因为步骤 0..i 共 i+1 步，下一次 label 要从 i+1 开始）。
3. `ActiveAgentIndicator` 接收 `iterationOffset`，显示 `第 {offset + iteration} 轮`。
4. 后端 `max_iterations` 预算不变（每次 run 独立），只是显示层累加。

### 3.4 滚动按钮位置

**根因**：`showScrollToBottom` 按钮在文档流里（`ActiveAgentIndicator` 下方），占布局空间并遮挡会话。

**方案**：把按钮从 `Chat.tsx` 的 `ActiveAgentIndicator` 后移出，放入 `scrollRef` 容器内（`<div ref={scrollRef}>`），使用 `sticky bottom-0` 让它悬浮在滚动区底部，不占文档流空间。

```tsx
<div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto relative">
  <MessageList ... />
  {showScrollToBottom && (
    <div className="sticky bottom-2 flex justify-center py-2 pointer-events-none">
      <button
        onClick={scrollToLatest}
        aria-label="滚动到最新消息"
        className="pointer-events-auto flex items-center justify-center w-9 h-9 rounded-full bg-bg-elevated border border-border shadow-lg hover:bg-bg-hover transition-colors"
      >
        <ChevronDown className="w-4 h-4 text-text-secondary" />
      </button>
    </div>
  )}
</div>
```

`pointer-events-none` + `pointer-events-auto`：滚动区域背景不拦点击，仅按钮可点。

## 4. 实施步骤

- [x] **步骤 1**：`chatStreamStore.ts` —— 新增 `iterationOffset` 字段；`clearStream` 累加
- [x] **步骤 2**：`ActiveAgentIndicator.tsx` —— 接收 `iterationOffset` 并叠加显示
- [x] **步骤 3**：`Chat.tsx` —— 把 `iterationOffset` 透传到 `ActiveAgentIndicator`
- [x] **步骤 4**：`TurnGroup.tsx` —— `useEffect` 同步 `defaultExpanded` 到本地态
- [x] **步骤 5**：新建 `SessionFailedBanner.tsx`
- [x] **步骤 6**：`ChatNoticeStack.tsx` —— 新增 `sessionFailed` 优先级
- [x] **步骤 7**：新建 `ChatSessionNotices.tsx`（把 Chat.tsx 的 notices 组装逻辑 + dismiss 状态抽出来）；Chat.tsx 改用 `<ChatSessionNotices>`
- [x] **步骤 8**：`Chat.tsx` —— 滚动按钮从文档流迁移到 `scrollRef` 内 `sticky`
- [x] **步骤 9**：更新 `architecture-baseline.json` 的 `chatStreamStore.ts` 条目（ratchet 协议）
- [x] **步骤 10**：`tsc --noEmit` 通过；`architecture-check.mjs` 通过；vitest 全绿（widgets/chat + send-message + pages 三套件）
- [x] **步骤 11**：code-reviewer agent 过一遍。发现 1 HIGH + 3 MEDIUM + 2 LOW：
  - HIGH：TurnGroup 的 useEffect 把 `expanded` 放依赖，导致用户手动折叠被立即撤销 → 改 `useRef` 追踪 `prevDefaultExpanded`，只响应 false→true 翻转
  - MEDIUM：dismiss 状态跨会话不重置 → 加 `useEffect` 切会话清空
  - MEDIUM：TurnGroup 展开/折叠行为无测试 → 加 `TurnGroup.expand.test.tsx`（4 用例）
  - MEDIUM：ChatSessionNotices "切会话 dismiss" 测试用两次独立 render 不反映真实场景 → 改 `rerender`
  - LOW：`formatSessionFailedMarkdown` / `formatSessionFailedJson` 无调用方 → 删
  - LOW：error retry 的 sendMessage 没传 sessionId → 统一传
- [x] **步骤 12**：tsc / tests 全绿（widgets/chat 134/664 + send-message 30/200 + pages 38/144）；提交、push、开 PR
- [x] **步骤 13**：PR #2646 首次 CI 因 merge 冲突不触发 → rebase 到 `origin/main`（解决 architecture-baseline.json 冲突：取 HEAD 的 PluginsTab 687，保留我方 chatStreamStore 847）；rebase 后 main 侧增长使该文件达 853 行 → baseline 棘轮到 853；lint 修复 2 个新测试文件的 import/order（3 errors）；CI 14 项全绿，`mergeStateStatus=CLEAN`

## 5. 风险评估与依赖

- **低风险**：所有改动都是前端 UI / 状态层，不涉及后端 API。
- **轮次累加的边界**：
  - `clearStream` 在流结束时被调用，此时 `streaming.iteration` 是最后一次收到的轮次值。如果流异常终止（如网络断开）没收到 DONE 事件，iteration 可能小于实际值 —— 显示层累加是尽力而为，不影响后端预算。
  - 切换会话时不重置 `iterationOffset`（属于会话级槽位），跨 run 累加正确。
- **滚动按钮 `sticky` 的父容器**：`scrollRef` 已有 `relative`，是合法 `sticky` 定位上下文。
- **失败横幅与中断横幅互斥**：两者都用 `INTERRUPTED_RUN_ERROR` 判定，不会重复显示。
