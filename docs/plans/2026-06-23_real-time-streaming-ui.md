# 实时流式 UI 优化：思考过程 + 工具调用 + Agent 编排

## 背景与目标

用户在使用 Sage 聊天时（如"帮我分析一下 /home/fz/project 有哪些项目"），
看不到思考过程、实时工具调用和 agent 编排信息，只能看到最终结果。
工具调用在结果之后才展示，体验不透明。

**目标**：让用户在流式响应过程中实时看到：
1. LLM 的思考/推理过程
2. 工具调用的逐步执行（调用 + 结果）
3. Agent 编排的迭代进度

## 问题定位

### P0：工具调用只在流结束后才显示

**根因**：`useChat.ts` 的 `derivedMessages` 只替换 `content` 和 `reasoning_content`，
不包含 `tool_calls`。`streamingToolCalls[]` 在 `acting`/`observing` 事件时累积到本地数组，
但只在 `finishStream()` 时才写回 store。

### P1：思考面板默认折叠

**根因**：`Message.tsx` 的 `ThinkingPanel` 用 `useState(false)` 永远默认折叠，
即使 reasoning 内容正在实时累积。

### P2：Agent 编排信息几乎不可见

**根因**：`ActiveAgentIndicator` 只有一行文字，没有迭代轮次、没有 agent 切换时间线。

## 技术方案

### P0：实时工具调用

**改动文件**：`src/features/send-message/useChat.ts`

**方案**：
1. 把 `streamingToolCalls` 从普通数组改为 `useState`，使其参与 React 渲染
2. 在 `derivedMessages` 中把实时 `tool_calls` 注入到 streaming message
3. `acting` 事件到达时立即更新 state → UI 渲染新工具调用
4. `observing` 事件到达时更新对应工具调用的 result → UI 渲染结果

```typescript
// 从 const streamingToolCalls: ToolCall[] = [] 改为：
const [streamingToolCalls, setStreamingToolCalls] = useState<ToolCall[]>([]);

// derivedMessages 加入 tool_calls：
const derivedMessages = useMemo<Message[]>(() => {
  if (!streaming) return messages;
  return messages.map((m) =>
    m.id === streaming.messageId
      ? {
          ...m,
          content: streaming.content,
          reasoning_content: streaming.reasoning || undefined,
          tool_calls: streamingToolCalls.length > 0 ? streamingToolCalls : undefined,
        }
      : m,
  );
}, [messages, streaming, streamingToolCalls]);
```

### P1：ThinkingPanel 自动展开

**改动文件**：`src/widgets/chat/Message.tsx`

**方案**：
- 增加 `isStreaming` prop，当消息正在流式且 reasoning 存在时自动展开
- 或者改为 reasoning 存在时默认展开（`useState(true)`）

### P2：增强 Agent 编排指示器

**改动文件**：`src/widgets/chat/ActiveAgentIndicator.tsx`

**方案**：
- 从 `useChat` 导出 `iteration`（当前 ReAct 轮次）
- 显示 `"🤖 第 2 轮 · 编码助手 · 🔧 调工具 Bash…"` 格式
- 保留 agent 切换历史（最近 3 个）

## 实施步骤

- [x] 步骤 1：`useChat.ts` — streamingToolCalls 改为 state + derivedMessages 注入
- [x] 步骤 2：`useChat.ts` — acting/observing 事件处理更新 state
- [x] 步骤 3：`Message.tsx` — ThinkingPanel 流式时自动展开
- [x] 步骤 4：`useChat.ts` — 导出 iteration / streamingMessageId / streamingState 字段
- [x] 步骤 5：`ActiveAgentIndicator.tsx` — 增强显示迭代轮次 + 流式阶段
- [ ] 步骤 6：本地验证（npm run dev + electron:dev）
- [ ] 步骤 7：编写测试
- [x] 步骤 8：更新计划文档标记完成

## 风险评估

- **性能**：`streamingToolCalls` 频繁 setState 可能引起额外渲染。
  缓解：工具调用事件频率低（通常 <10 次/对话），影响可忽略。
- **兼容性**：`finishStream()` 需要改用 `streamingToolCalls` 的最新值。
  缓解：使用 ref 镜像同步最新值（类似 `streamingContentRef` 模式）。
- **测试**：需要更新 `useChat.test.ts` 以覆盖新的实时行为。
