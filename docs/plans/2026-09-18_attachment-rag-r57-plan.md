# r57 批次计划：附件向量索引库函数层（聊天文件 RAG 第一切片）

日期：2026-09-16（分支创建于 main@08051607）
文件面：backend/wiki/vectorstore.py（+open_at 类方法）、新增
backend/services/attachment_rag.py + 单测；零路由/零前端改动。

## 背景

「聊天内文件 RAG」是既定 L 级大项（r37 已交付附件全文通道：txt/md/
pdf/docx → 提取文本 → 全文注入）。真向量检索的分块/嵌入/存储三块地基
wiki 模块已全部就绪（chunk_markdown、build/parse_embed_response、
VectorStore），但仅服务 wiki 页面。本批次把它们组合成附件侧的**纯库层**，
路由接线与嵌入配置来源（产品决策：复用 provider 设置还是请求级配置）
留给后续切片——本层只做显式依赖注入，与 wiki ingest 的可测设计同口径。

## 交付

1. `VectorStore.open_at(storage_path, dim)`：open() 的自定义路径版
   （加载已有存储或惰性创建；open() 改为委托，行为不变）。
   动机：构造函数不读盘，直接 new 会覆写既有文件；附件库要独立于
   wiki 的 .llm-wiki/vectors.json 存放。
2. `backend/services/attachment_rag.py`：
   - `index_attachment(media_id, text, storage_path, embed_config, http_post, target_chunk_size=500)`（async）：
     chunk_markdown → embed（注入 http_post）→ upsert
     （page_path=chat-attachment/<media_id>，重复索引幂等替换）；
     空文本 → chunks=0 且不落盘；嵌入请求失败/向量数不符 →
     AttachmentRagError（调用方后续决定 fail-open 口径）。
   - `search_attachments(query_vector, storage_path, dim, limit=5, media_ids=None)`：
     存储不存在 → []（未索引不是错误）；media_ids 过滤限定范围。
   - `remove_attachment(media_id, storage_path, dim)` → 删除记录数。
3. 单测 `backend/tests/unit/test_attachment_rag.py`（fake http_post，
   dim=4 小向量）：索引/检索/删除全链路、幂等重索引、空文本、
   请求数≠向量数、http_post 抛错、未索引检索、media_ids 过滤、
   open_at 持久化往返。

## 不做
- 路由 / 上传钩子 / IPC / 前端（切片 2）；
- 嵌入配置来源决策（切片 2 前置讨论）；
- HNSW 迁移（wiki vectorstore_hnsw 另行评估）。

## Win7 对齐
新功能（库层），不 cherry-pick 到 release/win7。
