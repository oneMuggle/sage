# 聊天文本文档附件通道（第三十七轮批次 A / 文件 RAG 第一切片）实施计划

> 日期: 2026-09-15 · 分支: `feat/attachments-files-r37` · 基于 main
> @ d646126c。来源: 第二十一轮差距分析 D2 文件半边 + RAG 切片口径
> （txt/md 直传支持为分析标注的 S 级先行项）。与并发车道零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 背景（证据）

- R26 分析: 附件上传后端 `POST /api/v1/chat/attachments` 与
  Electron IPC（media:upload-attachment）均已就绪，但**零 UI 调用**；
  ChatInput 拖入的文件在 handleSendMessage 处被静默丢弃（R17-F 只做
  了诚实提示；#702 只接通了图片）。
- 本切片：**txt/md 文本文档**端到端注入聊天上下文（pdf/docx 提取为
  后续批）。泛 RAG（分块/向量检索）仍为 L 级另批——本切片是"全文
  注入"式第一切片，与 RAG 的分块检索互补（小文档全文即可）。

## 实施

### A. 后端（S）

- `chat_attachment_routes.py`: 允许 text/plain / text/markdown 与
  .txt/.md 扩展（kind=DOCUMENT，MediaStore 新增 DOCUMENT kind 与
  默认 ext/mime）；上传响应额外带 `text`（utf-8 全文，上限 100k 字符）；
  新增 `GET /chat/attachments/{media_id}/text`（producer 读全文用，
  非 DOCUMENT → 400，不存在 → 404）。
- `ChatRequest.attachment_media_ids: List[str]`：producer 按 id 读
  全文（≤100k 字符/条、≤10 条），以 `<attached_document id=...>`
  块并入尾部 dynamic 上下文。fail-safe：单条失败跳过。

### B. 前端接线（M）

- `chatApi.chatStream` 第 7 参 `attachmentMediaIds` → invoke body
  `attachment_media_ids`；`useChat.sendMessage opts` 透传。
- `Chat.handleSendMessage`: txt/md 附件经 `window.electronAPI.media.
  uploadAttachment`（与 AttachmentUpload 同款 IPC 通道）上传，收集
  media id；其余扩展名维持 R17-F 诚实提示。
- ChatInput 附件警告文案更新（txt/md 已支持）。

## 测试

- 后端 `test_chat_attachment_text.py`: txt/md 上传带 text 响应 /
  kind=DOCUMENT / 非 utf-8 拒绝 / 非文本类型仍拒 / text 端点 404 与
  400 分支。
- 前端: manage/onboarding 回归 + tsc/eslint 全绿。

## 本批不做（后续切片）

- pdf/docx 提取（复用 office 解析，M）
- 分块 + 向量检索（真 RAG，L）
- 非文本二进制文件附件
