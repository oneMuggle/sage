# 聊天信任感与基础交互补全（第十七轮批次 B）实施计划

> 日期: 2026-09-12 · 分支: `feat/chat-trust-r17` · 基于 main @ b09f0c10
> 来源: 第十七轮差距分析（前端 UX × 后端能力两条线，对标 ChatGPT/Claude
> Desktop、Cherry Studio、AnythingLLM）。本批聚焦**全 S 级、高感知**的
> "聊天信任感"组合——每条消息可复制/可删除、输入历史可回溯、错误不丢
> 上下文、记忆召回可见。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 冲突规避: 不触碰 writing-skills（#661）/ win7 对齐（#660）/ llm-trace 区域。

## 背景（分析结论摘录）

- **复制按钮永不显示**: `Message.tsx` 中复制/点赞/点踩三个按钮包在
  `onFeedback &&` 条件里，唯一调用方 `Chat.tsx` 不传 `onFeedback`
  → 主界面没有任何复制按钮（点赞/点踩为死代码）。
- **无消息删除入口**: `messageApi.delete`（IPC `delete_message`）已存在，
  全 src 无 UI 调用。
- **↑ 输入历史: 文档已承诺未实现**: `shortcuts.ts:34` 声称
  "↑（空输入时）编辑上一条发送过的消息"，`InputCard` 未实现。
- **错误整页替换**: `Chat.tsx` 顶层 `error` 时渲染整页 ErrorState，
  历史消息全部不可见（主流做法是内联错误条+保留历史）。
- **记忆召回不可见**: legacy `/chat/stream` L13 注入记忆上下文是静默的，
  流事件无任何 memory 事件；前端 `Message.tsx` 已预留
  `memory_applied` 渲染点但后端零生产者（死字段）。
- **附件静默丢失止血**: `ChatInput.handleSend` 收集的
  knowledgeRefs/attachments/images 在 `Chat.tsx handleSendMessage` 处
  被丢弃（完整通道为 L 级另批），`chat.hint` 文案却引导用户使用。

## 批次任务

### A. 复制按钮修复（S）

`src/widgets/chat/Message.tsx`: 复制按钮移出 `onFeedback &&` 条件，
所有 assistant 消息恒显示；点赞/点踩维持 `onFeedback` 门控（后端
feedback API 落地前不显示，不删机制）。action bar 渲染条件从
`(onFeedback || canFork || canEditResend)` 改为包含"有复制按钮"。

### B. 消息删除入口（S）

- `Message.tsx`: 动作区加删除按钮（`Trash2` 图标），两步确认
  （复用既有 `TwoStepDelete` 交互模式）。
- `Chat.tsx`: 传入 `onDelete` → `messageApi.delete(id)` 成功后
  从 store 移除该消息。
- 仅对历史消息显示（流式中的 streamingMessage 不显示）。

### C. ↑ 输入历史（S——兑现既有承诺）

`src/widgets/chat/InputCard.tsx`: 空输入时 `ArrowUp` → 回填本会话
上一条 user 消息，继续 `↑` 更早 / `↓` 回到最新；一旦用户编辑
（输入变化）退出历史导航。历史源: `messages` store 里当前会话的
user 消息（倒序去重）。`shortcuts.ts` 注册表不动（已承诺该键位）。

### D. 错误内联（S）

`src/pages/Chat.tsx`: 顶层 `error` 时不再整页替换——在消息列表
下方渲染内联错误条（错误文本 + "关闭" 按钮），历史与输入框保持
可见可继续使用。

### E. 记忆召回展示（S——后端事件 + 前端接线）

- 后端 `backend/api/legacy_routes.py`（chat stream producer）:
  L13 记忆注入成功后，用 `MemoryManager.recall(query=data.message,
  limit=3, session_id=...)` 取结构化命中（fail-safe，异常跳过），
  推送流事件 `{"state": "memory_used", "session_id": ...,
  "memories": [{"id","memory_type","preview"}...]}`。
- 前端:
  - `src/shared/lib/store.ts` `Message` 增加可选字段
    `memory_refs?: { id: string; memory_type: string; preview: string }[]`。
  - `src/features/send-message/useChat.ts`: 处理 `memory_used` 事件 →
    `updateMessage(assistantId, { memory_refs, memory_applied: n })`。
  - `src/widgets/chat/Message.tsx`: `memory_applied` 区块升级为可
    展开列表（点击展开显示每条 preview + 类型徽章）。

### F. 附件丢失止血（S——文案诚实化）

- `src/shared/lib/i18n/zh.ts` / `en.ts`: `chat.hint` 移除
  "点击知识库按钮多选文档作为上下文引用"（该通道尚未打通）。
- `src/widgets/chat/ChatInput.tsx`: handleSend 检测到将被丢弃的
  knowledgeRefs/attachments/images 时 toast 提示
  "附件暂不随消息发送（即将支持）"。

## 测试

- 前端 vitest: Message 复制按钮恒显 / 删除两步确认回调 /
  memory_refs 展开渲染；InputCard ↑ 历史回填与退出；Chat 内联错误。
- 后端 pytest: legacy chat stream 在 L13 命中时发出 `memory_used`
  事件（mock memory_manager），未命中/异常时零事件且不阻塞。
- Lint: eslint（前端）+ ruff（后端）。

## Round 18 候选（来自同轮分析，按价值排序）

- 重新生成（最后一条 assistant 消息，复用 fork-before+重发链路）
- 会话置顶入口（is_pinned 字段已有、分组比较逻辑在遗留组件可抄）
- 会话 md/json 导出 + SQLite 自动备份
- 首次启动/端点配置向导
- prompt 模板库（CRUD + 斜杠面板联动）
- 聊天内文件 RAG（L：上传端点+分块索引+引用溯源）
