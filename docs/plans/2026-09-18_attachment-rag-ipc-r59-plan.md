# r59 批次计划：附件 RAG IPC 透传 + 前端客户端（管道收口）

日期：2026-09-16（分支创建于 main@88b466f2，含 r57 #960 / r58 #968）
文件面：electron/commands.ts、新增 src/shared/api/attachmentRagClient.ts、
commands 测试；零 UI 行为变更。

## 背景

r57/r58 在后端交付了附件向量索引三端点，但 Electron 渲染进程没有任何
通道可达（invoke 命令缺失）。聊天 producer 的检索注入策略（何时嵌入
query、命中如何进上下文）是下一个产品决策切片——本批次先把管道打通：
IPC 路由 + 类型化客户端，让后续任何 UI/producer 切片零后端前置。

## 交付

1. electron/commands.ts 三条路由：
   - `attachment_rag_index`：POST /chat/attachments/{id}/index
     （body 透传 embed 配置 + target_chunk_size）
   - `attachment_rag_search`：POST /chat/attachments/search
     （query_vector/dim/media_ids/limit）
   - `attachment_rag_delete_index`：DELETE /chat/attachments/{id}/index
2. `src/shared/api/attachmentRagClient.ts`：
   - 类型：AttachmentEmbedConfig / AttachmentIndexReport /
     AttachmentSearchHit / AttachmentSearchInput
   - attachmentRagClient.indexAttachment / searchAttachments /
     deleteAttachmentIndex（invoke 封装，错误经 handleApiError？——
     与 mcpClient 同口径直接抛）
3. 测试：commands.test.ts 断言 method/path/body 形态（index 的 name
   进路径、body 不含 name；search 直发 body）。

## 不做
- UI 入口 / producer 检索注入策略（下一批次的 fork 点）；
- 后端任何改动。

## Win7 对齐
新功能（管道），不 cherry-pick 到 release/win7。
