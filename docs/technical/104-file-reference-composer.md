# 文件引用输入（新会话页拖拽 / @ 菜单 / 会话内回显）

> 覆盖 `/welcome` 与 `/chat` 两个入口的文件引用能力：拖拽/选择器附件、`@` 文件与实体菜单、发送后的用户消息引用回显与持久化。
> 后端入口：`POST /api/v1/chat/stream` 的 `message_meta` 字段；数据列：`messages.client_meta`。

## 1. 背景与问题

历史上的文件引用能力只在聊天页（`ChatInput`）完整存在；新会话页 `WelcomeInputCard` 直接渲染裸 `InputCard`，因此：

- 拖拽文件没有 `onDrop` 处理，无法引用；
- 输入 `@` 没有 `useAtFileQuery` / `AtFileMenu`，菜单完全不存在；
- 发送后用户消息气泡没有附件/引用信息，刷新后也无法恢复。

此外 `Message` 组件虽有 `attachments` / `knowledgeRefs` props，但生产代码从未提供数据，而 `get_messages` 也没有用户消息展示元数据列。

## 2. 架构

### 2.1 共享 `@` 菜单逻辑

`src/features/chat/useAtFileMenu.tsx` 从原 `ChatInput` 内联逻辑抽出：

- 依据 `useAtFileQuery(value, cursorPos)` 识别当前 `@查询`；
- 渲染 `AtEntityMenu`（@memory:/@wiki:/@skill:/@agent:）与 `AtFileMenu`（文件 / Office 文档）；
- 文件选择插入 `@<path> `；Office 文档选择添加 `ChatOfficeRef` 并移除 `@查询`；
- 无会话/无工作区时由 `AtFileMenu` 显示 `chat.atFile.noWorkspace`，与「搜索无结果」区分。

`ChatInput` 与 `WelcomeInputCard` 共用该 hook，避免两套实现漂移。

### 2.2 新会话页懒创建草稿会话

`AtFileMenu` 的文件搜索依赖 `sessionId`（后端 `workspace_search_files` 通过会话解析工作区绑定）。新会话页在提交前没有会话，因此：

1. `WelcomeInputCard` 在 `@` 查询激活时回调 `Welcome.handleAtQueryActive`；
2. `Welcome.ensureDraftSession()` 懒创建会话：选了项目则 `projectApi.createSession(projectId)`（同步绑定项目目录），否则 `createSession()`（沿用最近工作区自动绑定）；
3. `setCurrentSessionId(sessionId)` 后 `SessionWorkspaceProvider` 回填 binding，`AtFileMenu` 立即用 sessionId 搜索；
4. 提交时若草稿会话的项目与目标项目一致则复用，避免一条消息创建两个会话。

### 2.3 Welcome → Chat 首条消息

`WelcomeInputCard` 的 `onSend(value, options)` 携带 `PendingComposerOptions`（`attachments/images/officeRefs`），经 `navigate('/chat', { state: { pendingMessage, pendingOptions } })` 传给聊天页。

`Chat` 的 pending effect 调用 `handleSendMessage`（而不是裸 `sendMessage`），因此首条消息与聊天页一样完成附件上传（`media.uploadAttachment` → `attachment_media_ids`）和图片裁剪。

## 3. 用户消息引用回显与持久化

### 3.1 展示元数据形状

`MessageDisplayMeta`（`src/shared/api/types/chatAndEventTypes.ts`）：

```json
{
  "attachments": [{ "name": "a.pdf", "size": 1024, "type": "application/pdf" }],
  "images": [{ "name": "chart.png", "size": 512, "type": "image/png" }],
  "file_refs": [{ "path": "src/App.tsx", "name": "App.tsx" }],
  "office_refs": [{ "doc_id": "doc-1", "doc_type": "pdf", "filename": "q3.pdf" }],
  "knowledge_refs": [{ "id": "k1", "title": "写作规范" }]
}
```

注意：

- `file_refs` 由 `buildMessageDisplayMeta` 从消息正文提取，规则与后端 `attachment_resolver` 同口径（`@` 前为空白/开头、token 含 `/` 或 `.`），并在中文句读处截断；
- `office_refs` 使用 snake_case —— Electron relay 的 `camelToSnakeKeys` 会把 `docId/docType` 转成 `doc_id/doc_type`，后端原样入库；
- 不携带 `dataUrl`，避免 base64 落库。

### 3.2 写入链路

1. `Chat.handleSendMessage` 组装 `displayMeta`，过滤未实际上传的附件；
2. `useChat.sendMessage` 把它挂到乐观 user 消息的 `client_meta`，并作为第 9 个参数传给 `chatApi.chatStream`（wire key `message_meta`）；
3. 队列/插话场景通过 `QueuedSendOptions.displayMeta` 随队列条目保留，flush 后不丢；
4. 后端 `ChatRequest.message_meta` 收到后序列化为 JSON，写入 user 行的 `messages.client_meta`；超过 32 KiB 丢弃该字段但不影响消息落库。

### 3.3 读取与渲染

`get_messages` 返回 `Message.to_dict()["client_meta"]`（畸形 JSON 降级 `null`）。`MessageClientMeta` 组件优先读取 `message.client_meta`，渲染文件/Office/知识库/附件 chips；同时保留 `MessageList` 的 `attachments/knowledgeRefs` props 作为兼容回退。

## 4. 涉及文件

| 层 | 文件 |
| --- | --- |
| 前端输入 | `src/features/chat/useAtFileMenu.tsx`、`src/widgets/chat/ChatInput.tsx`、`src/widgets/welcome/WelcomeInputCard.tsx`、`src/widgets/chat/InputCard.tsx` |
| 前端页面 | `src/pages/Welcome.tsx`、`src/pages/Chat.tsx` |
| 前端消息 | `src/widgets/chat/MessageClientMeta.tsx`、`src/features/send-message/messageDisplayMeta.ts` |
| 前端协议 | `src/shared/api/chatApi.ts`、`src/shared/api/types/chatAndEventTypes.ts`、`src/shared/lib/store.ts` |
| 后端 | `backend/api/legacy_models.py`、`backend/api/legacy_routes.py`、`backend/data/database.py`、`backend/data/session_repo.py` |

## 5. 测试

- 前端：`WelcomeInputCard.test.tsx`（拖拽附件、@ 菜单激活）、`Welcome.test.tsx`（草稿会话只创建一次）、`messageDisplayMeta.test.ts`、`Message.clientMeta.test.tsx`、`useChat.test.ts`（乐观 `client_meta` + `message_meta` 透传）、`Chat.pending-composer-options.test.tsx`。
- 后端：`test_session_repo.py`（`client_meta` 往返/畸形降级/迁移）、`test_chat_stream_persist.py`（`message_meta` 落库、超 32 KiB 丢弃）。

## 6. 已知边界

- 草稿会话在用户只输入 `@` 后放弃时会留下一个空会话（与项目工作台新建会话行为一致）。
- 未绑定工作区的会话，`@` 菜单只显示可诊断空态，需先绑定工作区/选择项目。
- `knowledge_refs` 目前只做展示，后端暂不消费该字段。
