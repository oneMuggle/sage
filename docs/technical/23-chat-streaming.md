# 23 — Chat 流式响应端到端 (PR-6)

> 收口计划 [`docs/plans/2026-06-12_finish-designed-features.md`](../plans/2026-06-12_finish-designed-features.md) 的"缺口 B":
> 后端 `POST /api/v1/chat/stream` 已实现 NDJSON 流式协议 + 完整集成测试,
> 但 Tauri 层无 `agent_chat_stream` 命令,前端 `chatApi` 也无流式调用方法,
> 流式 UX (thinking/acting/observing 实时反馈) 无法触达用户。本章记录端到端贯通方案。

## 1. 全景

```
┌──────────┐   POST /chat/stream   ┌──────────────────┐
│ Frontend │ ────────────────────► │ Python FastAPI   │
│  (React) │   NDJSON (一行一事件)  │  SageAgent.run_  │
│          │ ◄──────────────────── │  loop()          │
└────┬─────┘                       └──────────────────┘
     │   invoke('agent_chat_stream')    │
     │   listen('chat-stream-{sid}')    │   app.emit(payload)
     ▼                                  ▼
┌──────────────────────────────────────────────┐
│ Tauri Rust                                   │
│   agent_chat_stream  →  spawn 任务           │
│     └─ PythonBackend::post_stream            │
│         └─ bytes_stream → NDJSON line stream │
└──────────────────────────────────────────────┘
```

## 2. NDJSON 协议

后端 `backend/api/legacy_routes.py:455` 的 `/chat/stream` 返回 `StreamingResponse`,
`media_type=application/x-ndjson`,每行一个 JSON 对象,无 padding。

每个事件来源: `backend.core.legacy.agent_state.AgentEvent.to_dict()`,
字段:

```python
{
  "state": "thinking" | "acting" | "observing" | "done" | "failed",
  "iteration": int,
  "content": "...",            # 可选, LLM 答案逐字到达
  "tool_call": {...},          # 可选, OpenAI 工具调用格式
  "tool_result": {...},        # 可选, tool 执行结果
  "error": "..."               # 可选, 失败时携带
}
```

## 3. Tauri 层 (`src-tauri/src/`)

### 3.1 `python.rs` — `post_stream` + `LineStream`

`PythonBackend` 新增 `post_stream<B: Serialize>(path, body) -> Result<LineStream, String>`。

实现要点 (`src-tauri/src/python.rs`) :

1. 发送 POST 请求,非 2xx 立即 `Err` 终止(不进入流)。
2. 后台 `tokio::spawn` 拉 `resp.bytes_stream()`,按 `\n` 切分 NDJSON 行,
   通过 `mpsc::channel<Result<String, String>>(32)` 推给调用方。
3. 末尾残留(无换行)的数据也作为一行推送。
4. 调用方断开(channel close)时后台 task 立即 `return`,不浪费资源。
5. 返回的 `LineStream` 是手实现的 `Stream<Item = Result<String, String>>` 包装
   `mpsc::Receiver::poll_recv`,**不**引入 `tokio-stream` crate(避免 Win7 兼容链路上
   edition2024 拉入)。

依赖 (`src-tauri/Cargo.toml`) :

- `reqwest` 加 `stream` feature (启用 `bytes_stream()`)
- `futures-util` (lock `< 0.3.35` 避免拉 edition2024 链路)
- `PythonBackend` 加 `#[derive(Clone)]` (供 `tokio::spawn` clone Arc)

### 3.2 `commands.rs` — `agent_chat_stream`

```rust
#[tauri::command]
pub async fn agent_chat_stream(
    session_id, message,
    api_key, api_url, model, max_context, temperature,
    app: AppHandle, state: State<'_, Arc<AppState>>,
) -> Result<String, String>  // 立即返回 stream_id (UUID)
```

行为:

1. 生成 `stream_id = uuid::Uuid::new_v4()`,返回给前端。
2. `tokio::spawn` 后台 task:
   - 调 `backend.post_stream("/chat/stream", &ChatRequest { ... })` 拿 `LineStream`
   - 逐行 `serde_json::from_str::<AgentEvent>`,emit 到 `chat-stream-{stream_id}`
   - `state=done|failed` 时终止;若流自然结束但后端没发 done,补发一个 done
   - 解析失败时 emit `state=observing, content=<raw line>, error=<parse err>`,
     不让一行坏 JSON 杀掉整条流
3. 前端 `listen("chat-stream-{stream_id}", cb)` 接收,多并行流互不干扰。

### 3.3 `models.rs` — AgentEvent 等结构

`AgentEvent / AgentToolCall / AgentToolCallFunction / AgentToolResult` 字段
与后端 `to_dict()` 一一对应,serde 自动 derive 即可。

## 4. 前端层 (`src/`)

### 4.1 `lib/tauriEvent.ts` — listen shim

参照 `lib/tauriInvoke.ts` 模式,集中 re-export `listen` 与 `UnlistenFn`。
当前 main (Tauri 2) 与 release/win7 (Tauri 1.6) 都从 `@tauri-apps/api/event` 导出,
路径一致;保留 shim 是为了未来升级时集中调整。

### 4.2 `lib/api.ts` — `chatApi.chatStream`

签名:

