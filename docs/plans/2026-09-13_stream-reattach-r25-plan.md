# 流重接与消息对账（第二十五轮批次 A）实施计划

> 日期: 2026-09-13 · 分支: `feat/stream-reattach-r25` · 基于 main @ f512adfb
> 来源: 第二十一轮差距分析 D4 [P1] + D5 [P1]。与并发车道
> （search-fts / empty-response-guard / word-h4h5 / win-path）零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 背景（证据）

- renderer 重载（升级/崩溃恢复）后长任务输出全部丢失：后端可能仍在跑
  且结果落库，但 UI 不回流，用户只能重发（重新烧 token）。
- 恢复基建其实早已就位，缺的只是"最后一公里"：
  - `BroadcastQueue.subscribe()` 会把 attach 之前缓冲的事件**重放**给
    首个 subscriber（chat_stream_registry.py:68-76，注释明写"保持重连
    行为"）；
  - Electron main 的 `listen('chat-stream-{streamId}')` relay 直接按
    streamId attach 既有流（main.ts I2 注释）；
  - `ChatStreamRegistry.create` 有同会话 busy 仲裁，409 响应体就带
    `active_stream_id`。
- D5: 网关（gateway/base.py 写库）与 scheduler 写库不经渲染进程，
  开着会话看不到新消息；流结束后无对账。

## 实施

### D4 后端（S）

- `StreamRegistry.find_active_by_session(session_id)`：与 create 的
  busy 仲裁同口径（pending/running 且未挂起），无活跃返回 None。
- `GET /chat/stream/active?session_id=`（注册在 `/{stream_id}` attach
  之前）：返回 `{"streamId": uuid | null}`。

### D4 前端（M）

- `chatApi.activeStream(sessionId)`：查询活跃流。
- `chatApi.listenStream(streamId, handlers)`：只监听既有流（不
  create），独立 180s 看门狗 + done/failed 终态化，复用 NDJSON 通道。
- `useChat.reattachActiveStream(sid)`：
  - 模块级 `reattachedSids` 去重（StrictMode 双挂载/重复调用只接一次
    —— Electron main 对重复 listen 早退，双 handler 会重复累积内容）；
  - 重建 assistant 占位 + markStreamActive（interrupt 经 streamId 命中
    真实 agent）；
  - 精简事件面：content/reasoning 增量、done/failed 终态、审批/提问
    转发、session_updated；工具/编排等复杂事件降级为 streaming meta
    文案（重放机制保证内容完整，编排任务板详见"本批不做"）。
- `Chat.tsx`：挂载/切会话时 `reattachActiveStream(currentSessionId)`。

### D5 对账（S）

- `useChat` 流结束（onDone）后 `loadMessages(sid)` —— get_messages
  每次直查无缓存，以服务端为准消除"开着会话看不到外部写库新消息"
  的窗口；reattach 的 finish 同样对账。

## 测试

- `test_stream_active_query` 5 例：registry 命中/跳过终态与挂起/跨
  会话隔离 + 路由信封（直调 + TestClient）。
- 前端：Chat 页测试 mock 补 `reattachActiveStream`，28 文件 156 例
  全过；tsc/eslint 全绿。

## 本批不做（后续候选）

- reattach 的编排任务板完整恢复（task_plan/task_status 等重建逻辑，
  需事件处理器抽取重构）
- 持久化离线发送队列（L）
- WebSocket 推送（PARITY 规划项）
