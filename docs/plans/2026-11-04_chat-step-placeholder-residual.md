# 会话气泡占位残留修复（思考中… / 观察结果…）

- 日期：2026-11-04
- 分支：`fix/chat-step-placeholder-residual`（基于 `origin/main`）
- 用户报告：win7 最新安装包，**非流式**模式下
  1. 多步 run 结束后，LLM 的回复被替换成「🤔 思考中…」，切换会话再切回来才显示正确内容；
  2. 执行工具时出现「👀 观察结果…」，执行到下一个命令时也不消失。

## 背景与根因

前端把「发送占位 → 流式覆盖 → 逐步（step-by-step）拼接」拆成两套状态：

- `useStore.messages`：持久化消息（含用户消息与服务端回读行）；
- `useChatStreamStore`：按会话的流式 overlay（`streaming`、`streamingToolCalls`、`completedSteps`）。

`step_done` 事件到达时（`src/features/send-message/useChat.ts`）：

1. 把当前 streaming 快照压进 `completedSteps`；
2. `finalizeStep` 把 `streaming.messageId` 换成**新的随机 uuid**；
3. 重置 `streaming.content = THINKING_PLACEHOLDER`。

问题在于第 2 步：新的 uuid **从未被 `addMessage` 写入 `useStore.messages`**。因此：

- **症状 1**：`finishStream` 的 `updateMessage(assistantId, …)` / `replaceMessageId(assistantId, 服务端 id)`
  全部对不存在的行空操作（`messages` 里只有最初那条 uuid 的占位行）；
  `loadMessages` 的 `mergeLoadedMessages` 又不识别占位哨兵，于是最初那条
  「🤔 思考中…」行原样留在 `messages` 末尾。切换会话会用服务端数据整体覆盖
  `messages`，所以切走再切回就"好"了。
- **症状 2**：`step_done` 里 `stepContent` 只过滤了 `THINKING_PLACEHOLDER`；
  非流式模式下该步没有 `content_delta`，`streaming.content` 停留在最后一个中间态
  文案（通常是「👀 观察结果…」），于是它被当作已完成步骤的正文压进
  `completedSteps`，并在下一条命令执行期间一直显示。

后端侧证实：非流式时 `STEP_DONE` 之前没有 content delta，
`legacy_routes.py` 的 `step_content = "".join(streamed_partial_parts)` 为空串，
占位文案完全来自前端 overlay。

## 技术方案

### Fix A：`step_done` 把步骤实体化进 `useStore.messages`

- 在 `step_done` 中：
  - 用 `isIntermediatePlaceholderText()` 过滤**所有**中间态占位文案
    （🤔 思考中… / 🔧 行动中… / 🔧 调工具 xxx… / 👀 观察结果… / ❌ 失败），不再只匹配 `THINKING_PLACEHOLDER`；
  - `updateMessage(assistantId, { content, reasoning_content, tool_calls, step_index })`
    把当前步骤写进 store（取代"只进 `completedSteps`"）；
  - `addMessage({ id: nextAssistantId, content: THINKING_PLACEHOLDER, … })`
    为下一步落地占位行，保证后续 `updateMessage` / `replaceMessageId` 有行可命中。
- `derivedMessages` 增加按 **id** 的去重：`completedSteps` 中已被实体化进
  `messages` 的条目不再重复拼接（保留按 `step_index` 去重作为服务端回读后的兜底）。

### Fix B：`finishStream` 兜底清扫残留占位行

- 跟踪本轮所有乐观 assistant id（`optimisticAssistantIds`）。
- `finishStream` 在 `replaceMessageId` 之后、`loadMessages` 之前，删除仍未产出
  真实内容的占位行（`content` 仍是中间态占位文案的行）。
- 只删占位行：有正文 / reasoning / tool_calls 的步骤行保留，等待 `loadMessages`
  正常对账。

### 占位文案单一真相源

- `src/shared/lib/agentStateMapping.ts` 导出占位常量与
  `isIntermediatePlaceholderText()`；`agentStateToText()` 复用同一批常量。
- `thinkingPlaceholder.ts` 的 `THINKING_PLACEHOLDER` 改为 re-export 同一常量，
  避免两处字符串漂移。

## 涉及文件

| 文件 | 变更 |
| --- | --- |
| `src/shared/lib/agentStateMapping.ts` | 新增占位常量 + `isIntermediatePlaceholderText()`；`agentStateToText` 复用 |
| `src/features/send-message/thinkingPlaceholder.ts` | `THINKING_PLACEHOLDER` 改为从 `agentStateMapping` re-export |
| `src/features/send-message/useChat.ts` | `derivedMessages` 按 id 去重；`step_done` 实体化 + 添加下一步占位行；`finishStream` 清扫；`removeMessage` 依赖 |
| `src/features/send-message/__tests__/useChat.stepByStep.test.ts` | 新增 3 个回归测试 |

后端无需改动（`legacy_routes.py` 已正确落库空 content 的步骤行）。

## 实施步骤

- [x] 步骤 1：`agentStateMapping.ts` 抽出占位常量与 `isIntermediatePlaceholderText()`
- [x] 步骤 2：`thinkingPlaceholder.ts` re-export 共享常量
- [x] 步骤 3：`useChat.ts` 的 `derivedMessages` 按 id 去重
- [x] 步骤 4：`useChat.ts` 的 `step_done` 实体化步骤 + 添加下一步占位行
- [x] 步骤 5：`useChat.ts` 的 `finishStream` 清扫残留占位行（Fix B）
- [x] 步骤 6：补回归测试（非流式多步：步骤正文无占位 / 结束后无占位行 / 无终稿时占位行被清扫）
- [x] 步骤 7：worktree 内跑 vitest + tsc，确认无回归（另补 `architecture-baseline.json` 棘轮 1047 → 1094）

## 风险评估与依赖

- **风险 1：双渲染**。实体化后同一步骤同时存在于 `messages` 与 `completedSteps`。
  已用 id 去重 + 既有 `step_index` 去重双层防护。
- **风险 2：后台会话**。`addMessage` 有 session 守卫，后台会话不会写入本地 store；
  `finishStream` 的清扫按 id 查不到行即 no-op，切回会话时由 `loadMessages` 拉取
  服务端数据，行为与修复前一致。
- **风险 3：真实回答恰好等于占位文案**。匹配为整体精确相等（`🔧 调工具 ` 前缀 +
  `…` 后缀为动态分支），模型正文恰好逐字等于占位文案的概率可忽略。
- **依赖**：`useStore.removeMessage` 已存在（`store.ts:409`），仅需在 `useChat` 解构并加入
  `sendMessage` 的 useCallback 依赖。
- **分支同步**：修复在 `main` 完成后按项目策略 cherry-pick 到 `release/win7`。
  本次改动为纯前端 TS，无 pydantic / py38 差异。
