# 聊天图片通道打通（第二十三轮批次 A）实施计划

> 日期: 2026-09-12 · 分支: `feat/attachments-r23` · 基于 main @ d7517abe
> 来源: 第二十一轮差距分析 D2 [P0]——"vision 模型可选但无从发送"。
> 与并发车道（search-fts / empty-response-guard / excel）零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 背景（证据）

- 前端拖拽/粘贴/按钮收集的 `images`（`{name,size,type,dataUrl}`）在
  `Chat.handleSendMessage` 被静默丢弃（R17-F 只做了诚实提示）；
  ModelsTab 已提供 vision 模型选择器——能力存在但入口断裂。
- 后端通道完好: `ChatRequest.images`（data URL 列表，≤4 张/单张
  5MiB，legacy_routes:2565 校验 + 2626 转 OpenAI 多模态分段），
  `llm_client._convert_messages` 原样透传。缺的只是前端接线。

## 实施

1. `chatApi.chatStream` 增加第 6 参 `images?: string[]` → invoke
   payload `images`（camelToSnake 恒等，后端 ChatRequest 直接收）。
2. `useChat.sendMessage` `opts.images` 透传。
3. `Chat.handleSendMessage`: 从 options.images 取 dataUrl，前端先行
   校验（≤4 张、单张 base64 解码 ≤5MiB，超限 toast + 截断）后下发。
4. `ChatInput`: R17-F 警告收窄为 files/knowledgeRefs（images 已支持）。
5. i18n: `chat.attachment_not_sent` 文案更新（图片已支持）。

## 本批不做

- 用户消息气泡内的图片回显（需 store Message 挂 attachments + 渲染
  通道，Round 24 候选）
- files 附件上传通道（chat_attachment_routes 上传端点已就绪，接
  mediaIpc 上传 + 消息引用，M/L 独立批）
- hex/编排路径的多模态 content（domain Message 仍为 str，后端另批）

## 测试

- `stream.test.ts` invoke 契约更新（images 缺省 `[]`）+ 全套
  send-message 测试回归。
- tsc / eslint 全绿。
