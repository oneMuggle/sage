# 23 — Chat 流式响应端到端 (PR-6)

> 本章记录端到端贯通方案: 后端 `POST /api/v1/chat/stream` 已实现 NDJSON 流式协议 + 完整集成测试,
> 但 Tauri 层无 `agent_chat_stream` 命令,前端 `chatApi` 也无流式调用方法,
> 流式 UX (thinking/acting/observing 实时反馈) 无法触达用户。

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

## 9. 流式状态 store 化(2026-08-19)

2026-08-19 起,§4.4 描述的 `useChat` component-local `streaming` /
`streamingToolCalls` / `taskBoard` 三个 useState 全部迁出至独立 zustand store
`useChatStreamStore`(文件: `src/features/send-message/chatStreamStore.ts`),
以保证**路由切换(`/chat` ↔ `/settings`)时流式进度不丢失**:

- store 是 module-singleton(zustand `create` 默认行为),跨 React 组件实例
  / 跨路由挂载点保留;
- `useChat` 通过 `useChatStreamStore` 订阅并写回,内部不再持
  `streaming / streamingToolCalls / taskBoard` 的 useState;
- `TaskBoardState` 类型从 useChat 提取到 store 文件,`useChat` 仍 re-export
  `TaskBoard` 别名指向 `TaskBoardState`,对外 API 不变。

**所有 action 校验 `messageId`**,防止上一个流的迟到事件污染下一个流:

| action                | 校验逻辑                                                                                |
| --------------------- | --------------------------------------------------------------------------------------- |
| `appendContent`       | `prev.streaming?.messageId === messageId` 才拼接,否则返回原 state 静默丢弃              |
| `replaceContent`      | 同上,匹配才覆盖 `content`                                                              |
| `appendReasoning`     | 同上,匹配才拼接 `reasoning`                                                            |
| `setStreamingMeta`    | 同上,匹配才打 patch(state / currentAgentId / iteration)                                |
| `clearStream`         | 同上,匹配才置 `streaming: null`;`streamingToolCalls` / `taskBoard` 由 reset 路径清理   |
| `startStream`         | 不校验(本身就是"开始下一条流的入口",无条件覆盖)                                        |
| `updateTaskBoard`     | `runId` 校验由 updater 闭包内做,store 层不二次校验以保留灵活性                          |

详见 §4.4 验收清单及配套测试:

- `src/features/send-message/__tests__/chatStreamStore.test.ts` (8 例:messageId 校验 / 累积语义 / 一锅端)
- `src/features/send-message/__tests__/useChat.stream-survives-unmount.test.tsx` (1 例:跨"卸载"存活)

**已知遗留**:`chatStreamStore.ts` 中 `updateTaskBoard(runId, updater)` 的
`runId` 参数当前未在 store 内部读取(updater 闭包已做匹配),会触发
`tsc --noEmit` 的 `TS6133 noUnusedParameters` 一行警告;属"无功能影响"
已知缺陷,已记录待后续 session 清理。

## 10. 迭代上限错误定位 + 思考/正文可见性(2026-10-29, PR #2650)

用户反馈两类同源问题:主 SSE 路径下只看到工具调用气泡、看不到思考过程与最终回答;
失败时只抛出一句"任务复杂度超出迭代上限 10 次",既误导(用户以为是
`complexity_classifier` 的分类结果)又无用(不知道是哪个 agent、该调哪个设置)。

### 10.1 迭代上限事件携带 agent / source

`SageAgent.run_loop` 计算 `effective_max_iterations` 的优先级链保持不变:

```
显式参数 max_iterations  >  orch_settings.max_iterations  >  profile.max_iterations  >  DEFAULT_MAX_ITERATIONS(10)
```

新增的是**记录来源**:同一分支里记下 `_limit_source`,并连同 agent id 一并写进
FAILED 事件字符串(见 `backend/core/legacy/agent.py` 的 `_limit_source` /
`_limit_agent_part`):

