# r66 批次计划：RAG 切片 4a——producer 超长附件检索注入（opt-in 请求级嵌入）

日期：2026-09-17（分支创建于 main@fffdef44，含 RAG 三切片 #960/#968/#976）
文件面：新增 backend/services/attachment_context.py + 单测；legacy_routes
chat 请求模型 + R37 注入块小改；前端接线为切片 4b。

## fork 决策（query 嵌入来源）

采用**opt-in 请求级嵌入配置**（与 wiki ingest / r58 index 路由同口径）：
聊天请求新增可选 `attachment_rag: {embed: {...}, top_k}`。默认不传 =
现状全文注入（零行为变化）。理由：Sage 无全局 embed provider 概念，
请求级是已确立的两处先例；且超长文档注入是显式场景，opt-in 无惊吓。

## 交付

1. `backend/services/attachment_context.py`：
   - `build_attachment_context(media_id, *, query, text_extractor, rag=None,
     store_path, query_embedder)`：单附件注入决策纯编排——
     - 全文 ≤ MAX_TEXT_INJECT_CHARS → 现状注入（截断全文）；
     - 超限且配置 rag → query_embedder(query) 得查询向量 →
       search_attachments（r58 库层）→ 注入「首段 2k + top_k chunk 块
       （带 media_id/序号/相似度标注）」；
     - 超限未配 rag → 注入前 100k（现状口径，不回归）；
     - 任何异常 → 返回 None（fail-safe，绝不阻断聊天）。
   - query_embedder 注入（测试 fake；生产用 httpx 调 embed 端点）。
2. `legacy_routes.py`：
   - 请求模型增 `attachment_rag: {embed:{...}, top_k}` 可选块；
   - R37 注入块改调 build_attachment_context（txt 直读；pdf/docx 走
     chat_attachment_routes._extract_document_text 提取全文）；
   - query_embedder 生产实现（httpx → embed 端点，parse 复用 wiki
     embeddings.parse_embed_response）。
3. 测试：attachment_context 单测（短文现状注入 / 超长+rag 走检索块 /
   超长无 rag 截断 / 异常 fail-safe / pdf 提取路径 fake）。

## 不做
- 前端设置开关与请求组装（切片 4b）；引用溯源 UI（后续）。

## Win7 对齐
新功能，不 cherry-pick 到 release/win7。