```ts
chatStream(
  sessionId, message,
  handlers: {
    onEvent: (evt: AgentEvent) => void;
    onError?: (err: Error) => void;
    onDone?: () => void;
  },
  config?: ChatConfig,
): Promise<{ streamId: string; cancel: () => void }>
```

契约:

1. 同步 `invoke('agent_chat_stream', { sessionId, message, apiKey, ... })` 拿 `streamId`。
2. `await listen('chat-stream-{streamId}', cb)` 注册订阅。
3. `cb(payload)` 把 `payload: AgentEvent` 透传给 `onEvent`。
4. `state === 'done' | 'failed'` 时:`settled` flag 防止双重 onDone;
   内部 `unlisten()` 后调 `onDone`;若 `failed + error`,额外 `onError(new Error(error))`。
5. `onEvent` 抛错时(用户回调坏)立即 `settled + cancel + onError + onDone` —
   不让坏回调拖死循环。
6. `listen` reject 时:抛 `ApiException({ code: 'STREAM_LISTEN_FAILED' })`。
7. 返回 `cancel()` 供调用方在 unmount/中断时释放 listener。
   注: **不取消后端流**; 中断整个 chat 用 `chatApi.interrupt()`。

### 4.3 `lib/store.ts` — `updateMessage`

`StoreState` 新增 `updateMessage(id, patch: Partial<Message>)`,
流式 chat 结束时把最终 content 写回 store.messages。

### 4.4 `features/send-message/useChat.ts` — 流式接入

核心变化:

- 内部 `useState<streaming>` 镜像当前流式 assistant 消息的 `{ messageId, content, state }`。
- `derivedMessages = useMemo(...)` 把 store.messages 的对应 id 消息的 content 覆盖
  为 `streaming.content`,让 widget 实时看到 thinking → 答案。
- `streamingContentRef` 镜像内容,`finally` 块同步读 ref 并 `updateMessage(assistantId, { content: finalContent })`,
  让流结束后 `derivedMessages` 退回 store 仍保留完整答案。
- 取消逻辑:`cancelRef.current = () => unlisten()`;
  `interrupt()` 先调 cancelRef,再调 `chatApi.interrupt()`。

### 4.5 UI 中间态文案

`agentStateToUiText(state, toolName?)` 把后端状态映射为 UI 文本,
由 useChat 在 onEvent 里写入 `streaming.content`:

| state       | UI 文本                 |
| ----------- | ----------------------- |
| `thinking`  | `🤔 思考中…`            |
| `acting`    | `🔧 调工具 {toolName}…` |
| `observing` | `👀 观察结果…`          |
| `failed`    | `❌ 失败`               |

若事件同时带 `content` (LLM 答案逐字到达),`content` 优先于 UI 文本。
Widget `MessageList.tsx` 无需改,只显示 `messages[].content` 即可看到
"🤔 思考中 → 🔧 调工具 calculator → 答案逐字"。

## 5. 测试

| 文件                                                         | 覆盖                                                                                                          |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| `src/features/send-message/__tests__/stream.test.ts`         | chatStream 契约 (6 例): invoke 参数 / listen 订阅 / 事件分发 / done / failed / listen reject / 非法 sessionId |
| `src/features/send-message/__tests__/useChat.test.ts` (更新) | useChat 流式路径: 成功 done → store 写回最终 content; listen reject → error 状态; interrupt 仍吞错            |
| `backend/tests/integration/test_chat_stream.py` (已有,PR-0)  | 后端 NDJSON 端点契约                                                                                          |
| `cargo check --manifest-path src-tauri/Cargo.toml`           | Rust 类型 + 依赖                                                                                              |

## 6. 验收

- [x] `cargo check` 全绿
- [x] `npx tsc --noEmit` 全绿
- [x] `npx vitest run src/features/send-message` 12/12 绿 (含新增 6 例)
- [ ] Manual: 与真实 Ollama/OpenAI 端点对话,
      能看到 "🤔 思考中" → "🔧 调工具 X" → 答案逐字到达 (待 dev 联调)
- [ ] `npm run tauri dev` 端到端无 console 报错

## 7. 风险与限制

| 风险                                                                                     | 应对                                                                 |
| ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| 后端流是 fire-and-forget,`chatStream` 的 `cancel()` 不取消后端                           | 中断整个 chat 用 `chatApi.interrupt()` (Tauri → Python `/interrupt`) |
| 多并行流用 stream_id 区分;前端组件 unmount 时必须 `cancel()` 防止 listener 泄漏          | useChat 把 cancel 存 ref,interrupt() 中先调 cancel                   |
| NDJSON 一行被截断在两个 chunk 之间 → 后台 task 维护 `buf` 跨 chunk 累积                  | 已在 `python.rs::post_stream` 实现                                   |
| `state=observing` + `error="NDJSON parse error"` 是兼容事件;前端可降级显示 raw line      | agentStateToUiText 不覆盖 `observing` 的特殊 error 分支              |
| Tauri 1.6 (win7) 与 2.x 的 `listen` 路径都从 `@tauri-apps/api/event` 导,目前 shim 同一份 | 保留 tauriEvent.ts 集中调整                                          |

## 8. 后续工作 (未在 PR-6 范围)

- 流式 token-by-token 渲染 (目前是事件级,一次更新一行 thinking/答案);
  需后端 `/chat/stream` 支持 SSE/逐字 token push
- 流式中断时的"已生成内容"保留(目前直接清 streaming)
- 流式状态持久化(刷新页面后从 last_event 续推)
