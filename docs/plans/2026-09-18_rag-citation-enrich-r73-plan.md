# r73 批次计划：RAG 引用溯源明细增强——chunk 索引/相关度进事件与气泡

日期：2026-09-18（分支创建于 main@0bdb707f，含 r71 #1115）
文件面：attachment_context.py（结果带 chunk 明细）、legacy_routes（事件
载荷扩展）、types/store/Message 前端渲染；测试三侧小增量。

## 背景

r71 的引用溯源只带 {media_id, mode}——用户展开只能看到附件 id，不知道
命中了哪些片段、相关度如何。后端 `_rag_injection` 的 SearchHit 本身就有
chunk_index/score，本批次把它带到事件与气泡。

## 交付

1. 后端：`AttachmentContextResult.chunks` 从 int 改为
   `List[{index, score}]`（index 为 chunk_index+1，score 保留两位场景
   由前端格式化）；`attachment_rag_used` citations 条目变为
   `{media_id, mode, chunks: [{index, score}]}`。
2. 前端：types/Store 类型同步；展开列表每个 media_id 下缩进列出
   「#index（score）」行。
3. 测试：后端 6 例更新（chunks 断言改列表形态）+ legacy 事件载荷断言
   不变（结构透传）；前端渲染已由 r71 测试覆盖结构，补一条 score 行
   断言（Message.trust 测试模式）——视现有测试成本，最少化。

## Win7 对齐
新功能，不 cherry-pick 到 release/win7。