```
max_iterations_exceeded (limit=10, agent=writer, source=profile)
```

| `source` 取值 | 含义 | 用户该去哪调 |
| --- | --- | --- |
| `explicit` | 调用方硬覆盖(如父 agent 委派时按任务复杂度给定) | 调用方代码;用户侧只能拆分任务 |
| `orch.global` | 编排全局设置 | 设置 → 编排 → Agent 迭代次数上限 |
| `profile` | 该 agent profile 的 `max_iterations` | Agent 编辑面板里该 agent 的最大迭代次数 |
| `default` | 兜底值 10(无 profile 且全局为 0) | 设置 → 编排 → Agent 迭代次数上限 |

`agent=` 段在 profile id 与 `agent_id` 都为空时**整段省略**(不会出现
`agent=, source=…` 的畸形串),前端此时回落为「本次任务」措辞。

前端 `src/shared/lib/errorMapping.ts` 的 `parseAgentErrorLimit` 扩展解析
`agent` / `source` 两个可选字段,`buildIterationLimitMessage` 据此渲染:

```
「写作助手」达到迭代上限 10 次（上限来源：Agent 默认配置）。
可在 Agent 编辑面板调整该 Agent 的最大迭代次数后重试，或拆分任务减少往返。
```

旧格式(仅 `limit=`)仍然兼容,解析不到 `agent` / `source` 时回落通用文案。

### 10.2 思考过程(reasoning)可见性

排查结论:**前端主 SSE 路径的 reasoning 累积本就存在**——`useChat` 的 onEvent
先调 `applyTransparencyAndToolEvents`(`chatStreamRuntime.ts:231`),由它按
`reasoning_delta` / `reasoning` append、`reasoning_final` replace 写入
`useChatStreamStore`,主路径与 reattach 路径共用同一处。真正的缺口在后端:

- **流式分支**只看 provider 的增量 `reasoning_delta`;当 provider 把整段思考塞进
  `response.reasoning_content` 而不发增量时,整段思考被丢弃(非流式路径本来就有
  `response.reasoning_content` 兜底)。
- 修复:`agent.py` 流式分支在 `stream_reasoning_parts` 为空时回退
  `response.reasoning_content`,补发一条 `REASONING` 事件,与非流式路径口径对齐。

### 10.3 中间态占位符不得吞掉已流式正文

第二条"只看到工具气泡"的路径在 `useChat.ts`,比 reasoning 更致命:

| 现象 | 修复前 | 修复后 |
| --- | --- | --- |
| 已流式产出正文后又来一个工具事件 | `thinking` / `acting` / `observing` 占位文案**无条件** `replaceContent`,正文被擦掉 | `hasRealContent` 为真时占位符不写回 |
| 迭代上限失败(无 DONE 收尾) | `finishStream` 把残留占位符 `🤔 思考中…` 当正文写回消息 | 从未产出正文时清空占位符,不写回 |
| DONE 事件再次携带全文 | 与已流式内容重复 | `hasRealContent` 为真时不再 append |
| `step_done` 切换新气泡 | 标记残留,新步骤被误判为"已有正文" | 重置 `hasRealContent = false` |

首个真实 token 仍替换占位符(用户不会同时看到 `🤔 思考中…` 和正文),之后 token
追加。相关回归用例:

- `src/features/send-message/__tests__/useChat.streamingAndGates.test.ts` —
  `intermediate placeholders do not overwrite already-streamed content`、
  `done event does not duplicate already-streamed content`
- `backend/tests/unit/test_agent_run_loop.py` —
  `test_run_loop_failed_event_names_agent_and_source`
- `backend/tests/unit/test_agent_streaming.py` —
  `test_run_loop_streaming_emits_reasoning_from_response_fallback`
- `src/shared/lib/errorMapping.test.ts` — agent/source 解析与差异化文案(共 29 例)
