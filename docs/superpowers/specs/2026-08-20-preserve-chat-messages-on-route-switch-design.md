# 页面切换期间保留聊天消息设计

## 背景与目标

发送消息后，Chat 页面会先在前端 Zustand store 中加入用户消息和助手占位消息，LLM 回复通过独立的流式 store 增量更新。用户在流式处理中切换到设置等其他页面时，Chat 组件卸载；重新进入 Chat 页面会触发历史消息加载。由于后端持久化可能尚未完成，旧的历史消息列表会覆盖前端尚未持久化的消息，导致用户消息和 LLM 回复消失。

目标是保证在流式请求进行期间离开并返回 Chat 页面，用户消息、助手占位消息以及最终助手回复都能保留，同时不改变正常历史消息加载和后端已持久化消息的优先级。

## 涉及的文件与模块

- `src/shared/lib/store.ts`
  - 会话消息 Zustand store
  - `loadMessages` 历史消息加载入口
- `src/features/send-message/useChat.ts`
  - 创建本地用户/助手消息
  - 流结束时写回助手最终内容
- `src/features/send-message/chatStreamStore.ts`
  - 跨页面保存进行中的流式状态
- `src/features/send-message/__tests__/useChat.test.ts`
  - 发送消息和流式完成测试
- `src/features/send-message/__tests__/useChat.stream-survives-unmount.test.tsx`
  - 跨组件卸载的流式状态测试

## 技术方案

### 消息合并策略

`loadMessages(sessionId)` 获取后端消息后，不再无条件执行 `set({ messages })`。加载过程读取当前 store 中属于目标会话的本地消息，并按消息 ID 合并：

1. 后端返回的消息作为基础集合；
2. 对当前会话中本地存在、但后端返回中尚不存在的消息予以保留；
3. 同 ID 消息以后端消息为准，确保后端持久化结果可以更新本地占位内容；
4. 其他会话的消息不混入当前消息列表；
5. 合并后的列表保留后端返回顺序，再追加本地缺失消息，并保持本地消息原有顺序，避免切回页面时消息顺序发生非预期变化。

该策略同时覆盖用户消息和助手占位消息。流式最终事件到达后，现有 `updateMessage` 会更新对应助手消息；如果后端已经返回同 ID 的最终消息，则以现有 store 更新逻辑继续工作。

### 并发与边界

- 只保护当前 `sessionId` 的本地消息，避免会话切换时串入其他会话。
- 不改变 `isLoading` 和错误处理语义。
- 不在路由组件卸载时取消 chat stream。
- 不新增后端 API 或数据库字段。
- 保留现有 `chatStreamStore` 作为流式状态的单一数据源。

## 实施步骤

- [x] 为 `loadMessages` 增加“后端历史消息 + 未持久化本地消息”的回归测试
- [x] 实现按消息 ID 的不可变合并逻辑
- [x] 增加页面卸载/重新加载后流式回复仍能写回的测试覆盖
- [x] 运行相关 Vitest 测试、TypeScript 检查和前端构建
- [x] 运行代码审查并根据结果修正

## 风险评估与依赖

- 风险：后端消息时间戳与本地乐观消息时间戳可能不同。本方案不重新按时间戳排序，而是保留后端输入顺序并稳定追加本地缺失消息，避免改变后端历史的既有顺序。
- 风险：重复加载消息可能暂时保留已失败的本地占位消息。流错误路径仍会由 `finishStream` 写入明确错误内容，因此不应留下“思考中”状态。
- 依赖：现有 `useChatStreamStore` 的 module singleton 行为，以及 `useChat` 的 `finishStream` 回写逻辑。
- 不在本次范围内：重构路由布局、改变后端持久化时机、修改 Electron IPC 流协议。
